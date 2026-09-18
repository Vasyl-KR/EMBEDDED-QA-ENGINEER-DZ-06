# hw6/hw7 — SENTRY-C1 pytest Test Framework

Домашнє завдання курсу Embedded QA Engineer: pytest-фреймворк для
автоматизованого тестування прошивки **SENTRY-C1** (ESP32-S3) через
UART CLI. Пристрій керується повністю через послідовний порт
(115200 8N1), опис усіх команд і поведінки — у PRD прошивки
(`fw_3/SENTRY-C1_PRD.md` в репозиторії курсу).

## Структура проєкту

```
├── drivers/
│   └── device.py        # DeviceDriver: уся протокольна логіка (framing, ANSI, таймаути)
├── tests/
│   ├── smoke/
│   │   └── test_smoke.py
│   └── functional/
│       ├── test_alarm.py
│       ├── test_config.py
│       └── test_distance_stability.py
├── conftest.py           # фікстури: port → device → logged_device
└── pytest.ini
```

## Встановлення

```bash
pip install pyserial pytest
```

## Запуск

Переконайся, що плата підключена і жодна інша програма
(`monitor.bat`/`flash.bat` тощо) не тримає відкритим COM-порт.

```bash
pytest -v                    # усі тести в алфавітному порядку
pytest -v -m smoke           # лише смоки
pytest -v -m functional      # лише функціональні
```

## Фікстури (conftest.py)

- `port` (session) — автопошук COM-порту за VID.
- `device` (session) — одне serial-з'єднання на весь прогін (дороге, тому не відкривається щотесту).
- `logged_device` (function) — чистий стан авторизації перед кожним тестом: `logout` → `register`/`login`. Дешево, тому per-test.

## Логування

Кожен тестовий файл має власний `logging.getLogger(__name__)` і логує
ключові кроки (`log.info(...)`) — що надсилається, скільки рядків
прийшло, який стан отримано. У `pytest.ini` увімкнено `log_cli = true`,
тому ці логи видно **наживо в консолі для кожного тесту**.

## Тести

- **smoke** (`tests/smoke/test_smoke.py`) — базова живучість: відповідь на `help`, відповідь на `status`, виживання після `reboot` (через `wait_for_pattern("Device ready")`, без `time.sleep`).
- **test_alarm.py** — параметризована перевірка межі спрацювання (`value >= threshold` за PRD 8.2): нижче/на межі/вище порогу.
- **test_config.py** — persistence конфігурації через реальний `reboot`. Позначений `@pytest.mark.xfail`: **реальний баг прошивки** — `config save` рапортує успіх, але після фізичного reboot `config load` все одно виводить "No saved config found in NVS" і завантажує дефолти, хоча PRD стверджує, що збережена конфігурація має пережити reboot.
- **test_distance_stability.py** — стабільність послідовних показань HC-SR04 для статичного об'єкта (розкид у межах толерантності).

