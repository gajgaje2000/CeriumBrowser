import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]  # scripts/tests -> scripts -> repo_root
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def mock_brave(tmp_path):
    brave = tmp_path / "brave"
    brave.mkdir()
    return brave


@pytest.fixture
def mock_src(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "components").mkdir()
    (src / "chrome").mkdir()
    return src
