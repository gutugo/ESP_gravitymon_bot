# GravityMon Telegram Bot

## Server
- **IP:** 213.139.210.66
- **SSH:** `ssh root@213.139.210.66`
- **Project path:** `/opt/gravitymon/`
- **API endpoint:** `http://213.139.210.66:8080/api/v1/webhook`

## Architecture
```
ESP (HTTP POST) → Host Nginx:8080 → FastAPI:5000 (Docker) → SQLite
                                          ↓
                                    Telegram Bot (Docker, polling)
                                          ↓
                                    APScheduler (daily reports)
```
- **Host nginx** config: `/etc/nginx/sites-available/gravitymon`
- **Docker containers:** `gravitymon-api` (port 127.0.0.1:5000), `gravitymon-bot`
- **Firewall:** UFW allows port 8080/tcp

## Key Files
| File | Purpose |
|------|---------|
| `app/bot.py` | Telegram bot + inline keyboards |
| `app/main.py` | FastAPI webhook server |
| `app/database.py` | SQLite operations |
| `app/graphs.py` | Matplotlib charts (0.0025 SG scale) |
| `app/alerts.py` | Battery alert system |
| `app/daily_report.py` | Daily report generation |
| `app/scheduler.py` | APScheduler for daily reports |

## Bot Commands
| Command | Action |
|---------|--------|
| `/start` | Dashboard + auto-subscribe |
| `/status` | Current readings |
| `/graph` | Generate charts |
| `/report` | Test daily report |
| `/subscribe` | Enable notifications |
| `/unsubscribe` | Disable notifications |

### Admin Commands (master admin only)
| Command | Action |
|---------|--------|
| `/users` | List all allowed user IDs |
| `/adduser <id>` | Add user to whitelist |
| `/rmuser <id>` | Remove user (cannot remove master admin) |

### Admin Panel (inline buttons)
- Main menu shows **⚙️ Админ** button for master admin only
- Admin panel displays all whitelisted users with Telegram names
- **❌** button to remove a user (master admin cannot be removed)
- **➕ Добавить** button to add a user by chat_id

## Daily Report
- **Schedule:** 08:00 UTC+7 (01:00 UTC)
- **Recipients:** All subscribers
- **Content:** 24h stats, fermentation status, battery, missed packets

## Alert Thresholds
| Level | Voltage | Cooldown |
|-------|---------|----------|
| Low | ≤ 3.3V | 6 hours |
| Critical | ≤ 3.1V | 6 hours |

## Deployment
```bash
# Git remotes: origin (GitHub), server (production)
git push server main
ssh root@213.139.210.66 "cd /opt/gravitymon && docker compose build && docker compose up -d"

# Logs
ssh root@213.139.210.66 "docker logs gravitymon-bot --tail 50"
ssh root@213.139.210.66 "docker logs gravitymon-api --tail 50"

# Host nginx (not in Docker)
ssh root@213.139.210.66 "nginx -t && systemctl reload nginx"
```

## Timezone
All timestamps use **UTC+7**. DB stores UTC, converted for display.

## Test Commands
```bash
# Send test data
curl -X POST http://213.139.210.66:8080/api/v1/webhook \
  -H "Content-Type: application/json" \
  -d '{"name":"708_1_SG","ID":"0081a7","temperature":20.5,"temp_units":"C","gravity":1.025,"battery":3.89,"RSSI":-65,"interval":900}'

# Send test daily report
docker exec gravitymon-bot python -c "
import asyncio
from daily_report import generate_daily_report
from alerts import send_telegram_message
import database
async def test():
    await database.init_db()
    device = await database.get_default_device()
    report = await generate_daily_report(device['device_id'], device['name'])
    await send_telegram_message(167129794, report)
asyncio.run(test())"
```

## Access Control
- **Master admin** (`MASTER_ADMIN` env var): always allowed, can manage whitelist
- **Whitelist** stored in `allowed_users` DB table, seeded from `ALLOWED_USERS` env on first run
- Cached in memory, refreshed on `/adduser` and `/rmuser`

## Database Tables
- `devices` - ESP devices
- `readings` - sensor data
- `subscribers` - notification recipients
- `alerts_sent` - cooldown tracking
- `allowed_users` - bot access whitelist

## ESP Configuration
- Webhook URL must be set on the ESP device via its web interface
- **Configuration** → **Push Targets** → **HTTP Post** → URL: `http://213.139.210.66:8080/api/v1/webhook`
- See `ESP_CONFIGURATION.md` for full instructions

## Recent Changes (2026-02-01)

### Infrastructure
- Removed Docker nginx container, proxy through host nginx instead (saves ~60 MB image + 1 container)
- Host nginx on port 8080 proxies to FastAPI on 127.0.0.1:5000
- Added UFW rule for port 8080/tcp

### Features
- Master admin role (`MASTER_ADMIN` env var) with dynamic whitelist management
- Admin commands: `/users`, `/adduser`, `/rmuser`
- Admin panel with inline buttons (⚙️ Админ in main menu)
- Whitelist stored in DB (`allowed_users` table), seeded from `ALLOWED_USERS` env on first run
- Migrated server from 193.233.204.221 to 213.139.210.66

### Previous Changes (2026-01-16)
- Fixed double `callback.answer()` in `bot.py`
- Fixed matplotlib locator singleton reuse in `graphs.py`
- Custom date range for graphs, daily Excel export
- GitHub repo security audit: no leaks found
