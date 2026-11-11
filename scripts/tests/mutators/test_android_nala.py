import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.android import nala


def _setup(mock_brave):
    p = mock_brave / "android/nala/BUILD.gn"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""template("nala_icon_override") {
  copy(target_name) {
    _source = "$nala_base_path/drawable/${invoker.source}"
    sources = [ _source ]
    outputs = [ "$target_gen_dir/res/drawable/${invoker.dest}" ]
  }
}

copy("nala_icons") {
  sources = []
  foreach(icon, nala_icons) {
    sources +=
        [ "//brave/node_modules/@brave/leo/tokens/android/drawable/$icon" ]
  }
  outputs = [ "$target_gen_dir/res/drawable/{{source_file_part}}" ]
}
""")
    return p


def test_apply(mock_brave):
    p = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    nala.apply(ctx)
    content = p.read_text()
    assert "//brave/app/theme/brave/android/shields_drawables/" in content
    assert "ic_social_brave_outline_favicon_fullheight.xml" in content


def test_idempotent(mock_brave):
    p = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    nala.apply(ctx)
    first_run = p.read_text()
    nala.apply(ctx)
    assert p.read_text() == first_run
