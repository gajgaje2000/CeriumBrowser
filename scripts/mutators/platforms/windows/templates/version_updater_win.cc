// Copyright 2012 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// Cerium Browser — Native Windows Version Updater Implementation
// Replaces Google Omaha / Sparkle updater in chrome/browser/ui/webui/help/version_updater_win.cc.
// Queries the GitLab Releases API directly, verifies SHA256 checksums, and launches
// mini_installer silently with administrative elevation fallback for system-level installs.

#include "chrome/browser/ui/webui/help/version_updater.h"

#include <memory>
#include <optional>
#include <string>
#include <string_view>

#include "base/byte_size.h"
#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/logging.h"
#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "base/process/launch.h"
#include "base/process/process.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/thread_pool.h"
#include "base/values.h"
#include "base/version.h"
#include "build/build_config.h"
#include "chrome/browser/browser_process.h"
#include "chrome/browser/first_run/upgrade_util.h"
#include "chrome/common/chrome_version.h"
#include "chrome/install_static/install_util.h"
#include "chrome/installer/util/install_util.h"
#include "chrome/installer/util/util_constants.h"
#include "crypto/hash.h"
#include "net/http/http_response_headers.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"
#include "services/network/public/cpp/simple_url_loader.h"
#include "services/network/public/mojom/url_response_head.mojom.h"
#include "url/gurl.h"

namespace {

constexpr char kGitLabReleasesApiUrl[] =
    "https://gitlab.com/api/v4/projects/CeriumBrowser%2FCerium-Browser/releases?per_page=1";

class CeriumVersionUpdaterWin : public VersionUpdater {
 public:
  CeriumVersionUpdaterWin() : weak_factory_(this) {}
  ~CeriumVersionUpdaterWin() override = default;
  CeriumVersionUpdaterWin(const CeriumVersionUpdaterWin&) = delete;
  CeriumVersionUpdaterWin& operator=(const CeriumVersionUpdaterWin&) = delete;

  void CheckForUpdate(StatusCallback status_callback,
                      PromoteCallback promote_callback) override {
    callback_ = std::move(status_callback);
    callback_.Run(CHECKING, 0, false, false, std::string(), 0, std::u16string());

    base::ThreadPool::PostTaskAndReplyWithResult(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
        base::BindOnce(&upgrade_util::IsUpdatePendingRestart),
        base::BindOnce(&CeriumVersionUpdaterWin::OnPendingRestartCheck,
                       weak_factory_.GetWeakPtr()));
  }

 private:
  void OnPendingRestartCheck(bool is_pending) {
    if (is_pending) {
      callback_.Run(NEARLY_UPDATED, 0, false, false, std::string(), 0,
                    std::u16string());
      return;
    }
    FetchReleaseManifest();
  }

  void FetchReleaseManifest() {
    auto resource_request = std::make_unique<network::ResourceRequest>();
    resource_request->url = GURL(kGitLabReleasesApiUrl);
    resource_request->method = "GET";
    resource_request->credentials_mode = network::mojom::CredentialsMode::kOmit;
    resource_request->headers.SetHeader(net::HttpRequestHeaders::kAccept,
                                        "application/json");

    net::NetworkTrafficAnnotationTag traffic_annotation =
        net::DefineNetworkTrafficAnnotation("cerium_version_updater_win", R"(
          semantics {
            sender: "Cerium Version Updater"
            description: "Checks for and downloads Cerium Browser updates from GitLab Releases API."
            trigger: "User opens about page or periodic auto-update check."
            data: "None."
            destination: OTHER
          }
          policy {
            cookies_allowed: NO
            setting: "This feature cannot be disabled."
            chrome_policy {}
          })");

    manifest_loader_ = network::SimpleURLLoader::Create(
        std::move(resource_request), traffic_annotation);
    manifest_loader_->DownloadToString(
        g_browser_process->shared_url_loader_factory().get(),
        base::BindOnce(&CeriumVersionUpdaterWin::OnManifestDownloaded,
                       weak_factory_.GetWeakPtr()),
        128 * 1024);
  }

