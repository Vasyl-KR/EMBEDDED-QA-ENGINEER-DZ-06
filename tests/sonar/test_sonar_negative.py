"""Active sonar HC-SR04 - NEGATIVE cases (TEST_CASES.md, section 2.2).

One test per case: the function name is `test_tc_snr_<NN>_<slug>`, the first docstring
line holds the case ID and an English title of the case. Parametrized cases use the row
letters of the parameter table as pytest ids (`a-N=0`, `b-N=21`, ...). Manual cases
(TC-SNR-38 - object out of range, TC-SNR-39 - sensor unplugged) are not automated.

Every test writes its steps and the expected / actual values to the log (`log.info`), the
driver adds every command and the board's answer - all of it goes to the HTML report.
After every rejected command the sensor must still work.
"""

import logging

import pytest

log = logging.getLogger(__name__)

pytestmark = [pytest.mark.sonar, pytest.mark.negative, pytest.mark.regression]

BUG_SNR_03 = ("BUG-SNR-03: PRD DS-2 says other `distance ...` commands answer E711 while `distance log` runs, "
              "but `distance alarm <cm>` is accepted (`alarm at 50 cm`) - unlike `distance`, `distance N` and `distance calibrate`")


def has_error(resp):
    return any(code.startswith("E") for code in resp.codes)


def sensor_works(dev):
    log.info("Check: the sensor still works after the error (`distance`)")
    return dev.echo_cm(dev.distance()) is not None


def offset_unchanged(dev):
    return dev.stats().has(r"calibration \+0\.0 cm|no measurements yet")


# ---- AC-1 ------------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    pytest.param("distance", id="a-distance"),
    pytest.param("distance 3", id="b-distance-3"),
    pytest.param("distance log 500", id="c-log-500"),
    pytest.param("distance calibrate 50", id="d-calibrate-50"),
    pytest.param("distance alarm 50", id="e-alarm-50"),
])
def test_tc_snr_23_commands_without_login(online, cmd):
    """TC-SNR-23 - Sonar commands without login"""
    log.info("Precondition: Wi-Fi is up, no session (`logout`; W211 is fine)")
    online.logout()
    log.info("Step: `%s`. Expected: E003, the command is not executed", cmd)
    resp = online.command(cmd)
    executed = resp.has(r"ping: echo|continuous pinging|calibrated|alarm at")
    log.info("Actual codes: %s, command executed: %s", resp.codes, executed)
    assert resp.has_code("E003"), resp
    assert not executed, f"the command was executed: {resp}"


# ---- DS-1 ------------------------------------------------------------------------------

@pytest.mark.parametrize("count", [
    pytest.param(0, id="a-N=0-min-1"),
    pytest.param(21, id="b-N=21-max+1"),
    pytest.param(25, id="c-N=25"),
    pytest.param(100, id="d-N=100"),
    pytest.param(1000, id="e-N=1000"),
])
def test_tc_snr_24_count_out_of_range(sonar, count):
    """TC-SNR-24 - Measurement count out of range"""
    log.info("Step 1: `distance %s`. Expected: `E704 count must be 1-20`, no measurements were made", count)
    resp = sonar.distance_raw(count)
    log.info("Actual codes: %s", resp.codes)
    assert resp.has_code("E704"), resp
    assert resp.has(r"count must be 1-20"), resp
    assert not resp.has(r"ping: echo|\d+/\d+: "), f"measurements were made: {resp}"
    log.info("Step 2: `distance` - the sensor works")
    assert sensor_works(sonar)


@pytest.mark.parametrize("arg", [
    pytest.param("abc", id="a-abc"),
    pytest.param("1.5", id="b-1.5"),
    pytest.param("-1", id="c-minus-1"),
])
def test_tc_snr_25_count_garbage(sonar, arg):
    """TC-SNR-25 - Garbage instead of the measurement count"""
    log.info("Step 1: `distance %s`. Expected: an E code (E703 or E704)", arg)
    resp = sonar.distance_raw(arg)
    log.info("Actual codes: %s", resp.codes)
    assert has_error(resp), resp
    assert sensor_works(sonar)


def test_tc_snr_26_unknown_subcommand(sonar):
    """TC-SNR-26 - Unknown subcommand"""
    log.info("Step: `distance foo`. Expected: E703 and a usage line listing all subcommands")
    resp = sonar.distance_raw("foo")
    log.info("Actual codes: %s", resp.codes)
    assert resp.has_code("E703"), resp
    assert resp.has(r"usage: distance \[N\]\|log \[ms\]\|stop\|calibrate <cm>\|reset\|alarm <cm>\|off\|filter on\|off\|stats\|history"), resp


