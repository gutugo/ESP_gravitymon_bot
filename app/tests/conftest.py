import os
import sys
import tempfile

import pytest

# Ensure app/ is on sys.path so bare imports like `import database` work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Must set env vars BEFORE importing config (pydantic reads them at import time)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-123")
os.environ.setdefault("MASTER_ADMIN", "111")
os.environ.setdefault("ALLOWED_USERS", "111,222")
os.environ.setdefault("API_TOKEN", "")

import database
from config import settings


@pytest.fixture()
async def tmp_db(tmp_path, monkeypatch):
    """Create a temporary SQLite database and patch DATABASE_URL."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(database, "DATABASE_URL", db_path)
    await database.init_db()
    return db_path


@pytest.fixture()
async def sample_device(tmp_db):
    """Insert a sample device and return its info."""
    await database.upsert_device("abc123", "TestDevice", interval_sec=900)
    return {"device_id": "abc123", "name": "TestDevice"}


@pytest.fixture()
async def sample_reading(sample_device):
    """Insert a sample reading and return it."""
    await database.insert_reading(
        device_id="abc123",
        temperature=20.5,
        temp_unit="C",
        gravity=1.050,
        gravity_unit="G",
        battery=3.89,
        angle=45.0,
        rssi=-65,
        interval_sec=900,
    )
    return {
        "device_id": "abc123",
        "temperature": 20.5,
        "gravity": 1.050,
        "battery": 3.89,
    }
