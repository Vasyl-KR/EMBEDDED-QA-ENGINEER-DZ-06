"""SENTRY Guard - POSITIVE cases (TEST_CASES.md, section 3.1). Firmware 2.3.0 only.

One test per case: the function name is `test_tc_grd_<NN>_<slug>`, the first docstring line holds the case ID and
an English title. Parametrized cases use the row letters of the parameter table as pytest ids (`a-...`, `b-...`),
so every row of the table is a separate result.

All cases rely on a static target at D = SWM_TARGET_CM with 50 < D < 150 cm: zone 50 stays quiet (the target is
outside the zone), zone 150 always gives INTRUSION (the target is inside). The `guard` fixture puts the board in
the known Guard state before and after every test (disarmed, PIN 1234, zone 50, relay closed, NORMAL, no alerts).

Timing is measured with the device timestamps of the log lines (`I (12345) sentry:`), not with wall-clock sleeps.
"""

import logging
import re

import pytest

from drivers.device import GUARD_DEFAULT_PIN as PIN, GUARD_TEST_PIN as NEW_PIN

log = logging.getLogger(__name__)

pytestmark = [pytest.mark.guard, pytest.mark.positive, pytest.mark.target, pytest.mark.since("2.3.0")]

ZONE_QUIET = 50    # < D: the static target is outside the zone
ZONE_NEAR = 150    # > D: the static target is inside the zone -> INTRUSION
EXIT_DELAY_MS = 10_000
INTRUSION_DELAY_MS = 15_000
REMINDER_MS = 10_000
TIMER_TOLERANCE_MS = 1_000


def _alarm_after_intrusion(guard):
    """Zone 150, `guard arm`, no PIN: returns (arming/intrusion/alarm log, the lines right after the alarm)."""
    guard.guard_zone(ZONE_NEAR)
    resp = guard.guard_arm(wait_for=r"GENERAL ALARM", timeout=45)
    after = guard.collect(1.0)   # CRITICAL alert, relay and state lines follow within milliseconds
    return resp, after


# ---- GD-1 ------------------------------------------------------------------------------

def test_tc_grd_01_guard_status(guard, target_cm):
    """TC-GRD-01 - Guard status"""
    log.info("Precondition: one `distance` measurement (disarmed Guard does not ping; the last distance is -1.0 before the first ping)")
    guard.distance()
    for cmd in ("guard", "guard status"):
        log.info("Step: `%s`", cmd)
        st = guard.guard_state(cmd)
        log.info("Expected: disarmed, zone %s cm, last distance = D +-1 cm (D = %s). Actual: %s, zone %s cm, distance %s cm",
                 ZONE_QUIET, target_cm, st["state"], st["zone"], st["distance"])
        assert st["state"] == "disarmed", st["response"]
        assert st["zone"] == ZONE_QUIET, st["response"]
        assert abs(st["distance"] - target_cm) <= 1, f"last distance {st['distance']} cm, D = {target_cm} cm"


def test_tc_grd_02_arming(guard):
    """TC-GRD-02 - Arming (10 s exit delay)"""
    log.info("Step 1: `guard arm`; step 2: wait for `ARMED`, measure the delay with the device timestamps")
    resp = guard.guard_arm()
    seconds = [int(s) for s in re.findall(r"arming in (\d+) s", resp.text)]
    start = resp.stamps(r"arming in 10 s")
    armed = resp.stamps(r"ARMED\. Perimeter")
    delay = armed[0] - start[0] if start and armed else None
    log.info("Expected: `arming in N s` counts down from 10, `ARMED` 10 +-1 s after the start, no INTRUSION meanwhile. "
             "Actual: countdown %s, delay %s ms", seconds, delay)
    assert seconds and seconds[0] == 10 and seconds == sorted(seconds, reverse=True), resp
    assert delay is not None and abs(delay - EXIT_DELAY_MS) <= TIMER_TOLERANCE_MS, resp
    assert not resp.has(r"INTRUSION"), resp
    log.info("Step 3: `guard status`. Expected: ARMED")
    assert guard.guard_state()["state"] == "ARMED"


# ---- GD-2 ------------------------------------------------------------------------------

