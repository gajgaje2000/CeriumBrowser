import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.platforms.android import sync


def _setup(mock_brave):
    p_xml = mock_brave / "android/java/brave-res/layout/brave_sync_layout.xml"
    p_xml.parent.mkdir(parents=True, exist_ok=True)
    p_xml.write_text("""<LinearLayout>
            <TextView
               android:layout_width="match_parent"
               android:layout_height="0px"
               android:layout_weight="1.4"
               android:paddingHorizontal="15dip"
               android:text="@string/brave_sync_description_page_1"
               android:gravity="top"
               style="@style/BraveSyncDescriptionTextDefaultRegular" />
           <android.widget.Button android:id="@+id/brave_sync_btn_scan_chain_code"
               android:layout_width="match_parent"
               android:layout_height="wrap_content" />
</LinearLayout>
""")
    return [p_xml]


def test_apply(mock_brave):
    files = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    sync.apply(ctx)

    xml_content = files[0].read_text()
    assert "cerium_sync_self_host_notice" in xml_content
    assert "https://github.com/brave/go-sync" in xml_content
    assert "#brave-override-sync-server-url" in xml_content


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
