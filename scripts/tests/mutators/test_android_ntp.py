import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.android import ntp


def _setup_modern(mock_brave):
    p = mock_brave / "browser/ui/android/ntp_widgets/java/src/org/chromium/chrome/browser/ntp/NtpUtil.java"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""class NtpUtil {
    boolean topSites = prefs.readBoolean(PREF_SHOW_TOP_SITES, true);
    boolean stats = prefs.readBoolean(PREF_SHOW_BRAVE_STATS, true);
}
""")
    return p


def test_apply_modern(mock_brave):
    p = _setup_modern(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    ntp.apply(ctx)
    content = p.read_text()
    assert ".readBoolean(PREF_SHOW_TOP_SITES, false);" in content
    assert ".readBoolean(PREF_SHOW_BRAVE_STATS, false);" in content


def test_idempotent(mock_brave):
    p = _setup_modern(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    ntp.apply(ctx)
    first_run = p.read_text()
    ntp.apply(ctx)
    assert p.read_text() == first_run
