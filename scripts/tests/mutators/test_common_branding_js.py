import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import branding_js


def _setup(mock_brave):
    bjs = mock_brave / "build/commands/lib/branding.js"
    bjs.parent.mkdir(parents=True, exist_ok=True)
    bjs.write_text("""  fileMap.add([
    path.join(
      config.braveCoreDir,
      'node_modules',
      '@brave',
      'leo',
      'icons',
      config.getBraveLogoIconName(),
    ),
    dest,
  ])
""")

    about = mock_brave / "browser/resources/settings/br/about_page.ts"
    about.parent.mkdir(parents=True, exist_ok=True)
    about.write_text("""const buildBraveVersionLink = (braveVersion: string, build: string) => {
  const wrapper = document.createElement('a')
  wrapper.setAttribute('href', 'https://brave.com/latest/')
  wrapper.textContent = `Brave ${braveVersion} ${build}`
  return wrapper
}
// updateStatusMessageLink.href = 'https://support.brave.app/hc/en-us/articles/360042816611-Why-isn-t-Brave-updating-automatically-on-Windows-'
// updateStatusMessageLink.href = 'https://community.brave.app?p=update_error'
""")
    return bjs, about


def test_apply(mock_brave):
    bjs, about = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    branding_js.apply(ctx)
    content_bjs = bjs.read_text()
    assert "'product_logo.svg'" in content_bjs
    assert "@brave" not in content_bjs

    content_about = about.read_text()
    assert "`Cerium ${braveVersion} ${build}`" in content_about
    assert "`Brave ${braveVersion} ${build}`" not in content_about
    assert "https://gitlab.com/cerium-browser/cerium/-/releases" in content_about
    assert "https://brave.com/latest/" not in content_about
    assert "https://gitlab.com/cerium-browser/cerium/-/issues" in content_about


def test_idempotent(mock_brave):
    bjs, about = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    branding_js.apply(ctx)
    first_bjs = bjs.read_text()
    first_about = about.read_text()
    branding_js.apply(ctx)
    assert bjs.read_text() == first_bjs
    assert about.read_text() == first_about
