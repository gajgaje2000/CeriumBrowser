import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import devtools


def _setup(mock_src):
    gn_file = mock_src / "third_party/devtools-frontend/src/scripts/build/typescript/ts_library_split.gni"
    gn_file.parent.mkdir(parents=True, exist_ok=True)
    gn_file.write_text("""template("ts_library_split") {
  public_inputs = filter_include(_all_sources, [ "*.ts" ])
}
""")
    return gn_file


def test_apply(mock_brave, mock_src):
    gn_file = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True)
    devtools.apply(ctx)
    content = gn_file.read_text()
    assert 'not_needed([ "public_inputs" ])' in content


def test_idempotent(mock_brave, mock_src):
    gn_file = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True)
    devtools.apply(ctx)
    first_run = gn_file.read_text()
    devtools.apply(ctx)
    assert gn_file.read_text() == first_run