  void OnManifestDownloaded(std::optional<std::string> response_body) {
    if (!response_body) {
      if (manifest_loader_->ResponseInfo() &&
          manifest_loader_->ResponseInfo()->headers &&
          manifest_loader_->ResponseInfo()->headers->response_code() == 304) {
        callback_.Run(UPDATED, 0, false, false, std::string(), 0,
                      std::u16string());
        return;
      }
      callback_.Run(FAILED, 0, false, false, std::string(), 0,
                    u"Failed to fetch release manifest from GitLab");
      return;
    }

    std::optional<base::Value> parsed_json =
        base::JSONReader::Read(*response_body, base::JSON_PARSE_RFC);
    if (!parsed_json || !parsed_json->is_list() || parsed_json->GetList().empty()) {
      callback_.Run(FAILED, 0, false, false, std::string(), 0,
                    u"Invalid release manifest format from GitLab");
      return;
    }

    const base::DictValue* release = parsed_json->GetList()[0].GetIfDict();
    if (!release) {
      callback_.Run(FAILED, 0, false, false, std::string(), 0,
                    u"Invalid release entry");
      return;
    }

    const std::string* tag_name = release->FindString("tag_name");
    if (!tag_name) {
      callback_.Run(FAILED, 0, false, false, std::string(), 0,
                    u"Release missing tag_name");
      return;
    }

    std::string_view version_str = *tag_name;
    if (base::StartsWith(version_str, "v")) {
      version_str.remove_prefix(1);
    }

    base::Version current_version(CHROME_VERSION_STRING);
    base::Version remote_version(version_str);
    if (!remote_version.IsValid() || remote_version <= current_version) {
      callback_.Run(UPDATED, 0, false, false, std::string(), 0,
                    std::u16string());
      return;
    }

#if defined(ARCH_CPU_ARM64)
    const char* target_pkg_name = "cerium_arm64.exe";
#else
    const char* target_pkg_name = "cerium_x64.exe";
#endif

    const base::DictValue* assets = release->FindDict("assets");
    const base::ListValue* links = assets ? assets->FindList("links") : nullptr;
    if (!links) {
      callback_.Run(FAILED, 0, false, false, std::string(), 0,
                    u"No release assets found");
      return;
    }

    std::string package_url;
    for (const base::Value& item : *links) {
      const base::DictValue* link = item.GetIfDict();
      if (!link) continue;
      const std::string* name = link->FindString("name");
      if (name && *name == target_pkg_name) {
        const std::string* direct_url = link->FindString("direct_asset_url");
        if (!direct_url) direct_url = link->FindString("url");
        if (direct_url) {
          package_url = *direct_url;
          break;
        }
      }
    }

    if (package_url.empty()) {
      callback_.Run(FAILED, 0, false, false, std::string(), 0,
                    u"No installer found for current architecture");
      return;
    }

    DownloadPackage(std::string(version_str), package_url);
  }

  void DownloadPackage(const std::string& version,
                       const std::string& package_url) {
    callback_.Run(UPDATING, 0, false, false, version, 0, std::u16string());

    auto resource_request = std::make_unique<network::ResourceRequest>();
    resource_request->url = GURL(package_url);
    resource_request->method = "GET";
    resource_request->credentials_mode = network::mojom::CredentialsMode::kOmit;

    net::NetworkTrafficAnnotationTag traffic_annotation =
        net::DefineNetworkTrafficAnnotation("cerium_installer_download", R"(
          semantics {
            sender: "Cerium Version Updater"
            description: "Downloads the Cerium Browser Windows update package from GitLab."
            trigger: "Available update detected."
            data: "None."
            destination: OTHER
          }
          policy {
            cookies_allowed: NO
            setting: "This feature cannot be disabled."
            chrome_policy {}
          })");

    package_loader_ = network::SimpleURLLoader::Create(
        std::move(resource_request), traffic_annotation);

    package_loader_->SetOnDownloadProgressCallback(base::BindRepeating(
        &CeriumVersionUpdaterWin::OnDownloadProgress,
        weak_factory_.GetWeakPtr(), version));

    package_loader_->DownloadToTempFile(
        g_browser_process->shared_url_loader_factory().get(),
        base::BindOnce(&CeriumVersionUpdaterWin::OnPackageDownloaded,
                       weak_factory_.GetWeakPtr(), version));
  }