# ---- DS-2 ------------------------------------------------------------------------------

@pytest.mark.parametrize("interval", [
    pytest.param(0, id="a-ms=0"),
    pytest.param(50, id="b-ms=50"),
    pytest.param(99, id="c-ms=99-min-1"),
    pytest.param(5001, id="d-ms=5001-max+1"),
    pytest.param(10000, id="e-ms=10000"),
])
def test_tc_snr_27_interval_out_of_range(sonar, interval):
    """TC-SNR-27 - `distance log` interval out of range"""
    log.info("Step 1: `distance log %s`. Expected: `E705 interval must be 100-5000 ms`", interval)
    resp = sonar.start_log(interval, wait=True)
    log.info("Actual codes: %s", resp.codes)
    assert resp.has_code("E705"), resp
    assert resp.has(r"interval must be 100-5000 ms"), resp
    log.info("Step 2: `distance stop` - must answer W710 (no stream was started)")
    assert sonar.stop_log().has_code("W710"), "a stream was started despite the error"


@pytest.mark.parametrize("arg", [
    pytest.param("abc", id="a-abc"),
    pytest.param("-100", id="b-minus-100"),
])
def test_tc_snr_28_interval_garbage(sonar, arg):
    """TC-SNR-28 - Garbage instead of the interval"""
    log.info("Step 1: `distance log %s`. Expected: an E code", arg)
    resp = sonar.start_log(arg, wait=True)
    log.info("Actual codes: %s", resp.codes)
    assert has_error(resp), resp
    log.info("Step 2: `distance stop` - must answer W710 (no stream was started)")
    assert sonar.stop_log().has_code("W710"), "a stream was started despite the error"


def test_tc_snr_29_stop_without_running(sonar):
    """TC-SNR-29 - `distance stop` with nothing running"""
    for attempt in (1, 2):
        log.info("Step %d: `distance stop`. Expected: `W710 measuring is not running`", attempt)
        resp = sonar.stop_log()
        assert resp.has_code("W710"), f"attempt {attempt}: {resp}"
        assert resp.has(r"measuring is not running"), f"attempt {attempt}: {resp}"


@pytest.mark.parametrize("cmd", [
    pytest.param("distance", id="a-distance"),
    pytest.param("distance 3", id="b-distance-3"),
    pytest.param("distance calibrate 50", id="c-calibrate-50"),
    pytest.param("distance alarm 50", id="d-alarm-50", marks=pytest.mark.xfail(strict=True, reason=BUG_SNR_03)),
])
def test_tc_snr_30_other_commands_while_logging(sonar, cmd):
    """TC-SNR-30 - Other commands while `distance log` runs"""
    log.info("Step 1: `distance log 200`; step 2: `%s`. Expected: `E711 measuring is running. Use 'distance stop'`", cmd)
    sonar.start_log(200)
    sonar.collect(0.6)
    resp = sonar.command(cmd, timeout=3)
    still_running = sonar.collect(1.0).has(r"ping: echo")
    log.info("Step 3: `distance stop`. Actual codes: %s, the stream keeps going: %s", resp.codes, still_running)
    sonar.stop_log()
    assert resp.has_code("E711"), resp
    assert resp.has(r"measuring is running\. Use 'distance stop'"), resp
    assert still_running, "the stream was interrupted by the rejected command"
    if "calibrate" in cmd:
        assert offset_unchanged(sonar), "offset changed by a rejected command"
    if "alarm" in cmd:
        assert sonar.stats().has(r"alarm off"), "threshold changed by a rejected command"


def test_tc_snr_31_second_log_while_logging(sonar):
    """TC-SNR-31 - (!) Second `distance log` while a stream is running"""
    log.info("Step 1: `distance log 500`; step 2: `distance log 200`; step 3: measure the period for 3 more seconds; "
             "step 4: `distance stop`")
    sonar.start_log(500)
    sonar.collect(0.8)
    resp = sonar.start_log(200, wait=True)
    gaps = sonar.collect(3.0).gaps(r"ping: echo")
    sonar.stop_log()
    log.info("Expected (observation, the PRD is silent): W709 and the period stays at 500 ms. Actual codes: %s, periods: %s",
             resp.codes, gaps)
    assert resp.has_code("W709"), resp
    assert resp.has(r"measuring already running"), resp
    assert gaps and all(g >= 500 for g in gaps), f"the running stream changed its interval: {gaps}"


# ---- DS-3 ------------------------------------------------------------------------------

