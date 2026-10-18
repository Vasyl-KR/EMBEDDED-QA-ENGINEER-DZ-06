"""SENTRY Guard - NEGATIVE cases (TEST_CASES.md, section 3.2). Firmware 2.3.0 only.

Same conventions as test_guard_positive.py: `test_tc_grd_<NN>_<slug>`, English title in the first docstring line,
row letters of the parameter tables as pytest ids. Manual cases (TC-GRD-20 tamper, TC-GRD-21 K4, TC-GRD-22 LED)
are not automated.

BUG-GRD-01: the wrong-PIN counter is NOT reset by `guard arm` and not by a correct PIN (PRD GD-4), only by a
reboot, and it keeps counting past 3 (`Attempts: 4/3` ...). Tests that count attempts use the `fresh_attempts`
fixture (a rebooted board); the cases that check the reset are xfail(strict) with this bug.
"""

import logging

import pytest

from drivers.device import GUARD_DEFAULT_PIN as PIN, GUARD_TEST_PIN as NEW_PIN

log = logging.getLogger(__name__)

pytestmark = [pytest.mark.guard, pytest.mark.negative, pytest.mark.target, pytest.mark.since("2.3.0")]

WRONG_PIN = "0000"
ZONE_QUIET = 50

BUG_GRD_01 = ("BUG-GRD-01: PRD GD-4 says the wrong-PIN counter starts from zero at every `guard arm` and after a "
              "correct PIN; the firmware keeps counting (only a reboot resets it)")


# ---- GD-4 ------------------------------------------------------------------------------

@pytest.mark.parametrize("attempt", [
    pytest.param(1, id="a-attempt-1"),
    pytest.param(2, id="b-attempt-2"),
    pytest.param(3, id="c-attempt-3-alarm"),
])
def test_tc_grd_14_wrong_pin_attempts(fresh_attempts, attempt):
    """TC-GRD-14 - Wrong PIN and the attempts counter"""
    guard = fresh_attempts
    log.info("Precondition: counter at zero, zone %s, ARMED", ZONE_QUIET)
    guard.guard_arm()
    for n in range(1, attempt + 1):
        log.info("Step: `guard disarm` with a wrong PIN (attempt %d)", n)
        resp = guard.guard_disarm(WRONG_PIN)
        seen = guard.attempts(resp)
        log.info("Expected: E803, Attempts: %d/3. Actual: codes %s, attempts %s", n, resp.codes, seen)
        assert resp.has_code("E803"), resp
        assert seen == n, resp
    st = guard.guard_state()
    if attempt < 3:
        log.info("Expected: Guard is still ARMED. Actual: %s", st["state"])
        assert st["state"] == "ARMED", st["response"]
    else:
        log.info("Expected: the 3rd wrong PIN raises the ALARM. Actual: %s", st["state"])
        assert resp.has(r"GENERAL ALARM: 3 wrong PIN attempts"), resp
        assert st["state"] == "ALARM", st["response"]


@pytest.mark.parametrize("scenario", [
    pytest.param("a", id="a-reset-after-correct-pin", marks=pytest.mark.xfail(strict=True, reason=BUG_GRD_01)),
    pytest.param("b", id="b-reset-by-second-arm", marks=pytest.mark.xfail(strict=True, reason=BUG_GRD_01)),
    pytest.param("c", id="c-control-first-attempt"),
])
def test_tc_grd_15_attempts_counter_resets(fresh_attempts, scenario):
    """TC-GRD-15 - The attempts counter starts from zero at every `guard arm` and after a correct PIN"""
    guard = fresh_attempts
    log.info("Scenario %s from a clean state (counter at zero)", scenario)
    guard.guard_arm()
    if scenario in ("a", "b"):
        for _ in range(2):
            guard.guard_disarm(WRONG_PIN)
    if scenario == "a":
        log.info("2 wrong PINs, the correct PIN, `guard arm` again")
        guard.guard_disarm(PIN)
        guard.guard_arm()
    elif scenario == "b":
        log.info("2 wrong PINs, `guard arm` again without disarming")
        guard.guard_arm(wait_for=None)
    log.info("Last step: one wrong PIN")
    resp = guard.guard_disarm(WRONG_PIN)
    seen = guard.attempts(resp)
    log.info("Expected: Attempts: 1/3. Actual: %s", seen)
    assert seen == 1, resp


