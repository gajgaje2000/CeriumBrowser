import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.windows import toolchain


def _setup(mock_src):
    vs_toolchain = mock_src / "build/vs_toolchain.py"
    vs_toolchain.parent.mkdir(parents=True, exist_ok=True)
    vs_toolchain.write_text(
        "def MountToolchain(toolchain_dir, ciopfs):\n"
        "    if ciopfs:\n"
        "        if True:\n"
        "            subprocess.check_call(\n"
        "                [\n"
        "                    ciopfs,\n"
        "                    '-o',\n"
        "                    'use_ino',\n"
        "                    toolchain_dir + '.ciopfs',\n"
        "                    toolchain_dir,\n"
        "                ]\n"
        "            )\n"
        "\n"
        "def GetToolchainHash():\n"
        "    toolchain_hash_mapping_key = 'GYP_MSVS_HASH_%s' % TOOLCHAIN_HASH\n"
        "    return [os.environ.get(toolchain_hash_mapping_key, TOOLCHAIN_HASH)]\n"
        "\n"
        "def ShouldUpdateToolchain():\n"
        '    """Check if the toolchain should be upgraded."""\n'
        "    if not os.path.exists(json_data_file):\n"
        "        return True\n"
        "    version = '2022'\n"
        "    return version != env_version\n"
    )

    win_build_gn = mock_src / "build/config/win/BUILD.gn"
    win_build_gn.parent.mkdir(parents=True, exist_ok=True)
    win_build_gn.write_text(
        'config("winver") {\n'
        '  defines = [\n'
        '    "NTDDI_VERSION=NTDDI_WIN10_FE",\n'
        '  ]\n'
        '}\n'
    )

    return vs_toolchain, win_build_gn


def test_apply(mock_brave, mock_src):
    vs_toolchain, win_build_gn = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True, target_os="win")
    toolchain.apply(ctx)

    vs_txt = vs_toolchain.read_text()
    assert "NOTE: ciopfs mount skipped" in vs_txt
    assert "os.environ.get('GYP_MSVS_HASH')" in vs_txt
    assert "'44f9aa3391'" in vs_txt
    assert "return not os.path.exists(json_data_file)" in vs_txt

    gn_txt = win_build_gn.read_text()
    assert '"NTDDI_WIN11_BR=0x0A000014",' in gn_txt
    assert '"NTDDI_VERSION=0x0A000014",' in gn_txt


def test_idempotent(mock_brave, mock_src):
    vs_toolchain, win_build_gn = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True, target_os="win")
    toolchain.apply(ctx)
    first = (vs_toolchain.read_text(), win_build_gn.read_text())
    toolchain.apply(ctx)
    second = (vs_toolchain.read_text(), win_build_gn.read_text())
    assert first == second


def test_skips_cleanly_without_src(mock_brave):
    ctx = MutatorContext(str(mock_brave), src_dir=None, strict=True, target_os="win")
    toolchain.apply(ctx)
