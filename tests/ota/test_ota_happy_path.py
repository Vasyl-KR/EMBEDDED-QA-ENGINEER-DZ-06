"""OTA - HAPPY PATH cases (TEST_CASES.md, section 1.1). Only the positive cases are automated; the negative
cases and network failures (section 1.2) stay manual.

One test per case: the function name is `test_tc_ota_<NN>_<slug>`, the first docstring line holds the case ID and
an English title. Parametrized cases use the row letters of the parameter table as pytest ids.

SAFETY: an OTA test that leaves the board on a random firmware would poison the whole run. Every test here uses
`ota_base` (directly or through `ota_beta`): the board is on the base firmware (2.1.0) before the test and is
brought back to it AFTER the test - always, whatever happened (see `return_to_base` in conftest.py). Because of the
known "settings are reset by an update" problem the fixtures also restore Wi-Fi and the profile.
When the run STARTED on another firmware (for example 2.3.0 for the Guard tests), that firmware is installed again
after the last OTA test of this module (`_restore_start_firmware`), so the modules that follow see the same firmware
as at the start.

TC-OTA-08 (data persistence) and the rollback / `ota url` cases (TC-OTA-11, 12) are not automated here.
"""

import logging
import re

import pytest

from conftest import BASE_FW, BETA_FW, _fw_str

log = logging.getLogger(__name__)

pytestmark = [pytest.mark.ota, pytest.mark.positive]

ADDRESS = {"ota_0": "0x20000", "ota_1": "0x1a0000"}
PROGRESS_STEPS = list(range(10, 101, 10))


# ---- helpers ----------------------------------------------------------------------------

def parse_status(resp):
    """`ota status` -> dict(fw, partition, state, previous_fw, previous_partition); previous_* are None for `none`."""
    running = resp.find(r"running:\s+v(\d+\.\d+\.\d+) in (ota_\d) \((\w[\w ]*)\)")
    previous = resp.find(r"previous:\s+v(\d+\.\d+\.\d+) in (ota_\d)")
    return {
        "fw": tuple(int(x) for x in running.group(1).split(".")) if running else None,
        "partition": running.group(2) if running else None,
        "state": running.group(3) if running else None,
        "has_previous_line": resp.has(r"previous:"),
        "previous_fw": tuple(int(x) for x in previous.group(1).split(".")) if previous else None,
        "previous_partition": previous.group(2) if previous else None,
    }


def assert_update_succeeded(dev, run, restore_session, from_fw, to_fw):
    """The common expectations of a successful flashing OTA (process, self-check after the reboot, result)."""
    process, boot = run.process, run.boot
    src_fw, dst_fw = _fw_str(from_fw), _fw_str(to_fw)
    transition = process.find(rf"current v{re.escape(src_fw)} \((ota_\d)\) -> target partition (ota_\d)")
    progress = run.progress()
    log.info("Expected: `current v%s (ota_N) -> target partition ota_M`, `downloading`, `image: sentry_fw7 v%s`, "
             "progress %s, `success: v%s -> v%s`, self-check passed after the reboot. Actual: progress %s, "
             "transition %s", src_fw, dst_fw, PROGRESS_STEPS, src_fw, dst_fw, progress,
             transition.groups() if transition else None)
    assert transition, process
    source, target = transition.groups()
    assert source != target, f"the new image must go to the inactive partition, got {source} -> {target}"
    assert process.has(r"downloading "), process
    assert process.has(rf"image: sentry_fw7 v{re.escape(dst_fw)}"), process
    assert progress == PROGRESS_STEPS, f"progress lines: {progress}"
    assert process.has(rf"success: v{re.escape(src_fw)} -> v{re.escape(dst_fw)} in \d+ s"), process
    assert process.has(r"Rebooting"), process
    assert not any(code.startswith("E") for code in process.codes), process.codes

    assert run.booted, "the board did not finish booting after the update"
    assert boot.has(r"PENDING_VERIFY"), "no PENDING_VERIFY message after the reboot"
    assert boot.has(r"self-check passed"), "no `self-check passed` after the reboot"
    assert boot.has(r"marked VALID"), "the new firmware was not marked VALID"

    restore_session()
    info = dev.version()
    log.info("Result: version %s, partition %s @ %s, state %s (expected v%s in %s)",
             info["fw"], info["partition"], info["address"], info["state"], dst_fw, target)
    assert info["fw"] == to_fw, info["response"]
    assert info["state"] == "valid", info["response"]
    assert info["partition"] == target and info["address"].lower() == ADDRESS[target], info["response"]
    return source, target


