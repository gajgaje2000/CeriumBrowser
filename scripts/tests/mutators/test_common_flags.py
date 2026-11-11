import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import flags

FLAGS_JS = """\
document.addEventListener('DOMContentLoaded', function() {
  // some brave promo code
});
"""

CONTENT_CLIENT_CC = """\
scoped_refptr<base::RefCountedMemory> BraveContentClient::GetDataResourceBytes(
    int resource_id) {
  if (resource_id == IDR_FLAGS_UI_APP_JS) {
    // something
  }
  return ChromeContentClient::GetDataResourceBytes(resource_id);
}"""


def _make_files(brave):
    p1 = brave / "components/flags_ui/resources/brave_flags_overrides.js"
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_text(FLAGS_JS)

    p2 = brave / "common/brave_content_client.cc"
    p2.parent.mkdir(parents=True, exist_ok=True)
    p2.write_text(CONTENT_CLIENT_CC)
    return p1, p2


def test_apply(mock_brave):
    p1, p2 = _make_files(mock_brave)
    ctx = MutatorContext(str(mock_brave))
    flags.apply(ctx)
    assert 'Cerium: Overrides disabled' in p1.read_text()
    assert 'IDR_FLAGS_UI_APP_JS' not in p2.read_text()
    assert 'Direct delegate' in p2.read_text()


def test_idempotent(mock_brave):
    p1, p2 = _make_files(mock_brave)
    ctx = MutatorContext(str(mock_brave))
    flags.apply(ctx)
    s1, s2 = p1.read_text(), p2.read_text()
    flags.apply(ctx)
    assert p1.read_text() == s1
    assert p2.read_text() == s2
