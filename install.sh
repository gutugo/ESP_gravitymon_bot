#!/bin/bash
# GravityMon One-Click Installer
# Run this script on your VPS

set -e

echo "=== GravityMon Installer ==="

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# Install Docker Compose plugin if needed
if ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose..."
    apt-get update && apt-get install -y docker-compose-plugin
fi

# Create project directory
mkdir -p /opt/gravitymon/{app/handlers,nginx,data}
cd /opt/gravitymon

# Create requirements.txt
cat > app/requirements.txt << 'REQEOF'
aiogram>=3.4.0
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
aiosqlite>=0.19.0
pandas>=2.0.0
matplotlib>=3.8.0
python-dotenv>=1.0.0
httpx>=0.26.0
REQEOF

# Create config.py
cat > app/config.py << 'CFGEOF'
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    telegram_bot_token: str = ""
    database_url: str = "/data/gravitymon.db"
    api_host: str = "0.0.0.0"
    api_port: int = 5000
    api_token: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
CFGEOF

# Create database.py
cat > app/database.py << 'DBEOF'
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional
from config import settings

DATABASE_URL = settings.database_url

async def init_db():
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                temperature REAL NOT NULL,
                temp_unit TEXT DEFAULT 'C',
                gravity REAL NOT NULL,
                gravity_unit TEXT DEFAULT 'G',
                angle REAL,
                battery REAL NOT NULL,
                rssi INTEGER,
                interval_sec INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_readings_device_time ON readings(device_id, timestamp DESC);
        """)
        await db.commit()

async def upsert_device(device_id: str, name: str):
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("""
            INSERT INTO devices (device_id, name, last_seen) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(device_id) DO UPDATE SET name = excluded.name, last_seen = CURRENT_TIMESTAMP
        """, (device_id, name))
        await db.commit()

async def insert_reading(device_id: str, temperature: float, temp_unit: str, gravity: float,
                         gravity_unit: str, battery: float, angle: Optional[float] = None,
                         rssi: Optional[int] = None, interval_sec: Optional[int] = None):
    async with aiosqlite.connect(DATABASE_URL) as db:
        await db.execute("""
            INSERT INTO readings (device_id, temperature, temp_unit, gravity, gravity_unit, angle, battery, rssi, interval_sec)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (device_id, temperature, temp_unit, gravity, gravity_unit, angle, battery, rssi, interval_sec))
        await db.commit()

