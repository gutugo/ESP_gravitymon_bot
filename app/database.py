import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import Optional
from config import settings

DATABASE_URL = settings.database_url


async def init_db():
    """Initialize database with schema."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        # Enable WAL mode for better concurrent read/write support
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP,
                interval_sec INTEGER DEFAULT 900
            );

            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                temperature REAL NOT NULL,
                temp_unit TEXT DEFAULT 'C',
                gravity REAL NOT NULL,
                gravity_unit TEXT DEFAULT 'G',
                angle REAL,
                battery REAL NOT NULL,
                rssi INTEGER,
                interval_sec INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_readings_device_time
            ON readings(device_id, timestamp DESC);

            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alerts_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS allowed_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Migration: add interval_sec column to devices if missing
        cursor = await db.execute("PRAGMA table_info(devices)")
        columns = [row[1] for row in await cursor.fetchall()]
        if 'interval_sec' not in columns:
            await db.execute("ALTER TABLE devices ADD COLUMN interval_sec INTEGER DEFAULT 900")
        if 'watched' not in columns:
            await db.execute("ALTER TABLE devices ADD COLUMN watched INTEGER DEFAULT 1")

        await db.commit()


async def upsert_device(device_id: str, name: str, interval_sec: Optional[int] = None):
    """Insert or update device."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("""
            INSERT INTO devices (device_id, name, last_seen, interval_sec)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                name = excluded.name,
                last_seen = CURRENT_TIMESTAMP,
                interval_sec = COALESCE(excluded.interval_sec, devices.interval_sec)
        """, (device_id, name, interval_sec))
        await db.commit()


async def insert_reading(
    device_id: str,
    temperature: float,
    temp_unit: str,
    gravity: float,
    gravity_unit: str,
    battery: float,
    angle: Optional[float] = None,
    rssi: Optional[int] = None,
    interval_sec: Optional[int] = None
):
    """Insert a new reading."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("""
            INSERT INTO readings
            (device_id, temperature, temp_unit, gravity, gravity_unit, angle, battery, rssi, interval_sec)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (device_id, temperature, temp_unit, gravity, gravity_unit, angle, battery, rssi, interval_sec))
        await db.commit()


async def get_latest_reading(device_id: Optional[str] = None):
    """Get the latest reading for a device or all devices."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        if device_id:
            cursor = await db.execute("""
                SELECT r.*, d.name as device_name
                FROM readings r
                JOIN devices d ON r.device_id = d.device_id
                WHERE r.device_id = ?
                ORDER BY r.timestamp DESC
                LIMIT 1
            """, (device_id,))
        else:
            cursor = await db.execute("""
                SELECT r.*, d.name as device_name
                FROM readings r
                JOIN devices d ON r.device_id = d.device_id
                ORDER BY r.timestamp DESC
                LIMIT 1
            """)
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_readings_for_period(device_id: str, period: str):
    """Get readings for a specific time period."""
    now = datetime.now(timezone.utc)

    period_map = {
        'hour': timedelta(hours=1),
        'day': timedelta(days=1),
        'week': timedelta(weeks=1),
        'month': timedelta(days=30)
    }

    delta = period_map.get(period, timedelta(days=1))
    start_time = now - delta

    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT timestamp, temperature, temp_unit, gravity, gravity_unit, battery
            FROM readings
            WHERE device_id = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (device_id, start_time.strftime('%Y-%m-%d %H:%M:%S')))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_readings_for_date_range(device_id: str, start_date: datetime, end_date: datetime):
    """Get readings between start_date and end_date (UTC)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT timestamp, temperature, temp_unit, gravity, gravity_unit, battery
            FROM readings
            WHERE device_id = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (device_id, start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S')))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_device_date_range(device_id: str) -> tuple[datetime, datetime] | None:
    """Get min and max timestamp for a device's readings."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute("""
            SELECT MIN(timestamp), MAX(timestamp)
            FROM readings
            WHERE device_id = ?
        """, (device_id,))
        row = await cursor.fetchone()
        if row and row[0] and row[1]:
            min_ts = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
            max_ts = datetime.fromisoformat(row[1]).replace(tzinfo=timezone.utc)
            return (min_ts, max_ts)
        return None


async def get_all_devices(watched_only: bool = True):
    """Get all registered devices. Filter to watched-only by default."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        if watched_only:
            cursor = await db.execute("""
                SELECT device_id, name, last_seen, interval_sec, watched
                FROM devices
                WHERE watched = 1
                ORDER BY last_seen DESC
            """)
        else:
            cursor = await db.execute("""
                SELECT device_id, name, last_seen, interval_sec, watched
                FROM devices
                ORDER BY last_seen DESC
            """)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_default_device():
    """Get the most recently active watched device."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT device_id, name, interval_sec
            FROM devices
            WHERE watched = 1
            ORDER BY last_seen DESC
            LIMIT 1
        """)
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_device_interval(device_id: str) -> int:
    """Get the device's configured interval in seconds."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            "SELECT interval_sec FROM devices WHERE device_id = ?", (device_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else 900


async def set_device_watched(device_id: str, watched: bool):
    """Toggle the watched flag for a device."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute(
            "UPDATE devices SET watched = ? WHERE device_id = ?",
            (1 if watched else 0, device_id),
        )
        await db.commit()


