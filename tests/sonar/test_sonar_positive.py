"""Active sonar HC-SR04 - POSITIVE cases (TEST_CASES.md, section 2.1).

One test per case: the function name is `test_tc_snr_<NN>_<slug>`, the first docstring
line holds the case ID and an English title of the case. Parametrized cases use the row
letters of the parameter table as pytest ids (`a-N=1`, `b-N=2`, ...), so every row of the
table is a separate result. Manual cases (TC-SNR-21, TC-SNR-22) are not automated.

Every test writes its steps and the expected / actual values to the log (`log.info`), the
driver adds every command and the board's answer - all of it goes to the HTML report.

Tests marked `target` need a static target at SWM_TARGET_CM (= D). Other distances are
produced with `distance calibrate <ref>` (the sensor then reads `ref`).
"""

import logging
import re

import pytest

log = logging.getLogger(__name__)

pytestmark = [pytest.mark.sonar, pytest.mark.positive, pytest.mark.regression]

BUG_SNR_01 = "BUG-SNR-01: PRD DS-3 says `distance calibrate reset`, firmware answers E706 usage (only `distance reset` works)"
BUG_SNR_02 = "BUG-SNR-02: PRD DS-1 says N is 1-20 inclusive, firmware rejects 20 with E704 `count must be 1-20`"


# ---- DS-1 ------------------------------------------------------------------------------

@pytest.mark.target
def test_tc_snr_01_single_measurement(sonar, target_cm):
    """TC-SNR-01 - Single measurement"""
    log.info("Step 1: enter `distance`; D = %s cm", target_cm)
    resp = sonar.distance()
    value = sonar.echo_cm(resp)
    log.info("Expected: one line `ping: echo X cm`, X = D +-1 cm, no E / W codes, no [COLLISION]. "
             "Actual: X = %s cm, codes: %s", value, resp.codes)
    assert value is not None, resp
    assert not resp.codes, resp
    assert not resp.has(r"\[COLLISION\]"), resp
    assert abs(value - target_cm) <= 1, f"measured {value} cm, D = {target_cm} cm (allowed +-1)"


@pytest.mark.parametrize("count", [
    pytest.param(1, id="a-N=1-min"),
    pytest.param(2, id="b-N=2-min+1"),
    pytest.param(10, id="c-N=10-middle"),
    pytest.param(19, id="d-N=19-max-1"),
    pytest.param(20, id="e-N=20-max", marks=pytest.mark.xfail(strict=True, reason=BUG_SNR_02)),
])
def test_tc_snr_02_n_measurements_within_1_20(sonar, target_cm, count):
    """TC-SNR-02 - `distance N`: number of measurements within 1-20"""
    log.info("Step 1: enter `distance %s`; step 2: wait for the `avg` line", count)
    resp = sonar.distance(count, timeout=45)
    lines = re.findall(r"\[SONAR\] (\d+)/(\d+): ([\d.]+) cm", resp.text)
    values = [float(x) for _, _, x in lines]
    avg = resp.find(r"avg ([\d.]+) cm \((\d+)/(\d+) ok\)")
    log.info("Expected: %s lines `i/N`, `avg ... (%s/%s ok)`, every x = D +-3 cm, avg between min and max, no E / W codes. "
             "Actual: %s lines, values %s, codes %s", count, count, count, len(lines), values, resp.codes)
    assert not resp.codes, resp
    assert [int(i) for i, _, _ in lines] == list(range(1, count + 1)), resp
    assert all(abs(v - target_cm) <= 3 for v in values), f"{values} vs D = {target_cm}"
    assert avg, resp
    assert int(avg.group(2)) == int(avg.group(3)) == count, resp
    assert min(values) <= float(avg.group(1)) <= max(values), resp


# ---- DS-2 ------------------------------------------------------------------------------

def test_tc_snr_03_log_without_interval(sonar):
    """TC-SNR-03 - `distance log` without an interval"""
    log.info("Step 1: `distance log`; step 2: wait 3 s; step 3: `distance stop`")
    sonar.start_log()
    resp = sonar.collect(3.0)
    stop = sonar.stop_log()
    interval = resp.find(r"continuous pinging every (\d+) ms \(command\)")
    log.info("Expected: `continuous pinging every N ms (command)`, then `ping: echo` lines, after stop - `pinging stopped`. "
             "Actual: default interval = %s ms, ping lines: %d",
             interval.group(1) if interval else None, len(resp.stamps(r"ping: echo")))
    assert interval, resp
    assert resp.has(r"ping: echo [\d.]+ cm"), resp
    assert stop.has(r"pinging stopped \(command\)"), stop


