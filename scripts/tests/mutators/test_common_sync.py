import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import sync


def _setup(mock_brave):
    p_gn = mock_brave / "components/brave_sync/BUILD.gn"
    p_gn.parent.mkdir(parents=True, exist_ok=True)
    p_gn.write_text("""declare_args() {
  brave_sync_endpoint = "https://sync-v2.brave.com/v2"
}
""")

    p_html = mock_brave / "browser/resources/settings/brave_sync_page/brave_sync_setup.html"
    p_html.parent.mkdir(parents=True, exist_ok=True)
    p_html.write_text("""<div class="sync-setup">
  <div class="content">
    <h1>$i18n{braveSyncSetupTitle}</h1>
    <p>$i18n{braveSyncSetupSubtitle}</p>
    <div class="actions">
    </div>
  </div>
</div>
""")
    return [p_gn, p_html]


def test_apply(mock_brave):
    files = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    sync.apply(ctx)

    gn_content = files[0].read_text()
    assert 'brave_sync_endpoint = "https://127.0.0.1:8295/v2"' in gn_content
    assert "sync-v2.brave.com" not in gn_content

    html_content = files[1].read_text()
    assert "sync-self-host-notice" in html_content
    assert "https://github.com/brave/go-sync" in html_content
    assert "#brave-override-sync-server-url" in html_content


def test_idempotent(mock_brave):
    files = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    sync.apply(ctx)
    first = [f.read_text() for f in files]
    sync.apply(ctx)
    second = [f.read_text() for f in files]
    assert first == second


def test_without_files(mock_brave):
    ctx = MutatorContext(str(mock_brave), strict=False)
    sync.apply(ctx)