# ---- TC-OTA-01 .. 05: read-only cases on the base firmware ------------------------------------

def test_tc_ota_01_firmware_version(ota_base, restore_session):
    """TC-OTA-01 - Firmware version"""
    log.info("Step 1: `version`")
    info = ota_base.version()
    log.info("Step 2: `reboot` and read the boot banner (`App version`)")
    boot, found = ota_base.reboot_and_capture()
    assert found, "the board did not finish booting"
    restore_session()
    log.info("Step 3: `ota status`")
    status = parse_status(ota_base.ota_status())
    base = _fw_str(BASE_FW)
    log.info("Expected: the same v%s in `version`, the boot banner and `ota status`; partition line with `state: valid`. "
             "Actual: version=%s, status=%s", base, info["fw"], status["fw"])
    assert info["response"].has(rf"SENTRY SWM-2 sonar watch module, fw v{re.escape(base)} \(build [^)]+\)"), info["response"]
    assert info["fw"] == BASE_FW
    assert info["state"] == "valid"
    assert info["partition"] in ADDRESS and info["address"].lower() == ADDRESS[info["partition"]], info["response"]
    assert boot.has_raw(rf"App version:\s+{re.escape(base)}"), "boot banner does not show the same version"
    assert status["fw"] == BASE_FW
    assert status["partition"] == info["partition"]


@pytest.mark.parametrize("stage", [
    pytest.param("base", id="a-fresh-base"),
    pytest.param("beta", id="b-after-update"),
])
def test_tc_ota_02_ota_status(stage, request):
    """TC-OTA-02 - `ota status`"""
    # NB: the case says `previous: none` on a freshly flashed board; after the first OTA cycle of a run that is no
    # longer true, so stage (a) only checks that the line exists. Stage (b) is the state after an update.
    dev = request.getfixturevalue("ota_base" if stage == "base" else "ota_beta")
    log.info("Step: `ota status` on the %s firmware", "base" if stage == "base" else "beta (after the update)")
    status = parse_status(dev.ota_status())
    version = dev.version()
    log.info("Actual: %s", status)
    assert status["fw"] == (BASE_FW if stage == "base" else BETA_FW)
    assert status["state"] == "valid"
    assert status["partition"] == version["partition"]
    assert status["has_previous_line"], "the `previous:` line is missing"
    if stage == "beta":
        assert status["previous_fw"] == BASE_FW, "after the update the previous firmware must be the base one"
        assert status["previous_partition"] != status["partition"], "the previous firmware must sit in the other partition"


@pytest.mark.parametrize("stage, current, stable, beta, verdict", [
    pytest.param("base", "2.1.0", "2.1.0", "2.3.0", r"up to date \(stable\)", id="a-on-2.1.0"),
    pytest.param("beta", "2.3.0", "2.1.0", "2.3.0", r"running newer than stable", id="b-on-2.3.0"),
])
def test_tc_ota_03_ota_check(stage, current, stable, beta, verdict, request):
    """TC-OTA-03 - `ota check`"""
    dev = request.getfixturevalue("ota_base" if stage == "base" else "ota_beta")
    log.info("Step: `ota check` on %s", current)
    resp = dev.ota_check()
    log.info("Expected: current v%s, stable v%s, beta v%s and the verdict /%s/. Actual codes: %s",
             current, stable, beta, verdict, resp.codes)
    assert not resp.codes, resp
    assert resp.has(rf"current:\s+v{re.escape(current)}"), resp
    assert resp.has(rf"stable:\s+v{re.escape(stable)}"), resp
    assert resp.has(rf"beta:\s+v{re.escape(beta)}"), resp
    assert resp.has(verdict), resp


@pytest.mark.xfail(strict=True, reason="BUG-OTA-01: on 2.1.0 `ota update` with stable == running version "
                   "re-downloads and reinstalls the image (`W409 same version v2.1.0 - reinstalling`, reboot) instead of "
                   "`already up to date` (PRD OTA-4); on 2.3.0 the same check works (TC-OTA-07)")