@pytest.mark.parametrize("interval, window", [
    pytest.param(100, 3.0, id="a-N=100ms"),
    pytest.param(250, 3.0, id="b-N=250ms"),
    pytest.param(500, 5.0, id="c-N=500ms"),
    pytest.param(1000, 8.0, id="d-N=1000ms"),
    pytest.param(5000, 16.0, id="e-N=5000ms"),
])
def test_tc_snr_04_log_period(sonar, interval, window):
    """TC-SNR-04 - `distance log N`: measurement period"""
    log.info("Precondition: `distance filter off` (with the filter on, ~100 ms of the 5-sample median is added to the period)")
    sonar.set_filter("off")
    log.info("Step 1: `distance log %s`; step 2: collect the output for %s s and record the `I (ms)` stamp of every ping; "
             "step 3: `distance stop`", interval, window)
    sonar.start_log(interval)
    resp = sonar.collect(window)
    sonar.stop_log()
    gaps = resp.gaps(r"ping: echo")
    low, high = interval, interval * 1.3 + 30
    log.info("Expected: period between pings from %s to %.0f ms. Actual periods (ms): %s", low, high, gaps)
    assert len(gaps) >= (2 if interval == 5000 else 4), resp
    for gap in gaps:
        assert low <= gap <= high, f"gap {gap} ms for N = {interval}: {gaps}"


def test_tc_snr_05_stop(sonar):
    """TC-SNR-05 - `distance stop`"""
    log.info("Step 1: `distance log 100`; step 2: wait 1 s; step 3: `distance stop`; step 4: watch the output for 3 more seconds")
    sonar.start_log(100)
    sonar.collect(1.0)
    sonar.stop_log(wait=False)
    after = sonar.collect(3.0)
    late = len(after.stamps(r"ping: echo"))
    log.info("Expected: `pinging stopped (command)`, then at most one late ping. "
             "Actual: stopped=%s, late pings = %d", after.has(r"pinging stopped"), late)
    assert after.has(r"pinging stopped \(command\)"), after
    assert late <= 1, after
    assert not sonar.collect(1.5).has(r"ping: echo"), "pings keep coming after stop"


# ---- DS-3 ------------------------------------------------------------------------------

@pytest.mark.target
@pytest.mark.parametrize("ref", [
    pytest.param(5, id="a-ref=5cm-min"),
    pytest.param(30, id="b-ref=30cm"),
    pytest.param(60, id="c-ref=60cm"),
    pytest.param(150, id="d-ref=150cm"),
    pytest.param(300, id="e-ref=300cm-max"),
])
def test_tc_snr_06_calibration(sonar, target_cm, ref):
    """TC-SNR-06 - Calibration"""
    log.info("Step 1: `distance calibrate %s`; step 2: wait for `calibrated`; step 3: `distance`", ref)
    resp = sonar.calibrate(ref)
    m = resp.find(r"calibrated: measured ([\d.]+) cm, offset ([+-][\d.]+) cm")
    assert resp.has(rf"calibrating: put object at {ref}\.0 cm"), resp
    assert m, resp
    measured, offset = float(m.group(1)), float(m.group(2))
    after = sonar.echo_cm(sonar.distance())
    log.info("Expected: measured ~ D (+-3), offset = ref - measured, next ping = %s +-2 cm. "
             "Actual: measured = %s, offset = %s (ref - measured = %.1f), ping after = %s",
             ref, measured, offset, ref - measured, after)
    assert abs(measured - target_cm) <= 3, f"measured {measured} cm, D = {target_cm}"
    assert abs(offset - (ref - measured)) <= 0.2, f"offset {offset} != ref - measured ({ref - measured:.1f})"
    assert abs(after - ref) <= 2


@pytest.mark.target
def test_tc_snr_07_reset(sonar, target_cm):
    """TC-SNR-07 - `distance reset`"""
    log.info("Step 1: `distance calibrate 60`; step 2: `distance reset`; step 3: `distance`; step 4: `distance stats`")
    sonar.calibrate(60)
    reset = sonar.reset_calibration()
    value = sonar.echo_cm(sonar.distance())
    stats = sonar.stats()
    log.info("Expected: `calibration reset`, reading ~ D = %s, `calibration +0.0 cm` in stats. Actual: reading = %s", target_cm, value)
    assert reset.has(r"calibration reset")
    assert abs(value - target_cm) <= 3
    assert stats.has(r"calibration \+0\.0 cm")


