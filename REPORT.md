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

TBD
