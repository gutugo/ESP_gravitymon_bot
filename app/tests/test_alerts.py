from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import database
from alerts import _format_duration, check_and_send_alerts, check_device_offline


# ── _format_duration ────────────────────────────────────────────────

def test_format_duration_minutes():
    assert _format_duration(300) == "5мин"


def test_format_duration_hours_minutes():
    assert _format_duration(3900) == "1ч 5мин"


def test_format_duration_exact_hour():
    assert _format_duration(3600) == "1ч 0мин"


# ── check_and_send_alerts ──────────────────────────────────────────

async def test_alert_critical_battery(sample_device):
    await database.subscribe(100)
    with patch("alerts.send_telegram_message", new_callable=AsyncMock) as mock_send:
        await check_and_send_alerts("abc123", "TestDevice", battery=3.0)
    mock_send.assert_called_once()
    text = mock_send.call_args[0][1]
    assert "КРИТИЧЕСКОЕ" in text


async def test_alert_low_battery(sample_device):
    await database.subscribe(100)
    with patch("alerts.send_telegram_message", new_callable=AsyncMock) as mock_send:
        await check_and_send_alerts("abc123", "TestDevice", battery=3.2)
    mock_send.assert_called_once()
    text = mock_send.call_args[0][1]
    assert "Предупреждение" in text


async def test_alert_normal_battery(sample_device):
    await database.subscribe(100)
    with patch("alerts.send_telegram_message", new_callable=AsyncMock) as mock_send:
        await check_and_send_alerts("abc123", "TestDevice", battery=3.9)
    mock_send.assert_not_called()


async def test_alert_cooldown_skips(sample_device):
    await database.subscribe(100)
    with patch("alerts.send_telegram_message", new_callable=AsyncMock) as mock_send:
        await check_and_send_alerts("abc123", "TestDevice", battery=3.0)
        mock_send.reset_mock()
        await check_and_send_alerts("abc123", "TestDevice", battery=3.0)
    mock_send.assert_not_called()


async def test_alert_no_subscribers(sample_device):
    with patch("alerts.send_telegram_message", new_callable=AsyncMock) as mock_send:
        await check_and_send_alerts("abc123", "TestDevice", battery=3.0)
    mock_send.assert_not_called()


# ── check_device_offline ───────────────────────────────────────────

async def test_offline_device_sends_alert(tmp_db):
    # Device last seen 30 minutes ago, interval 900s → offline
    await database.subscribe(100)
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    import aiosqlite
    async with aiosqlite.connect(database.DATABASE_URL) as db:
        await db.execute(
            "INSERT INTO devices (device_id, name, last_seen, interval_sec) VALUES (?,?,?,?)",
            ("off1", "OfflineDevice", old_time, 900),
        )
        await db.commit()

    with patch("alerts.send_telegram_message", new_callable=AsyncMock) as mock_send:
        await check_device_offline()
    mock_send.assert_called_once()
    text = mock_send.call_args[0][1]
    assert "Пропущены показания" in text


async def test_online_device_no_alert(tmp_db):
    await database.subscribe(100)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    import aiosqlite
    async with aiosqlite.connect(database.DATABASE_URL) as db:
        await db.execute(
            "INSERT INTO devices (device_id, name, last_seen, interval_sec) VALUES (?,?,?,?)",
            ("on1", "OnlineDevice", now, 900),
        )
        await db.commit()

    with patch("alerts.send_telegram_message", new_callable=AsyncMock) as mock_send:
        await check_device_offline()
    mock_send.assert_not_called()
