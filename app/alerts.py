import logging
import httpx
import asyncio
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