@pytest.mark.target
@pytest.mark.xfail(strict=True, reason=BUG_SNR_01)
def test_tc_snr_08_calibrate_reset_as_in_prd(sonar):
    """TC-SNR-08 - `distance calibrate reset` (as written in the PRD)"""
    log.info("Step 1: `distance calibrate 60`; step 2: `distance calibrate reset`; step 3: `distance stats`")
    sonar.calibrate(60)
    resp = sonar.calibrate_reset()
    stats = sonar.stats()
    log.info("Expected (PRD DS-3): the command is accepted, calibration +0.0 cm, no E codes. Actual codes: %s", resp.codes)
    assert not any(code.startswith("E") for code in resp.codes), resp
    assert stats.has(r"calibration \+0\.0 cm")


# ---- DS-4 ------------------------------------------------------------------------------

@pytest.mark.target
@pytest.mark.parametrize("threshold, apparent, expect_alarm", [
    pytest.param(50, 40, True, id="a-T=50-A=40-alarm"),
    pytest.param(50, 70, False, id="b-T=50-A=70-quiet"),
    pytest.param(100, 90, True, id="c-T=100-A=90-alarm"),
    pytest.param(30, 45, False, id="d-T=30-A=45-quiet"),
    pytest.param(200, 190, True, id="e-T=200-A=190-alarm"),
])
def test_tc_snr_09_alarm_threshold(sonar, threshold, apparent, expect_alarm):
    """TC-SNR-09 - Alarm threshold"""
    log.info("Step 1: `distance calibrate %s` (reading = %s); step 2: `distance alarm %s`; step 3: `distance`",
             apparent, apparent, threshold)
    sonar.calibrate(apparent)
    set_resp = sonar.set_alarm(threshold)
    resp = sonar.distance()
    log.info("Expected: for A <= T `PROXIMITY ALARM ... (threshold %s cm)`, for A > T only a ping. "
             "Actual: alarm = %s, expected %s", threshold, resp.has(r"PROXIMITY ALARM"), expect_alarm)
    assert set_resp.has(rf"alarm at {threshold} cm")
    assert resp.has(r"PROXIMITY ALARM") is expect_alarm, resp
    if expect_alarm:
        assert resp.has(rf"contact at [\d.]+ cm \(threshold {threshold} cm\)"), resp


@pytest.mark.target
def test_tc_snr_10_alarm_off(sonar):
    """TC-SNR-10 - `distance alarm off`"""
    log.info("Step 1: `distance calibrate 40`; step 2: `distance alarm 50`; step 3: `distance alarm off`; step 4: `distance`")
    sonar.calibrate(40)
    sonar.set_alarm(50)
    off = sonar.alarm_off()
    resp = sonar.distance()
    stats = sonar.stats()
    log.info("Expected: `alarm off`, ping ~ 40 cm without PROXIMITY ALARM, `alarm off` in stats. Actual: ping = %s, alarm = %s",
             sonar.echo_cm(resp), resp.has(r"PROXIMITY ALARM"))
    assert off.has(r"\[SONAR\] alarm off")
    assert abs(sonar.echo_cm(resp) - 40) <= 2, resp
    assert not resp.has(r"PROXIMITY ALARM"), resp
    assert stats.has(r"alarm off")


HYSTERESIS_ROWS = [  # (apparent cm, alarm message expected, cleared message expected)
    (40, True, False), (40, False, False), (52, False, False),
    (56, False, True), (54, False, False), (48, True, False),
]


@pytest.mark.target
@pytest.mark.parametrize("row", [
    pytest.param(0, id="a-A=40-alarm"),
    pytest.param(1, id="b-A=40-no-repeat"),
    pytest.param(2, id="c-A=52-in-hysteresis-band"),
    pytest.param(3, id="d-A=56-cleared"),
    pytest.param(4, id="e-A=54-quiet"),
    pytest.param(5, id="f-A=48-alarm-again"),
])
def test_tc_snr_11_alarm_hysteresis(sonar, row):
    """TC-SNR-11 - Alarm hysteresis of 5 cm"""
    # The rows are consecutive steps of one scenario: the state before a row is rebuilt by
    # replaying the previous rows (sonar_reset runs between tests); only the row itself is asserted.
    log.info("Precondition: `distance alarm 50`; the rows before row %d are replayed without assertions", row + 1)
    sonar.set_alarm(50)
    for ref, _, _ in HYSTERESIS_ROWS[:row]:
        sonar.measure_at(ref)
    ref, alarm, cleared = HYSTERESIS_ROWS[row]
    log.info("Step: `distance calibrate %s`, `distance`. Expected: alarm = %s, cleared = %s", ref, alarm, cleared)
    ev = sonar.measure_at(ref)
    log.info("Actual: %s", ev)
    assert (ev["alarm"], ev["cleared"]) == (alarm, cleared), f"reads {ref} cm: {ev}"