@pytest.mark.parametrize("ref", [
    pytest.param(4, id="a-ref=4-min-1"),
    pytest.param(301, id="b-ref=301-max+1"),
    pytest.param(0, id="c-ref=0"),
    pytest.param(-5, id="d-ref=-5"),
    pytest.param(1000, id="e-ref=1000"),
])
def test_tc_snr_32_calibration_reference_out_of_range(sonar, ref):
    """TC-SNR-32 - Calibration reference outside 5-300"""
    log.info("Step 1: `distance calibrate %s`. Expected: `E706 usage: distance calibrate <ref 5-300 cm>`", ref)
    resp = sonar.calibrate_raw(ref)
    log.info("Actual codes: %s. Step 2: `distance stats` - the offset is unchanged", resp.codes)
    assert resp.has_code("E706"), resp
    assert resp.has(r"usage: distance calibrate <ref 5-300 cm>"), resp
    assert offset_unchanged(sonar), "offset changed by a rejected calibration"


@pytest.mark.parametrize("arg", [
    pytest.param("abc", id="a-abc"),
    pytest.param("", id="b-empty"),
])
def test_tc_snr_33_bad_calibration(sonar, arg):
    """TC-SNR-33 - Invalid calibration"""
    log.info("Step: `distance calibrate %s`. Expected: an E code, the offset is unchanged", arg or "(no argument)")
    resp = sonar.calibrate_raw(arg)
    log.info("Actual codes: %s", resp.codes)
    assert has_error(resp), resp
    assert offset_unchanged(sonar), "offset changed by a rejected calibration"


# ---- DS-4 ------------------------------------------------------------------------------

@pytest.mark.parametrize("threshold", [
    pytest.param(4, id="a-T=4-min-1"),
    pytest.param(301, id="b-T=301-max+1"),
    pytest.param(0, id="c-T=0"),
    pytest.param(-1, id="d-T=-1"),
    pytest.param(1000, id="e-T=1000"),
])
def test_tc_snr_34_alarm_threshold_out_of_range(sonar, threshold):
    """TC-SNR-34 - Alarm threshold outside 5-300"""
    log.info("Step 1: `distance alarm %s`. Expected: `E708 alarm must be 5-300 cm or 'off'`", threshold)
    resp = sonar.set_alarm(threshold)
    log.info("Actual codes: %s. Step 2: `distance stats` - the alarm stays off", resp.codes)
    assert resp.has_code("E708"), resp
    assert resp.has(r"alarm must be 5-300 cm or 'off'"), resp
    assert sonar.stats().has(r"alarm off|no measurements yet")


def test_tc_snr_35_alarm_threshold_not_numeric(sonar):
    """TC-SNR-35 - Non-numeric threshold"""
    log.info("Step: `distance alarm abc`. Expected: an E code, the alarm is unchanged")
    resp = sonar.set_alarm("abc")
    log.info("Actual codes: %s", resp.codes)
    assert has_error(resp), resp
    assert sonar.stats().has(r"alarm off|no measurements yet")


# ---- DS-5 ------------------------------------------------------------------------------

@pytest.mark.parametrize("arg", [
    pytest.param("maybe", id="a-maybe"),
    pytest.param("1", id="b-1"),
    pytest.param("ON ", id="c-ON-trailing-space"),
])
def test_tc_snr_36_filter_bad_argument(sonar, arg):
    """TC-SNR-36 - Filter: bad argument"""
    log.info("Step 1: `distance filter %s`. Expected: `E703 usage: distance filter on|off`", arg)
    resp = sonar.set_filter(arg)
    log.info("Actual codes: %s. Step 2: `distance stats` - the filter stays `median 5`", resp.codes)
    assert resp.has_code("E703"), resp
    assert resp.has(r"usage: distance filter on\|off"), resp
    assert sonar.stats().has(r"filter median 5|no measurements yet")


# ---- ST-3 ------------------------------------------------------------------------------

def test_tc_snr_37_distance_in_emergency(sonar, restore_session):
    """TC-SNR-37 - `distance` in EMERGENCY"""
    log.info("Steps 1-2: `state 3`, then `state 4` (EMERGENCY can only be entered from VERBOSE)")
    sonar.set_state(3)
    assert not sonar.set_state(4).codes, "could not enter EMERGENCY from VERBOSE"
    try:
        log.info("Step 3: `distance`. Expected: E005 (or E001), no measurement is made")
        resp = sonar.distance()
        log.info("Actual codes: %s", resp.codes)
        assert resp.has_code("E005") or resp.has_code("E001"), resp
        assert not resp.has(r"ping: echo"), resp
    finally:
        log.info("Step 4: EMERGENCY can only be left with `reboot`; restore Wi-Fi and login")
        assert sonar.reboot_and_wait()
        restore_session()
