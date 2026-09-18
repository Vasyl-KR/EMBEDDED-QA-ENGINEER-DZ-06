"""Alarm subsystem: value >= threshold must trigger, below must not
(PRD 8.2). Parametrized across the below/at/above-threshold boundary."""

import logging
import time

import pytest

log = logging.getLogger(__name__)

THRESHOLD = 80


def _reset_alarm(dev):
    """Force a known DISARMED state regardless of the prior test's state."""
    dev.send_command("alarm clear")  # no-op with a warning unless TRIGGERED
    dev.send_command("alarm disarm")


@pytest.mark.functional
@pytest.mark.parametrize(
    "value, should_trigger",
    [
        pytest.param(THRESHOLD - 1, False, id="below-threshold"),
        pytest.param(THRESHOLD, True, id="at-threshold"),
        pytest.param(THRESHOLD + 70, True, id="above-threshold"),
    ],
)
def test_alarm_triggers_at_or_above_threshold(logged_device, value, should_trigger):
    dev = logged_device
    log.info("Case: value=%d, threshold=%d, expected trigger=%s", value, THRESHOLD, should_trigger)

    dev.set_config("alarm_threshold", THRESHOLD)
    dev.send_command("sensor start")
    _reset_alarm(dev)
    dev.send_command("alarm arm")
    log.info("Sensor started, alarm armed with threshold=%d", THRESHOLD)

    dev.send_command(f"sensor set {value}")
    log.info("Override value set to %d, waiting for the alarm task's 1s tick", value)
    time.sleep(1.5)  # alarm task checks the value once per second

    state = dev.get_alarm_status()
    log.info("Alarm state after check: %s", state)

    if should_trigger:
        assert state == "TRIGGERED", f"value={value} >= threshold={THRESHOLD} must trigger"
    else:
        assert state != "TRIGGERED", f"value={value} < threshold={THRESHOLD} must not trigger"

    _reset_alarm(dev)
    dev.send_command("sensor stop")
    log.info("Cleanup done: alarm reset, sensor stopped")
