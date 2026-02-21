from datetime import datetime, timedelta, timezone
import database
from typing import Optional
from config import TZ_UTC7


def calculate_abv(og: float, fg: float) -> float:
    """Estimate ABV from original and final gravity."""
    if og <= fg or og <= 1.0:
        return 0.0
    return (og - fg) * 131.25


def get_fermentation_status(gravity_delta: float) -> tuple:
    """Determine fermentation status based on gravity change."""
    if gravity_delta < -0.010:
        return ("Активная", "active")
    elif gravity_delta < -0.002:
        return ("Замедляется", "slowing")
    elif gravity_delta < 0.001:
        return ("Завершена", "complete")
    else:
        return ("Стабильна", "stable")


def get_battery_status(voltage: float) -> tuple:
    """Determine battery status."""
    if voltage <= 3.1:
        return ("КРИТИЧЕСКИЙ", "critical")
    elif voltage <= 3.3:
        return ("Низкий", "low")
    elif voltage <= 3.6:
        return ("Средний", "medium")
    else:
        return ("Хороший", "good")


def get_signal_quality(rssi: float) -> str:
    """Determine signal quality from RSSI."""
    if rssi is None:
        return "н/д"
    if rssi >= -50:
        return "Отличный"
    elif rssi >= -60:
        return "Хороший"
    elif rssi >= -70:
        return "Средний"
    else:
        return "Слабый"


async def generate_daily_report(device_id: str, device_name: str) -> Optional[str]:
    """Generate formatted daily report message."""

    # Calculate yesterday's day boundaries in UTC+7, convert to UTC for DB
    now_utc7 = datetime.now(TZ_UTC7)
    yesterday_utc7 = now_utc7 - timedelta(days=1)

    # Yesterday 00:00:00 and 24:00:00 (today 00:00:00) in UTC+7
    day_start_utc7 = yesterday_utc7.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_utc7 = day_start_utc7 + timedelta(days=1)

    # Convert to UTC for database queries
    day_start_utc = day_start_utc7.astimezone(timezone.utc)
    day_end_utc = day_end_utc7.astimezone(timezone.utc)

    # Get stats for yesterday (00:00-24:00 UTC+7)
    stats = await database.get_24h_stats(device_id, day_start_utc, day_end_utc)
    if not stats:
        return None

    # Get first and last readings of the day for delta
    first_reading = await database.get_first_reading_24h(device_id, day_start_utc, day_end_utc)
    last_reading = await database.get_last_reading_in_period(device_id, day_start_utc, day_end_utc)

    if not last_reading:
        return None

    # Calculate gravity delta
    gravity_delta = 0.0
    first_gravity = first_reading['gravity'] if first_reading else last_reading['gravity']
    gravity_delta = last_reading['gravity'] - first_gravity

    # Get fermentation status
    ferm_status, ferm_code = get_fermentation_status(gravity_delta)

    # Calculate ABV estimate (assuming OG is max gravity seen)
    abv = calculate_abv(stats['grav_max'], last_reading['gravity'])

    # Get battery status with icon (use last reading of the day)
    batt_status, batt_code = get_battery_status(last_reading['battery'])
    if batt_code == "good":
        batt_icon = "✓"
    elif batt_code == "medium":
        batt_icon = ""
    else:
        batt_icon = "⚠️"

    # Get signal quality
    rssi_avg = stats['rssi_avg']
    if rssi_avg is not None:
        signal_text = f"{rssi_avg:.0f} dBm ({get_signal_quality(rssi_avg)})"
    else:
        signal_text = "н/д"

    # Calculate data completeness and missed packets
    # Get interval from device settings (updated on each webhook POST)
    interval = await database.get_device_interval(device_id)
    expected = database.get_expected_readings_count(interval)
    actual = stats['reading_count']
    missed = max(0, expected - actual)
    missed_icon = "✓" if missed == 0 else "⚠️"

    # Get alerts for yesterday
    alerts = await database.get_alerts_24h(device_id, day_start_utc, day_end_utc)
    if not alerts:
        alerts_section = "⚠️ <b>СОБЫТИЯ:</b> Нет ✓"
    else:
        alert_type_names = {
            "battery_low": "🪫 Низкий заряд",
            "battery_critical": "🚨 Крит. заряд",
        }
        alerts_section = f"⚠️ <b>СОБЫТИЯ:</b> {len(alerts)} шт."
        for alert in alerts:
            alert_name = alert_type_names.get(alert['alert_type'], alert['alert_type'])
            # Parse UTC time and convert to UTC+7
            alert_time_utc = datetime.strptime(alert['sent_at'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            alert_time_local = alert_time_utc.astimezone(TZ_UTC7)
            alerts_section += f"\n├ {alert_time_local.strftime('%H:%M')} — {alert_name}"

    # Build message
    message = f"""📊 <b>ЕЖЕДНЕВНЫЙ ОТЧЁТ</b>
📅 {yesterday_utc7.strftime("%d.%m.%Y")}
📱 <b>{device_name}</b>
━━━━━━━━━━━━━━

🌡 <b>ТЕМПЕРАТУРА:</b>
├ Мин: {stats['temp_min']:.1f}°C
├ Макс: {stats['temp_max']:.1f}°C
└ Средняя: {stats['temp_avg']:.1f}°C

📈 <b>ПЛОТНОСТЬ:</b>
├ Начало: {first_gravity:.4f} SG
├ Конец: {last_reading['gravity']:.4f} SG
├ Δ: {gravity_delta:+.4f} ({ferm_status})
└ Алкоголь: ~{abv:.1f}% об.

🔋 <b>БАТАРЕЯ:</b>
├ Уровень: {last_reading['battery']:.2f}V {batt_icon}
└ Статус: {batt_status}

📡 <b>УСТРОЙСТВО:</b>
├ Сигнал: {signal_text}
├ Получено: {actual}/{expected}
├ Пропущено: {missed} {missed_icon}
└ Интервал: {interval // 60} мин

{alerts_section}"""

    return message
