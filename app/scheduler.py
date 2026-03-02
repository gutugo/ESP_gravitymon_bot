import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import database
from daily_report import generate_daily_report
from alerts import send_telegram_message, check_device_offline
from config import TZ_UTC7
from excel_export import update_device_excel

logger = logging.getLogger(__name__)

scheduler: Optional[AsyncIOScheduler] = None


async def send_daily_reports():
    """Send daily reports to all subscribers for all devices."""
    logger.info("Starting daily report generation...")

    try:
        # Get all devices
        devices = await database.get_all_devices()
        if not devices:
            logger.info("No devices found, skipping daily report")
            return

        # Get all subscribers
        subscribers = await database.get_all_subscribers()
        if not subscribers:
            logger.info("No subscribers found, skipping daily report")
            return

        logger.info(f"Generating reports for {len(devices)} device(s), sending to {len(subscribers)} subscriber(s)")

        # Generate and send report for each device
        for device in devices:
            device_id = device['device_id']
            device_name = device['name']

            report = await generate_daily_report(device_id, device_name)
            if not report:
                logger.warning(f"No data for device {device_name}, skipping")
                continue

            # Send to all subscribers
            for chat_id in subscribers:
                try:
                    await send_telegram_message(chat_id, report)
                    logger.info(f"Sent daily report for {device_name} to {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to send report to {chat_id}: {e}")

        logger.info("Daily report generation completed")

        # Clean up old alert records
        await database.cleanup_old_alerts(days=30)

        # Update Excel exports with yesterday's data
        now_utc7 = datetime.now(TZ_UTC7)
        yesterday_utc7 = now_utc7 - timedelta(days=1)
        day_start_utc7 = yesterday_utc7.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end_utc7 = day_start_utc7 + timedelta(days=1)
        day_start_utc = day_start_utc7.astimezone(timezone.utc)
        day_end_utc = day_end_utc7.astimezone(timezone.utc)

        logger.info("Updating Excel exports with yesterday's data...")
        for device in devices:
            try:
                filepath = await update_device_excel(
                    device['device_id'], device['name'],
                    day_start_utc, day_end_utc
                )
                if filepath:
                    logger.info(f"Excel updated for {device['name']}")
                else:
                    logger.warning(f"No data for Excel export: {device['name']}")
            except Exception as e:
                logger.error(f"Failed to update Excel for {device['name']}: {e}")

    except Exception as e:
        logger.error(f"Error in daily report job: {e}")


def start_scheduler():
    """Initialize and start the background scheduler."""
    global scheduler

    scheduler = AsyncIOScheduler()

    # Daily report at 08:00 UTC+7
    trigger = CronTrigger(hour=8, minute=0, timezone=TZ_UTC7)

    scheduler.add_job(
        send_daily_reports,
        trigger=trigger,
        id='daily_report',
        name='Daily Report',
        replace_existing=True
    )

    # Device offline check every 15 minutes
    scheduler.add_job(
        check_device_offline,
        trigger=IntervalTrigger(minutes=15),
        id='device_offline_check',
        name='Device Offline Check',
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started. Daily report at 08:00 UTC+7, offline check every 15 min")

    return scheduler


def stop_scheduler():
    """Gracefully shutdown the scheduler."""
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
