import logging
import os

import pytest

from drivers.device import DeviceDriver, find_port

log = logging.getLogger(__name__)


def _load_dotenv(path=".env"):
    """Tiny .env loader (no extra dependency) - KEY=VALUE per line, '#'
    comments allowed. Existing environment variables take precedence."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

WIFI_SSID = os.environ.get("WIFI_SSID")
WIFI_PASSWORD = os.environ.get("WIFI_PASSWORD")


@pytest.fixture(scope="session")
def port():
    p = find_port()
    if not p:
        pytest.skip("No ESP32 device found (VID autodetect found nothing)")
    return p


@pytest.fixture(scope="session")
def device(port):
    # Opening the serial connection is the expensive part, so it is done
    # once per test run (session scope), not once per test.
    dev = DeviceDriver(port)
    dev.open()
    yield dev
    dev.close()


@pytest.fixture
def clean_wifi(device):
    # Function-scoped: guarantees a disconnected starting state before
    # each Wi-Fi test. The firmware refuses `connect` while already
    # connected ("sta is connected, disconnect before connecting to new
    # ap" -> connection timeout), so tests can't rely on whatever state
    # the previous test left the radio in.
    device.wifi_disconnect()
    yield device


@pytest.fixture
def clean_wifi_after(clean_wifi):
    """Like clean_wifi, but also forces + confirms a disconnect
    AFTER the test - for tests that attempt a connect expected to
    fail. A failed attempt can leave the radio mid-retry in the
    background even once wifi_connect() gives up waiting, and that
    leftover noise must not leak into whatever test runs next.

    This is teardown (after yield), so it runs whether the test
    passes, fails, or errors - unlike cleanup written at the end of
    the test body, which never runs if an earlier assert fails first.
    """
    yield clean_wifi
    if not clean_wifi.wifi_disconnect():
        log.warning("post-test cleanup disconnect was not confirmed")


@pytest.fixture(scope="session")
def wifi_credentials():
    if not WIFI_SSID or not WIFI_PASSWORD:
        pytest.skip(
            "WIFI_SSID/WIFI_PASSWORD not set - copy .env.example to .env "
            "and fill in your test network's credentials"
        )
    return WIFI_SSID, WIFI_PASSWORD