@pytest.mark.parametrize("zone", [
    pytest.param(10, id="a-N=10-min"),
    pytest.param(50, id="b-N=50-default"),
    pytest.param(100, id="c-N=100-middle"),
    pytest.param(200, id="d-N=200-max"),
])
def test_tc_grd_03_zone_valid_values(guard, zone):
    """TC-GRD-03 - `guard zone N`: valid values 10-200"""
    log.info("Step 1: `guard zone %s`; step 2: `guard status`", zone)
    resp = guard.guard_zone(zone)
    st = guard.guard_state()
    log.info("Expected: accepted without errors, `guard status` shows zone %s. Actual: codes %s, zone %s",
             zone, resp.codes, st["zone"])
    assert not resp.codes, resp
    assert resp.has(rf"zone < {zone} cm"), resp
    assert st["zone"] == zone, st["response"]


def test_tc_grd_04_object_outside_zone_is_quiet(guard):
    """TC-GRD-04 - Object outside the zone: no intrusion"""
    log.info("Precondition: zone %s < D. Step 1: `guard arm`, wait for ARMED; step 2: observe 30 s", ZONE_QUIET)
    guard.guard_arm()
    observed = guard.collect(30.0)
    st = guard.guard_state()
    unacked, alerts = guard.alerts(guard.alert_list())
    loud = [a for a in alerts if a["source"] == "watch" and a["level"] in ("WARNING", "CRITICAL")]
    log.info("Expected: stays ARMED, no INTRUSION / ALARM, no WARNING / CRITICAL alert from Guard. "
             "Actual: state %s, loud alerts %s", st["state"], loud)
    assert st["state"] == "ARMED", st["response"]
    assert not observed.has(r"INTRUSION|GENERAL ALARM"), observed
    assert not loud, loud


def test_tc_grd_05_object_inside_zone_gives_intrusion(guard, target_cm):
    """TC-GRD-05 - Object inside the zone: INTRUSION"""
    log.info("Precondition: zone %s > D. Step 1: `guard arm`; step 2: wait for INTRUSION", ZONE_NEAR)
    guard.guard_zone(ZONE_NEAR)
    resp = guard.guard_arm(wait_for=r"INTRUSION: unknown contact", timeout=25)
    armed = resp.stamps(r"ARMED\. Perimeter")
    intrusion = resp.stamps(r"INTRUSION: unknown contact")
    contact = resp.find(r"unknown contact at ([\d.]+) cm")
    st = guard.guard_state()
    log.info("Expected: INTRUSION after ARMED, `15 s to 'guard disarm <pin>'`, contact at D +-3 cm, status INTRUSION. "
             "Actual: ARMED at %s ms, INTRUSION at %s ms, contact %s cm, status %s",
             armed, intrusion, contact.group(1) if contact else None, st["state"])
    assert armed and intrusion and armed[0] <= intrusion[0], resp
    assert resp.has(r"15 s to 'guard disarm <pin>'"), resp
    assert contact and abs(float(contact.group(1)) - target_cm) <= 3, resp
    assert st["state"] == "INTRUSION", st["response"]


@pytest.mark.parametrize("before", [
    pytest.param("ARMED", id="a-ARMED"),
    pytest.param("INTRUSION", id="b-INTRUSION"),
])
def test_tc_grd_06_disarm_with_correct_pin(guard, before):
    """TC-GRD-06 - `guard disarm <pin>` with the correct PIN"""
    if before == "ARMED":
        log.info("Precondition: zone %s, ARMED", ZONE_QUIET)
        guard.guard_arm()
    else:
        log.info("Precondition: zone %s, INTRUSION; the PIN is entered 5 s after INTRUSION", ZONE_NEAR)
        guard.guard_zone(ZONE_NEAR)
        guard.guard_arm(wait_for=r"INTRUSION: unknown contact", timeout=25)
        guard.collect(5.0)
    log.info("Step: `guard disarm` with the correct PIN")
    resp = guard.guard_disarm(PIN)
    after = guard.collect(12.0) if before == "INTRUSION" else guard.collect(0.5)   # the 15 s would have expired by now
    st = guard.guard_state()
    log.info("Expected: `disarmed (was %s)`, no ALARM even after the 15 s. Actual: status %s", before, st["state"])
    assert resp.has(rf"disarmed \(was {before}\)"), resp
    assert not after.has(r"GENERAL ALARM"), after
    assert st["state"] == "disarmed", st["response"]


