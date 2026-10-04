import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sot.core.config import Config  # noqa: E402
from sot.core.pipeline import ingest  # noqa: E402
from sot.core.store import Store  # noqa: E402

AS_OF = date(2026, 9, 21)


@pytest.fixture(scope="session", autouse=True)
def fixtures():
    if not (ROOT / "fixtures/messy/staff_schedule.pdf").exists():
        import runpy
        runpy.run_path(str(ROOT / "tools/generate_fixtures.py"), run_name="__main__")


@pytest.fixture
def cfg():
    return Config(ROOT / "config/harborview.yaml")


@pytest.fixture
def run(cfg, tmp_path):
    def _run(folder, db="t.db"):
        store = Store(tmp_path / db)
        summary = ingest(cfg, store, [folder], AS_OF)
        return store, summary
    return _run


def issues(store, status="open"):
    return store.query("SELECT * FROM issues WHERE status=?", (status,))
