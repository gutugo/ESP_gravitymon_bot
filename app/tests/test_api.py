import pytest
from httpx import ASGITransport, AsyncClient

import database


@pytest.fixture()
async def client(tmp_db, monkeypatch):
    """Create an httpx AsyncClient wired to the FastAPI app."""
    # Import after tmp_db patches DATABASE_URL
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


VALID_PAYLOAD = {
    "name": "TestESP",
    "ID": "esp001",
    "temperature": 21.0,
    "temp_units": "C",
    "gravity": 1.048,
    "battery": 3.85,
    "RSSI": -60,
    "interval": 900,
}


async def test_health_check(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_webhook_stores_data(client):
    resp = await client.post("/api/v1/webhook", json=VALID_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["device_id"] == "esp001"

    # Verify data persisted
    reading = await database.get_latest_reading("esp001")
    assert reading is not None
    assert reading["temperature"] == 21.0


async def test_webhook_with_token_auth(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "api_token", "secret123")

    # Missing token → 401
    resp = await client.post("/api/v1/webhook", json=VALID_PAYLOAD)
    assert resp.status_code == 401

    # Wrong token → 401
    resp = await client.post(
        "/api/v1/webhook",
        json=VALID_PAYLOAD,
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401

    # Correct token → 200
    resp = await client.post(
        "/api/v1/webhook",
        json=VALID_PAYLOAD,
        headers={"Authorization": "Bearer secret123"},
    )
    assert resp.status_code == 200


async def test_list_devices_empty(client):
    resp = await client.get("/api/v1/devices")
    assert resp.status_code == 200
    assert resp.json()["devices"] == []


async def test_list_devices_after_webhook(client):
    await client.post("/api/v1/webhook", json=VALID_PAYLOAD)
    resp = await client.get("/api/v1/devices")
    devices = resp.json()["devices"]
    assert len(devices) == 1
    assert devices[0]["device_id"] == "esp001"


async def test_device_status(client):
    await client.post("/api/v1/webhook", json=VALID_PAYLOAD)
    resp = await client.get("/api/v1/devices/esp001/status")
    assert resp.status_code == 200
    assert resp.json()["gravity"] == 1.048


async def test_device_status_404(client):
    resp = await client.get("/api/v1/devices/nonexistent/status")
    assert resp.status_code == 404


async def test_readings_invalid_period(client):
    resp = await client.get("/api/v1/devices/x/readings?period=year")
    assert resp.status_code == 400
