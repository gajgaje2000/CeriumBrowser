import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import webui

BUILD_GN = """\
group("grdp") {
  public_deps = [
    ":external_js_bundles",
    "resources/opaque_ke",
    ":some_other_dep",
  ]
}
"""

SOURCES_GNI = """\
brave_resources_extra_grdps = [
  "$root_gen_dir/brave/web-ui-external_js/external_js.grdp",
  "$root_gen_dir/brave/web-ui-opaque_ke/opaque_ke.grdp",
  "$root_gen_dir/brave/web-ui-other/other.grdp",
]
"""


def _make_files(brave):
    p1 = brave / "ui/webui/resources/BUILD.gn"
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_text(BUILD_GN)

    p2 = brave / "ui/webui/resources/sources.gni"
    p2.parent.mkdir(parents=True, exist_ok=True)
    p2.write_text(SOURCES_GNI)
    return p1, p2


def test_apply(mock_brave):
    p1, p2 = _make_files(mock_brave)
    ctx = MutatorContext(str(mock_brave))
    webui.apply(ctx)
    build_content = p1.read_text()
    gni_content = p2.read_text()
    # external_js_bundles must be inside include_polymer block
    assert 'include_polymer' in build_content
    assert ':external_js_bundles' in build_content
    # gni: external_js.grdp inside !is_android && !is_ios
    assert '!is_android' in gni_content
    assert 'external_js.grdp' in gni_content


def test_idempotent(mock_brave):
    p1, p2 = _make_files(mock_brave)
    ctx = MutatorContext(str(mock_brave))
    webui.apply(ctx)
    s1, s2 = p1.read_text(), p2.read_text()
    webui.apply(ctx)
    assert p1.read_text() == s1
    assert p2.read_text() == s2
