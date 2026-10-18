"""Standalone script (not a test): bring the board to firmware 2.3.0 over OTA.

    python tools/update_to_2_3_0.py

Reads WIFI_SSID / WIFI_PASSWORD / SWM_LOGIN / SWM_PASSWORD from framework/.env (or the environment), connects to
the board over UART, restores Wi-Fi and the login if needed, installs 2.3.0 with `ota install` (with `force` when the
board runs a newer version) and checks the result. Nothing is done when 2.3.0 is already running.

Exit code: 0 - the board runs 2.3.0 (valid) when the script ends; 1 - the update failed; 2 - setup problem
(no board, no credentials).
"""

import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from drivers.device import DeviceDriver, find_port  # noqa: E402

TARGET = (2, 3, 0)
log = logging.getLogger("update_to_2_3_0")


def load_dotenv():
    """KEY=VALUE per line from framework/.env; real environment variables win. Values are never printed."""
    path = HERE.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def version_text(version):
    return ".".join(map(str, version))


def restore_session(dev, ssid, wifi_password, login, password):
    """Wi-Fi and login back (an update reboots the board; the saved network / profile may also be gone)."""
    return dev.ensure_online(ssid, wifi_password) and dev.ensure_logged_in(login, password)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    load_dotenv()
    ssid, wifi_password = os.environ.get("WIFI_SSID"), os.environ.get("WIFI_PASSWORD")
    login, password = os.environ.get("SWM_LOGIN"), os.environ.get("SWM_PASSWORD")
    if not (ssid and wifi_password and login and password):
        log.error("WIFI_SSID / WIFI_PASSWORD / SWM_LOGIN / SWM_PASSWORD are not set (see .env.example)")
        return 2
    port = find_port()
    if not port:
        log.error("No ESP32 device found (VID autodetect found nothing). Is the COM port free?")
        return 2

    dev = DeviceDriver(port)
    dev.open()
    try:
        dev.sync()
        current = dev.version()
        if current["fw"] is None:
            log.error("Cannot read the firmware version from the board")
            return 2
        log.info("Board runs v%s (%s, %s)", version_text(current["fw"]), current["partition"], current["state"])
        if current["fw"] == TARGET and current["state"] == "valid":
            log.info("Already on v%s - nothing to do", version_text(TARGET))
            return 0
        if not restore_session(dev, ssid, wifi_password, login, password):
            log.error("Could not restore Wi-Fi / login - the OTA server is not reachable without them")
            return 1

        command = f"ota install {version_text(TARGET)}" + (" force" if current["fw"] > TARGET else "")
        log.info("Updating: `%s`", command)
        run = dev.ota_flash(command)
        if not (run.succeeded and run.booted):
            log.error("Update failed: %s", run.process)
            dev.wait_responsive(120)
            return 1

        if not dev.wait_responsive(120) or not restore_session(dev, ssid, wifi_password, login, password):
            log.error("The board did not come back after the update")
            return 1
        after = dev.version()
        log.info("Board runs v%s (%s @ %s, %s)", version_text(after["fw"]) if after["fw"] else "?",
                 after["partition"], after["address"], after["state"])
        if after["fw"] != TARGET or after["state"] != "valid":
            log.error("The board is not on v%s (valid) after the update", version_text(TARGET))
            return 1
        log.info("Done: v%s is running", version_text(TARGET))
        return 0
    finally:
        dev.close()


if __name__ == "__main__":
    sys.exit(main())
