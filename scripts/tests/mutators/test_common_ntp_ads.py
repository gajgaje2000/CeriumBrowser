import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import ntp_ads


def _make_files(brave, src=None):
    p1 = brave / "components/brave_ads/core/internal/prefs/pref_registry.cc"
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_text('registry->RegisterBooleanPref(prefs::kSponsoredEnabled, true);')

    p2 = brave / "components/ntp_background_images/common/view_counter_pref_registry.cc"
    p2.parent.mkdir(parents=True, exist_ok=True)
    p2.write_text('registry->RegisterBooleanPref(prefs::kNewTabPageShowBackgroundImage, true);')

    p3 = brave / "browser/brave_profile_prefs.cc"
    p3.parent.mkdir(parents=True, exist_ok=True)
    p3.write_text(
        'registry->RegisterBooleanPref(kNewTabPageShowStats, true);\n'
        '  registry->SetDefaultPrefValue(ntp_prefs::kNtpCustomLinksVisible,\n'
        '                                base::Value(false));\n'
        '  registry->RegisterIntegerPref(\n'
        '      kNewTabPageShowsOptions,\n'
        '      static_cast<int>(NewTabPageShowsOptions::kDashboard));'
    )

    files = [p1, p2, p3]

    if src is not None:
        p4 = src / "chrome/browser/prefs/browser_prefs.cc"
        p4.parent.mkdir(parents=True, exist_ok=True)
        p4.write_text('registry->RegisterBooleanPref(ntp_prefs::kNtpShortcutsVisible, true);')
        # Also create most_visited file
        p5 = src / "chrome/browser/ui/webui/cr_components/most_visited/most_visited_pref_observer.cc"
        p5.parent.mkdir(parents=True, exist_ok=True)
        p5.write_text('registry->RegisterBooleanPref(ntp_prefs::kNtpShortcutsVisible, true);')
        # Create components dir so has_chromium_src() returns True
        (src / "components").mkdir(parents=True, exist_ok=True)
        files += [p4, p5]

    return files


def test_apply(mock_brave, mock_src):
    files = _make_files(mock_brave, mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src))
    ntp_ads.apply(ctx)
    assert 'kSponsoredEnabled, false' in files[0].read_text()
    assert 'kNewTabPageShowBackgroundImage, false' in files[1].read_text()
    assert 'kNewTabPageShowStats, false' in files[2].read_text()
    assert 'NewTabPageShowsOptions::kBlankpage' in files[2].read_text()
    assert 'kNtpShortcutsVisible, false' in files[3].read_text()


def test_idempotent(mock_brave, mock_src):
    files = _make_files(mock_brave, mock_src)
    ctx = MutatorContext(str(mock_brave), src_dir=str(mock_src))
    ntp_ads.apply(ctx)
    snapshots = [f.read_text() for f in files]
    ntp_ads.apply(ctx)
    for f, snap in zip(files, snapshots):
        assert f.read_text() == snap
