"""Shared pytest fixtures.

The environment variables are set *before* the application is imported so
that the settings singleton picks up an isolated data directory and
database.  Every test therefore runs against its own temporary storage.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="tda-tests-"))
os.environ["ENVIRONMENT"] = "test"
os.environ["DATA_DIR"] = str(TEST_ROOT)
os.environ["UPLOAD_DIR"] = str(TEST_ROOT / "uploads")
os.environ["ARTIFACT_DIR"] = str(TEST_ROOT / "artifacts")
os.environ["DEMO_DIR"] = str(TEST_ROOT / "demo")
os.environ["EXPORT_DIR"] = str(TEST_ROOT / "exports")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ["SEED_DEMO_DATA_ON_STARTUP"] = "false"
os.environ["DEFAULT_PROVIDER"] = "free"
os.environ["SECRET_KEY"] = "test-secret-key-for-encryption-tests"

import sys  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.base import SessionLocal, engine  # noqa: E402
from app.db.models import Base, Dataset  # noqa: E402
from app.demo import generator  # noqa: E402
from app.ingest import store  # noqa: E402


def pytest_sessionfinish(session, exitstatus):  # pragma: no cover - cleanup
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _prepare_database() -> None:
    Base.metadata.create_all(bind=engine)


@pytest.fixture()
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="session")
def demo_files() -> dict:
    """Generate the synthetic demo files once for the whole session."""
    return generator.write_demo_data(settings.demo_dir)


@pytest.fixture()
def demo_datasets(db: Session, demo_files: dict) -> dict[str, Dataset]:
    """Ingest the demo datasets and return them by name."""
    created: dict[str, Dataset] = {}
    for filename, label in (
        ("retail_orders.csv", "Retail Orders"),
        ("customers.csv", "Customers"),
        ("inventory.csv", "Inventory"),
        ("supplier_deliveries.csv", "Supplier Deliveries"),
    ):
        raw = (settings.demo_dir / filename).read_bytes()
        stored = store.create_dataset(db, raw=raw, filename=filename, is_demo=True)
        stored.dataset.name = label
        db.commit()
        created[label] = stored.dataset
    return created


@pytest.fixture()
def orders(demo_datasets: dict[str, Dataset]) -> Dataset:
    return demo_datasets["Retail Orders"]


@pytest.fixture()
def ctx_factory(db):
    """Return a factory that builds a ToolContext scoped to a dataset."""
    from app.core.config import settings
    from app.tools.base import ToolContext

    def factory(dataset_id: str, **kwargs) -> ToolContext:
        return ToolContext(
            db=db,
            settings=settings,
            authorized_dataset_ids=(dataset_id,),
            **kwargs,
        )

    return factory


@pytest.fixture()
def deliveries(demo_datasets: dict[str, Dataset]) -> Dataset:
    return demo_datasets["Supplier Deliveries"]


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def reference_values(demo_files: dict) -> dict:
    return demo_files
