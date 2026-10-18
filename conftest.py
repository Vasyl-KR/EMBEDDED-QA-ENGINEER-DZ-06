import logging
import os
from pathlib import Path

import pytest

from drivers.device import DeviceDriver, find_port, parse_version

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent


def _load_dotenv():
    """Tiny .env loader (no extra dependency): KEY=VALUE per line, '#' comments.
    Looks in framework/ first, then in the repo root. Real environment
    variables take precedence. Secrets are never printed or logged."""
    for path in (HERE / ".env", HERE.parent / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


# ---- connection -------------------------------------------------------------

@pytest.fixture(scope="session")
def port():
    p = find_port()
    if not p:
        pytest.skip("No ESP32 device found (VID autodetect found nothing)")
    return p


@pytest.fixture(scope="session")
def device(port):
    # One serial connection for the whole run: opening the port can reset the
    # ESP32 (DTR/RTS), so it is done once and never per test.
    dev = DeviceDriver(port)
    dev.open()
    dev.sync()  # swallow whatever the board prints right after the port opens
    yield dev
    # Final teardown of the whole run: end the session if one is still open (not after every test).
    try:
        if dev.is_logged_in():
            log.info("Final teardown: ending the session (logout)")
            dev.logout()
        else:
            log.info("Final teardown: no open session, logout is not needed")
    except Exception as exc:  # the port or the board may be gone - closing the port must still happen
        log.warning("Final teardown: logout was not performed (%s)", exc)
    finally:
        dev.close()


@pytest.fixture(scope="session")
def fw(device):
    """Running firmware: dict(fw=(2,1,0), partition, state, ...)."""
    info = device.version()
    if info["fw"] is None:
        pytest.exit("Cannot read firmware version - is the board flashed with SWM-2 firmware?")
    log.info("Firmware under test: v%s, %s, state %s",
             ".".join(map(str, info["fw"])), info["partition"], info["state"])
    return info


@pytest.fixture(autouse=True)
def _version_gate(request, fw):
    """since('2.3.0') / until('2.3.0') markers skip tests by the firmware that is actually running."""
    since = request.node.get_closest_marker("since")
    until = request.node.get_closest_marker("until")
    if since and fw["fw"] < parse_version(since.args[0]):
        pytest.skip(f"needs firmware >= {since.args[0]}")
    if until and fw["fw"] >= parse_version(until.args[0]):
        pytest.skip(f"needs firmware < {until.args[0]}")


# ---- credentials (from .env, never hardcoded) ------------------------------------

@pytest.fixture(scope="session")
def wifi_credentials():
    ssid, password = os.environ.get("WIFI_SSID"), os.environ.get("WIFI_PASSWORD")
    if not ssid or not password:
        pytest.skip("WIFI_SSID / WIFI_PASSWORD not set - copy .env.example to .env and fill it in")
    return ssid, password


@pytest.fixture(scope="session")
def account():
    login, password = os.environ.get("SWM_LOGIN"), os.environ.get("SWM_PASSWORD")
    if not login or not password:
        pytest.skip("SWM_LOGIN / SWM_PASSWORD not set - see .env.example")
    return login, password


@pytest.fixture(scope="session")
def target_cm():
    """Distance D (cm) of the static target in front of the sensor; request it only in tests that use the value."""
    value = os.environ.get("SWM_TARGET_CM")
    if not value:
        pytest.skip("SWM_TARGET_CM not set - no static target for this test")
    return float(value)


@pytest.fixture(autouse=True)
def _target_gate(request):
    """Tests marked `target` need a static target: skipped when SWM_TARGET_CM is not set."""
    if request.node.get_closest_marker("target") and not os.environ.get("SWM_TARGET_CM"):
        pytest.skip("SWM_TARGET_CM not set - no static target for this test")


# ---- device state --------------------------------------------------------------------

@pytest.fixture
def online(device, wifi_credentials):
    """Wi-Fi connected. Function-scoped on purpose: a firmware update can wipe
    the saved network (known OTA bug: settings reset after OTA), a reboot drops
    the link, and some tests disconnect deliberately - so the state is checked
    before every test and repaired if needed."""
    log.info("Precondition: Wi-Fi is connected (checked, connected if needed)")
    ok = device.ensure_online(*wifi_credentials)
    assert ok, "could not connect to the test Wi-Fi network"  # no credentials in the assert expression
    return device


@pytest.fixture
def logged_in(online, account):
    """A logged-in session. Also repairs a wiped profile (see DeviceDriver.ensure_logged_in)."""
    log.info("Precondition: logged in (register + login if needed)")
    ok = online.ensure_logged_in(*account)
    assert ok, "could not log in with SWM_LOGIN / SWM_PASSWORD"
    return online


@pytest.fixture
def restore_session(device, wifi_credentials, account):
    """Callable for tests that reboot / update the board: brings Wi-Fi and the login back."""
    def _restore():
        wifi_ok = device.ensure_online(*wifi_credentials)
        assert wifi_ok, "Wi-Fi not restored"
        login_ok = device.ensure_logged_in(*account)
        assert login_ok, "login not restored"
        return device
    return _restore


@pytest.fixture
def sonar(logged_in):
    """Logged in, sonar in a known state before and after the test (calibration
    offset, alarm threshold, filter and a running `distance log` are persistent
    device state and must never leak into the next test)."""
    log.info("Precondition: clean sonar state (distance stop, alarm off, reset, filter on)")
    logged_in.sonar_reset()
    yield logged_in
    log.info("Cleanup: restoring the clean sonar state")
    logged_in.sonar_reset()


# ---- SENTRY Guard (firmware 2.3.0 only) --------------------------------------------------------

GUARD_FW = (2, 3, 0)


def _guard_known_state(dev, restore):
    """Session back (logout / EMERGENCY reboot), then the Guard defaults: see DeviceDriver.guard_reset."""
    if dev.system_state() == 4:  # EMERGENCY: a reboot is the only way out
        log.info("Guard fixture: the board is in EMERGENCY - rebooting")
        dev.reboot_and_wait()
    restore()
    dev.guard_reset()


@pytest.fixture
def guard(logged_in, restore_session, target_cm):
    """Guard tests: a logged-in 2.3.0 board in the known Guard state (disarmed, PIN 1234, zone 50, relay closed,
    NORMAL, no alerts) before and after the test. The firmware is checked live (not from the session start),
    because OTA tests may have changed it. The static target must stand between the quiet zone (50 cm) and the
    intrusion zone (150 cm), so that `guard zone 50` is quiet and `guard zone 150` always gives INTRUSION."""
    if not 50 < target_cm < 150:
        pytest.skip(f"Guard tests need 50 < D < 150 cm (SWM_TARGET_CM = {target_cm})")
    if logged_in.version()["fw"] < GUARD_FW:
        pytest.skip("SENTRY Guard exists in firmware >= 2.3.0 only (flash it first: `ota update beta`)")
    if not getattr(logged_in, "guard_clean", False):
        log.info("Precondition: Guard in the known state (disarmed, PIN 1234, zone 50, relay closed, NORMAL, no alerts)")
        _guard_known_state(logged_in, restore_session)
    yield logged_in
    log.info("Cleanup: Guard back to the known state")
    logged_in.guard_clean = False
    _guard_known_state(logged_in, restore_session)
    logged_in.guard_clean = True


@pytest.fixture
def fresh_attempts(guard, restore_session):
    """The wrong-PIN counter at zero. BUG-GRD-01: the counter is NOT reset by `guard arm` and not by a correct PIN
    (PRD GD-4), only by a reboot - so tests that count attempts start from a rebooted board. Remove this
    fixture's reboot when the bug is fixed."""
    log.info("Precondition: wrong-PIN counter at zero (BUG-GRD-01 workaround: reboot)")
    reboot_ok = guard.reboot_and_wait()
    assert reboot_ok, "the board did not come back after the reboot"
    _guard_known_state(guard, restore_session)
    return guard


# ---- OTA: the base firmware is always restored --------------------------------------------

BASE_FW = (2, 1, 0)   # stable: the base firmware 
BETA_FW = (2, 3, 0)   # beta: reached through OTA only


def _fw_str(version):
    return ".".join(map(str, version))


def _restore_session(dev, wifi_credentials, account):
    """Wi-Fi and login back after a reboot / OTA. Also repairs what an update can wipe (known OTA bug:
    settings reset after an update): the saved network and the profile are recreated when missing."""
    wifi_ok = dev.ensure_online(*wifi_credentials)
    login_ok = wifi_ok and dev.ensure_logged_in(*account)
    return wifi_ok and login_ok


def return_to_base(dev, wifi_credentials, account):
    """Bring the board to BASE_FW no matter what the previous test left behind (another firmware, an OTA in
    progress, a rebooting board, a lost Wi-Fi / profile, a custom update server). If the base cannot be
    restored, the whole run is aborted: continuing on an unknown firmware would poison every next test."""
    if not dev.wait_responsive(180):
        pytest.exit("OTA fixture: the board does not answer - cannot restore the base firmware", returncode=3)
    if not _restore_session(dev, wifi_credentials, account):
        pytest.exit("OTA fixture: cannot restore Wi-Fi / login on the board", returncode=3)
    for attempt in (1, 2):
        current = dev.version()
        if current["fw"] == BASE_FW and current["state"] == "valid":
            break
        log.warning("OTA fixture: the board runs v%s (%s) instead of v%s - installing the base (attempt %d)",
                    _fw_str(current["fw"]) if current["fw"] else "?", current["state"], _fw_str(BASE_FW), attempt)
        dev.ota_flash(f"ota install {_fw_str(BASE_FW)} force")
        if not dev.wait_responsive(120) or not _restore_session(dev, wifi_credentials, account):
            pytest.exit("OTA fixture: the board did not come back after reinstalling the base firmware", returncode=3)
    else:
        current = dev.version()
    if current["fw"] != BASE_FW or current["state"] != "valid":
        pytest.exit(f"OTA fixture: the base firmware v{_fw_str(BASE_FW)} could not be restored", returncode=3)
    dev.ota_server("default")  # a test may have switched the update server
    log.info("OTA fixture: the board is on the base firmware v%s (%s @ %s)",
             _fw_str(BASE_FW), current["partition"], current["address"])
    return current


@pytest.fixture(scope="module")
def _restore_start_firmware(device, fw, wifi_credentials, account):
    """After the last OTA test of the module: the board goes back to the firmware the run STARTED on. The OTA tests
    themselves always begin and end on BASE_FW (see `ota_base`); when the run started on another firmware (for example
    2.3.0 for the Guard tests), that one is installed again here, so the modules that follow see the same firmware as
    at the start of the run."""
    start = fw["fw"]
    yield
    if start == BASE_FW:
        return
    answers = device.wait_responsive(180) and _restore_session(device, wifi_credentials, account)
    if not answers:
        pytest.exit("OTA fixture: the board does not answer - cannot restore the start firmware", returncode=3)
    if device.version()["fw"] == start:
        return
    command = f"ota install {_fw_str(start)}" + (" force" if start < device.version()["fw"] else "")
    log.info("OTA module finished: restoring the firmware the run started on (v%s)", _fw_str(start))
    run = device.ota_flash(command)
    if not (run.succeeded and run.booted and device.wait_responsive(120)
            and _restore_session(device, wifi_credentials, account) and device.version()["fw"] == start):
        pytest.exit(f"OTA fixture: the start firmware v{_fw_str(start)} could not be restored", returncode=3)


@pytest.fixture
def ota_base(device, wifi_credentials, account, _restore_start_firmware):
    """The board on the BASE firmware with Wi-Fi and login - before the test AND after it, whatever the test did
    (pass, fail, error, interrupted download). Every OTA test must use this fixture (directly or through
    `ota_beta`): a test that leaves the board on a random firmware would poison the whole run. When the run started
    on another firmware, `_restore_start_firmware` installs it again after the last OTA test of the module."""
    log.info("Precondition: returning the board to the base firmware v%s", _fw_str(BASE_FW))
    return_to_base(device, wifi_credentials, account)
    yield device
    log.info("Cleanup: returning the board to the base firmware v%s", _fw_str(BASE_FW))
    return_to_base(device, wifi_credentials, account)


@pytest.fixture
def ota_beta(ota_base, wifi_credentials, account):
    """The board on the BETA firmware (reached through `ota update beta`). The base firmware is restored by
    the teardown of `ota_base`, which this fixture depends on."""
    log.info("Precondition: updating the board to the beta firmware v%s", _fw_str(BETA_FW))
    run = ota_base.ota_flash("ota update beta")
    assert run.succeeded and run.booted, f"could not update to the beta firmware: {run.process}"
    restored = _restore_session(ota_base, wifi_credentials, account)  # no credentials inside an assert expression
    assert restored, "could not restore Wi-Fi / login after the update"
    assert ota_base.version()["fw"] == BETA_FW, "the board is not on the beta firmware after the update"
    return ota_base
