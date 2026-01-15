# GravityMon Telegram Bot

A Telegram bot for monitoring fermentation using ESP-based hydrometers (GravityMon/iSpindel). Track temperature, gravity, and battery levels with real-time notifications and daily reports.

## Features

- **Real-time Monitoring** - View current temperature, gravity, and battery status
- **Interactive Graphs** - Generate charts for different time periods (1h, 24h, 7d, 30d)
- **Multi-device Support** - Monitor multiple ESP devices from one bot
- **Push Notifications** - Alerts for low and critical battery levels
- **Daily Reports** - Automated summary of 24h fermentation data with:
  - Temperature min/max/avg
  - Gravity changes and fermentation status
  - ABV estimation
  - Battery health
  - Signal quality and packet statistics
- **Russian Interface** - Bot messages in Russian language

## Architecture

```
ESP Device (HTTP POST) → Nginx → FastAPI → SQLite
                                    ↓
                              Telegram Bot (polling)
                                    ↓
                              APScheduler (daily reports)
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- ESP device with GravityMon or iSpindel firmware

### Installation

1. Clone the repository:
```bash
git clone https://github.com/gutugo/ESP_gravitymon_bot.git
cd ESP_gravitymon_bot
```

2. Create environment file:
```bash
cp .env.example .env
```

3. Edit `.env` with your settings:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
DATABASE_URL=gravitymon.db
```

4. Start the services:
```bash
docker-compose up -d
```

5. Configure your ESP device to send data to:
```
http://YOUR_SERVER_IP:8080/api/v1/webhook
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | Required |
| `DATABASE_URL` | SQLite database path | `gravitymon.db` |

### ESP Device Setup

Configure your GravityMon/iSpindel device with:

```json
{
  "http_post_target": "http://YOUR_SERVER:8080/api/v1/webhook",
  "http_post_header1": "Content-Type: application/json"
}
```

See [ESP_CONFIGURATION.md](ESP_CONFIGURATION.md) for detailed setup instructions.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Show status and subscribe to notifications |
| `/status` | Display current device readings |
| `/graph` | Open graph generation menu |
| `/report` | Generate daily report manually |
| `/subscribe` | Enable push notifications |
| `/unsubscribe` | Disable push notifications |

## API Endpoints

### Webhook Endpoint

```
POST /api/v1/webhook
Content-Type: application/json
```

**Request body:**
```json
{
  "name": "Device_Name",
  "ID": "device_id",
  "temperature": 20.5,
  "temp_units": "C",
  "gravity": 1.045,
  "battery": 3.89,
  "RSSI": -65,
  "interval": 900
}
```

### Health Check

```
GET /health
```

## Alert System

The bot sends notifications when battery voltage drops below thresholds:

| Level | Voltage | Action |
|-------|---------|--------|
| Low | ≤ 3.3V | Warning notification |
| Critical | ≤ 3.1V | Urgent notification |

Alerts have a 6-hour cooldown to prevent spam.

## Daily Reports

Automated reports are sent daily at 08:00 (UTC+7) including:

- Temperature statistics (min/max/average)
- Gravity delta and fermentation status
- Estimated ABV calculation
- Battery health assessment
- Signal quality metrics
- Missed packet count
- Alert summary

## Project Structure

```
├── app/
│   ├── bot.py          # Telegram bot handlers
│   ├── main.py         # FastAPI webhook server
│   ├── database.py     # SQLite operations
│   ├── graphs.py       # Matplotlib chart generation
│   ├── alerts.py       # Push notification system
│   ├── daily_report.py # Daily report generation
│   ├── scheduler.py    # APScheduler for daily reports
│   ├── config.py       # Configuration management
│   └── handlers/       # Keyboard handlers
├── nginx/              # Nginx configuration
├── docker-compose.yml  # Docker services
├── .env.example        # Environment template
└── ESP_CONFIGURATION.md
```

## Development

### Local Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r app/requirements.txt

# Run locally
python app/bot.py
```

### Docker Commands

```bash
# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f bot
docker-compose logs -f api

# Restart services
docker-compose restart

# Stop all
docker-compose down
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [GravityMon](https://github.com/mp-se/gravitymon) - ESP firmware for hydrometers
- [iSpindel](https://github.com/universam1/iSpindel) - Original digital hydrometer project
- [aiogram](https://github.com/aiogram/aiogram) - Async Telegram Bot framework