# ---- DS-5 ------------------------------------------------------------------------------

@pytest.mark.parametrize("state, reply, in_stats", [
    pytest.param("off", r"\[SONAR\] filter off", r"filter off", id="a-off"),
    pytest.param("on", r"\[SONAR\] filter on \(median of 5\)", r"filter median 5", id="b-on"),
])
def test_tc_snr_12_filter(sonar, state, reply, in_stats):
    """TC-SNR-12 - Filter"""
    log.info("Step 1: `distance stats` - the filter is on by default (`filter median 5`)")
    assert sonar.stats().has(r"filter median 5"), "the filter must be on by default"
    log.info("Step 2: `distance filter %s`; step 3: `distance stats`. Expected reply /%s/ and /%s/ in stats", state, reply, in_stats)
    assert sonar.set_filter(state).has(reply)
    assert sonar.stats().has(in_stats)


def test_tc_snr_13_stats(sonar):
    """TC-SNR-13 - Statistics"""
    def stats():
        resp = sonar.stats()
        if resp.has(r"no measurements yet"):
            return 0, 0, None
        m = resp.find(r"measurements (\d+), errors (\d+), min ([\d.]+), max ([\d.]+), avg ([\d.]+) cm")
        assert m, resp
        assert resp.has(r"calibration [+-][\d.]+ cm, filter .*, alarm "), resp
        return int(m.group(1)), int(m.group(2)), tuple(float(m.group(i)) for i in (3, 4, 5))

    log.info("Step 1: `distance stats`, remember `measurements` (c0)")
    before, _, _ = stats()
    log.info("Step 2: `distance 5`; step 3: `distance stats`. c0 = %s", before)
    sonar.distance(5, timeout=30)
    count, errors, (lo, hi, avg) = stats()
    log.info("Expected: measurements = c0 + 5 = %s, errors = 0, min <= avg <= max. Actual: measurements = %s, errors = %s, "
             "min = %s, avg = %s, max = %s", before + 5, count, errors, lo, avg, hi)
    assert count == before + 5
    assert errors == 0
    assert lo <= avg <= hi


def test_tc_snr_14_history(sonar):
    """TC-SNR-14 - Measurement history"""
    log.info("Step 1: `distance 10`; step 2: `distance 2`; step 3: `distance history`")
    sonar.distance(10, timeout=30)
    sonar.distance(2, timeout=15)
    resp = sonar.history()
    entries = re.findall(r"^\s*(\d+)\.\s+[0-9-]{2}:[0-9-]{2}:[0-9-]{2}\s+[\d.]+ cm", resp.text, re.M)
    log.info("Expected: `last 10 measurements:` and entries 1-10. Actual numbers: %s", entries)
    assert resp.has(r"last 10 measurements:"), resp
    assert [int(n) for n in entries] == list(range(1, 11)), resp


# ---- DS-6 ------------------------------------------------------------------------------

COLLISION_ROWS = [  # (apparent cm, [COLLISION] expected)
    (10, True), (10, False), (22, False), (10, False), (30, False), (10, True),
]


@pytest.mark.target
@pytest.mark.parametrize("row", [
    pytest.param(0, id="a-A=10-first-approach"),
    pytest.param(1, id="b-A=10-same-approach"),
    pytest.param(2, id="c-A=22-not-rearmed"),
    pytest.param(3, id="d-A=10-same-approach"),
    pytest.param(4, id="e-A=30-moved-away"),
    pytest.param(5, id="f-A=10-new-approach"),
])
def test_tc_snr_15_collision_once_per_approach(sonar, row):
    """TC-SNR-15 - Collision: once per approach"""
    log.info("Precondition: `distance calibrate 60` + `distance` (the collision state is re-armed); "
             "the rows before row %d are replayed without assertions", row + 1)
    sonar.measure_at(60)
    for ref, _ in COLLISION_ROWS[:row]:
        sonar.measure_at(ref)
    ref, expected = COLLISION_ROWS[row]
    log.info("Step: `distance calibrate %s`, `distance`. Expected [COLLISION]: %s", ref, expected)
    got = sonar.measure_at(ref)["collision"]
    log.info("Actual [COLLISION]: %s", got)
    assert got is expected, f"reads {ref} cm"