# ---- GD-3 ------------------------------------------------------------------------------

def test_tc_grd_07_intrusion_without_pin_becomes_alarm(guard):
    """TC-GRD-07 - INTRUSION without a PIN -> ALARM and its effects"""
    log.info("Precondition: zone %s, no alerts. Step 1: `guard arm`; step 2: no PIN for 15 s", ZONE_NEAR)
    resp, after = _alarm_after_intrusion(guard)
    intrusion = resp.stamps(r"INTRUSION: unknown contact")
    alarm = resp.stamps(r"GENERAL ALARM: no disarm after intrusion")
    delay = alarm[0] - intrusion[0] if intrusion and alarm else None
    log.info("Expected: ALARM 15 +-1 s after INTRUSION. Actual: %s ms", delay)
    assert delay is not None and abs(delay - INTRUSION_DELAY_MS) <= TIMER_TOLERANCE_MS, resp

    effects = after.text
    log.info("Expected: CRITICAL alert from watch, relay OPEN, NORMAL -> VERBOSE (AL-5)")
    assert re.search(r"\[CIC #\d+ CRITICAL\] watch", effects), after
    assert re.search(r"\[VALVE\] OPEN", effects), after
    assert re.search(r"\[STATE\] 1 NORMAL -> 3 VERBOSE", effects), after

    log.info("Step 3: observe 25 s - the alarm reminder is repeated every 10 s")
    observed = guard.collect(25.0)
    reminders = observed.stamps(r"ALARM active")
    gaps = observed.gaps(r"ALARM active")
    log.info("Expected: >= 2 reminders, gap 10 +-1 s. Actual: %d reminders, gaps %s ms", len(reminders), gaps)
    assert len(reminders) >= 2, observed
    assert all(abs(g - REMINDER_MS) <= TIMER_TOLERANCE_MS for g in gaps), gaps

    log.info("Step 4: `relay status`, `alert list`, `state`")
    relay, state = guard.relay_state(), guard.system_state()
    unacked, alerts = guard.alerts(guard.alert_list())
    critical = [a for a in alerts if a["level"] == "CRITICAL" and a["source"] == "watch"]
    log.info("Actual: relay %s, state %s, CRITICAL watch alerts %d", relay, state, len(critical))
    assert relay == "open"
    assert state == 3
    assert critical


@pytest.mark.parametrize("before", [
    pytest.param("ARMED", id="a-ARMED"),
    pytest.param("disarmed", id="b-disarmed"),
])
def test_tc_grd_08_panic(guard, before):
    """TC-GRD-08 - `guard panic`"""
    if before == "ARMED":
        log.info("Precondition: ARMED (zone %s)", ZONE_QUIET)
        guard.guard_arm()
    else:
        log.info("Precondition: Guard disarmed (PRD does not say whether panic works then - the actual behaviour is checked)")
    log.info("Step 2: `guard panic`; step 3: `guard status`")
    resp = guard.guard_panic()
    st = guard.guard_state()
    relay = guard.relay_state()
    log.info("Expected: ALARM at once, CRITICAL alert, relay OPEN. Actual: status %s, relay %s", st["state"], relay)
    assert resp.has(r"GENERAL ALARM: PANIC command"), resp
    assert resp.has(r"\[CIC #\d+ CRITICAL\] watch"), resp
    assert st["state"] == "ALARM", st["response"]
    assert relay == "open"


def test_tc_grd_09_disarm_stops_alarm(guard):
    """TC-GRD-09 - Correct PIN stops the ALARM"""
    log.info("Precondition: ALARM (`guard panic`). Step 2: `guard disarm` with the correct PIN")
    guard.guard_panic()
    resp = guard.guard_disarm(PIN)
    st = guard.guard_state()
    relay = guard.relay_state()
    log.info("Expected: alarm stopped, Guard disarmed (PRD is silent about the relay - actual: %s). Actual status: %s",
             relay, st["state"])
    assert resp.has(r"disarmed \(was ALARM\)"), resp
    assert st["state"] == "disarmed", st["response"]
    assert relay == "closed"


# ---- GD-5 ------------------------------------------------------------------------------