async def subscribe(chat_id: int):
    """Subscribe user to notifications."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("""
            INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)
        """, (chat_id,))
        await db.commit()


async def unsubscribe(chat_id: int):
    """Unsubscribe user from notifications."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        await db.commit()


async def is_subscribed(chat_id: int) -> bool:
    """Check if user is subscribed."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            "SELECT 1 FROM subscribers WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return row is not None


async def get_all_subscribers():
    """Get all subscriber chat_ids."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute("SELECT chat_id FROM subscribers")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def should_send_alert(device_id: str, alert_type: str, cooldown_hours: int = 6) -> bool:
    """Check if alert should be sent (not sent recently)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).strftime('%Y-%m-%d %H:%M:%S')
        cursor = await db.execute("""
            SELECT 1 FROM alerts_sent
            WHERE device_id = ? AND alert_type = ? AND sent_at > ?
        """, (device_id, alert_type, cutoff))
        row = await cursor.fetchone()
        return row is None


async def record_alert_sent(device_id: str, alert_type: str):
    """Record that an alert was sent."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("""
            INSERT INTO alerts_sent (device_id, alert_type) VALUES (?, ?)
        """, (device_id, alert_type))
        await db.commit()


async def claim_alert_slot(device_id: str, alert_type: str, cooldown_hours: int = 6) -> bool:
    """Atomically claim the right to send an alert.

    Combines the cooldown check and the record into a single conditional INSERT,
    so two concurrent callers can't both pass the check and double-send. SQLite
    serializes writes, so exactly one INSERT wins. Returns True if claimed (caller
    should send), False if a recent alert already exists (cooldown active).
    """
    async with aiosqlite.connect(DATABASE_URL) as db:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).strftime('%Y-%m-%d %H:%M:%S')
        cursor = await db.execute("""
            INSERT INTO alerts_sent (device_id, alert_type)
            SELECT ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM alerts_sent
                WHERE device_id = ? AND alert_type = ? AND sent_at > ?
            )
        """, (device_id, alert_type, device_id, alert_type, cutoff))
        await db.commit()
        return cursor.rowcount > 0


# ==================== Daily Report Functions ====================

async def get_24h_stats(device_id: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> dict:
    """Get aggregated statistics for a time period (default: last 24 hours)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')

        if end_time:
            end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
            cursor = await db.execute("""
                SELECT
                    MIN(temperature) as temp_min,
                    MAX(temperature) as temp_max,
                    AVG(temperature) as temp_avg,
                    MIN(gravity) as grav_min,
                    MAX(gravity) as grav_max,
                    AVG(gravity) as grav_avg,
                    MIN(battery) as batt_min,
                    MAX(battery) as batt_max,
                    AVG(battery) as batt_avg,
                    AVG(rssi) as rssi_avg,
                    COUNT(*) as reading_count
                FROM readings
                WHERE device_id = ? AND timestamp >= ? AND timestamp < ?
            """, (device_id, start_str, end_str))
        else:
            cursor = await db.execute("""
                SELECT
                    MIN(temperature) as temp_min,
                    MAX(temperature) as temp_max,
                    AVG(temperature) as temp_avg,
                    MIN(gravity) as grav_min,
                    MAX(gravity) as grav_max,
                    AVG(gravity) as grav_avg,
                    MIN(battery) as batt_min,
                    MAX(battery) as batt_max,
                    AVG(battery) as batt_avg,
                    AVG(rssi) as rssi_avg,
                    COUNT(*) as reading_count
                FROM readings
                WHERE device_id = ? AND timestamp >= ?
            """, (device_id, start_str))
        row = await cursor.fetchone()
        if row and row[0] is not None:
            return {
                'temp_min': row[0],
                'temp_max': row[1],
                'temp_avg': row[2],
                'grav_min': row[3],
                'grav_max': row[4],
                'grav_avg': row[5],
                'batt_min': row[6],
                'batt_max': row[7],
                'batt_avg': row[8],
                'rssi_avg': row[9],
                'reading_count': row[10]
            }
        return None


