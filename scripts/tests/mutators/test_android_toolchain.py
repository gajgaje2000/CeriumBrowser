import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.android import toolchain


def _setup(mock_src):
    tgni = mock_src / "build/timestamp.gni"
    tgni.parent.mkdir(parents=True, exist_ok=True)
    tgni.write_text("""if (is_android) {
  if (!enable_android_secondary_abi) {
    assert(
        current_toolchain == default_toolchain,
        "Trying to run compute_build_timestamp.py in toolchain: $current_toolchain")
  }
}
""")
    return tgni


def test_apply(mock_brave, mock_src):
    tgni = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True)
    toolchain.apply(ctx)
    content = tgni.read_text()
    assert 'not_needed([ "enable_android_secondary_abi" ])' in content


def test_idempotent(mock_brave, mock_src):
    tgni = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True)
    toolchain.apply(ctx)
    first_run = tgni.read_text()
    toolchain.apply(ctx)
    assert tgni.read_text() == first_run


def test_without_src(mock_brave):
    ctx = MutatorContext(str(mock_brave), src_dir=None, strict=True)
    toolchain.apply(ctx)
