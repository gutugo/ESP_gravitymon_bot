import logging
import httpx
import asyncio
from datetime import datetime, timezone
from config import settings
import database

logger = logging.getLogger(__name__)

# Thresholds
BATTERY_LOW = 3.3
BATTERY_CRITICAL = 3.1


async def send_telegram_message(chat_id: int, text: str):
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            })
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")


async def check_and_send_alerts(device_id: str, device_name: str, battery: float):
    """Check conditions and send alerts to all subscribers."""

    # Check battery level
    if battery <= BATTERY_CRITICAL:
        alert_type = "battery_critical"
        message = (
            f"🚨 <b>КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ!</b>\n\n"
            f"Устройство: <b>{device_name}</b>\n"
            f"🪫 Батарея: <b>{battery:.2f}V</b>\n\n"
            f"⚠️ Батарея критически разряжена!\n"
            f"Срочно зарядите устройство!"
        )
    elif battery <= BATTERY_LOW:
        alert_type = "battery_low"
        message = (
            f"⚠️ <b>Предупреждение</b>\n\n"
            f"Устройство: <b>{device_name}</b>\n"
            f"🪫 Батарея: <b>{battery:.2f}V</b>\n\n"
            f"Низкий заряд батареи.\n"
            f"Рекомендуется зарядить устройство."
        )
    else:
        return  # No alert needed

    # Check if we should send (cooldown)
    if not await database.should_send_alert(device_id, alert_type, cooldown_hours=6):
        logger.info(f"Alert {alert_type} for {device_id} skipped (cooldown)")
        return

    # Get all subscribers
    subscribers = await database.get_all_subscribers()
    if not subscribers:
        logger.info("No subscribers to notify")
        return

    # Send to all subscribers
    logger.info(f"Sending {alert_type} alert to {len(subscribers)} subscribers")
    for chat_id in subscribers:
        await send_telegram_message(chat_id, message)

    # Record alert sent
    await database.record_alert_sent(device_id, alert_type)


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable Xч Yмин string."""
    total_min = int(seconds // 60)
    hours = total_min // 60
    minutes = total_min % 60
    if hours > 0:
        return f"{hours}ч {minutes}мин"
    return f"{minutes}мин"


async def check_device_offline():
    """Check all devices for offline status and alert subscribers."""
    devices = await database.get_all_devices()
    if not devices:
        return

    now = datetime.now(timezone.utc)

    for device in devices:
        device_id = device['device_id']
        device_name = device['name']
        interval_sec = device.get('interval_sec') or 900
        last_seen_str = device.get('last_seen')

        if not last_seen_str:
            continue

        last_seen = datetime.fromisoformat(last_seen_str).replace(tzinfo=timezone.utc)
        silence = (now - last_seen).total_seconds()
        # Expected interval + 2 min safety for WiFi reconnect / timing jitter
        threshold = interval_sec + 120

        if silence <= threshold:
            logger.debug(f"Device {device_name} is online (last seen {_format_duration(silence)} ago)")
            continue

        alert_type = "device_offline"

        if not await database.should_send_alert(device_id, alert_type, cooldown_hours=6):
            logger.debug(f"Offline alert for {device_name} skipped (cooldown)")
            continue

        missed = max(1, int(silence / interval_sec) - 1)
        expected_min = interval_sec // 60
        message = (
            f"📡 <b>Пропущены показания!</b>\n\n"
            f"📱 {device_name}\n"
            f"⏱ Последний сигнал: <b>{_format_duration(silence)} назад</b>\n"
            f"📊 Пропущено: <b>~{missed}</b> показаний\n"
            f"⚠️ Ожидался каждые {expected_min} мин"
        )

        subscribers = await database.get_all_subscribers()
        if not subscribers:
            logger.info("No subscribers for offline alert")
            continue

        logger.warning(f"Device {device_name} offline for {_format_duration(silence)}, alerting {len(subscribers)} subscribers")
        for chat_id in subscribers:
            await send_telegram_message(chat_id, message)

        await database.record_alert_sent(device_id, alert_type)