async def get_latest_reading(device_id: Optional[str] = None):
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        if device_id:
            cursor = await db.execute("""
                SELECT r.*, d.name as device_name FROM readings r
                JOIN devices d ON r.device_id = d.device_id WHERE r.device_id = ?
                ORDER BY r.timestamp DESC LIMIT 1
            """, (device_id,))
        else:
            cursor = await db.execute("""
                SELECT r.*, d.name as device_name FROM readings r
                JOIN devices d ON r.device_id = d.device_id ORDER BY r.timestamp DESC LIMIT 1
            """)
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_readings_for_period(device_id: str, period: str):
    now = datetime.now()
    period_map = {'hour': timedelta(hours=1), 'day': timedelta(days=1),
                  'week': timedelta(weeks=1), 'month': timedelta(days=30)}
    delta = period_map.get(period, timedelta(days=1))
    start_time = now - delta
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT timestamp, temperature, temp_unit, gravity, gravity_unit, battery
            FROM readings WHERE device_id = ? AND timestamp >= ? ORDER BY timestamp ASC
        """, (device_id, start_time.isoformat()))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_all_devices():
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT device_id, name, last_seen FROM devices ORDER BY last_seen DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_default_device():
    async with aiosqlite.connect(DATABASE_URL) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT device_id, name FROM devices ORDER BY last_seen DESC LIMIT 1")
        row = await cursor.fetchone()
        return dict(row) if row else None
DBEOF

# Create graphs.py
cat > app/graphs.py << 'GRAPHEOF'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from io import BytesIO
from typing import List, Dict

PERIOD_CONFIG = {
    'hour': {'title': '1 час', 'date_format': '%H:%M', 'locator': mdates.MinuteLocator(interval=10)},
    'day': {'title': '1 день', 'date_format': '%H:%M', 'locator': mdates.HourLocator(interval=4)},
    'week': {'title': '1 неделя', 'date_format': '%d.%m', 'locator': mdates.DayLocator()},
    'month': {'title': '1 месяц', 'date_format': '%d.%m', 'locator': mdates.DayLocator(interval=5)},
}

def generate_graph(readings: List[Dict], device_name: str, period: str,
                   show_temperature: bool = True, show_gravity: bool = True) -> BytesIO:
    if not readings:
        return _generate_empty_graph(device_name, period)
    timestamps, temperatures, gravities = [], [], []
    temp_unit, gravity_unit = 'C', 'SG'
    for r in readings:
        try:
            ts = r['timestamp']
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            timestamps.append(ts)
            temperatures.append(r['temperature'])
            gravities.append(r['gravity'])
            temp_unit = r.get('temp_unit', 'C')
            gravity_unit = 'SG' if r.get('gravity_unit', 'G') == 'G' else 'P'
        except (KeyError, ValueError):
            continue
    if not timestamps:
        return _generate_empty_graph(device_name, period)
    num_plots = sum([show_temperature, show_gravity])
    if num_plots == 0:
        return _generate_empty_graph(device_name, period)
    fig, axes = plt.subplots(nrows=num_plots, ncols=1, figsize=(10, 4 * num_plots), squeeze=False)
    config = PERIOD_CONFIG.get(period, PERIOD_CONFIG['day'])
    ax_idx = 0
    if show_temperature:
        ax = axes[ax_idx, 0]
        ax.plot(timestamps, temperatures, 'r-', linewidth=2, marker='o', markersize=3)
        ax.fill_between(timestamps, temperatures, alpha=0.2, color='red')
        ax.set_ylabel(f'Температура (°{temp_unit})', fontsize=11, fontweight='bold')
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.xaxis.set_major_formatter(mdates.DateFormatter(config['date_format']))
        ax.xaxis.set_major_locator(config['locator'])
        ax_idx += 1
    if show_gravity:
        ax = axes[ax_idx, 0]
        ax.plot(timestamps, gravities, 'b-', linewidth=2, marker='s', markersize=3)
        ax.fill_between(timestamps, gravities, alpha=0.2, color='blue')
        ax.set_ylabel(f'Плотность ({gravity_unit})', fontsize=11, fontweight='bold')
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.xaxis.set_major_formatter(mdates.DateFormatter(config['date_format']))
        ax.xaxis.set_major_locator(config['locator'])
        ax.yaxis.set_major_formatter(plt.FormatStrFormatter('%.4f'))
    fig.suptitle(f'{device_name} — {config["title"]}', fontsize=14, fontweight='bold')
    fig.autofmt_xdate()
    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    plt.close(fig)
    return buf

def _generate_empty_graph(device_name: str, period: str) -> BytesIO:
    config = PERIOD_CONFIG.get(period, PERIOD_CONFIG['day'])
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.text(0.5, 0.5, 'Нет данных за выбранный период', ha='center', va='center', fontsize=14, transform=ax.transAxes)
    ax.axis('off')
    fig.suptitle(f'{device_name} — {config["title"]}', fontsize=14, fontweight='bold')
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    plt.close(fig)
    return buf
GRAPHEOF

# Create handlers/__init__.py
cat > app/handlers/__init__.py << 'HINITEOF'
# Telegram bot handlers
HINITEOF

# Create handlers/keyboards.py
cat > app/handlers/keyboards.py << 'KBEOF'
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData

class MenuCallback(CallbackData, prefix="menu"):
    action: str

class GraphCallback(CallbackData, prefix="graph"):
    action: str
    period: str = "day"
    show_temp: bool = True
    show_gravity: bool = True

class DeviceCallback(CallbackData, prefix="device"):
    action: str
    device_id: str = ""

def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Графики", callback_data=MenuCallback(action="graphs").pack()),
         InlineKeyboardButton(text="🔄 Обновить", callback_data=MenuCallback(action="refresh").pack())],
        [InlineKeyboardButton(text="📱 Устройства", callback_data=MenuCallback(action="devices").pack())]
    ])

def get_graph_keyboard(period: str = "day", show_temp: bool = True, show_gravity: bool = True) -> InlineKeyboardMarkup:
    periods = [("1 Час", "hour"), ("1 День", "day"), ("1 Нед", "week"), ("1 Мес", "month")]
    period_buttons = []
    for label, p in periods:
        if p == period:
            label = f"• {label} •"
        period_buttons.append(InlineKeyboardButton(text=label,
            callback_data=GraphCallback(action="period", period=p, show_temp=show_temp, show_gravity=show_gravity).pack()))
    temp_label = "✅ Температура" if show_temp else "❌ Температура"
    gravity_label = "✅ Плотность" if show_gravity else "❌ Плотность"
    toggle_buttons = [
        InlineKeyboardButton(text=temp_label, callback_data=GraphCallback(action="toggle_temp", period=period, show_temp=not show_temp, show_gravity=show_gravity).pack()),
        InlineKeyboardButton(text=gravity_label, callback_data=GraphCallback(action="toggle_gravity", period=period, show_temp=show_temp, show_gravity=not show_gravity).pack())
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        period_buttons[:2], period_buttons[2:], toggle_buttons,
        [InlineKeyboardButton(text="📊 Построить график", callback_data=GraphCallback(action="generate", period=period, show_temp=show_temp, show_gravity=show_gravity).pack())],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=GraphCallback(action="back", period=period, show_temp=show_temp, show_gravity=show_gravity).pack())]
    ])

def get_devices_keyboard(devices: list, current_device_id: str = "") -> InlineKeyboardMarkup:
    buttons = []
    for device in devices:
        label = device['name']
        if device['device_id'] == current_device_id:
            label = f"• {label} •"
        buttons.append([InlineKeyboardButton(text=label, callback_data=DeviceCallback(action="select", device_id=device['device_id']).pack())])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=MenuCallback(action="status").pack())])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
KBEOF

echo "Creating main API and bot files..."

# Create main.py (API server)
cat > app/main.py << 'MAINEOF'
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager
from config import settings
import database

class ISpindelPayload(BaseModel):
    name: str
    ID: str
    token: Optional[str] = ""
    interval: Optional[int] = 900
    temperature: float
    temp_units: Optional[str] = "C"
    gravity: float
    angle: Optional[float] = None
    battery: float
    RSSI: Optional[int] = None
    corr_gravity: Optional[float] = None
    gravity_unit: Optional[str] = "G"
    run_time: Optional[int] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()
    print("Database initialized")
    yield

app = FastAPI(title="GravityMon API", version="1.0.0", lifespan=lifespan)

@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "service": "gravitymon-api"}

@app.post("/api/v1/webhook")
async def receive_data(payload: ISpindelPayload, authorization: Optional[str] = Header(None)):
    if settings.api_token:
        if authorization != f"Bearer {settings.api_token}":
            raise HTTPException(status_code=401, detail="Invalid token")
    try:
        await database.upsert_device(device_id=payload.ID, name=payload.name)
        await database.insert_reading(
            device_id=payload.ID, temperature=payload.temperature, temp_unit=payload.temp_units or "C",
            gravity=payload.gravity, gravity_unit=payload.gravity_unit or "G", battery=payload.battery,
            angle=payload.angle, rssi=payload.RSSI, interval_sec=payload.interval
        )
        print(f"Received: {payload.name} temp={payload.temperature} gravity={payload.gravity} battery={payload.battery}")
        return {"status": "ok", "device": payload.name, "device_id": payload.ID}
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/devices")
async def list_devices():
    return {"devices": await database.get_all_devices()}

@app.get("/api/v1/devices/{device_id}/status")
async def get_device_status(device_id: str):
    reading = await database.get_latest_reading(device_id)
    if not reading:
        raise HTTPException(status_code=404, detail="Device not found")
    return reading

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.api_host, port=settings.api_port, reload=False)
MAINEOF

# Create bot.py
cat > app/bot.py << 'BOTEOF'
import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.enums import ParseMode
from config import settings
import database
import graphs
from handlers.keyboards import MenuCallback, GraphCallback, DeviceCallback, get_main_keyboard, get_graph_keyboard, get_devices_keyboard

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()
router = Router()
user_devices: dict[int, str] = {}

def format_time_ago(timestamp) -> str:
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    now = datetime.now()
    if timestamp.tzinfo:
        now = datetime.now(timestamp.tzinfo)
    diff = now - timestamp
    minutes = int(diff.total_seconds() / 60)
    if minutes < 1: return "только что"
    elif minutes < 60: return f"{minutes} мин назад"
    elif minutes < 1440: return f"{minutes // 60} ч назад"
    else: return f"{minutes // 1440} дн назад"

def format_status_message(reading: dict) -> str:
    device_name = reading.get('device_name', reading.get('name', 'Устройство'))
    temp = reading.get('temperature', 0)
    temp_unit = reading.get('temp_unit', 'C')
    gravity = reading.get('gravity', 0)
    battery = reading.get('battery', 0)
    timestamp = reading.get('timestamp', '')
    time_ago = format_time_ago(timestamp) if timestamp else "неизвестно"
    return (f"<b>{device_name}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"🌡 <b>Температура:</b> {temp:.1f}°{temp_unit}\n"
            f"📊 <b>Плотность:</b> {gravity:.4f} SG\n"
            f"🔋 <b>Батарея:</b> {battery:.2f}V\n"
            f"📡 <b>Обновлено:</b> {time_ago}")

@router.message(Command("start", "help"))
async def cmd_start(message: Message):
    await database.init_db()
    reading = await database.get_latest_reading()
    if reading:
        user_devices[message.from_user.id] = reading.get('device_id', '')
        await message.answer(format_status_message(reading), parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
    else:
        await message.answer("👋 <b>Добро пожаловать в GravityMon Bot!</b>\n\nПока нет данных от устройства.\nИспользуйте /status для проверки.", parse_mode=ParseMode.HTML)

@router.message(Command("status"))
async def cmd_status(message: Message):
    device_id = user_devices.get(message.from_user.id)
    reading = await database.get_latest_reading(device_id)
    if reading:
        user_devices[message.from_user.id] = reading.get('device_id', '')
        await message.answer(format_status_message(reading), parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
    else:
        await message.answer("❌ Нет данных от устройства.", parse_mode=ParseMode.HTML)

@router.message(Command("graph"))
async def cmd_graph(message: Message):
    await message.answer("📈 <b>Выберите параметры графика:</b>", parse_mode=ParseMode.HTML, reply_markup=get_graph_keyboard())

@router.callback_query(MenuCallback.filter(F.action.in_({"status", "refresh"})))
async def callback_status(callback: CallbackQuery):
    device_id = user_devices.get(callback.from_user.id)
    reading = await database.get_latest_reading(device_id)
    if reading:
        user_devices[callback.from_user.id] = reading.get('device_id', '')
        await callback.message.edit_text(format_status_message(reading), parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
    else:
        await callback.answer("Нет данных", show_alert=True)
    await callback.answer()

@router.callback_query(MenuCallback.filter(F.action == "graphs"))
async def callback_graphs_menu(callback: CallbackQuery):
    await callback.message.edit_text("📈 <b>Выберите параметры графика:</b>", parse_mode=ParseMode.HTML, reply_markup=get_graph_keyboard())
    await callback.answer()

@router.callback_query(MenuCallback.filter(F.action == "devices"))
async def callback_devices_menu(callback: CallbackQuery):
    devices = await database.get_all_devices()
    current_device = user_devices.get(callback.from_user.id, "")
    if devices:
        await callback.message.edit_text("📱 <b>Выберите устройство:</b>", parse_mode=ParseMode.HTML, reply_markup=get_devices_keyboard(devices, current_device))
    else:
        await callback.answer("Нет устройств", show_alert=True)
    await callback.answer()

@router.callback_query(DeviceCallback.filter(F.action == "select"))
async def callback_select_device(callback: CallbackQuery, callback_data: DeviceCallback):
    user_devices[callback.from_user.id] = callback_data.device_id
    await callback.answer("Устройство выбрано ✓")
    reading = await database.get_latest_reading(callback_data.device_id)
    if reading:
        await callback.message.edit_text(format_status_message(reading), parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())

@router.callback_query(GraphCallback.filter(F.action == "period"))
async def callback_change_period(callback: CallbackQuery, callback_data: GraphCallback):
    await callback.message.edit_reply_markup(reply_markup=get_graph_keyboard(period=callback_data.period, show_temp=callback_data.show_temp, show_gravity=callback_data.show_gravity))
    await callback.answer()

@router.callback_query(GraphCallback.filter(F.action.in_({"toggle_temp", "toggle_gravity"})))
async def callback_toggle_graph(callback: CallbackQuery, callback_data: GraphCallback):
    if not callback_data.show_temp and not callback_data.show_gravity:
        await callback.answer("Выберите хотя бы один график!", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=get_graph_keyboard(period=callback_data.period, show_temp=callback_data.show_temp, show_gravity=callback_data.show_gravity))
    await callback.answer()

@router.callback_query(GraphCallback.filter(F.action == "generate"))
async def callback_generate_graph(callback: CallbackQuery, callback_data: GraphCallback):
    await callback.answer("Генерация графика...")
    device_id = user_devices.get(callback.from_user.id)
    if not device_id:
        device = await database.get_default_device()
        if device: device_id = device['device_id']
        else:
            await callback.message.answer("❌ Нет устройств")
            return
    readings = await database.get_readings_for_period(device_id, callback_data.period)
    device = await database.get_latest_reading(device_id)
    device_name = device.get('device_name', 'Устройство') if device else 'Устройство'
    graph_buffer = graphs.generate_graph(readings=readings, device_name=device_name, period=callback_data.period, show_temperature=callback_data.show_temp, show_gravity=callback_data.show_gravity)
    photo = BufferedInputFile(graph_buffer.read(), filename=f"graph_{callback_data.period}.png")
    await callback.message.answer_photo(photo=photo, caption=f"📈 {device_name}", reply_markup=get_graph_keyboard(period=callback_data.period, show_temp=callback_data.show_temp, show_gravity=callback_data.show_gravity))

@router.callback_query(GraphCallback.filter(F.action == "back"))
async def callback_back_to_status(callback: CallbackQuery):
    device_id = user_devices.get(callback.from_user.id)
    reading = await database.get_latest_reading(device_id)
    if reading:
        await callback.message.edit_text(format_status_message(reading), parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
    await callback.answer()

async def main():
    await database.init_db()
    logger.info("Database initialized")
    dp.include_router(router)
    logger.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
BOTEOF

# Create Dockerfile
cat > app/Dockerfile << 'DOCKEOF'
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc-dev libffi-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data
CMD ["python", "main.py"]
DOCKEOF

# Create docker-compose.yml
cat > docker-compose.yml << 'COMPEOF'
version: "3.8"

services:
  nginx:
    image: nginx:alpine
    container_name: gravitymon-nginx
    ports:
      - "8080:80"
    volumes:
      - ./nginx/gravitymon.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - api
    networks:
      - gravitymon-net
    restart: unless-stopped

  api:
    build: ./app
    container_name: gravitymon-api
    command: python main.py
    environment:
      - DATABASE_URL=/data/gravitymon.db
    env_file:
      - .env
    volumes:
      - ./data:/data
    expose:
      - "5000"
    networks:
      - gravitymon-net
    restart: unless-stopped

  bot:
    build: ./app
    container_name: gravitymon-bot
    command: python bot.py
    environment:
      - DATABASE_URL=/data/gravitymon.db
    env_file:
      - .env
    volumes:
      - ./data:/data
    depends_on:
      - api
    networks:
      - gravitymon-net
    restart: unless-stopped

networks:
  gravitymon-net:
    driver: bridge
COMPEOF

# Create nginx config
cat > nginx/gravitymon.conf << 'NGXEOF'
upstream api_server {
    server api:5000;
}

server {
    listen 80;
    server_name _;
    proxy_connect_timeout 60s;
    proxy_read_timeout 60s;
    proxy_send_timeout 60s;

    location /api/ {
        proxy_pass http://api_server;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://api_server/api/v1/health;
    }

    location / {
        return 404 '{"error": "not found"}';
        add_header Content-Type application/json;
    }
}
NGXEOF

# Create .env file (user must edit with their token)
cat > .env << 'ENVEOF'
TELEGRAM_BOT_TOKEN=your_bot_token_here
API_TOKEN=
ENVEOF

echo ""
echo "IMPORTANT: Edit .env file with your Telegram bot token!"
echo "  nano .env"

echo ""
echo "=== Building and starting services ==="
docker compose build
docker compose up -d

sleep 5

echo ""
echo "=== Service Status ==="
docker compose ps

echo ""
echo "=== Testing API ==="
curl -s http://localhost:8080/health || echo "Waiting for API..."

echo ""
echo "==========================================="
echo "Installation complete!"
echo ""
echo "API Endpoint: http://YOUR_SERVER_IP:8080/api/v1/webhook"
echo ""
echo "Configure your ESP to send data to this URL."
echo "Then open Telegram and message your bot"
echo "==========================================="
