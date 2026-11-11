import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.android import search_widget


def _setup(mock_brave):
    layout = mock_brave / "android/java/brave-res/layout/quick_action_search_and_bookmark_widget_layout.xml"
    layout.parent.mkdir(parents=True, exist_ok=True)
    layout.write_text('<ImageView android:src="@mipmap/app_icon" />\n')

    view_adapter = mock_brave / "browser/quick_search_engines/android/java/src/org/chromium/brave/browser/quick_search_engines/views/QuickSearchEnginesViewAdapter.java"
    view_adapter.parent.mkdir(parents=True, exist_ok=True)
    view_adapter.write_text("quickSearchViewHolder.mSearchEngineLogo.setImageResource(R.drawable.ic_social_brave_release_favicon_fullheight_color);\n")

    settings_adapter = mock_brave / "browser/quick_search_engines/android/java/src/org/chromium/brave/browser/quick_search_engines/settings/QuickSearchEnginesAdapter.java"
    settings_adapter.parent.mkdir(parents=True, exist_ok=True)
    settings_adapter.write_text("quickSearchEnginesSettingsViewHolder.mSearchEngineLogo.setImageResource(R.drawable.ic_social_brave_release_favicon_fullheight_color);\n")

    return layout, view_adapter, settings_adapter


def test_apply(mock_brave):
    layout, view_adapter, settings_adapter = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    search_widget.apply(ctx)
    assert 'android:src="@drawable/brave_icon_search"' in layout.read_text()
    assert 'R.drawable.ic_brave_icon_search' in view_adapter.read_text()
    assert 'R.drawable.ic_brave_icon_search' in settings_adapter.read_text()


def test_idempotent(mock_brave):
    layout, view_adapter, settings_adapter = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    search_widget.apply(ctx)
    r1 = (layout.read_text(), view_adapter.read_text(), settings_adapter.read_text())
    search_widget.apply(ctx)
    r2 = (layout.read_text(), view_adapter.read_text(), settings_adapter.read_text())
    assert r1 == r2
