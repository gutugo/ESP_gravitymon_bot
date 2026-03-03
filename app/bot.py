import asyncio
import logging
from datetime import datetime, timezone, timedelta
from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, BufferedInputFile, FSInputFile, TelegramObject
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import settings, TZ_UTC7
import database
import graphs
import scheduler
from excel_export import get_device_excel_path
from handlers.keyboards import (
    MenuCallback, GraphCallback, DeviceCallback, AdminCallback,
    get_main_keyboard, get_graph_keyboard, get_devices_keyboard,
    get_admin_keyboard
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cached allowed users list (loaded from DB on startup, refreshed on add/remove)
allowed_users: list[int] = []


async def reload_allowed_users():
    """Reload allowed users list from DB into module-level cache."""
    global allowed_users
    allowed_users = await database.get_allowed_users()


class AuthMiddleware(BaseMiddleware):
    """Reject messages from users not in the allowed list."""

    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not allowed_users and not settings.master_admin:
            return await handler(event, data)

        user = data.get("event_from_user")
        if user:
            if user.id == settings.master_admin:
                return await handler(event, data)
            if user.id not in allowed_users:
                if isinstance(event, Message):
                    await event.answer("⛔ Доступ запрещён")
                elif isinstance(event, CallbackQuery):
                    await event.answer("⛔ Доступ запрещён", show_alert=True)
                return
        return await handler(event, data)


# Initialize bot and dispatcher
bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()
router = Router()
router.message.middleware(AuthMiddleware())
router.callback_query.middleware(AuthMiddleware())

# Store user's selected device (in-memory, could be moved to DB)
user_devices: dict[int, str] = {}

# Store user's custom date ranges for graphs
user_custom_dates: dict[int, tuple[str, str]] = {}  # user_id -> (start_date, end_date)


class GraphStates(StatesGroup):
    """FSM states for custom date range input."""
    waiting_for_start_date = State()
    waiting_for_end_date = State()


class AdminStates(StatesGroup):
    """FSM states for admin user management."""
    waiting_for_user_id = State()


def format_time_ago(timestamp) -> str:
    """Format timestamp as 'X minutes ago' in Russian (UTC+7)."""
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

    # Always use UTC+7 for time calculations
    now = datetime.now(TZ_UTC7)
    if timestamp.tzinfo:
        timestamp = timestamp.astimezone(TZ_UTC7)
    else:
        # Naive timestamps from DB are UTC, convert to UTC+7
        timestamp = timestamp.replace(tzinfo=timezone.utc).astimezone(TZ_UTC7)

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
            reply_markup=get_main_keyboard(
                is_admin=message.from_user.id == settings.master_admin
            )
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
            reply_markup=get_main_keyboard(
                is_admin=message.from_user.id == settings.master_admin
            )
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
    custom_dates = user_custom_dates.get(message.from_user.id)
    await message.answer(
        "📈 <b>Выберите параметры графика:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_graph_keyboard(custom_dates=custom_dates)
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


# ==================== Admin Commands (master admin only) ====================

@router.message(Command("users"))
async def cmd_users(message: Message):
    """List all allowed users (master admin only)."""
    if message.from_user.id != settings.master_admin:
        return

    users = await database.get_allowed_users()
    if users:
        lines = [f"<code>{uid}</code>" for uid in users]
        text = (
            f"👥 <b>Разрешённые пользователи ({len(users)}):</b>\n"
            + "\n".join(lines)
        )
    else:
        text = "👥 <b>Список пользователей пуст</b>"

    if settings.master_admin:
        text += f"\n\n👑 Master admin: <code>{settings.master_admin}</code>"

    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("adduser"))
async def cmd_adduser(message: Message):
    """Add user to whitelist (master admin only)."""
    if message.from_user.id != settings.master_admin:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer(
            "Использование: <code>/adduser &lt;chat_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    chat_id = int(args[1].strip())
    added = await database.add_allowed_user(chat_id)
    await reload_allowed_users()

    if added:
        await message.answer(
            f"✅ Пользователь <code>{chat_id}</code> добавлен",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.answer(
            f"ℹ️ Пользователь <code>{chat_id}</code> уже в списке",
            parse_mode=ParseMode.HTML,
        )


@router.message(Command("rmuser"))
async def cmd_rmuser(message: Message):
    """Remove user from whitelist (master admin only)."""
    if message.from_user.id != settings.master_admin:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer(
            "Использование: <code>/rmuser &lt;chat_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    chat_id = int(args[1].strip())

    if chat_id == settings.master_admin:
        await message.answer("⛔ Нельзя удалить master admin")
        return

    removed = await database.remove_allowed_user(chat_id)
    await reload_allowed_users()

    if removed:
        await message.answer(
            f"✅ Пользователь <code>{chat_id}</code> удалён",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.answer(
            f"ℹ️ Пользователь <code>{chat_id}</code> не найден в списке",
            parse_mode=ParseMode.HTML,
        )


# ==================== Admin Panel (inline buttons) ====================

async def _resolve_users() -> list[dict]:
    """Resolve allowed user IDs to name/username via Telegram API."""
    user_ids = await database.get_allowed_users()
    result = []
    for uid in user_ids:
        try:
            chat = await bot.get_chat(uid)
            result.append({
                "chat_id": uid,
                "name": chat.full_name or str(uid),
                "username": chat.username or "",
            })
        except Exception:
            result.append({"chat_id": uid, "name": str(uid), "username": ""})
    return result


async def _send_admin_panel(chat_id: int):
    """Build and send the admin panel message."""
    users = await _resolve_users()
    count = len(users)
    await bot.send_message(
        chat_id=chat_id,
        text=f"⚙️ <b>Управление пользователями ({count})</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_keyboard(users, settings.master_admin),
    )


@router.callback_query(MenuCallback.filter(F.action == "admin"))
async def callback_admin_menu(callback: CallbackQuery):
    """Open admin panel."""
    if callback.from_user.id != settings.master_admin:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    chat_id = callback.message.chat.id
    await callback.message.delete()
    await _send_admin_panel(chat_id)
    await callback.answer()


@router.callback_query(AdminCallback.filter(F.action == "info"))
async def callback_admin_info(callback: CallbackQuery, callback_data: AdminCallback):
    """Show user ID on tap."""
    await callback.answer(f"ID: {callback_data.chat_id}")


@router.callback_query(AdminCallback.filter(F.action == "remove"))
async def callback_admin_remove(callback: CallbackQuery, callback_data: AdminCallback):
    """Remove user via admin panel."""
    if callback.from_user.id != settings.master_admin:
        await callback.answer("⛔", show_alert=True)
        return

    if callback_data.chat_id == settings.master_admin:
        await callback.answer("⛔ Нельзя удалить master admin", show_alert=True)
        return

    await database.remove_allowed_user(callback_data.chat_id)
    await reload_allowed_users()

    # Refresh admin panel
    chat_id = callback.message.chat.id
    await callback.message.delete()
    await _send_admin_panel(chat_id)
    await callback.answer(f"✅ Удалён {callback_data.chat_id}")


@router.callback_query(AdminCallback.filter(F.action == "add"))
async def callback_admin_add(callback: CallbackQuery, state: FSMContext):
    """Start add-user flow."""
    if callback.from_user.id != settings.master_admin:
        await callback.answer("⛔", show_alert=True)
        return

    chat_id = callback.message.chat.id
    await callback.message.delete()
    await bot.send_message(
        chat_id=chat_id,
        text="➕ <b>Введите chat_id пользователя:</b>",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(AdminStates.waiting_for_user_id)
    await callback.answer()


@router.message(AdminStates.waiting_for_user_id)
async def process_admin_add_user(message: Message, state: FSMContext):
    """Process user ID input from admin add flow."""
    if not message.text or not message.text.strip().isdigit():
        await message.answer("❌ Введите числовой chat_id")
        return

    chat_id = int(message.text.strip())
    added = await database.add_allowed_user(chat_id)
    await reload_allowed_users()
    await state.clear()

    if added:
        await message.answer(
            f"✅ Пользователь <code>{chat_id}</code> добавлен",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.answer(
            f"ℹ️ Пользователь <code>{chat_id}</code> уже в списке",
            parse_mode=ParseMode.HTML,
        )

    # Show updated admin panel
    await _send_admin_panel(message.chat.id)


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
            reply_markup=get_main_keyboard(
                is_admin=callback.from_user.id == settings.master_admin
            )
        )
        await callback.answer()
    else:
        await callback.answer("Нет данных от устройства", show_alert=True)


@router.callback_query(MenuCallback.filter(F.action == "graphs"))
async def callback_graphs_menu(callback: CallbackQuery):
    """Show graphs menu - delete and send new for single dashboard."""
    custom_dates = user_custom_dates.get(callback.from_user.id)
    chat_id = callback.message.chat.id
    await callback.message.delete()
    await bot.send_message(
        chat_id=chat_id,
        text="📈 <b>Выберите параметры графика:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_graph_keyboard(custom_dates=custom_dates)
    )
    await callback.answer()


@router.callback_query(MenuCallback.filter(F.action == "devices"))
async def callback_devices_menu(callback: CallbackQuery):
    """Show devices list - delete and send new for single dashboard."""
    devices = await database.get_all_devices(watched_only=False)
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
        await callback.answer()
    else:
        await callback.answer("Нет зарегистрированных устройств", show_alert=True)


@router.callback_query(MenuCallback.filter(F.action == "export"))
async def callback_export_excel(callback: CallbackQuery):
    """Send Excel export file."""
    device_id = user_devices.get(callback.from_user.id)
    if not device_id:
        device = await database.get_default_device()
        if not device:
            await callback.answer("❌ Нет устройств", show_alert=True)
            return
        device_id = device['device_id']
        device_name = device['name']
    else:
        device = await database.get_latest_reading(device_id)
        device_name = device.get('device_name', 'Device') if device else 'Device'

    # Get Excel file path
    excel_path = get_device_excel_path(device_name)

    if not excel_path:
        await callback.answer("❌ Файл не найден. Экспорт обновляется ежедневно в 08:00", show_alert=True)
        return

    await callback.answer("Отправка файла...")

    # Send file
    try:
        document = FSInputFile(excel_path)
        await bot.send_document(
            chat_id=callback.message.chat.id,
            document=document,
            caption=f"📊 Данные устройства: {device_name}"
        )
    except Exception as e:
        logger.error(f"Failed to send Excel file: {e}")
        await callback.message.answer("❌ Ошибка при отправке файла")


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
            reply_markup=get_main_keyboard(
                is_admin=callback.from_user.id == settings.master_admin
            )
        )


@router.callback_query(DeviceCallback.filter(F.action == "toggle_watch"))
async def callback_toggle_watch(callback: CallbackQuery, callback_data: DeviceCallback):
    """Toggle watched status for a device."""
    device_id = callback_data.device_id

    # Find current watched state
    devices = await database.get_all_devices(watched_only=False)
    device = next((d for d in devices if d['device_id'] == device_id), None)
    if not device:
        await callback.answer("Устройство не найдено", show_alert=True)
        return

    new_state = not bool(device.get('watched', 1))
    await database.set_device_watched(device_id, new_state)

    # Refresh devices keyboard
    devices = await database.get_all_devices(watched_only=False)
    current_device = user_devices.get(callback.from_user.id, "")
    chat_id = callback.message.chat.id
    await callback.message.delete()
    await bot.send_message(
        chat_id=chat_id,
        text="📱 <b>Выберите устройство:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_devices_keyboard(devices, current_device)
    )
    status = "включено" if new_state else "отключено"
    await callback.answer(f"Наблюдение {status} ✓")


@router.callback_query(GraphCallback.filter(F.action == "period"))
async def callback_change_period(callback: CallbackQuery, callback_data: GraphCallback):
    """Handle period change."""
    custom_dates = user_custom_dates.get(callback.from_user.id)
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=callback.message.caption,
                reply_markup=get_graph_keyboard(
                    period=callback_data.period,
                    show_temp=callback_data.show_temp,
                    show_gravity=callback_data.show_gravity,
                    custom_dates=custom_dates
                )
            )
        else:
            await callback.message.edit_reply_markup(
                reply_markup=get_graph_keyboard(
                    period=callback_data.period,
                    show_temp=callback_data.show_temp,
                    show_gravity=callback_data.show_gravity,
                    custom_dates=custom_dates
                )
            )
    except Exception as e:
        logger.warning(f"Failed to edit message in callback_change_period: {e}")
    await callback.answer()


@router.callback_query(GraphCallback.filter(F.action == "toggle_temp"))
@router.callback_query(GraphCallback.filter(F.action == "toggle_gravity"))
async def callback_toggle_graph(callback: CallbackQuery, callback_data: GraphCallback):
    """Handle graph toggle."""
    # Check if at least one is enabled
    if not callback_data.show_temp and not callback_data.show_gravity:
        await callback.answer("Выберите хотя бы один график!", show_alert=True)
        return

    custom_dates = user_custom_dates.get(callback.from_user.id)
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=callback.message.caption,
                reply_markup=get_graph_keyboard(
                    period=callback_data.period,
                    show_temp=callback_data.show_temp,
                    show_gravity=callback_data.show_gravity,
                    custom_dates=custom_dates
                )
            )
        else:
            await callback.message.edit_reply_markup(
                reply_markup=get_graph_keyboard(
                    period=callback_data.period,
                    show_temp=callback_data.show_temp,
                    show_gravity=callback_data.show_gravity,
                    custom_dates=custom_dates
                )
            )
    except Exception as e:
        logger.warning(f"Failed to edit message in callback_toggle_graph: {e}")
    await callback.answer()


@router.callback_query(GraphCallback.filter(F.action == "custom_range"))
async def callback_custom_range(callback: CallbackQuery, callback_data: GraphCallback, state: FSMContext):
    """Handle custom date range selection."""
    device_id = user_devices.get(callback.from_user.id)
    if not device_id:
        device = await database.get_default_device()
        if device:
            device_id = device['device_id']
        else:
            await callback.answer("❌ Нет устройств", show_alert=True)
            return

    # Get available date range for device
    date_range = await database.get_device_date_range(device_id)
    if not date_range:
        await callback.answer("❌ Нет данных для устройства", show_alert=True)
        return

    min_date, max_date = date_range
    min_date_local = min_date.astimezone(TZ_UTC7)
    max_date_local = max_date.astimezone(TZ_UTC7)

    # Store callback data for later use
    await state.update_data(
        show_temp=callback_data.show_temp,
        show_gravity=callback_data.show_gravity,
        device_id=device_id,
        min_date=min_date_local.strftime('%Y-%m-%d'),
        max_date=max_date_local.strftime('%Y-%m-%d')
    )

    chat_id = callback.message.chat.id
    await callback.message.delete()

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"📅 <b>Введите начальную дату</b> (ГГГГ-ММ-ДД)\n\n"
            f"Доступный диапазон:\n"
            f"<code>{min_date_local.strftime('%Y-%m-%d')}</code> — <code>{max_date_local.strftime('%Y-%m-%d')}</code>\n\n"
            f"Максимальный период: 1 год"
        ),
        parse_mode=ParseMode.HTML
    )

    await state.set_state(GraphStates.waiting_for_start_date)
    await callback.answer()


@router.message(GraphStates.waiting_for_start_date)
async def process_start_date(message: Message, state: FSMContext):
    """Process start date input."""
    if not message.text:
        await message.answer(
            "❌ Пожалуйста, введите дату текстом в формате ГГГГ-ММ-ДД",
            parse_mode=ParseMode.HTML
        )
        return

    date_text = message.text.strip()

    # Validate date format
    try:
        start_date = datetime.strptime(date_text, '%Y-%m-%d')
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД\n"
            "Например: <code>2025-01-01</code>",
            parse_mode=ParseMode.HTML
        )
        return

    data = await state.get_data()
    min_date = datetime.strptime(data['min_date'], '%Y-%m-%d')
    max_date = datetime.strptime(data['max_date'], '%Y-%m-%d')

    # Validate date is within range
    if start_date.date() < min_date.date() or start_date.date() > max_date.date():
        await message.answer(
            f"❌ Дата вне диапазона!\n"
            f"Доступно: <code>{data['min_date']}</code> — <code>{data['max_date']}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    await state.update_data(start_date=date_text)

    await message.answer(
        f"✓ Начало: <b>{date_text}</b>\n\n"
        f"📅 <b>Введите конечную дату</b> (ГГГГ-ММ-ДД)",
        parse_mode=ParseMode.HTML
    )

    await state.set_state(GraphStates.waiting_for_end_date)


@router.message(GraphStates.waiting_for_end_date)
async def process_end_date(message: Message, state: FSMContext):
    """Process end date input."""
    if not message.text:
        await message.answer(
            "❌ Пожалуйста, введите дату текстом в формате ГГГГ-ММ-ДД",
            parse_mode=ParseMode.HTML
        )
        return

    date_text = message.text.strip()

    # Validate date format
    try:
        end_date = datetime.strptime(date_text, '%Y-%m-%d')
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД\n"
            "Например: <code>2025-01-15</code>",
            parse_mode=ParseMode.HTML
        )
        return

    data = await state.get_data()
    start_date = datetime.strptime(data['start_date'], '%Y-%m-%d')
    max_date = datetime.strptime(data['max_date'], '%Y-%m-%d')

    # Validate end date >= start date
    if end_date.date() < start_date.date():
        await message.answer(
            f"❌ Конечная дата должна быть >= начальной!\n"
            f"Начальная дата: <code>{data['start_date']}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # Validate end date within range
    if end_date.date() > max_date.date():
        await message.answer(
            f"❌ Дата вне диапазона!\n"
            f"Максимум: <code>{data['max_date']}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # Validate range <= 1 year
    days_diff = (end_date - start_date).days
    if days_diff > 365:
        await message.answer(
            f"❌ Диапазон слишком большой!\n"
            f"Максимум: 365 дней\n"
            f"Выбрано: {days_diff} дней",
            parse_mode=ParseMode.HTML
        )
        return

    # Store custom dates
    user_custom_dates[message.from_user.id] = (data['start_date'], date_text)

    # Clear state
    await state.clear()

    # Return to graph keyboard with custom period selected
    custom_dates = user_custom_dates.get(message.from_user.id)
    await message.answer(
        f"✓ Диапазон установлен: <b>{data['start_date']}</b> — <b>{date_text}</b>\n\n"
        f"📈 <b>Выберите параметры графика:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_graph_keyboard(
            period="custom",
            show_temp=data.get('show_temp', True),
            show_gravity=data.get('show_gravity', True),
            custom_dates=custom_dates
        )
    )


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

    # Get custom dates if using custom period
    custom_dates = user_custom_dates.get(callback.from_user.id)
    start_date = None
    end_date = None

    # Check if custom period is selected but no dates are set
    if callback_data.period == "custom" and not custom_dates:
        await callback.message.answer(
            "❌ Сначала выберите диапазон дат, нажав кнопку «📅 Диапазон»",
            parse_mode=ParseMode.HTML
        )
        return

    # Get readings based on period type
    if callback_data.period == "custom" and custom_dates:
        # Parse dates and convert to UTC for database query
        start_local = datetime.strptime(custom_dates[0], '%Y-%m-%d').replace(tzinfo=TZ_UTC7)
        end_local = datetime.strptime(custom_dates[1], '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=TZ_UTC7)
        start_date = start_local.astimezone(timezone.utc)
        end_date = end_local.astimezone(timezone.utc)
        readings = await database.get_readings_for_date_range(device_id, start_date, end_date)
    else:
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
        show_gravity=callback_data.show_gravity,
        start_date=start_date,
        end_date=end_date
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
            show_gravity=callback_data.show_gravity,
            custom_dates=custom_dates
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
            reply_markup=get_main_keyboard(
                is_admin=callback.from_user.id == settings.master_admin
            )
        )
    await callback.answer()


async def main():
    """Start the bot."""
    # Initialize database
    await database.init_db()
    logger.info("Database initialized")

    # Seed allowed users from env var if DB table is empty
    env_users = [
        int(uid.strip()) for uid in settings.allowed_users.split(",") if uid.strip()
    ]
    if env_users:
        await database.seed_allowed_users(env_users)

    # Load allowed users cache from DB
    await reload_allowed_users()
    logger.info(f"Loaded {len(allowed_users)} allowed users from DB")

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
