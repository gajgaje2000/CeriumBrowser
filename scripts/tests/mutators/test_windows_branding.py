import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.windows import branding


def _setup(mock_brave):
    modes_h = mock_brave / "chromium_src/chrome/install_static/chromium_install_modes.h"
    modes_h.parent.mkdir(parents=True, exist_ok=True)
    modes_h.write_text("""inline constexpr wchar_t kCompanyPathName[] = L"BraveSoftware";
inline constexpr wchar_t kProductPathName[] = L"Brave-Origin";
inline constexpr wchar_t kProductPathName[] = L"Brave-Browser";
inline constexpr wchar_t kProductPathName[] = L"Brave-Browser-Development";
.base_app_name = L"Brave Origin",
.base_app_id = L"BraveOrigin",
.browser_prog_id_prefix = L"BraveOHTML",
.browser_prog_id_description =
            L"Brave Origin HTML Document",
.pdf_prog_id_prefix = L"BraveOPDF",
.pdf_prog_id_description =
            L"Brave Origin PDF Document",
.base_app_name = L"Brave",
.base_app_id = L"Brave",
.browser_prog_id_prefix = L"BraveHTML",
.browser_prog_id_description =
            L"Brave HTML Document",
.pdf_prog_id_prefix = L"BravePDF",
.pdf_prog_id_description =
            L"Brave PDF Document",
""")

    shell_cc = mock_brave / "installer/util/brave_shell_util.cc"
    shell_cc.parent.mkdir(parents=True, exist_ok=True)
    shell_cc.write_text("""std::wstring GetProgIdForFileType() {
  switch (install_static::GetChromeChannel()) {
    case version_info::Channel::STABLE:
      return L"BraveFile";
    case version_info::Channel::BETA:
      return L"BraveBFile";
    case version_info::Channel::DEV:
      return L"BraveDFile";
    case version_info::Channel::CANARY:
      return L"BraveSSFile";
    default:
      break;
  }
}
""")

    # Section 3 Windows Updater & Installer Registry files
    f1 = mock_brave / "chromium_src/chrome/installer/util/google_update_constants.cc"
    f1.parent.mkdir(parents=True, exist_ok=True)
    f1.write_text("""const wchar_t kGoogleUpdateSetupExe[] = L"BraveUpdateSetup.exe";
const wchar_t kRegPathClients[] = L"Software\\\\BraveSoftware\\\\Update\\\\Clients";
const wchar_t kRegPathClientState[] =
    L"Software\\\\BraveSoftware\\\\Update\\\\ClientState";
const wchar_t kRegPathClientStateMedium[] =
    L"Software\\\\BraveSoftware\\\\Update\\\\ClientStateMedium";
const wchar_t kRegPathGoogleUpdate[] = L"Software\\\\BraveSoftware\\\\Update";
""")

    f2 = mock_brave / "chromium_src/chrome/install_static/install_modes.cc"
    f2.parent.mkdir(parents=True, exist_ok=True)
    f2.write_text("""L"Software\\\\BraveSoftware\\\\Update\\\\Clients\\\\"
L"Software\\\\BraveSoftware\\\\Update\\\\ClientState\\\\"
L"Software\\\\BraveSoftware\\\\Update\\\\ClientStateMedium\\\\"
""")

    f3 = mock_brave / "chromium_src/chrome/installer/mini_installer/mini_installer_constants.cc"
    f3.parent.mkdir(parents=True, exist_ok=True)
    f3.write_text("""const wchar_t kClientsKeyBase[] = L"Software\\\\BraveSoftware\\\\Update\\\\Clients\\\\";
const wchar_t kClientStateKeyBase[] =
    L"Software\\\\BraveSoftware\\\\Update\\\\ClientState\\\\";
const wchar_t kCleanupRegistryKey[] =
    L"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\Brave";
const wchar_t kClientsKeyBase[] = L"Software\\\\Brave-Browser-Development";
const wchar_t kClientStateKeyBase[] = L"Software\\\\Brave-Browser-Development";
const wchar_t kCleanupRegistryKey[] = L"Software\\\\Brave-Browser-Development";
""")

    f4 = mock_brave / "chromium_src/chrome/installer/launcher_support/chrome_launcher_support.cc"
    f4.parent.mkdir(parents=True, exist_ok=True)
    f4.write_text("""const wchar_t kInstallationRegKey[] =
    L"Software\\\\BraveSoftware\\\\Update\\\\ClientState";
""")

    f5 = mock_brave / "chromium_src/chrome/browser/component_updater/updater_state_win.cc"
    f5.parent.mkdir(parents=True, exist_ok=True)
    f5.write_text("""const wchar_t kGoogleUpdatePoliciesKey[] =
    L"SOFTWARE\\\\Policies\\\\BraveSoftware\\\\Update";
const wchar_t kRegPathGoogleUpdate[] = L"Software\\\\BraveSoftware\\\\Update";
const wchar_t kRegPathClientsGoogleUpdate[] =
    L"Software\\\\BraveSoftware\\\\Update\\\\Clients\\\\"
""")

    f6 = mock_brave / "chromium_src/chrome/installer/gcapi/google_update_util.cc"
    f6.parent.mkdir(parents=True, exist_ok=True)
    f6.write_text("""L"Software\\\\BraveSoftware\\\\Update\\\\Clients\\\\"
L"Software\\\\BraveSoftware\\\\Update\\\\ClientState\\\\"
""")

    return modes_h, shell_cc, [f1, f2, f3, f4, f5, f6]


def test_apply(mock_brave):
    modes_h, shell_cc, extra_files = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    branding.apply(ctx)
    assert 'L"Cerium"' in modes_h.read_text()
    assert 'return L"CeriumFile";' in shell_cc.read_text()
    for f in extra_files:
        assert "Cerium" in f.read_text()
        assert "BraveSoftware" not in f.read_text()


def test_idempotent(mock_brave):
    modes_h, shell_cc, extra_files = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    branding.apply(ctx)
    r1 = (modes_h.read_text(), shell_cc.read_text(), [f.read_text() for f in extra_files])
    branding.apply(ctx)
    r2 = (modes_h.read_text(), shell_cc.read_text(), [f.read_text() for f in extra_files])
    assert r1 == r2