async def get_first_reading_24h(device_id: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> dict:
    """Get the first reading in time period for delta calculation."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')

        if end_time:
            end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
            cursor = await db.execute("""
                SELECT gravity, temperature, battery, timestamp, interval_sec
                FROM readings
                WHERE device_id = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                LIMIT 1
            """, (device_id, start_str, end_str))
        else:
            cursor = await db.execute("""
                SELECT gravity, temperature, battery, timestamp, interval_sec
                FROM readings
                WHERE device_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC
                LIMIT 1
            """, (device_id, start_str))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_last_reading_in_period(device_id: str, start_time: datetime, end_time: datetime) -> dict:
    """Get the last reading in time period for delta calculation."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
        cursor = await db.execute("""
            SELECT gravity, temperature, battery, timestamp
            FROM readings
            WHERE device_id = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (device_id, start_str, end_str))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_alerts_count_24h(device_id: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> int:
    """Count alerts triggered in time period (default: last 24 hours)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')

        if end_time:
            end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
            cursor = await db.execute("""
                SELECT COUNT(*) FROM alerts_sent
                WHERE device_id = ? AND sent_at >= ? AND sent_at < ?
            """, (device_id, start_str, end_str))
        else:
            cursor = await db.execute("""
                SELECT COUNT(*) FROM alerts_sent
                WHERE device_id = ? AND sent_at >= ?
            """, (device_id, start_str))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_alerts_24h(device_id: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> list[dict]:
    """Get alerts with details in time period (default: last 24 hours)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')

        if end_time:
            end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
            cursor = await db.execute("""
                SELECT alert_type, sent_at FROM alerts_sent
                WHERE device_id = ? AND sent_at >= ? AND sent_at < ?
                ORDER BY sent_at ASC
            """, (device_id, start_str, end_str))
        else:
            cursor = await db.execute("""
                SELECT alert_type, sent_at FROM alerts_sent
                WHERE device_id = ? AND sent_at >= ?
                ORDER BY sent_at ASC
            """, (device_id, start_str))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_device_max_gravity(device_id: str) -> Optional[float]:
    """Get the highest gravity ever recorded for a device (proxy for original gravity)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            "SELECT MAX(gravity) FROM readings WHERE device_id = ?", (device_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] is not None else None


def get_expected_readings_count(interval_sec: int = 900) -> int:
    """Calculate expected number of readings in 24h based on interval."""
    return round(24 * 60 * 60 / interval_sec)


async def get_avg_interval(device_id: str, start_time: datetime, end_time: datetime) -> Optional[float]:
    """Calculate average interval between readings in a period (seconds)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute("""
            SELECT timestamp FROM readings
            WHERE device_id = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC
        """, (device_id, start_time.strftime('%Y-%m-%d %H:%M:%S'),
              end_time.strftime('%Y-%m-%d %H:%M:%S')))
        rows = await cursor.fetchall()
        if len(rows) < 2:
            return None
        first = datetime.fromisoformat(rows[0][0])
        last = datetime.fromisoformat(rows[-1][0])
        return (last - first).total_seconds() / (len(rows) - 1)


# ==================== Excel Export Functions ====================

async def get_all_readings_for_device(device_id: str) -> list[dict]:
    """Get all readings for a device (for Excel export)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT timestamp, temperature, temp_unit, gravity, battery, rssi, angle, interval_sec
            FROM readings
            WHERE device_id = ?
            ORDER BY timestamp ASC
        """, (device_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_readings_for_device_period(device_id: str, start_utc: datetime, end_utc: datetime) -> list[dict]:
    """Get readings for a device within a UTC time range (for Excel incremental update)."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT timestamp, temperature, temp_unit, gravity, battery, rssi, angle, interval_sec
            FROM readings
            WHERE device_id = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC
        """, (device_id, start_utc.strftime('%Y-%m-%d %H:%M:%S'), end_utc.strftime('%Y-%m-%d %H:%M:%S')))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# ==================== Allowed Users Functions ====================

async def get_allowed_users() -> list[int]:
    """Get all allowed user chat_ids."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute("SELECT chat_id FROM allowed_users")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def add_allowed_user(chat_id: int) -> bool:
    """Add user to whitelist. Returns True if added, False if already exists."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        try:
            await db.execute(
                "INSERT INTO allowed_users (chat_id) VALUES (?)", (chat_id,)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_allowed_user(chat_id: int) -> bool:
    """Remove user from whitelist. Returns True if removed, False if not found."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute(
            "DELETE FROM allowed_users WHERE chat_id = ?", (chat_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def seed_allowed_users(chat_ids: list[int]):
    """Seed allowed_users table from env var if table is empty."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM allowed_users")
        row = await cursor.fetchone()
        if row[0] > 0:
            return
        for chat_id in chat_ids:
            await db.execute(
                "INSERT OR IGNORE INTO allowed_users (chat_id) VALUES (?)",
                (chat_id,),
            )
        await db.commit()


async def cleanup_old_alerts(days: int = 30):
    """Delete alert records older than the specified number of days."""
    async with aiosqlite.connect(DATABASE_URL) as db:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        await db.execute("DELETE FROM alerts_sent WHERE sent_at < ?", (cutoff,))
        await db.commit()
