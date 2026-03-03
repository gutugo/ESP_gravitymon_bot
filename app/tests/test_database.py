from datetime import datetime, timedelta, timezone

import aiosqlite
import database


# ── Schema ──────────────────────────────────────────────────────────

async def test_init_db_creates_tables(tmp_db):
    async with aiosqlite.connect(tmp_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = sorted(row[0] for row in await cursor.fetchall())
    for expected in ["allowed_users", "alerts_sent", "devices", "readings", "subscribers"]:
        assert expected in tables


# ── Devices ─────────────────────────────────────────────────────────

async def test_upsert_device_insert(tmp_db):
    await database.upsert_device("d1", "Device1", interval_sec=600)
    devices = await database.get_all_devices()
    assert len(devices) == 1
    assert devices[0]["device_id"] == "d1"
    assert devices[0]["name"] == "Device1"
    assert devices[0]["interval_sec"] == 600


async def test_upsert_device_update(tmp_db):
    await database.upsert_device("d1", "Old", interval_sec=300)
    await database.upsert_device("d1", "New", interval_sec=600)
    devices = await database.get_all_devices()
    assert len(devices) == 1
    assert devices[0]["name"] == "New"
    assert devices[0]["interval_sec"] == 600


async def test_get_default_device(sample_device):
    device = await database.get_default_device()
    assert device is not None
    assert device["device_id"] == "abc123"


async def test_get_device_interval_default(tmp_db):
    val = await database.get_device_interval("nonexistent")
    assert val == 900


async def test_get_device_interval_custom(tmp_db):
    await database.upsert_device("x1", "X", interval_sec=120)
    assert await database.get_device_interval("x1") == 120


# ── Readings ────────────────────────────────────────────────────────

async def test_insert_and_get_latest(sample_reading):
    reading = await database.get_latest_reading("abc123")
    assert reading is not None
    assert reading["temperature"] == 20.5
    assert reading["gravity"] == 1.050


async def test_get_latest_reading_none(tmp_db):
    assert await database.get_latest_reading("no_device") is None


async def test_get_readings_for_period(sample_reading):
    rows = await database.get_readings_for_period("abc123", "day")
    assert len(rows) == 1


async def test_get_readings_for_period_empty(sample_device):
    rows = await database.get_readings_for_period("abc123", "hour")
    assert rows == []


async def test_get_readings_for_date_range(sample_reading):
    now = datetime.now(timezone.utc)
    rows = await database.get_readings_for_date_range(
        "abc123", now - timedelta(hours=1), now + timedelta(hours=1)
    )
    assert len(rows) == 1


# ── Subscribers ─────────────────────────────────────────────────────

async def test_subscribe_and_query(tmp_db):
    await database.subscribe(100)
    assert await database.is_subscribed(100) is True
    subs = await database.get_all_subscribers()
    assert 100 in subs


async def test_unsubscribe(tmp_db):
    await database.subscribe(100)
    await database.unsubscribe(100)
    assert await database.is_subscribed(100) is False


async def test_subscribe_idempotent(tmp_db):
    await database.subscribe(100)
    await database.subscribe(100)
    subs = await database.get_all_subscribers()
    assert subs.count(100) == 1


# ── Alerts ──────────────────────────────────────────────────────────

async def test_should_send_alert_fresh(sample_device):
    assert await database.should_send_alert("abc123", "battery_low") is True


async def test_should_send_alert_cooldown(sample_device):
    await database.record_alert_sent("abc123", "battery_low")
    assert await database.should_send_alert("abc123", "battery_low", cooldown_hours=6) is False


async def test_cleanup_old_alerts(sample_device):
    await database.record_alert_sent("abc123", "battery_low")
    # Manually backdate the alert
    async with aiosqlite.connect(database.DATABASE_URL) as db:
        old = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute("UPDATE alerts_sent SET sent_at = ?", (old,))
        await db.commit()
    await database.cleanup_old_alerts(days=30)
    assert await database.should_send_alert("abc123", "battery_low") is True


# ── 24h Stats ───────────────────────────────────────────────────────

async def test_get_24h_stats(sample_reading):
    stats = await database.get_24h_stats("abc123")
    assert stats is not None
    assert stats["reading_count"] == 1
    assert stats["temp_avg"] == 20.5


async def test_get_24h_stats_no_data(sample_device):
    stats = await database.get_24h_stats("abc123")
    assert stats is None


async def test_get_first_reading_24h(sample_reading):
    r = await database.get_first_reading_24h("abc123")
    assert r is not None
    assert r["gravity"] == 1.050


# ── Expected readings (pure function) ──────────────────────────────

def test_expected_readings_count_default():
    assert database.get_expected_readings_count(900) == 96


def test_expected_readings_count_custom():
    assert database.get_expected_readings_count(300) == 288


# ── Avg interval ────────────────────────────────────────────────────

async def test_get_avg_interval_single_reading(sample_reading):
    now = datetime.now(timezone.utc)
    result = await database.get_avg_interval(
        "abc123", now - timedelta(hours=1), now + timedelta(hours=1)
    )
    # Only 1 reading → None
    assert result is None


async def test_get_avg_interval_multiple(sample_device):
    # Insert two readings manually
    async with aiosqlite.connect(database.DATABASE_URL) as db:
        now = datetime.now(timezone.utc)
        t1 = (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t2 = now.strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO readings (device_id, timestamp, temperature, gravity, battery) VALUES (?,?,?,?,?)",
            ("abc123", t1, 20, 1.05, 3.8),
        )
        await db.execute(
            "INSERT INTO readings (device_id, timestamp, temperature, gravity, battery) VALUES (?,?,?,?,?)",
            ("abc123", t2, 21, 1.04, 3.7),
        )
        await db.commit()

    result = await database.get_avg_interval(
        "abc123", now - timedelta(hours=1), now + timedelta(hours=1)
    )
    assert result is not None
    assert 1700 < result < 1900  # ~30 minutes = 1800s


# ── Allowed users ──────────────────────────────────────────────────

async def test_add_and_get_allowed_users(tmp_db):
    assert await database.add_allowed_user(500) is True
    users = await database.get_allowed_users()
    assert 500 in users


async def test_add_allowed_user_duplicate(tmp_db):
    await database.add_allowed_user(500)
    assert await database.add_allowed_user(500) is False


async def test_remove_allowed_user(tmp_db):
    await database.add_allowed_user(500)
    assert await database.remove_allowed_user(500) is True
    assert 500 not in await database.get_allowed_users()


async def test_remove_allowed_user_not_found(tmp_db):
    assert await database.remove_allowed_user(999) is False


async def test_seed_allowed_users(tmp_db):
    await database.seed_allowed_users([10, 20, 30])
    users = await database.get_allowed_users()
    assert set(users) == {10, 20, 30}


async def test_seed_allowed_users_skips_when_not_empty(tmp_db):
    await database.add_allowed_user(1)
    await database.seed_allowed_users([10, 20])
    users = await database.get_allowed_users()
    assert users == [1]


# ── Watched devices ──────────────────────────────────────────────

async def test_device_watched_default(tmp_db):
    await database.upsert_device("d1", "Dev1")
    devices = await database.get_all_devices(watched_only=False)
    assert devices[0]["watched"] == 1


async def test_set_device_unwatched(tmp_db):
    await database.upsert_device("d1", "Dev1")
    await database.set_device_watched("d1", False)
    devices = await database.get_all_devices(watched_only=False)
    assert devices[0]["watched"] == 0


async def test_get_all_devices_watched_only(tmp_db):
    await database.upsert_device("d1", "Watched")
    await database.upsert_device("d2", "Unwatched")
    await database.set_device_watched("d2", False)
    devices = await database.get_all_devices(watched_only=True)
    assert len(devices) == 1
    assert devices[0]["device_id"] == "d1"


async def test_get_all_devices_all(tmp_db):
    await database.upsert_device("d1", "Watched")
    await database.upsert_device("d2", "Unwatched")
    await database.set_device_watched("d2", False)
    devices = await database.get_all_devices(watched_only=False)
    assert len(devices) == 2


async def test_get_default_device_skips_unwatched(tmp_db):
    await database.upsert_device("d1", "Unwatched")
    await database.set_device_watched("d1", False)
    assert await database.get_default_device() is None


async def test_set_device_watched_rewatch(tmp_db):
    await database.upsert_device("d1", "Dev1")
    await database.set_device_watched("d1", False)
    await database.set_device_watched("d1", True)
    devices = await database.get_all_devices(watched_only=True)
    assert len(devices) == 1
