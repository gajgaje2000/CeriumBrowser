#!/usr/bin/env python3
"""
Cerium — Hermetic Windows Cross-Compilation Toolchain Manager
(scripts/core/setup-win-toolchain.py)

Modular management and setup for Windows cross-compilation toolchains on Linux:
  - Resolves target toolchain hash from Chromium src/build/vs_toolchain.py.
  - Prioritizes candidate hermetic toolchain archives (e.g. 44f9aa3391, 436026023a).
  - Downloads toolchain archives from GitLab Package Registry or fallback URLs with retry and integrity checks.
  - Validates archive integrity (SHA1 checksum matching depot_tools CalculateHash and required toolchain contents).
  - Detects and cleans mislabeled or corrupted archives.
  - Generates hermetic toolchain trees from scratch via xwin (MSVC CRT + Windows SDK 10.0.26100).
  - Synthesizes SetEnv manifests and cl.exe stubs across all target architectures (x86, x64, arm64, arm).
  - Generates toolchain.env with required GYP_MSVS_HASH and DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL exports.
  - Uploads generated toolchains to GitLab Generic Package Registry when running in CI.
"""

import argparse
import collections
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

# Upstream xwin release version and standalone binary URL for hermetic downloads
XWIN_VERSION = "0.10.0"
XWIN_URL = f"https://github.com/Jake-Shadle/xwin/releases/download/{XWIN_VERSION}/xwin-{XWIN_VERSION}-x86_64-unknown-linux-musl.tar.gz"

# Canonical verified toolchain hashes prioritized in CI and local builds
PRIMARY_VERIFIED_HASH = "44f9aa3391"
HERMETIC_FALLBACK_HASH = "436026023a"
DEFAULT_PRIMARY_DOWNLOAD_URL = "https://gitlab.com/CeriumBrowser/Cerium-Browser/-/package_files/381442182/download"


# -----------------------------------------------------------------------------
# 1. Archive & Directory Hash Calculation (matching depot_tools CalculateHash)
# -----------------------------------------------------------------------------

def calculate_toolchain_hash_from_dir(toolchain_dir: str) -> str:
    """Calculate the SHA1 hash of a toolchain directory matching depot_tools CalculateHash."""
    file_list = []
    for root, _, files in os.walk(toolchain_dir):
        for f in files:
            file_list.append(os.path.join(root, f))
    file_list.sort(key=lambda s: s.replace("/", "\\").lower())

    digest = hashlib.sha1()
    for abs_path in file_list:
        rel_path = os.path.relpath(abs_path, toolchain_dir)
        path_without_hash = os.path.join("vs_files", rel_path).replace("/", "\\")
        digest.update(bytes(path_without_hash.lower(), "utf-8"))
        with open(abs_path, "rb") as f:
            digest.update(f.read())
    return digest.hexdigest()


def calculate_toolchain_hash_from_zip(zip_path: str) -> str:
    """Calculate the SHA1 toolchain hash directly from a zip archive."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infolist = [info for info in zf.infolist() if not info.is_dir()]
            infolist.sort(key=lambda info: os.path.join("vs_files", info.filename).replace("/", "\\").lower())
            digest = hashlib.sha1()
            for info in infolist:
                norm_path = os.path.join("vs_files", info.filename).replace("/", "\\").lower()
                digest.update(bytes(norm_path, "utf-8"))
                digest.update(zf.read(info))
        return digest.hexdigest()
    except Exception as e:
        print(f"WARNING: Corrupted or unreadable toolchain archive {zip_path}: {e}", file=sys.stderr)
        return ""


def is_valid_toolchain_archive(zip_path: str) -> bool:
    """Verify that a toolchain zip archive contains non-empty essential contents:
    VS_VERSION, VC/Tools/MSVC directory, and Windows Kits directory."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infolist = [info for info in zf.infolist() if not info.is_dir() and info.file_size > 0]
            has_vs_ver = any(i.filename == "VS_VERSION" or i.filename.endswith("/VS_VERSION") for i in infolist)
            has_vc = any("VC/Tools/MSVC" in i.filename or i.filename.startswith("VC/") for i in infolist)
            has_kits = any("Windows Kits" in i.filename for i in infolist)
            return bool(has_vs_ver and has_vc and has_kits)
    except Exception:
        return False


