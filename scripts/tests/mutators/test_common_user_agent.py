import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import user_agent

UA_UTILS_CC = """\
constexpr char kBraveBrandNameForCHUA[] = "Brave";
#define BRAVE_GET_USER_AGENT_BRAND_LIST brand = kBraveBrandNameForCHUA;
#define BRAVE_BRAND_VERSION_OVERRIDE_FOR_FULL_BRAND_VERSION_TYPE \\
base::StrCat({ major_version, ".0.0.0" })
"""

CONTENT_BROWSER_CC = """\
blink::UserAgentMetadata BraveContentBrowserClient::GetUserAgentMetadata() {
  blink::UserAgentMetadata metadata;
  metadata.full_version = base::StrCat({"something"});
  return metadata;
}"""

EXCEPTIONS_CC = """\
bool BraveUserAgentExceptions::CanShowBrave(const GURL& url) {
  std::string domain = url.host();
  return !excepted_domains_.contains(domain);
}

bool ShouldHideBraveBrand(const GURL& url) {
  BraveUserAgentExceptions* exceptions = GetInstance();
  return exceptions && !exceptions->CanShowBrave(url);
}"""

VERSION_INFO_CC = """\
std::string GetProductNameAndVersionForReducedUserAgent() {
  return base::StrCat( { "Chrome/", GetMajorVersionNumber(), ".0.0.0" } );
}"""


def _make_brave_files(brave):
    files = {}

    p1 = brave / "chromium_src/components/embedder_support/user_agent_utils.cc"
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_text(UA_UTILS_CC)
    files['ua_utils'] = p1

    p2 = brave / "browser/brave_content_browser_client.cc"
    p2.parent.mkdir(parents=True, exist_ok=True)
    p2.write_text(CONTENT_BROWSER_CC)
    files['content_browser'] = p2

    p3 = brave / "components/brave_user_agent/browser/brave_user_agent_exceptions.cc"
    p3.parent.mkdir(parents=True, exist_ok=True)
    p3.write_text(EXCEPTIONS_CC)
    files['exceptions'] = p3

    return files


def _make_src_files(src):
    p = src / "components/version_info/version_info_with_user_agent.cc"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(VERSION_INFO_CC)
    # has_chromium_src requires 'components' dir
    (src / "components").mkdir(parents=True, exist_ok=True)
    return p


def test_apply(mock_brave, mock_src):
    files = _make_brave_files(mock_brave)
    version_file = _make_src_files(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src))
    user_agent.apply(ctx)

    assert 'maybe_unused' in files['ua_utils'].read_text()
    assert 'Google Chrome' in files['ua_utils'].read_text()
    assert 'full_version' in files['ua_utils'].read_text()
    assert 'standard Chromium / Chrome' in files['content_browser'].read_text()
    assert 'Never show Brave brand' in files['exceptions'].read_text()
    assert 'Always hide Brave brand' in files['exceptions'].read_text()
    assert 'BRAVE_CHROMIUM_VERSION' in version_file.read_text()


def test_idempotent(mock_brave, mock_src):
    files = _make_brave_files(mock_brave)
    version_file = _make_src_files(mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src))
    user_agent.apply(ctx)
    snapshots = {k: v.read_text() for k, v in files.items()}
    snap_ver = version_file.read_text()
    user_agent.apply(ctx)
    for k, v in files.items():
        assert v.read_text() == snapshots[k]
    assert version_file.read_text() == snap_ver