@pytest.mark.target
@pytest.mark.parametrize("ref, collision", [
    pytest.param(5, True, id="a-ref=5cm-collision"),
    pytest.param(15, True, id="b-ref=15cm-collision"),
    pytest.param(19, True, id="c-ref=19cm-collision-edge"),
    pytest.param(21, False, id="d-ref=21cm-quiet-edge"),
    pytest.param(30, False, id="e-ref=30cm-quiet"),
    pytest.param(100, False, id="f-ref=100cm-quiet"),
])
def test_tc_snr_16_collision_threshold_20_cm(sonar, ref, collision):
    """TC-SNR-16 - Collision: 20 cm threshold"""
    log.info("Step 1: `distance calibrate 60`, `distance` (re-arm); step 2: `distance calibrate %s`, `distance`", ref)
    sonar.measure_at(60)
    got = sonar.measure_at(ref)["collision"]
    log.info("Expected [COLLISION]: %s. Actual: %s", collision, got)
    assert got is collision


# ---- persistence, states, session, telemetry -----------------------------------------------------------------

@pytest.mark.target
def test_tc_snr_17_settings_survive_reboot(sonar, restore_session):
    """TC-SNR-17 - Sonar settings survive a reboot"""
    log.info("Step 1: `distance calibrate 60`, `distance alarm 45`, `distance filter off`")
    sonar.calibrate(60)
    sonar.set_alarm(45)
    sonar.set_filter("off")
    log.info("Step 2: `reboot`, wait for `ready. state 1 NORMAL`; step 3: restore Wi-Fi and login")
    assert sonar.reboot_and_wait()
    restore_session()
    log.info("Steps 4-5: `distance` and `distance stats`")
    after = sonar.echo_cm(sonar.distance())
    stats = sonar.stats()
    log.info("Expected: reading ~ 60, `filter off`, `alarm on`. Actual: %s cm, filter off = %s, alarm on = %s",
             after, stats.has(r"filter off"), stats.has(r"alarm on"))
    assert abs(after - 60) <= 2, "calibration lost after reboot"
    assert stats.has(r"filter off"), stats
    assert stats.has(r"alarm on"), stats
    log.info("Steps 6-7: calibrate to 50 (no alarm) and to 40 (alarm), the threshold was 45")
    assert sonar.measure_at(50)["alarm"] is False
    assert sonar.measure_at(40)["alarm"] is True


@pytest.mark.target
def test_tc_snr_18_debug_raw_values(sonar, target_cm):
    """TC-SNR-18 - DEBUG: raw values"""
    log.info("Step 1: `distance calibrate 60`; step 2: `state 2`; step 3: `distance`")
    sonar.calibrate(60)
    try:
        sonar.set_state(2)
        resp = sonar.distance()
        value = sonar.echo_cm(resp)
        log.info("Expected: reading ~ D = %s (no calibration) and [DBG] diagnostics. Actual: %s cm, [DBG] = %s",
                 target_cm, value, resp.has(r"\[DBG\]"))
        assert abs(value - target_cm) <= 3, f"DEBUG reading still follows the calibration: {resp}"
        assert resp.has(r"\[DBG\]"), f"no [DBG] diagnostics in DEBUG: {resp}"
    finally:
        log.info("Step 4: `state 1`; step 5: `distance` - the reading is ~ 60 again")
        sonar.set_state(1)
    assert abs(sonar.echo_cm(sonar.distance()) - 60) <= 2


def test_tc_snr_19_logout_stops_measuring(sonar, account):
    """TC-SNR-19 - `logout` stops the measurements"""
    log.info("Step 1: `distance log 100`; step 2: wait 1 s; step 3: `logout`; step 4: watch the output for 3 s")
    sonar.start_log(100)
    sonar.collect(1.0)
    sonar.logout()
    after = sonar.collect(3.0)
    log.info("Expected: no new pings after logout. Actual ping lines: %d", len(after.stamps(r"ping: echo")))
    assert not after.has(r"ping: echo"), "measurements go on after logout"
    log.info("Step 5: log in again; `distance stop` must answer W710 (the stream was not resumed)")
    ok = sonar.ensure_logged_in(*account)
    assert ok
    assert sonar.stop_log().has_code("W710"), "the stream was resumed after login"


@pytest.mark.target
def test_tc_snr_20_telemetry_last_measurement(sonar):
    """TC-SNR-20 - Telemetry reports the last measurement"""
    log.info("Step 1: `distance`; step 2: `health now`")
    measured = sonar.echo_cm(sonar.distance())
    resp = sonar.health_now()
    m = resp.find(r"sonar ([\d.]+)\s*cm")
    log.info("Expected: telemetry `sonar` = the measurement +-1.5 cm. Actual: measurement = %s, telemetry = %s",
             measured, m.group(1) if m else None)
    assert m, resp
    assert abs(float(m.group(1)) - measured) <= 1.5, resp
