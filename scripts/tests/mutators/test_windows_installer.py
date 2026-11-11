import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.windows import installer


def _setup(mock_brave):
    worker_cc = mock_brave / "chromium_src/chrome/installer/setup/install_worker.cc"
    worker_cc.parent.mkdir(parents=True, exist_ok=True)
    worker_cc.write_text("""void UpdateBraveVpn(const base::FilePath& target_path,
                    const base::Version& new_version,
                    WorkItemList* install_list) {
  if (brave_vpn::IsBraveVPNHelperServiceInstalled()) {
    return;
  }
}
""")

    mini_cc = mock_brave / "chromium_src/chrome/installer/mini_installer/mini_installer.cc"
    mini_cc.parent.mkdir(parents=True, exist_ok=True)
    mini_cc.write_text("""  const bool result = RegKey::ReadSZValue( \\
      HKEY_CURRENT_USER, L"Software\\\\BraveSoftware\\\\Promo", \\
      L"StubInstallerPath", value, _countof(value)); \\
""")
    return worker_cc, mini_cc


def test_apply(mock_brave):
    worker_cc, mini_cc = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    installer.apply(ctx)
    text = worker_cc.read_text()
    assert "// Cerium: Disable VPN NT background service registration" in text
    assert "IsBraveVPNHelperServiceInstalled" not in text
    assert "/* Cerium: Skip promo registry read */" in mini_cc.read_text()


def test_idempotent(mock_brave):
    worker_cc, mini_cc = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    installer.apply(ctx)
    r1 = (worker_cc.read_text(), mini_cc.read_text())
    installer.apply(ctx)
    r2 = (worker_cc.read_text(), mini_cc.read_text())
    assert r1 == r2
