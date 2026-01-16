import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.enums import ParseMode

from config import settings, TZ_UTC7
import database
import graphs
import scheduler
from handlers.keyboards import (
    MenuCallback, GraphCallback, DeviceCallback,
    get_main_keyboard, get_graph_keyboard, get_devices_keyboard
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize bot and dispatcher
bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()
router = Router()

# Store user's selected device (in-memory, could be moved to DB)
user_devices: dict[int, str] = {}


def format_time_ago(timestamp) -> str:
    """Format timestamp as 'X minutes ago' in Russian (UTC+7)."""
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

    # Always use UTC+7 for time calculations
    now = datetime.now(TZ_UTC7)
    if timestamp.tzinfo:
        timestamp = timestamp.astimezone(TZ_UTC7)
    else:
        # Assume naive timestamps are UTC, convert to UTC+7
        timestamp = timestamp.replace(tzinfo=TZ_UTC7)

    diff = now - timestamp
    minutes = int(diff.total_seconds() / 60)

    if minutes < 1:
        return "только что"
    elif minutes < 60:
        return f"{minutes} мин назад"
    elif minutes < 1440:
        hours = minutes // 60
        return f"{hours} ч назад"
    else:
        days = minutes // 1440
        return f"{days} дн назад"


# Battery thresholds
BATTERY_LOW = 3.3      # Low battery warning
BATTERY_CRITICAL = 3.1  # Critical battery warning


def format_status_message(reading: dict) -> str:
    """Format status message in Russian."""
    device_name = reading.get('device_name', reading.get('name', 'Устройство'))
    temp = reading.get('temperature', 0)
    temp_unit = reading.get('temp_unit', 'C')
    gravity = reading.get('gravity', 0)
    battery = reading.get('battery', 0)
    timestamp = reading.get('timestamp', '')

    time_ago = format_time_ago(timestamp) if timestamp else "неизвестно"

    # Battery status with warning
    if battery <= BATTERY_CRITICAL:
        battery_status = f"🪫 <b>Батарея:</b> {battery:.2f}V ⚠️ <b>КРИТИЧЕСКИ НИЗКИЙ!</b>"
    elif battery <= BATTERY_LOW:
        battery_status = f"🪫 <b>Батарея:</b> {battery:.2f}V ⚠️ <b>Низкий заряд</b>"
    else:
        battery_status = f"🔋 <b>Батарея:</b> {battery:.2f}V"

    # Build message
    message = (
        f"📱 <b>{device_name}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🌡 <b>Температура:</b> {temp:.1f}°{temp_unit}\n"
        f"📊 <b>Плотность:</b> {gravity:.4f} SG\n"
        f"{battery_status}\n"
        f"📡 <b>Обновлено:</b> {time_ago}"
    )

    # Add warning block if battery is low
    if battery <= BATTERY_LOW:
        message += "\n\n⚠️ <b>Требуется зарядка устройства!</b>"

    return message


@router.message(Command("start", "help"))
async def cmd_start(message: Message):
    """Handle /start and /help commands."""
    await database.init_db()

    # Auto-subscribe user on start
    await database.subscribe(message.from_user.id)

    # Get latest reading
    reading = await database.get_latest_reading()

    if reading:
        # Store device for user
        user_devices[message.from_user.id] = reading.get('device_id', '')

        text = format_status_message(reading)
        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "👋 <b>Добро пожаловать в GravityMon Bot!</b>\n\n"
            "Пока нет данных от устройства.\n"
            "Убедитесь, что ESP настроен на отправку данных на этот сервер.\n\n"
            "Используйте /status для проверки статуса.\n"
            "✅ Вы подписаны на уведомления.",
            parse_mode=ParseMode.HTML
        )


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    """Subscribe to notifications."""
    await database.subscribe(message.from_user.id)
    await message.answer(
        "✅ <b>Вы подписаны на уведомления!</b>\n\n"
        "Вы будете получать оповещения о:\n"
        "• Низком заряде батареи\n"
        "• Критическом разряде батареи",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    """Unsubscribe from notifications."""
    await database.unsubscribe(message.from_user.id)
    await message.answer(
        "❌ <b>Вы отписаны от уведомлений.</b>\n\n"
        "Чтобы снова получать оповещения, используйте /subscribe",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Handle /status command."""
    device_id = user_devices.get(message.from_user.id)
    reading = await database.get_latest_reading(device_id)

    if reading:
        user_devices[message.from_user.id] = reading.get('device_id', '')
        text = format_status_message(reading)
        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "❌ Нет данных от устройства.\n"
            "Проверьте настройки ESP.",
            parse_mode=ParseMode.HTML
        )


@router.message(Command("graph"))
async def cmd_graph(message: Message):
    """Handle /graph command."""
    await message.answer(
        "📈 <b>Выберите параметры графика:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_graph_keyboard()
    )


@router.message(Command("report"))
async def cmd_test_report(message: Message):
    """Test daily report generation."""
    from daily_report import generate_daily_report

    device = await database.get_default_device()
    if not device:
        await message.answer("Нет устройств")
        return

    report = await generate_daily_report(device['device_id'], device['name'])
    if report:
        await message.answer(report, parse_mode=ParseMode.HTML)
    else:
        await message.answer("Нет данных за последние 24 часа")


@router.callback_query(MenuCallback.filter(F.action == "status"))
@router.callback_query(MenuCallback.filter(F.action == "refresh"))
async def callback_status(callback: CallbackQuery):
    """Handle status/refresh callback - delete and send new for single dashboard."""
    device_id = user_devices.get(callback.from_user.id)
    reading = await database.get_latest_reading(device_id)

    if reading:
        user_devices[callback.from_user.id] = reading.get('device_id', '')
        text = format_status_message(reading)
        chat_id = callback.message.chat.id
        await callback.message.delete()
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
    else:
        await callback.answer("Нет данных от устройства", show_alert=True)

    await callback.answer()


@router.callback_query(MenuCallback.filter(F.action == "graphs"))
async def callback_graphs_menu(callback: CallbackQuery):
    """Show graphs menu - delete and send new for single dashboard."""
    chat_id = callback.message.chat.id
    await callback.message.delete()
    await bot.send_message(
        chat_id=chat_id,
        text="📈 <b>Выберите параметры графика:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_graph_keyboard()
    )
    await callback.answer()


@router.callback_query(MenuCallback.filter(F.action == "devices"))
async def callback_devices_menu(callback: CallbackQuery):
    """Show devices list - delete and send new for single dashboard."""
    devices = await database.get_all_devices()
    current_device = user_devices.get(callback.from_user.id, "")

    if devices:
        chat_id = callback.message.chat.id
        await callback.message.delete()
        await bot.send_message(
            chat_id=chat_id,
            text="📱 <b>Выберите устройство:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_devices_keyboard(devices, current_device)
        )
    else:
        await callback.answer("Нет зарегистрированных устройств", show_alert=True)

    await callback.answer()


@router.callback_query(DeviceCallback.filter(F.action == "select"))
async def callback_select_device(callback: CallbackQuery, callback_data: DeviceCallback):
    """Handle device selection - delete and send new for single dashboard."""
    user_devices[callback.from_user.id] = callback_data.device_id
    await callback.answer("Устройство выбрано ✓")

    # Show status for selected device
    reading = await database.get_latest_reading(callback_data.device_id)
    if reading:
        text = format_status_message(reading)
        chat_id = callback.message.chat.id
        await callback.message.delete()
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )


@router.callback_query(GraphCallback.filter(F.action == "period"))
async def callback_change_period(callback: CallbackQuery, callback_data: GraphCallback):
    """Handle period change."""
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=callback.message.caption,
                reply_markup=get_graph_keyboard(
                    period=callback_data.period,
                    show_temp=callback_data.show_temp,
                    show_gravity=callback_data.show_gravity
                )
            )
        else:
            await callback.message.edit_reply_markup(
                reply_markup=get_graph_keyboard(
                    period=callback_data.period,
                    show_temp=callback_data.show_temp,
                    show_gravity=callback_data.show_gravity
                )
            )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(GraphCallback.filter(F.action == "toggle_temp"))
@router.callback_query(GraphCallback.filter(F.action == "toggle_gravity"))
async def callback_toggle_graph(callback: CallbackQuery, callback_data: GraphCallback):
    """Handle graph toggle."""
    # Check if at least one is enabled
    if not callback_data.show_temp and not callback_data.show_gravity:
        await callback.answer("Выберите хотя бы один график!", show_alert=True)
        return

    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=callback.message.caption,
                reply_markup=get_graph_keyboard(
                    period=callback_data.period,
                    show_temp=callback_data.show_temp,
                    show_gravity=callback_data.show_gravity
                )
            )
        else:
            await callback.message.edit_reply_markup(
                reply_markup=get_graph_keyboard(
                    period=callback_data.period,
                    show_temp=callback_data.show_temp,
                    show_gravity=callback_data.show_gravity
                )
            )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(GraphCallback.filter(F.action == "generate"))
async def callback_generate_graph(callback: CallbackQuery, callback_data: GraphCallback):
    """Generate and send graph."""
    await callback.answer("Генерация графика...")

    device_id = user_devices.get(callback.from_user.id)
    if not device_id:
        device = await database.get_default_device()
        if device:
            device_id = device['device_id']
        else:
            await callback.message.answer("❌ Нет устройств для отображения")
            return

    # Get readings
    readings = await database.get_readings_for_period(device_id, callback_data.period)

    # Get device name
    device = await database.get_latest_reading(device_id)
    device_name = device.get('device_name', 'Устройство') if device else 'Устройство'

    # Generate graph
    graph_buffer = graphs.generate_graph(
        readings=readings,
        device_name=device_name,
        period=callback_data.period,
        show_temperature=callback_data.show_temp,
        show_gravity=callback_data.show_gravity
    )

    # Send photo (delete old message first to keep single dashboard)
    photo = BufferedInputFile(
        graph_buffer.read(),
        filename=f"graph_{callback_data.period}.png"
    )

    chat_id = callback.message.chat.id
    await callback.message.delete()

    await bot.send_photo(
        chat_id=chat_id,
        photo=photo,
        caption=f"📈 {device_name}",
        reply_markup=get_graph_keyboard(
            period=callback_data.period,
            show_temp=callback_data.show_temp,
            show_gravity=callback_data.show_gravity
        )
    )


@router.callback_query(GraphCallback.filter(F.action == "back"))
async def callback_back_to_status(callback: CallbackQuery):
    """Go back to status view - always delete and send new for single dashboard."""
    device_id = user_devices.get(callback.from_user.id)
    reading = await database.get_latest_reading(device_id)

    if reading:
        text = format_status_message(reading)
        chat_id = callback.message.chat.id
        await callback.message.delete()
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
    await callback.answer()


async def main():
    """Start the bot."""
    # Initialize database
    await database.init_db()
    logger.info("Database initialized")

    # Start scheduler for daily reports
    scheduler.start_scheduler()

    # Register router
    dp.include_router(router)

    # Start polling
    logger.info("Starting bot...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.stop_scheduler()


if __name__ == "__main__":
    asyncio.run(main())
