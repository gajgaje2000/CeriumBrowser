"""
Windows Native Version Updater & Elevation Fallback Mutator
(scripts/mutators/platforms/windows/version_updater.py)

Implements:
1. System-level restart rename elevation fallback in brave/chromium_src/chrome/browser/first_run/upgrade_util_win.cc.
2. CeriumVersionUpdaterWin in chrome/browser/ui/webui/help/version_updater_win.cc querying GitLab Releases API
   (loaded cleanly from templates/version_updater_win.cc).
3. BUILD.gn dependency wiring in chrome/browser/ui/webui/help/BUILD.gn.
"""

import os
from scripts.mutators.context import MutatorContext

# Path to the standalone C++ implementation template for CeriumVersionUpdaterWin
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
VERSION_UPDATER_TEMPLATE = os.path.join(TEMPLATE_DIR, "version_updater_win.cc")


def load_version_updater_template() -> str:
    """Load the standalone C++ CeriumVersionUpdaterWin source template."""
    with open(VERSION_UPDATER_TEMPLATE, "r", encoding="utf-8") as f:
        return f.read()


def apply(ctx: MutatorContext):
    # 1. System-level restart rename elevation fallback in brave-core
    ctx.replace_in_file(
        "chromium_src/chrome/browser/first_run/upgrade_util_win.cc",
        '#include "chrome/installer/util/app_command.h"',
        '#include "base/command_line.h"\n#include "chrome/installer/util/app_command.h"\n#include "chrome/installer/util/install_util.h"',
    )

    ctx.replace_in_file(
        "chromium_src/chrome/browser/first_run/upgrade_util_win.cc",
        """  Microsoft::WRL::ComPtr<IUnknown> unknown = CreateProcessLauncher();
  if (!unknown) {
    return false;
  }""",
        """  Microsoft::WRL::ComPtr<IUnknown> unknown = CreateProcessLauncher();
  if (!unknown) {
    // Cerium: Fallback for system-level installs when Omaha ProcessLauncher
    // is not installed. Execute setup.exe --rename-chrome-exe elevated.
    installer::AppCommand rename_cmd(installer::kCmdRenameChromeExe, {});
    if (rename_cmd.Initialize(HKEY_LOCAL_MACHINE)) {
      DWORD exit_code = 0;
      if (InstallUtil::ExecuteExeAsAdmin(base::CommandLine::FromString(rename_cmd.command_line()), &exit_code) &&
          exit_code == installer::RENAME_SUCCESSFUL) {
        TRACE_EVENT0("startup", "InvokeGoogleUpdateForRename RENAME_SUCCESSFUL");
        return true;
      }
      LOG(ERROR) << "Fallback elevated rename failed; exit code = " << exit_code;
    }
    return false;
  }""",
    )

    # 2. Add dependencies to chrome/browser/ui/webui/help/BUILD.gn (in Chromium src)
    ctx.replace_in_src(
        "chrome/browser/ui/webui/help/BUILD.gn",
        """      deps += [
        "//chrome/app:generated_resources_grit",
        "//chrome/browser:browser_process",
        "//chrome/browser/first_run",
        "//chrome/browser/google",
        "//content/public/browser",
        "//ui/aura",
        "//ui/base",
        "//ui/gfx",
      ]""",
        """      deps += [
        "//chrome/app:generated_resources_grit",
        "//chrome/browser:browser_process",
        "//chrome/browser/first_run",
        "//chrome/browser/google",
        "//chrome/install_static:install_static_util",
        "//chrome/installer/util:with_no_strings",
        "//content/public/browser",
        "//crypto",
        "//services/network/public/cpp",
        "//ui/aura",
        "//ui/base",
        "//ui/gfx",
      ]""",
        check_token="//chrome/installer/util:with_no_strings",
    )

    # 3. Implement CeriumVersionUpdaterWin in chrome/browser/ui/webui/help/version_updater_win.cc (in Chromium src)
    cerium_version_updater_impl = load_version_updater_template()

    def mutate_version_updater_win(content: str):
        if content == cerium_version_updater_impl:
            return content, False, True
        return cerium_version_updater_impl, True, False

    ctx.mutate_file(
        "chrome/browser/ui/webui/help/version_updater_win.cc",
        mutate_version_updater_win,
        in_src=True,
    )
