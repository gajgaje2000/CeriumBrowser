import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.android import resources


def _setup(mock_brave):
    p = mock_brave / "android/brave_java_resources.gni"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""brave_base_module_resources = [
  "java/res_chromium_base/drawable/sample.xml",
]
""")
    return p


def test_apply(mock_brave):
    p = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    resources.apply(ctx)
    content = p.read_text()
    assert "mipmap-anydpi-v26/app_icon.xml" in content
    assert "mipmap-anydpi-v26/layered_app_icon.xml" in content


def test_idempotent(mock_brave):
    p = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    resources.apply(ctx)
    first_run = p.read_text()
    resources.apply(ctx)
    assert p.read_text() == first_run