def test_tc_grd_10_change_pin(guard, restore_session):
    """TC-GRD-10 - Change the PIN (new PIN works, old PIN does not, survives a reboot)"""
    try:
        log.info("Step 1: `guard pin <default> <new>` with the Guard disarmed")
        resp = guard.guard_pin(PIN, NEW_PIN)
        assert resp.has(r"PIN changed") and not resp.codes, resp

        log.info("Step 2: ARMED, `guard disarm` with the OLD PIN. Expected: E803, still ARMED")
        guard.guard_arm()
        old = guard.guard_disarm(PIN)
        assert old.has_code("E803"), old
        assert guard.guard_state()["state"] == "ARMED"

        log.info("Step 3: `guard disarm` with the NEW PIN. Expected: disarmed")
        new = guard.guard_disarm(NEW_PIN)
        assert new.has(r"disarmed \(was ARMED\)"), new

        log.info("Step 4: `reboot`, restore Wi-Fi and login")
        assert guard.reboot_and_wait(), "the board did not come back after the reboot"
        restore_session()

        log.info("Step 5: ARMED, `guard disarm` with the NEW PIN. Expected: the new PIN survived the reboot")
        guard.guard_arm()
        after = guard.guard_disarm(NEW_PIN)
        assert after.has(r"disarmed \(was ARMED\)"), after
    finally:
        log.info("Step 6: the default PIN is restored")
        guard.guard_pin(NEW_PIN, PIN)


def test_tc_grd_11_log_keeps_last_ten_events(guard):
    """TC-GRD-11 - `guard log` keeps the last 10 events"""
    log.info("Step 1: 4 x (`guard arm`, wait for ARMED, `guard disarm`) = 12 events (arming, armed, disarmed)")
    for _ in range(4):
        guard.guard_arm()
        guard.guard_disarm(PIN)
    log.info("Step 2: `guard log`")
    events = guard.guard_events(guard.guard_log())
    kinds = [text.split()[0] for _, _, text in events]
    stamps = [stamp for _, stamp, _ in events]
    expected = ["disarmed", "arming", "armed"] * 3 + ["disarmed"]   # events 3..12: the first two (arming, armed) are gone
    log.info("Expected: exactly 10 entries, oldest first, newest last: %s. Actual: %d entries %s", expected, len(events), kinds)
    assert [n for n, _, _ in events] == list(range(1, 11)), events
    assert kinds == expected, events
    assert stamps == sorted(stamps), stamps


def test_tc_grd_12_logout_does_not_disarm(guard, restore_session):
    """TC-GRD-12 - `logout` does not disarm Guard (and does not stop an ALARM)"""
    log.info("Step 1: ARMED. Step 2: `logout`, `login`. Step 3: `guard status`")
    guard.guard_arm()
    guard.logout()
    restore_session()
    st = guard.guard_state()
    log.info("Expected: still ARMED. Actual: %s", st["state"])
    assert st["state"] == "ARMED", st["response"]

    log.info("Step 4: `guard panic`, `logout`, `login`, `relay status`, `guard status`")
    guard.guard_panic()
    guard.logout()
    restore_session()
    st = guard.guard_state()
    relay = guard.relay_state()
    log.info("Expected: still ALARM, relay stays OPEN (a plain logout closes the relay). Actual: %s, relay %s", st["state"], relay)
    assert st["state"] == "ALARM", st["response"]
    assert relay == "open"


# ---- HL-1, HL-2 ------------------------------------------------------------------------

def test_tc_grd_13_telemetry_shows_watch_state(guard):
    """TC-GRD-13 - Telemetry carries the Guard state"""
    log.info("Step 1: `health now` with the Guard disarmed")
    report = guard.health_now()
    watch = report.find(r"watch (\w+) alerts (\d+)")
    unacked, _ = guard.alerts(guard.alert_list())
    log.info("Expected: `watch disarmed alerts N`, N = unacknowledged alerts. Actual: %s, unacknowledged: %s",
             watch.groups() if watch else None, unacked)
    assert watch and watch.group(1) == "disarmed", report
    assert int(watch.group(2)) == unacked, report

    log.info("Step 2: `guard panic`, `health now`")
    guard.guard_panic()
    report = guard.health_now()
    log.info("Expected: `watch ALARM alerts N` and the warning `WARN watch alarm`")
    assert report.has(r"watch ALARM alerts \d+"), report
    assert report.has(r"WARN watch alarm"), report