  void OnDownloadProgress(const std::string& version, uint64_t current) {
    int percent = 0;
    if (package_loader_->ResponseInfo() && package_loader_->ResponseInfo()->headers) {
      std::optional<base::ByteSize> content_length =
          package_loader_->ResponseInfo()->headers->GetContentLength();
      if (content_length.has_value() && content_length->InBytes() > 0) {
        int64_t total = static_cast<int64_t>(content_length->InBytes());
        percent = static_cast<int>((current * 100) / total);
        if (percent > 100) percent = 100;
        callback_.Run(UPDATING, percent, false, false, version, total,
                      std::u16string());
        return;
      }
    }
    callback_.Run(UPDATING, percent, false, false, version, 0,
                  std::u16string());
  }

  void OnPackageDownloaded(const std::string& version,
                           base::FilePath file_path) {
    if (file_path.empty() || !base::PathExists(file_path)) {
      callback_.Run(FAILED, 0, false, false, version, 0,
                    u"Failed to download installer package");
      return;
    }

    std::string expected_sha256;
    if (package_loader_->ResponseInfo() && package_loader_->ResponseInfo()->headers) {
      expected_sha256 =
          package_loader_->ResponseInfo()->headers->GetNormalizedHeader(
              "x-checksum-sha256").value_or(std::string());
    }

    base::ThreadPool::PostTaskAndReplyWithResult(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
        base::BindOnce(&CeriumVersionUpdaterWin::VerifyAndInstall, file_path,
                       expected_sha256),
        base::BindOnce(&CeriumVersionUpdaterWin::OnInstallFinished,
                       weak_factory_.GetWeakPtr(), version));
  }

  static bool VerifyAndInstall(const base::FilePath& file_path,
                               const std::string& expected_sha256) {
    if (!expected_sha256.empty()) {
      std::string file_data;
      if (!base::ReadFileToString(file_path, &file_data)) {
        base::DeleteFile(file_path);
        return false;
      }

      std::string actual_hash =
          base::HexEncodeLower(crypto::hash::Sha256(file_data));
      if (actual_hash != base::ToLowerASCII(expected_sha256)) {
        LOG(ERROR) << "SHA256 mismatch: expected " << expected_sha256
                   << " got " << actual_hash;
        base::DeleteFile(file_path);
        return false;
      }
    }

    base::CommandLine cmd(file_path);
    cmd.AppendSwitch("silent");
    cmd.AppendSwitch("chrome");
    cmd.AppendSwitch("do-not-launch-chrome");

    int exit_code = 1;
    if (install_static::IsSystemInstall()) {
      cmd.AppendSwitch("system-level");
      DWORD dw_exit = 1;
      if (InstallUtil::ExecuteExeAsAdmin(cmd, &dw_exit)) {
        exit_code = static_cast<int>(dw_exit);
      }
    } else {
      base::LaunchOptions options;
      options.start_hidden = true;
      base::Process proc = base::LaunchProcess(cmd, options);
      if (proc.IsValid()) {
        proc.WaitForExit(&exit_code);
      }
    }

    base::DeleteFile(file_path);
    return exit_code == 0 || upgrade_util::IsUpdatePendingRestart();
  }

  void OnInstallFinished(const std::string& version, bool success) {
    if (success) {
      callback_.Run(NEARLY_UPDATED, 0, false, false, version, 0,
                    std::u16string());
    } else {
      callback_.Run(FAILED, 0, false, false, version, 0,
                    u"Installer execution or checksum verification failed");
    }
  }

  StatusCallback callback_;
  std::unique_ptr<network::SimpleURLLoader> manifest_loader_;
  std::unique_ptr<network::SimpleURLLoader> package_loader_;
  base::WeakPtrFactory<CeriumVersionUpdaterWin> weak_factory_;
};

}  // namespace

std::unique_ptr<VersionUpdater> VersionUpdater::Create(
    content::WebContents* web_contents) {
  return std::make_unique<CeriumVersionUpdaterWin>();
}
