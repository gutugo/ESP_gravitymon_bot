# GravityMon ESP Configuration / Настройка ESP GravityMon

---

## English

### Method 1: Via Web Interface

1. **Connect to your GravityMon device**
   - If device is in AP mode: Connect to WiFi network `GravityMon` or `gravitymon_XXXX`
   - If device is on your network: Open browser and go to `http://gravitymon.local` or device IP address

2. **Navigate to Push Targets**
   - Click **Configuration** in the menu
   - Select **Push Targets**
   - Choose **HTTP Post**

3. **Configure HTTP Post settings**
   | Setting | Value |
   |---------|-------|
   | URL | `http://YOUR_SERVER_IP:8080/api/v1/webhook` |
   | Header 1 | `Content-Type: application/json` |
   | Header 2 | `Authorization: Bearer YOUR_API_TOKEN` |
   | Format | iSpindel |

   > **Authentication is required.** The server rejects requests without the
   > `Authorization` header (HTTP 401). Use the `API_TOKEN` value configured in
   > the server's `.env`. Both the URL and the header must be set.

4. **Save and Reboot**
   - Click **Save**
   - Reboot the device

### Method 2: Direct Configuration File Edit

If you have access to the device configuration file, update these fields:

```json
{
  "http_post_target": "http://YOUR_SERVER_IP:8080/api/v1/webhook",
  "http_post_header1": "Content-Type: application/json",
  "http_post_header2": "Authorization: Bearer YOUR_API_TOKEN"
}
```

### Verification

After configuration, the device will send data every **15 minutes** (based on `sleep_interval: 900`).

To verify data is being received:
1. Open Telegram
2. Find bot `@YOUR_BOT_USERNAME`
3. Send `/status` command
4. You should see your device data

### Troubleshooting

| Problem | Solution |
|---------|----------|
| No data in bot | Check WiFi connection on ESP device |
| Connection error | Verify URL is correct (no typos) |
| 401 / Unauthorized | Header 2 missing or wrong token — set `Authorization: Bearer YOUR_API_TOKEN` exactly |
| Device not found | Wait for next sleep cycle (up to 15 min) |
| Wrong data format | Ensure Format is set to "iSpindel" |

---

## Русский

### Способ 1: Через веб-интерфейс

1. **Подключитесь к устройству GravityMon**
   - Если устройство в режиме точки доступа: Подключитесь к WiFi сети `GravityMon` или `gravitymon_XXXX`
   - Если устройство в вашей сети: Откройте браузер и перейдите на `http://gravitymon.local` или IP-адрес устройства

2. **Перейдите к настройкам отправки данных**
   - Нажмите **Configuration** в меню
   - Выберите **Push Targets**
   - Выберите **HTTP Post**

3. **Настройте параметры HTTP Post**
   | Параметр | Значение |
   |----------|----------|
   | URL | `http://YOUR_SERVER_IP:8080/api/v1/webhook` |
   | Header 1 | `Content-Type: application/json` |
   | Header 2 | `Authorization: Bearer YOUR_API_TOKEN` |
   | Format | iSpindel |

   > **Требуется аутентификация.** Сервер отклоняет запросы без заголовка
   > `Authorization` (HTTP 401). Используйте значение `API_TOKEN` из `.env`
   > сервера. Нужно задать и URL, и заголовок.

4. **Сохраните и перезагрузите**
   - Нажмите **Save**
   - Перезагрузите устройство

### Способ 2: Прямое редактирование конфигурации

Если у вас есть доступ к файлу конфигурации устройства, измените эти поля:

```json
{
  "http_post_target": "http://YOUR_SERVER_IP:8080/api/v1/webhook",
  "http_post_header1": "Content-Type: application/json",
  "http_post_header2": "Authorization: Bearer YOUR_API_TOKEN"
}
```

### Проверка

После настройки устройство будет отправлять данные каждые **15 минут** (согласно `sleep_interval: 900`).

Для проверки получения данных:
1. Откройте Telegram
2. Найдите бота `@YOUR_BOT_USERNAME`
3. Отправьте команду `/status`
4. Вы должны увидеть данные вашего устройства

### Решение проблем

| Проблема | Решение |
|----------|---------|
| Нет данных в боте | Проверьте WiFi подключение на ESP устройстве |
| Ошибка соединения | Проверьте правильность URL (без опечаток) |
| 401 / Unauthorized | Header 2 отсутствует или неверный токен — задайте `Authorization: Bearer YOUR_API_TOKEN` точно |
| Устройство не найдено | Подождите следующий цикл сна (до 15 мин) |
| Неверный формат данных | Убедитесь, что Format установлен в "iSpindel" |

---

## Server Information / Информация о сервере

| | |
|---|---|
| **API Endpoint** | `http://YOUR_SERVER_IP:8080/api/v1/webhook` |
| **Telegram Bot** | `@YOUR_BOT_USERNAME` |
| **Health Check** | `http://YOUR_SERVER_IP:8080/health` |

---

## Bot Commands / Команды бота

| Command | Description | Описание |
|---------|-------------|----------|
| `/start` | Welcome + current status | Приветствие + текущий статус |
| `/status` | Show current readings | Показать текущие показания |
| `/graph` | Temperature & gravity graphs | Графики температуры и плотности |
| `/help` | Help information | Справочная информация |
