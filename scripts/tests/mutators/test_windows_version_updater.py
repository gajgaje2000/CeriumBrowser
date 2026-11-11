import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.windows import version_updater


def _setup(mock_brave, mock_src):
    upgrade_cc = mock_brave / "chromium_src/chrome/browser/first_run/upgrade_util_win.cc"
    upgrade_cc.parent.mkdir(parents=True, exist_ok=True)
    upgrade_cc.write_text(
        '#include "chrome/installer/util/app_command.h"\n'
        "bool InvokeGoogleUpdateForRename() {\n"
        "  Microsoft::WRL::ComPtr<IUnknown> unknown = CreateProcessLauncher();\n"
        "  if (!unknown) {\n"
        "    return false;\n"
        "  }\n"
        "  return true;\n"
        "}\n"
    )

    help_gn = mock_src / "chrome/browser/ui/webui/help/BUILD.gn"
    help_gn.parent.mkdir(parents=True, exist_ok=True)
    help_gn.write_text(
        'if (is_win) {\n'
        '      deps += [\n'
        '        "//chrome/app:generated_resources_grit",\n'
        '        "//chrome/browser:browser_process",\n'
        '        "//chrome/browser/first_run",\n'
        '        "//chrome/browser/google",\n'
        '        "//content/public/browser",\n'
        '        "//ui/aura",\n'
        '        "//ui/base",\n'
        '        "//ui/gfx",\n'
        '      ]\n'
        '}\n'
    )

    updater_cc = mock_src / "chrome/browser/ui/webui/help/version_updater_win.cc"
    updater_cc.parent.mkdir(parents=True, exist_ok=True)
    updater_cc.write_text("// upstream chromium version updater\n")

    return upgrade_cc, help_gn, updater_cc


def test_apply(mock_brave, mock_src):
    upgrade_cc, help_gn, updater_cc = _setup(mock_brave, mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True, target_os="win")
    version_updater.apply(ctx)

    upgrade_txt = upgrade_cc.read_text()
    assert '#include "base/command_line.h"' in upgrade_txt
    assert '#include "chrome/installer/util/install_util.h"' in upgrade_txt
    assert "InstallUtil::ExecuteExeAsAdmin" in upgrade_txt

    gn_txt = help_gn.read_text()
    assert '"//chrome/install_static:install_static_util",' in gn_txt
    assert '"//chrome/installer/util:with_no_strings",' in gn_txt
    assert '"//crypto",' in gn_txt

    assert updater_cc.read_text() == version_updater.load_version_updater_template()
    assert "Cerium Browser" in updater_cc.read_text()


def test_idempotent(mock_brave, mock_src):
    upgrade_cc, help_gn, updater_cc = _setup(mock_brave, mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True, target_os="win")
    version_updater.apply(ctx)
    first = (upgrade_cc.read_text(), help_gn.read_text(), updater_cc.read_text())
    version_updater.apply(ctx)
    second = (upgrade_cc.read_text(), help_gn.read_text(), updater_cc.read_text())
    assert first == second
