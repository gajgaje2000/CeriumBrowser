import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import shields


def _make_files(brave):
    f1 = brave / "components/brave_shields/core/common/features.cc"
    f1.parent.mkdir(parents=True, exist_ok=True)
    f1.write_text(
        'BASE_FEATURE(kBraveAdblockDefault1pBlocking, base::FEATURE_DISABLED_BY_DEFAULT);'
    )
    f2 = brave / "components/brave_shields/core/common/brave_shields_settings_values.h"
    f2.parent.mkdir(parents=True, exist_ok=True)
    f2.write_text('/*default_value=*/ControlType::BLOCK_THIRD_PARTY>;')
    return f1, f2


def test_apply(mock_brave):
    f1, f2 = _make_files(mock_brave)
    ctx = MutatorContext(str(mock_brave))
    shields.apply(ctx)
    assert 'FEATURE_ENABLED_BY_DEFAULT' in f1.read_text()
    assert 'ControlType::BLOCK>;' in f2.read_text()


def test_idempotent(mock_brave):
    f1, f2 = _make_files(mock_brave)
    ctx = MutatorContext(str(mock_brave))
    shields.apply(ctx)
    result1_f1 = f1.read_text()
    result1_f2 = f2.read_text()
    shields.apply(ctx)
    assert f1.read_text() == result1_f1
    assert f2.read_text() == result1_f2
