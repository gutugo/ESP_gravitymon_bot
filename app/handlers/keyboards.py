from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData


class MenuCallback(CallbackData, prefix="menu"):
    action: str  # "status", "graphs", "refresh", "devices"


class GraphCallback(CallbackData, prefix="graph"):
    action: str  # "period", "toggle_temp", "toggle_gravity", "generate", "back"
    period: str = "day"
    show_temp: bool = True
    show_gravity: bool = True


class DeviceCallback(CallbackData, prefix="device"):
    action: str  # "select"
    device_id: str = ""


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Main menu keyboard after status display."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📈 Графики",
                callback_data=MenuCallback(action="graphs").pack()
            ),
            InlineKeyboardButton(
                text="🔄 Обновить",
                callback_data=MenuCallback(action="refresh").pack()
            )
        ],
        [
            InlineKeyboardButton(
                text="📱 Устройства",
                callback_data=MenuCallback(action="devices").pack()
            )
        ]
    ])


def get_graph_keyboard(
    period: str = "day",
    show_temp: bool = True,
    show_gravity: bool = True,
    custom_dates: tuple[str, str] | None = None
) -> InlineKeyboardMarkup:
    """Graph selection keyboard."""
    # Period buttons
    periods = [
        ("1 Час", "hour"),
        ("1 День", "day"),
        ("1 Нед", "week"),
        ("1 Мес", "month")
    ]

    period_buttons = []
    for label, p in periods:
        if p == period:
            label = f"• {label} •"
        period_buttons.append(
            InlineKeyboardButton(
                text=label,
                callback_data=GraphCallback(
                    action="period",
                    period=p,
                    show_temp=show_temp,
                    show_gravity=show_gravity
                ).pack()
            )
        )

    # Custom date range button
    if custom_dates:
        start_short = custom_dates[0][5:]  # MM-DD from YYYY-MM-DD
        end_short = custom_dates[1][5:]
        custom_label = f"• 📅 {start_short} — {end_short} •" if period == "custom" else f"📅 {start_short} — {end_short}"
    else:
        custom_label = "• 📅 Диапазон •" if period == "custom" else "📅 Диапазон"

    custom_button = InlineKeyboardButton(
        text=custom_label,
        callback_data=GraphCallback(
            action="custom_range",
            period="custom",
            show_temp=show_temp,
            show_gravity=show_gravity
        ).pack()
    )

    # Toggle buttons
    temp_label = "✅ Температура" if show_temp else "❌ Температура"
    gravity_label = "✅ Плотность" if show_gravity else "❌ Плотность"

    toggle_buttons = [
        InlineKeyboardButton(
            text=temp_label,
            callback_data=GraphCallback(
                action="toggle_temp",
                period=period,
                show_temp=not show_temp,
                show_gravity=show_gravity
            ).pack()
        ),
        InlineKeyboardButton(
            text=gravity_label,
            callback_data=GraphCallback(
                action="toggle_gravity",
                period=period,
                show_temp=show_temp,
                show_gravity=not show_gravity
            ).pack()
        )
    ]

    # Generate button
    generate_button = InlineKeyboardButton(
        text="📊 Построить график",
        callback_data=GraphCallback(
            action="generate",
            period=period,
            show_temp=show_temp,
            show_gravity=show_gravity
        ).pack()
    )

    # Back button
    back_button = InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=GraphCallback(action="back", period=period, show_temp=show_temp, show_gravity=show_gravity).pack()
    )

    return InlineKeyboardMarkup(inline_keyboard=[
        period_buttons[:2],  # First row: Hour, Day
        period_buttons[2:],  # Second row: Week, Month
        [custom_button],     # Custom date range button
        toggle_buttons,      # Toggle row
        [generate_button],   # Generate button
        [back_button]        # Back button
    ])


def get_devices_keyboard(devices: list, current_device_id: str = "") -> InlineKeyboardMarkup:
    """Device selection keyboard."""
    buttons = []
    for device in devices:
        label = device['name']
        if device['device_id'] == current_device_id:
            label = f"• {label} •"
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=DeviceCallback(
                    action="select",
                    device_id=device['device_id']
                ).pack()
            )
        ])

    # Back button
    buttons.append([
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=MenuCallback(action="status").pack()
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