# ---- GD-2 ------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    pytest.param("9", id="a-9-min-1"),
    pytest.param("201", id="b-201-max+1"),
    pytest.param("0", id="c-0"),
    pytest.param("-1", id="d-minus-1"),
    pytest.param("abc", id="e-not-a-number"),
    pytest.param("", id="f-no-argument"),
])
def test_tc_grd_16_zone_out_of_range(guard, value):
    """TC-GRD-16 - `guard zone` outside 10-200"""
    log.info("Step 1: `guard zone %s`; step 2: `guard status`", value or "(no argument)")
    resp = guard.guard_zone(value)
    st = guard.guard_state()
    log.info("Expected: E808, the zone stays %s. Actual: codes %s, zone %s", ZONE_QUIET, resp.codes, st["zone"])
    assert resp.has_code("E808"), resp
    assert st["zone"] == ZONE_QUIET, st["response"]


# ---- GD-5 ------------------------------------------------------------------------------

@pytest.mark.parametrize("old, new, armed, code", [
    pytest.param(PIN, "123", False, "E804", id="a-3-digits"),
    pytest.param(PIN, "12345", False, "E804", id="b-5-digits"),
    pytest.param(PIN, "abcd", False, "E804", id="c-letters"),
    pytest.param(PIN, NEW_PIN, True, "E807", id="d-armed"),
    pytest.param("9999", NEW_PIN, False, "E803", id="e-wrong-old-pin"),
])
def test_tc_grd_17_invalid_pin_change(guard, old, new, armed, code):
    """TC-GRD-17 - Invalid `guard pin` changes"""
    if armed:
        log.info("Precondition: Guard ARMED")
        guard.guard_arm()
    log.info("Step: `guard pin <old> <new>`. Expected: %s", code)
    resp = guard.guard_pin(old, new)
    log.info("Actual codes: %s", resp.codes)
    assert resp.has_code(code), resp
    assert not resp.has(r"PIN changed"), resp
    log.info("Check: the default PIN still works")
    if armed:
        assert guard.guard_disarm(PIN).has(r"disarmed \(was ARMED\)")
    else:
        check = guard.guard_pin(PIN, PIN)
        assert check.has(r"PIN changed"), check


# ---- AC-1 ------------------------------------------------------------------------------

def test_tc_grd_18_guard_requires_login(guard, restore_session):
    """TC-GRD-18 - `guard ...` without a login gives E003"""
    log.info("Precondition: `logout`")
    guard.logout()
    for cmd in ("guard status", "guard arm", "guard zone 100", f"guard disarm {PIN}", "guard panic"):
        resp = guard.command(cmd, until=r"\bE\d{3}\b")
        log.info("Expected: E003. Actual codes: %s", resp.codes)
        assert resp.has_code("E003"), resp
    restore_session()
    st = guard.guard_state()
    log.info("Expected: nothing changed (disarmed, zone %s). Actual: %s, zone %s", ZONE_QUIET, st["state"], st["zone"])
    assert st["state"] == "disarmed", st["response"]
    assert st["zone"] == ZONE_QUIET, st["response"]


# ---- ST-3 ------------------------------------------------------------------------------

def test_tc_grd_19_guard_blocked_in_emergency(guard, restore_session):
    """TC-GRD-19 - `guard ...` is blocked in EMERGENCY"""
    log.info("Step 1: `state 3`, `state 4` (EMERGENCY; the only way out is a reboot)")
    guard.set_state(3)
    entered = guard.set_state(4)
    assert entered.has(r"EMERGENCY"), entered
    for cmd in ("guard status", "guard arm"):
        resp = guard.command(cmd, until=r"\bE\d{3}\b")
        log.info("Step 2: `%s`. Expected: E005. Actual codes: %s", cmd, resp.codes)
        assert resp.has_code("E005"), resp
    log.info("Step 3: `reboot`, restore Wi-Fi and login")
    assert guard.reboot_and_wait(), "the board did not come back after the reboot"
    restore_session()
    st = guard.guard_state()
    log.info("Expected: the blocked `guard arm` did nothing. Actual: %s", st["state"])
    assert st["state"] == "disarmed", st["response"]
