import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.android import toolbar


def _setup(mock_brave):
    btc = mock_brave / "android/java/org/chromium/chrome/browser/toolbar/bottom/BottomToolbarConfiguration.java"
    btc.parent.mkdir(parents=True, exist_ok=True)
    btc.write_text("""class BottomToolbarConfiguration {
    public static boolean isToolbarEnabled() {
        boolean val = prefs.readBoolean(BravePreferenceKeys.BRAVE_BOTTOM_TOOLBAR_ENABLED_KEY, true);
        boolean enable = true;
        return val && enable;
    }

    private static boolean isSmallScreen() {
        return false;
    }
}
""")
    return btc


def test_apply(mock_brave):
    btc = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    toolbar.apply(ctx)
    content = btc.read_text()
    assert ".readBoolean(BravePreferenceKeys.BRAVE_BOTTOM_TOOLBAR_ENABLED_KEY, false);" in content
    assert "boolean enable = false;" in content
    assert '@SuppressWarnings("unused")' in content


def test_idempotent(mock_brave):
    btc = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    toolbar.apply(ctx)
    first_run = btc.read_text()
    toolbar.apply(ctx)
    assert btc.read_text() == first_run