def test_tc_ota_04_update_on_current_stable(ota_base):
    """TC-OTA-04 - `ota update` on the current stable"""
    log.info("Step 1: `uptime`; step 2: `ota update` (stable is the running version); step 3: `uptime`")
    before = ota_base.uptime_seconds()
    resp = ota_base.ota_update()
    log.info("Expected: `[OTA] already up to date`, no `downloading`, no reboot. Actual: already=%s, downloading=%s",
             resp.has(r"already up to date"), resp.has(r"downloading"))
    assert resp.has(r"already up to date"), resp
    assert not resp.has(r"downloading"), f"the same version is being downloaded again: {resp}"
    after = ota_base.uptime_seconds()
    assert before is not None and after is not None and after >= before, f"the board rebooted (uptime {before} -> {after})"


def test_tc_ota_05_server_default(ota_base):
    """TC-OTA-05 - `ota server` and returning to the default server"""
    log.info("Step 1: `ota server`")
    shown = ota_base.ota_server()
    log.info("Step 2: `ota server default`; step 3: `ota check`")
    reset = ota_base.ota_server("default")
    check = ota_base.ota_check()
    log.info("Expected: the GitHub URL marked `(default)`, no errors, `ota check` works")
    assert shown.has(r"server:\s+https://raw\.githubusercontent\.com/\S+/fw7/\s+\(default\)"), shown
    assert not reset.codes, reset
    assert check.has(r"current:\s+v") and not check.codes, check


# ---- TC-OTA-06 .. 10: flashing cases ---------------------------------------------------------------

def test_tc_ota_06_update_beta_process_self_check_partition(ota_base, restore_session):
    """TC-OTA-06 - Update 2.1.0 -> 2.3.0 (`ota update beta`): process, self-check, partition"""
    log.info("Step 1: `version`, `ota status`")
    before = ota_base.version()
    log.info("Step 2: `ota update beta` (the flashing flow is captured up to the boot-ready line)")
    run = ota_base.ota_flash("ota update beta")
    log.info("Step 3: after the reboot - boot log, `reconnect`, `login`, `version`, `ota status`")
    source, target = assert_update_succeeded(ota_base, run, restore_session, BASE_FW, BETA_FW)
    status = parse_status(ota_base.ota_status())
    log.info("Expected: the partition changed (%s -> %s), `previous` is v%s in %s. Actual status: %s",
             before["partition"], target, _fw_str(BASE_FW), source, status)
    assert source == before["partition"]
    assert status["fw"] == BETA_FW
    assert status["previous_fw"] == BASE_FW and status["previous_partition"] == source


def test_tc_ota_07_update_beta_on_beta(ota_beta):
    """TC-OTA-07 - `ota update beta` on 2.3.0"""
    log.info("Step 1: `uptime`; step 2: `ota update beta` on 2.3.0; step 3: `uptime`")
    before = ota_beta.uptime_seconds()
    resp = ota_beta.ota_update("beta")
    log.info("Expected: `[OTA] already up to date`, nothing is downloaded, no reboot. Actual: already=%s, downloading=%s",
             resp.has(r"already up to date"), resp.has(r"downloading"))
    assert resp.has(r"already up to date"), resp
    assert not resp.has(r"downloading"), f"the same version is being downloaded again: {resp}"
    after = ota_beta.uptime_seconds()
    assert before is not None and after is not None and after >= before, f"the board rebooted (uptime {before} -> {after})"


def test_tc_ota_09_install_specific_version(ota_base, restore_session):
    """TC-OTA-09 - `ota install` of a specific version (upgrade)"""
    log.info("Step 1: `ota install 2.3.0` (no `force`); step 2: after the reboot `version`")
    run = ota_base.ota_flash("ota install 2.3.0")
    assert_update_succeeded(ota_base, run, restore_session, BASE_FW, BETA_FW)


def test_tc_ota_10_downgrade_with_force(ota_beta, restore_session):
    """TC-OTA-10 - Downgrade with `force`"""
    log.info("Step 1: `ota install 2.1.0 force` on 2.3.0; step 2: after the reboot `reconnect`, `login`, `version`; "
             "step 3: `guard status`, `alert list`")
    run = ota_beta.ota_flash("ota install 2.1.0 force")
    assert_update_succeeded(ota_beta, run, restore_session, BETA_FW, BASE_FW)
    guard, alerts = ota_beta.guard_status(), ota_beta.alert_list()
    log.info("Expected: Guard and alerts are not available on 2.1.0 (E099). Actual codes: guard %s, alerts %s",
             guard.codes, alerts.codes)
    assert guard.has_code("E099"), guard
    assert alerts.has_code("E099"), alerts
