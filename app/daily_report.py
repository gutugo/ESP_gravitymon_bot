from datetime import datetime
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

    # Get 24h stats
    stats = await database.get_24h_stats(device_id)
    if not stats:
        return None

    # Get first and latest readings for delta
    first_reading = await database.get_first_reading_24h(device_id)
    latest_reading = await database.get_latest_reading(device_id)

    if not latest_reading:
        return None

    # Calculate gravity delta
    gravity_delta = 0.0
    first_gravity = first_reading['gravity'] if first_reading else latest_reading['gravity']
    gravity_delta = latest_reading['gravity'] - first_gravity

    # Get fermentation status
    ferm_status, ferm_code = get_fermentation_status(gravity_delta)

    # Calculate ABV estimate (assuming OG is max gravity seen)
    abv = calculate_abv(stats['grav_max'], latest_reading['gravity'])

    # Get battery status with icon
    batt_status, batt_code = get_battery_status(latest_reading['battery'])
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
    interval = latest_reading.get('interval_sec') or 900
    expected = database.get_expected_readings_count(interval)
    actual = stats['reading_count']
    missed = max(0, expected - actual)
    missed_icon = "✓" if missed == 0 else "⚠️"

    # Get alerts count
    alerts_count = await database.get_alerts_count_24h(device_id)
    alerts_text = "Нет ✓" if alerts_count == 0 else f"{alerts_count} шт. ⚠️"

    # Build message (use UTC+7 for date)
    message = f"""📊 <b>ЕЖЕДНЕВНЫЙ ОТЧЁТ</b>
📅 {datetime.now(TZ_UTC7).strftime("%d.%m.%Y")}
📱 <b>{device_name}</b>
━━━━━━━━━━━━━━

🌡 <b>ТЕМПЕРАТУРА (24ч):</b>
├ Мин: {stats['temp_min']:.1f}°C
├ Макс: {stats['temp_max']:.1f}°C
└ Средняя: {stats['temp_avg']:.1f}°C

📈 <b>ПЛОТНОСТЬ (24ч):</b>
├ Начало: {first_gravity:.4f} SG
├ Сейчас: {latest_reading['gravity']:.4f} SG
├ Δ: {gravity_delta:+.4f} ({ferm_status})
└ ABV: ~{abv:.1f}%

🔋 <b>БАТАРЕЯ:</b>
├ Уровень: {latest_reading['battery']:.2f}V {batt_icon}
└ Статус: {batt_status}

📡 <b>УСТРОЙСТВО:</b>
├ Сигнал: {signal_text}
├ Получено: {actual}/{expected}
├ Пропущено: {missed} {missed_icon}
└ Интервал: {interval // 60} мин

⚠️ <b>СОБЫТИЯ:</b> {alerts_text}"""

    return message