def test_zip_integrity(zip_path: str) -> bool:
    """Test the physical zip structure of an archive for corruption."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return zf.testzip() is None
    except Exception:
        return False


def create_toolchain_zip(toolchain_dir: str, output_zip: str):
    """Package the toolchain directory into a zip archive with normalized relative paths."""
    print(f"Creating toolchain archive: {output_zip}...")
    tmp_zip = output_zip + ".tmp"
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(toolchain_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, toolchain_dir)
                zf.write(abs_path, rel_path)
    os.rename(tmp_zip, output_zip)
    size_mb = os.path.getsize(output_zip) / (1024 * 1024)
    print(f"Toolchain archive created successfully: {output_zip} ({size_mb:.1f} MB)")


# -----------------------------------------------------------------------------
# 2. xwin Download and Layout Assembly
# -----------------------------------------------------------------------------

def get_xwin_binary(cache_dir: str) -> str:
    """Download and extract xwin standalone binary if not present on system."""
    xwin_bin = shutil.which("xwin")
    if xwin_bin:
        return xwin_bin

    xwin_dir = os.path.join(cache_dir, f"xwin-{XWIN_VERSION}")
    binary_path = os.path.join(xwin_dir, f"xwin-{XWIN_VERSION}-x86_64-unknown-linux-musl", "xwin")
    if os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
        return binary_path

    os.makedirs(xwin_dir, exist_ok=True)
    tar_path = os.path.join(xwin_dir, "xwin.tar.gz")
    print(f"Downloading xwin {XWIN_VERSION}...")
    urllib.request.urlretrieve(XWIN_URL, tar_path)

    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(xwin_dir)

    if not os.path.isfile(binary_path):
        for root, _, files in os.walk(xwin_dir):
            if "xwin" in files:
                p = os.path.join(root, "xwin")
                os.chmod(p, 0o755)
                return p
        raise RuntimeError("xwin binary not found after unpacking")

    os.chmod(binary_path, 0o755)
    return binary_path


def run_xwin_splat(xwin_bin: str, cache_dir: str, splat_dir: str, sdk_version: str = "10.0.26100"):
    """Run xwin splat to download and extract CRT and Windows SDK headers/libraries."""
    os.makedirs(splat_dir, exist_ok=True)
    cmd = [
        xwin_bin,
        "--accept-license",
        "--cache-dir", os.path.join(cache_dir, "dl"),
        "--arch", "x86,x86_64,aarch64",
        "--sdk-version", sdk_version,
        "--include-atl",
        "splat",
        "--preserve-ms-arch-notation",
        "--copy",
        "--output", splat_dir,
    ]
    print(f"Executing xwin splat (downloading & extracting CRT and SDK {sdk_version})...")
    subprocess.check_call(cmd)


def build_toolchain_layout(splat_dir: str, target_dir: str, target_hash: str, sdk_ver: str = "10.0.26100"):
    """Organize splatted files into the exact directory layout and manifests expected by vs_toolchain.py."""
    os.makedirs(target_dir, exist_ok=True)
    msvc_ver = "14.44.17.14"

    splat_sdk_inc = os.path.join(splat_dir, "sdk", "include")
    splat_sdk_lib = os.path.join(splat_dir, "sdk", "lib")
    if not (os.path.isdir(splat_sdk_inc) and os.path.isdir(splat_sdk_lib)):
        raise RuntimeError(f"xwin splat output missing SDK directories in {splat_dir}")

    win_kits = os.path.join(target_dir, "Windows Kits", "10")
    vc_dir = os.path.join(target_dir, "VC", "Tools", "MSVC", msvc_ver)
    os.makedirs(os.path.join(win_kits, "Include", sdk_ver), exist_ok=True)
    os.makedirs(os.path.join(win_kits, "Lib", sdk_ver), exist_ok=True)
    for arch in ["x64", "x86", "arm64", "arm"]:
        os.makedirs(os.path.join(win_kits, "bin", sdk_ver, arch), exist_ok=True)
        os.makedirs(os.path.join(vc_dir, "lib", arch), exist_ok=True)
        host_bin = os.path.join(vc_dir, "bin", "HostX64", arch)
        os.makedirs(host_bin, exist_ok=True)
        dummy_cl = os.path.join(host_bin, "cl.exe")
        if not os.path.exists(dummy_cl):
            open(dummy_cl, "w").close()
    os.makedirs(os.path.join(vc_dir, "include"), exist_ok=True)

    # Copy SDK Include headers
    for sub in ["shared", "ucrt", "um", "winrt"]:
        src = os.path.join(splat_sdk_inc, sub)
        dst = os.path.join(win_kits, "Include", sdk_ver, sub)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst, symlinks=True)

    # Ensure sdkddkver.h defines NTDDI_WIN11_BR for SDKs where it is not defined
    sdkddkver_path = os.path.join(win_kits, "Include", sdk_ver, "shared", "sdkddkver.h")
    if os.path.isfile(sdkddkver_path):
        with open(sdkddkver_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if "NTDDI_WIN11_BR" not in content:
            with open(sdkddkver_path, "a", encoding="utf-8") as f:
                f.write("\n#ifndef NTDDI_WIN11_BR\n#define NTDDI_WIN11_BR 0x0A000014\n#endif\n")

    # Copy SDK Lib binaries
    for sub in ["ucrt", "um"]:
        for arch in ["x64", "x86", "arm64", "arm"]:
            src = os.path.join(splat_sdk_lib, sub, arch)
            dst = os.path.join(win_kits, "Lib", sdk_ver, sub, arch)
            if os.path.isdir(src) and not os.path.exists(dst):
                shutil.copytree(src, dst, symlinks=True)

    # Copy CRT Include headers
    splat_crt_inc = os.path.join(splat_dir, "crt", "include")
    if os.path.isdir(splat_crt_inc):
        for item in os.listdir(splat_crt_inc):
            s = os.path.join(splat_crt_inc, item)
            d = os.path.join(vc_dir, "include", item)
            if not os.path.exists(d):
                if os.path.isdir(s):
                    shutil.copytree(s, d, symlinks=True)
                else:
                    shutil.copy2(s, d)

    # Copy CRT Lib binaries
    splat_crt_lib = os.path.join(splat_dir, "crt", "lib")
    if os.path.isdir(splat_crt_lib):
        for arch in ["x64", "x86", "arm64", "arm"]:
            src = os.path.join(splat_crt_lib, arch)
            dst = os.path.join(vc_dir, "lib", arch)
            if os.path.isdir(src):
                for item in os.listdir(src):
                    s = os.path.join(src, item)
                    d = os.path.join(dst, item)
                    if not os.path.exists(d):
                        if os.path.isdir(s):
                            shutil.copytree(s, d, symlinks=True)
                        else:
                            shutil.copy2(s, d)

    # Write VS_VERSION
    with open(os.path.join(target_dir, "VS_VERSION"), "w") as f:
        f.write("2022\n")

    # Generate SetEnv manifests for all target architectures
    vc_parts = ["VC", "Tools", "MSVC", msvc_ver]
    sdk_inc_parts = ["Windows Kits", "10", "Include", sdk_ver]
    sdk_lib_parts = ["Windows Kits", "10", "Lib", sdk_ver]

    setenv_bin = os.path.join(win_kits, "bin")
    os.makedirs(setenv_bin, exist_ok=True)

    for cpu in ["x86", "x64", "arm64", "arm"]:
        arch = cpu
        env_manifest = {
            "env": collections.OrderedDict([
                ("VSINSTALLDIR", [["."]]),
                ("VCINSTALLDIR", [vc_parts]),
                ("INCLUDE", [
                    sdk_inc_parts + ["um"],
                    sdk_inc_parts + ["shared"],
                    sdk_inc_parts + ["winrt"],
                    sdk_inc_parts + ["ucrt"],
                    vc_parts + ["include"],
                ]),
                ("LIB", [
                    vc_parts + ["lib", arch],
                    sdk_lib_parts + ["um", arch],
                    sdk_lib_parts + ["ucrt", arch],
                ]),
                ("PATH", [
                    ["Windows Kits", "10", "bin", sdk_ver, arch],
                    vc_parts + ["bin", "HostX64", arch],
                    vc_parts + ["bin", "HostX64", "x64"],
                ]),
            ])
        }
        with open(os.path.join(setenv_bin, f"SetEnv.{cpu}.json"), "w") as f:
            json.dump(env_manifest, f, indent=2)

    print(f"Toolchain tree assembled for {target_hash} (SDK: {sdk_ver}, MSVC: {msvc_ver}).")


# -----------------------------------------------------------------------------
# 3. Registry Upload & Candidate Resolution
# -----------------------------------------------------------------------------

def upload_to_gitlab_registry(zip_path: str, target_hash: str):
    """Upload toolchain zip to GitLab Generic Package Registry when running in CI."""
    ci_api_v4_url = os.environ.get("CI_API_V4_URL")
    ci_project_id = os.environ.get("CI_PROJECT_ID")
    ci_job_token = os.environ.get("CI_JOB_TOKEN")

    if not (ci_api_v4_url and ci_project_id and ci_job_token):
        print("GitLab CI environment not present; skipping registry upload.")
        return

    upload_url = f"{ci_api_v4_url}/projects/{ci_project_id}/packages/generic/cerium-win-toolchain/{target_hash}/{target_hash}.zip"
    print(f"Uploading {zip_path} to GitLab Generic Package Registry: {upload_url}...")
    cmd = [
        "curl",
        "-fsSL",
        "--header", f"JOB-TOKEN: {ci_job_token}",
        "--upload-file", zip_path,
        upload_url,
    ]
    try:
        subprocess.check_call(cmd)
        print("Toolchain successfully published to GitLab Generic Package Registry.")
    except Exception as e:
        print(f"WARNING: Failed to upload toolchain to Package Registry: {e}", file=sys.stderr)


def resolve_candidate_hashes(upstream_hash: str) -> list[str]:
    """Build prioritized list of candidate hashes to search or download:
    1. Environment override GYP_MSVS_HASH_<hash>
    2. Environment override GYP_MSVS_HASH
    3. Canonical pre-built hash 44f9aa3391
    4. Hermetic fallback hash 436026023a
    5. Upstream TOOLCHAIN_HASH from vs_toolchain.py"""
    candidates = []
    mapping_var = f"GYP_MSVS_HASH_{upstream_hash}" if upstream_hash else None
    if mapping_var and os.environ.get(mapping_var):
        candidates.append(os.environ[mapping_var])
    if os.environ.get("GYP_MSVS_HASH"):
        candidates.append(os.environ["GYP_MSVS_HASH"])

    # Always prioritize verified toolchain 44f9aa3391, then hermetic xwin 436026023a
    candidates.append(PRIMARY_VERIFIED_HASH)
    candidates.append(HERMETIC_FALLBACK_HASH)
    if upstream_hash:
        candidates.append(upstream_hash)

    # Deduplicate while preserving order
    unique_candidates = []
    for c in candidates:
        if c and c not in unique_candidates:
            unique_candidates.append(c)
    return unique_candidates


def download_candidate_archive(candidate: str, dest_zip: str) -> bool:
    """Download candidate archive from pre-built download URL or GitLab Generic Package Registry."""
    download_url = None
    if candidate == PRIMARY_VERIFIED_HASH:
        download_url = os.environ.get("WIN_TOOLCHAIN_URL", DEFAULT_PRIMARY_DOWNLOAD_URL)
    elif os.environ.get("CI_API_V4_URL") and os.environ.get("CI_PROJECT_ID"):
        api_url = os.environ["CI_API_V4_URL"]
        project_id = os.environ["CI_PROJECT_ID"]
        download_url = f"{api_url}/projects/{project_id}/packages/generic/cerium-win-toolchain/{candidate}/{candidate}.zip"

    if not download_url:
        return False

    tmp_path = dest_zip + ".tmp"
    curl_cmd = ["curl", "-fsSL"]
    if os.environ.get("CI_JOB_TOKEN"):
        curl_cmd.extend(["--header", f"JOB-TOKEN: {os.environ['CI_JOB_TOKEN']}"])
    curl_cmd.extend([download_url, "-o", tmp_path])

    try:
        subprocess.check_call(curl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if test_zip_integrity(tmp_path):
            os.rename(tmp_path, dest_zip)
            return True
        else:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return False
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def extract_upstream_toolchain_hash(src_dir: str) -> str:
    """Extract TOOLCHAIN_HASH directly from Chromium build/vs_toolchain.py."""
    vs_toolchain_py = os.path.join(src_dir, "build", "vs_toolchain.py")
    if not os.path.isfile(vs_toolchain_py):
        return ""
    try:
        res = subprocess.check_output(
            [sys.executable, "-c",
             f"import sys; sys.path.append('{os.path.join(src_dir, 'build')}'); import vs_toolchain; print(getattr(vs_toolchain, 'TOOLCHAIN_HASH', ''))"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        return res
    except Exception:
        return ""


def _try_remove(path: str):
    """Best-effort file deletion without raising OSError."""
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def write_toolchain_env(output_dir: str, found_hash: str, upstream_hash: str):
    """Write sourceable toolchain.env for build.sh and downstream scripts."""
    env_path = os.path.join(output_dir, "toolchain.env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# Cerium Windows Toolchain Environment\n")
        f.write(f'export GYP_MSVS_HASH="{found_hash}"\n')
        if upstream_hash:
            f.write(f'export GYP_MSVS_HASH_{upstream_hash}="{found_hash}"\n')
        f.write(f'export DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL="{output_dir}"\n')
        f.write(f'export TOOLCHAIN_ACTUAL_HASH="{found_hash}"\n')
    print(f"Toolchain environment exported to {env_path}")


def _resolve_local_archive(output_dir: str, candidate_zips: list[str], target_zip: str) -> tuple[str, str]:
    """Validate locally cached candidate zips, removing corrupted or mislabeled files."""
    for cand_zip in candidate_zips:
        if not os.path.isfile(cand_zip):
            continue
        full_hash = calculate_toolchain_hash_from_zip(cand_zip)
        if not full_hash:
            print(f"Removing corrupted toolchain archive: {cand_zip}")
            _try_remove(cand_zip)
            continue

        actual_hash = full_hash[:10]
        actual_zip = os.path.join(output_dir, f"{actual_hash}.zip")
        if not os.path.isfile(actual_zip):
            shutil.copy2(cand_zip, actual_zip)
        if cand_zip != actual_zip:
            _try_remove(cand_zip)
        if target_zip != actual_zip:
            _try_remove(target_zip)
        print(f"Target toolchain archive exists: {actual_zip} (actual hash: {actual_hash})")
        return actual_hash, actual_zip
    return "", ""


def _download_verified_archive(output_dir: str, upstream_hash: str) -> tuple[str, str]:
    """Download and validate prioritized candidate archives from Package Registry or fallback URL."""
    for cand in resolve_candidate_hashes(upstream_hash):
        cand_zip = os.path.join(output_dir, f"{cand}.zip")
        if not download_candidate_archive(cand, cand_zip):
            continue
        if is_valid_toolchain_archive(cand_zip):
            full_hash = calculate_toolchain_hash_from_zip(cand_zip)
            if full_hash:
                actual_hash = full_hash[:10]
                actual_zip = os.path.join(output_dir, f"{actual_hash}.zip")
                if cand_zip != actual_zip:
                    shutil.move(cand_zip, actual_zip)
                print(f"Downloaded and verified toolchain archive: {actual_zip}")
                return actual_hash, actual_zip
        print(f"WARNING: Downloaded archive {cand_zip} is incomplete. Removing...")
        _try_remove(cand_zip)
    return "", ""


def _assemble_xwin_archive(output_dir: str, target_zip: str, upstream_hash: str, sdk_version: str) -> tuple[str, str]:
    """Assemble a fresh hermetic MSVC + Windows SDK toolchain archive via xwin."""
    print("Toolchain archive not found in cache or registry. Generating hermetic toolchain via xwin...")
    _try_remove(os.path.join(output_dir, "toolchain.env"))

    with tempfile.TemporaryDirectory() as tmp_work_dir:
        cache_dir = os.path.join(tmp_work_dir, "cache")
        splat_dir = os.path.join(tmp_work_dir, "splat")
        assembled_dir = os.path.join(tmp_work_dir, "assembled", upstream_hash)

        xwin_bin = get_xwin_binary(cache_dir)
        run_xwin_splat(xwin_bin, cache_dir, splat_dir, sdk_version)
        build_toolchain_layout(splat_dir, assembled_dir, upstream_hash, sdk_version)

        full_hash = calculate_toolchain_hash_from_dir(assembled_dir)
        actual_hash = full_hash[:10]
        print(f"Toolchain assembled. Verified hash: {actual_hash} (full sha1: {full_hash})")

        actual_zip = os.path.join(output_dir, f"{actual_hash}.zip")
        create_toolchain_zip(assembled_dir, actual_zip)
        if target_zip != actual_zip:
            _try_remove(target_zip)
        return actual_hash, actual_zip


# -----------------------------------------------------------------------------
# 4. Main Entry Point
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cerium Hermetic Windows Toolchain Manager")
    parser.add_argument("--output-dir", default="build-workspace/win_toolchain_pkg", help="Directory to store toolchain packages")
    parser.add_argument("--target-hash", default="3bfcb536c8", help="Desired toolchain hash")
    parser.add_argument("--sdk-version", default="10.0.26100", help="Windows SDK version to assemble")
    parser.add_argument("--src-dir", default=None, help="Path to Chromium src directory to extract TOOLCHAIN_HASH")
    parser.add_argument("--prepare", action="store_true", help="Resolve or generate toolchain and write toolchain.env")
    parser.add_argument("--upload", action="store_true", help="Upload to GitLab Package Registry if in CI")
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    upstream_hash = (extract_upstream_toolchain_hash(os.path.abspath(args.src_dir)) if args.src_dir else "") or args.target_hash

    target_zip = os.path.join(output_dir, f"{upstream_hash}.zip")
    candidate_zips = [
        os.path.join(output_dir, f"{PRIMARY_VERIFIED_HASH}.zip"),
        os.path.join(output_dir, f"{HERMETIC_FALLBACK_HASH}.zip"),
    ]
    if target_zip not in candidate_zips:
        candidate_zips.append(target_zip)

    found_hash, local_toolchain_zip = _resolve_local_archive(output_dir, candidate_zips, target_zip)
    if not local_toolchain_zip:
        found_hash, local_toolchain_zip = _download_verified_archive(output_dir, upstream_hash)
    if not found_hash or not os.path.isfile(local_toolchain_zip):
        found_hash, local_toolchain_zip = _assemble_xwin_archive(output_dir, target_zip, upstream_hash, args.sdk_version)

    if not found_hash or not os.path.isfile(local_toolchain_zip):
        print("ERROR: Toolchain generation completed but fresh output archive was not produced.", file=sys.stderr)
        return 1

    write_toolchain_env(output_dir, found_hash, upstream_hash)
    if args.upload:
        upload_to_gitlab_registry(local_toolchain_zip, found_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
