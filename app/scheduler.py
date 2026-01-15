import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import database
from daily_report import generate_daily_report
from alerts import send_telegram_message

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler = None


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

    except Exception as e:
        logger.error(f"Error in daily report job: {e}")


def start_scheduler():
    """Initialize and start the background scheduler."""
    global scheduler

    scheduler = AsyncIOScheduler()

    # Daily report at 01:00 UTC = 08:00 UTC+7
    trigger = CronTrigger(hour=1, minute=0, timezone=pytz.UTC)

    scheduler.add_job(
        send_daily_reports,
        trigger=trigger,
        id='daily_report',
        name='Daily Report',
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started. Daily report scheduled at 01:00 UTC (08:00 UTC+7)")

    return scheduler


def stop_scheduler():
    """Gracefully shutdown the scheduler."""
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
