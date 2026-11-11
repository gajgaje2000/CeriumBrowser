import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.android import expectations


def _setup(mock_src):
    bgn = mock_src / "chrome/android/BUILD.gn"
    bgn.parent.mkdir(parents=True, exist_ok=True)
    bgn.write_text("""group("validate_expectations") {
  deps = []
  deps += [
    ":trichrome_chrome_32_64_bundle",
    ":trichrome_chrome_64_bundle",
  ]
}
""")
    return bgn


def test_apply(mock_brave, mock_src):
    bgn = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True)
    expectations.apply(ctx)
    content = bgn.read_text()
    assert "defined(android_app_secondary_abi)" in content


def test_idempotent(mock_brave, mock_src):
    bgn = _setup(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src), strict=True)
    expectations.apply(ctx)
    first_run = bgn.read_text()
    expectations.apply(ctx)
    assert bgn.read_text() == first_run


def test_without_src(mock_brave):
    ctx = MutatorContext(str(mock_brave), src_dir=None, strict=True)
    expectations.apply(ctx)
