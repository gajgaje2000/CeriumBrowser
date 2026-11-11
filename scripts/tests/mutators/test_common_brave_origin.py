import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import brave_origin

UPSTREAM_BRANDING = """\
COMPANY_FULLNAME=Brave Software, Inc.
COMPANY_SHORTNAME=Brave
PRODUCT_FULLNAME=Brave Browser
PRODUCT_SHORTNAME=Brave
PRODUCT_INSTALLER_FULLNAME=Brave Browser Installer
PRODUCT_INSTALLER_SHORTNAME=Brave Installer
"""


def _make_files(brave):
    paths = [
        "app/theme/brave_origin/BRANDING",
        "app/theme/brave_origin/BRANDING.beta",
        "app/theme/brave_origin/BRANDING.development",
        "app/theme/brave_origin/BRANDING.nightly",
    ]
    created = []
    for rel in paths:
        p = brave / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(UPSTREAM_BRANDING)
        created.append(p)
    return created


def test_apply(mock_brave):
    files = _make_files(mock_brave)
    ctx = MutatorContext(str(mock_brave))
    brave_origin.apply(ctx)
    for f in files:
        content = f.read_text()
        assert 'COMPANY_FULLNAME=Cerium Browser Team' in content
        assert 'COMPANY_SHORTNAME=Cerium' in content
        assert 'PRODUCT_INSTALLER_FULLNAME=Cerium Installer' in content


def test_idempotent(mock_brave):
    files = _make_files(mock_brave)
    ctx = MutatorContext(str(mock_brave))
    brave_origin.apply(ctx)
    snapshots = [f.read_text() for f in files]
    brave_origin.apply(ctx)
    for f, snap in zip(files, snapshots):
        assert f.read_text() == snap
