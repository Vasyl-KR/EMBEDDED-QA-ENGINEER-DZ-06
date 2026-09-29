# DZ-14 — Тестування Wi-Fi та BLE

Домашнє завдання курсу Embedded QA Engineer: автоматизоване тестування
прошивки **station_WiFi** (Частина A) та переважно ручне тестування
прошивки **SENTRY-BLE** (Частина B) на одній платі ESP32-S3 DevKit.
Спільний PRD обох прошивок — `fw_4/PRD.md` у репозиторії курсу.

## Структура проєкту

```
├── drivers/
│   └── device.py              # DeviceDriver: протокольна логіка + wifi_* методи
├── tests/
│   ├── wifi/
│   │   ├── test_wifi_positive.py
│   │   └── test_wifi_negative.py
│   └── ble/
│       └── test_ble_smoke.py  # bleak: write LED через BLE + підтвердження у UART-лозі
├── conftest.py                # фікстури: port → device → clean_wifi, wifi_credentials
├── pytest.ini
├── requirements.txt
├── .env.example                # шаблон для WIFI_SSID/WIFI_PASSWORD
└── .env                        # реальні креди тестової мережі (у .gitignore, не здається)
```

## Встановлення

```bash
pip install -r requirements.txt
```

## Налаштування тестової мережі

SSID і пароль не хардкодяться в тестах — беруться з `.env` (читається
вручну в `conftest.py`, без зайвих залежностей):

```bash
cp .env.example .env
# і відредагувати WIFI_SSID / WIFI_PASSWORD під свою мережу (2.4 GHz)
```

## Запуск

Переконайтеся, що плата прошита `station_WiFi` (для Частини A) і жодна
інша програма не тримає відкритим COM-порт.

```bash
pytest -v tests/wifi/                # уся Частина A
pytest -v -m wifi                    # те саме через маркер
pytest -v -m wifi --html=reports/wifi.html --self-contained-html # з HTML репортингом
```

## Фікстури (conftest.py)

- `port` (session) — автопошук COM-порту за VID.
- `device` (session) — одне serial-з'єднання на весь прогін.
- `clean_wifi` (function) — перед кожним тестом викликає `wifi_disconnect()`: прошивка відмовляється виконувати `connect`, поки вже підключена (`sta is connected, disconnect before connecting to new ap` → `connection timeout`), тож кожен тест повинен стартувати з гарантовано відключеного стану.
- `clean_wifi_after` (function, будується на `clean_wifi`) — те саме плюс **teardown**: після тесту (незалежно від pass/fail) ще раз форсує й підтверджує `wifi_disconnect()`. Потрібна для тестів, що навмисно намагаються підключитись і очікують невдачі (`test_wrong_password`, `test_nonexistent_ssid`).
- `wifi_credentials` (session) — SSID/пароль з `.env`; `pytest.skip`, якщо не заповнено.

## DeviceDriver: нові Wi-Fi методи

- `wifi_scan()` — список SSID.
- `wifi_connect(ssid, password)` — проходить інтерактивний діалог `connect` (очікування по патернах, без `time.sleep`): промпт SSID → промпт пароля (якщо він з'являється — прошивка іноді пропускає цей крок і одразу конектиться) → результат. Порожній `ssid`/`password` = перевикористання збережених кредів. Повертає True/False. При `False` пише в лог (`drivers.device`, рівень WARNING) конкретну причину — немає промпта SSID, таймаут після відправки SSID, чи фінальний результат (`password too short` / `connection timeout` / `connect to the AP fail`).
- `wifi_status()` — dict: `connected`, `ssid`, `ip`, `rssi`.
- `wifi_disconnect()` — шле `disconnect` і **чекає підтвердження** по рядку `wifi station: disconnected` (а не просто відправляє команду й довіряє). Підтвердження не можна перевірити через `wifi_status()` — саме там і є баг (див. нижче).

## Тести Частини A

- **test_wifi_positive.py**: `test_scan_finds_networks`, `test_connect_success`, `test_credentials_survive_reboot` (`connect` з реальними кредами → `reboot` → `connect` з порожнім вводом → підключення по збережених кредах, PRD FR-W4).
- **test_wifi_negative.py**: `test_wrong_password`, `test_short_password` (`password too short (min 8 chars)`, PRD FR-W3), `test_nonexistent_ssid`.
- **`test_disconnect`** позначений `@pytest.mark.xfail`: **реальний баг прошивки** — після `disconnect` команда `status` все одно рапортує `WiFi: connected` (з порожнім SSID та IP `0.0.0.0`) замість `disconnected`, що суперечить PRD FR-W5/FR-W6.

Результат прогону: **6 passed, 1 xfailed**.

## Частина B (BLE)

Переконайтеся, що плата прошита `Bluedroid_GATT_Server` (SENTRY-BLE),
Bluetooth на комп'ютері увімкнений, і жодна інша програма не тримає
відкритим COM-порт.

```bash
pytest -v tests/ble/            # автотест B2
pytest -v -m ble                # те саме через маркер
pytest -v -m ble --html=reports/ble.html --self-contained-html # з HTML репортингом
```

**Тест Частини B** — `tests/ble/test_ble_smoke.py::test_ble_led_dual_channel`:
`bleak` шукає `SENTRY-BLE` → підключається → пише `01` у LED-характеристику
→ перевіряє `LED ON!` у UART-лозі (`device.wait_for(...)`, той самий
`DeviceDriver`, що й для Wi-Fi) → пише `00` → перевіряє `LED OFF!` →
відключається. Асинхронний код bleak обгорнутий у `asyncio.run(...)`
всередині звичайної sync-функції.

Результат прогону: **1 passed**.
