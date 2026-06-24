import html
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


async def send_telegram_message(chat_id: int, text: str) -> bool:
    """Send a message via Telegram Bot API. Returns False if user blocked the bot."""
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            })
            if resp.status_code == 403:
                logger.warning(f"User {chat_id} blocked the bot, unsubscribing")
                await database.unsubscribe(chat_id)
                return False
            if resp.status_code != 200:
                # 400 (bad HTML/markup), 429 (rate limit), 5xx, etc. — never silently drop
                logger.error(
                    f"Telegram API error {resp.status_code} sending to {chat_id}: {resp.text}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
            return False


async def check_and_send_alerts(device_id: str, device_name: str, battery: float):
    """Check conditions and send alerts to all subscribers."""

    safe_name = html.escape(device_name)

    # Check battery level
    if battery <= BATTERY_CRITICAL:
        alert_type = "battery_critical"
        message = (
            f"🚨 <b>КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ!</b>\n\n"
            f"Устройство: <b>{safe_name}</b>\n"
            f"🪫 Батарея: <b>{battery:.2f}V</b>\n\n"
            f"⚠️ Батарея критически разряжена!\n"
            f"Срочно зарядите устройство!"
        )
    elif battery <= BATTERY_LOW:
        alert_type = "battery_low"
        message = (
            f"⚠️ <b>Предупреждение</b>\n\n"
            f"Устройство: <b>{safe_name}</b>\n"
            f"🪫 Батарея: <b>{battery:.2f}V</b>\n\n"
            f"Низкий заряд батареи.\n"
            f"Рекомендуется зарядить устройство."
        )
    else:
        return  # No alert needed

    # Get all subscribers (skip without consuming the cooldown if nobody listens)
    subscribers = await database.get_all_subscribers()
    if not subscribers:
        logger.info("No subscribers to notify")
        return

    # Atomically claim the cooldown slot before sending. Doing the check + record
    # in one write prevents duplicate blasts when two readings arrive concurrently
    # (the webhook fires this as a detached task on every reading).
    if not await database.claim_alert_slot(device_id, alert_type, cooldown_hours=6):
        logger.info(f"Alert {alert_type} for {device_id} skipped (cooldown)")
        return

    # Send to all subscribers
    logger.info(f"Sending {alert_type} alert to {len(subscribers)} subscribers")
    for chat_id in subscribers:
        await send_telegram_message(chat_id, message)


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

        subscribers = await database.get_all_subscribers()
        if not subscribers:
            logger.info("No subscribers for offline alert")
            continue

        # Atomic claim prevents duplicate offline alerts if checks overlap.
        if not await database.claim_alert_slot(device_id, alert_type, cooldown_hours=6):
            logger.debug(f"Offline alert for {device_name} skipped (cooldown)")
            continue

        missed = max(1, int(silence / interval_sec) - 1)
        expected_min = interval_sec // 60
        message = (
            f"📡 <b>Пропущены показания!</b>\n\n"
            f"📱 {html.escape(device_name)}\n"
            f"⏱ Последний сигнал: <b>{_format_duration(silence)} назад</b>\n"
            f"📊 Пропущено: <b>~{missed}</b> показаний\n"
            f"⚠️ Ожидался каждые {expected_min} мин"
        )

        logger.warning(f"Device {device_name} offline for {_format_duration(silence)}, alerting {len(subscribers)} subscribers")
        for chat_id in subscribers:
            await send_telegram_message(chat_id, message)


