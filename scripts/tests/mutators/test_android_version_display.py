import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.android import version_display


def _setup(mock_src):
    vgni = mock_src / "chrome/version.gni"
    vgni.parent.mkdir(parents=True, exist_ok=True)
    vgni.write_text("  chrome_version_name = chrome_version_full\n")
    return vgni


def test_apply(mock_brave, mock_src):
    vgni = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True)
    version_display.apply(ctx)
    assert "$chrome_version_minor.$chrome_version_build.$chrome_version_patch" in vgni.read_text()


def test_idempotent(mock_brave, mock_src):
    vgni = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True)
    version_display.apply(ctx)
    r1 = vgni.read_text()
    version_display.apply(ctx)
    r2 = vgni.read_text()
    assert r1 == r2


def test_without_src(mock_brave):
    ctx = MutatorContext(str(mock_brave), src_dir=None, strict=True)
    version_display.apply(ctx)
