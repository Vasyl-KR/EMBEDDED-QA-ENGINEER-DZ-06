# REPORT — DZ-14: Тестування Wi-Fi та BLE

## Частина A — Wi-Fi (station_WiFi)

### Налаштування тестової мережі

Тестова мережа — точка доступу з телефону (2.4 GHz), SSID і пароль
задаються у `.env` (не входить до архіву здачі, у `.gitignore`):

```
WIFI_SSID=<ваш SSID>
WIFI_PASSWORD=<ваш пароль>
```

Заповнити: скопіювати `.env.example` → `.env`, вписати свої значення
(деталі — у `README.md`).

### Прогін `pytest -v`

Повний HTML-звіт (`pytest-html`): [reports/wifi.html](reports/wifi.html).
Згенеровано 29-Sep-2026 13:51:13, **7 tests took 00:01:43**.

| Тест | Результат | Тривалість |
|------|-----------|------------|
| `test_wifi_negative.py::test_wrong_password` | PASSED | 00:00:19 |
| `test_wifi_negative.py::test_short_password` | PASSED | 00:00:09 |
| `test_wifi_negative.py::test_nonexistent_ssid` | PASSED | 00:00:21 |
| `test_wifi_positive.py::test_scan_finds_networks` | PASSED | 00:00:11 |
| `test_wifi_positive.py::test_connect_success` | PASSED | 00:00:11 |
| `test_wifi_positive.py::test_disconnect` | **XFAIL** | 00:00:11 |
| `test_wifi_positive.py::test_credentials_survive_reboot` | PASSED | 00:00:20 |

**Підсумок: 6 passed, 1 xfailed.**

### Знайдені баги

**ID: BUG-STATUS-01**
- **Severity: Medium**
- **Title: Поле `status` не оновлюється після дисконекту від мережі**
- **Тест:** `test_wifi_positive.py::test_disconnect` (позначений `@pytest.mark.xfail(strict=True)`).
- **Environment:**
  - HW: ESP32-S3 rev 2. 
  - FW: station_WiFi_merged.bin (commit 637a65161a0fef8a049fcd641016b1b7ed00f599)
  -	Інтерфейс: UART-консоль, 115200 8N1

- **Steps to reproduce:**
  1. Ввести команду `connect <ssid> <password>` - пітвердити успішне підключення.
  2. Зробити `disconnect`.
  3. Перевірити `status`.
- **Expected result:** Згідно PRD (FR-W5/FR-W6) `status` має показувати `WiFi: disconnected`, оскільки з'єднання розірвано і автоматичний reconnect не виконується.
- **Actual result:** `status` продовжує рапортувати `WiFi: connected`, але з порожнім SSID та IP `0.0.0.0` (RSSI `0`) — тобто прапорець "підключено" не скидається, хоча решта полів вже показують відсутність реального з'єднання.
- **Logs:** лог із реального прогону -
  ```
  Status after disconnect: {'connected': True, 'ssid': None, 'ip': '0.0.0.0', 'rssi': 0}
  ```
- **Additional notes:** сам факт розриву з'єднання підтверджується окремо, надійним каналом — рядком `wifi station: disconnected` у UART-логу.

---

## Частина B — BLE (SENTRY-BLE)

### B1. Ручний чек-лист (nRF Connect for Mobile)

Пристрій: `SENTRY-BLE`, MAC `28:84:85:89:1B:FA`. Паралельно з nRF Connect
тримався відкритим UART-термінал (115200 8N1) як другий канал
спостереження.

| # | Перевірка | PRD | Результат | Доказ (скріни/логи) |
|---|-----------|-----|-----------|-------|
| 1 | **Scan** — пристрій знайдено, зафіксовано RSSI | FR-A1 | ✅ PASS | RSSI `-38 dBm`, "LE General Discoverable", Complete Local Name `SENTRY-BLE` |
| 2 | **Connect + discovery** — сервіси `0x180D` і `0x1815`, дві характеристики (LED/RELAY) з правильними UUID | FR-A3, FR-G3 | ✅ PASS | [screens/nRF.jpg](screens/nRF.jpg); UART: `Connected, conn_id 0, remote 7b:ff:7d:52:91:b1` |
| 3 | **Heart Rate** — підписка на indications `0x2A37`, значення в межах 60-80 bpm | FR-G1, FR-G2 | ✅ PASS | CCCD `0x2902` = `Indications enabled`, значення `62 bpm`, звірено з UART-логом |
| 4 | **HR spike** — команда `hr spike`, наступні значення ~190-199 bpm на 5с | FR-C3 | ✅ PASS | nRF: `194 bpm`; UART: 5 тіків `194, 199, 197, 192, 199`, далі повернення до норми (`73 bpm`) |
| 5 | **LED через BLE** — write `01`/`00`, фізична реакція + лог | FR-G4 | ✅ PASS | UART: `LED ON!` / `LED OFF!`, LED на платі вмикався та вимикався |
| 6 | **RELAY через BLE** — write `01`/`00`, фізичне клацання + лог | FR-G4 | ✅ PASS | UART: `RELAY ON!` / `RELAY OFF!`, реле клацало на 01 |
| 7 | **Read після write** — читання повертає актуальний стан | FR-G5 | ✅ PASS | Read після write `01`/`00` повертав відповідне значення; додатково перевірено, що зміна стану фізичною кнопкою також коректно відображається через read |
| 8 | **Конфлікт каналів керування** — BLE `write 01` у LED → вимкнення через UART `led off` → BLE `read` | FR-G5 | ✅ PASS | [screens/real_photo.jpg](screens/real_photo.jpg) — фізичний стенд, видно LED на платі та реле; read після зовнішньої зміни каналом UART повернув коректне (оновлене) значення — усі три канали (BLE/UART/кнопка) керують одним фізичним станом |
| 9 | **Reconnect** — розрив з'єднання, повторне підключення | FR-A2 | ✅ PASS | UART: `Disconnected, remote 7b:ff:7d:52:91:b1, reason 0x16`; пристрій знову знайдено в скані, підключення повторно пройшло без проблем |

**Підсумок B1: 9/9 пунктів відповідають PRD, відхилень від очікуваної поведінки не знайдено (що дуже дивно і мені здається я щось пропустив)** 

### B2. Автотест на `bleak`

Повний HTML-звіт (`pytest-html`): [reports/ble.html](reports/ble.html).
Згенеровано 29-Sep-2026 15:36:51, **1 test took 00:00:02**.

| Тест | Результат | Тривалість |
|------|-----------|------------|
| `test_ble_smoke.py::test_ble_led_dual_channel` | PASSED | 00:00:02 |


**Підсумок: 1 passed**
