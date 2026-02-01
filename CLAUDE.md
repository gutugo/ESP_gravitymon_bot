# GravityMon Telegram Bot

## Server
- **IP:** 193.233.204.221
- **SSH:** `ssh root@193.233.204.221`
- **Project path:** `/opt/gravitymon/`
- **API endpoint:** `http://193.233.204.221:8080/api/v1/webhook`

## Architecture
```
ESP (HTTP POST) → Nginx:8080 → FastAPI:5000 → SQLite
                                    ↓
                              Telegram Bot (polling)
                                    ↓
                              APScheduler (daily reports)
```

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
ssh root@193.233.204.221 "cd /opt/gravitymon && docker-compose build bot && docker-compose up -d bot"

# Logs
docker logs gravitymon-bot --tail 50
docker logs gravitymon-api --tail 50
```

## Timezone
All timestamps use **UTC+7**. DB stores UTC, converted for display.

## Test Commands
```bash
# Send test data
curl -X POST http://193.233.204.221:8080/api/v1/webhook \
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

## Recent Changes (2026-01-16)

### Bug Fixes
- Fixed double `callback.answer()` in `bot.py` (callback_status, callback_devices_menu)
- Fixed matplotlib locator singleton reuse in `graphs.py` (changed to `locator_factory` lambdas)
- Added error handling for Excel file send in `callback_export_excel`

### Features Added (Previous Sessions)
- Custom date range for graphs (📅 Диапазон button)
- Daily Excel export (📊 XLSX button)
- Graph time scale improvements (5min/12h/1day ticks)

### Security
- GitHub repo audited: no leaks found
- `.env` properly gitignored, only placeholders in `.env.example`

### Test Plan
- Full test coverage plan saved at `.claude/plans/clever-percolating-cerf.md`
- ~100 tests planned across 10 test files
- Not yet implemented
