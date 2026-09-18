"""Smoke tests: is the device alive at all? Minimal checks, run after
every reflash before the slower functional suite."""

import logging

import pytest

log = logging.getLogger(__name__)


@pytest.mark.smoke
def test_help_responds(device):
    log.info("Sending 'help', expecting a command list back")
    response = device.send_command("help")
    log.info("Got %d lines back", len(response))
    assert any("Commands" in line for line in response), \
        "device did not answer 'help' with a command list"
    log.info("help response contains a command list - device is alive")


@pytest.mark.smoke
def test_status_responds_when_logged_in(logged_device):
    log.info("Sending 'status' as a logged-in user")
    response = logged_device.send_command("status")
    log.info("status returned %d lines", len(response))
    assert response, "device gave no response to 'status'"


@pytest.mark.smoke
def test_device_survives_reboot(logged_device):
    log.info("Issuing reboot, waiting for boot banner (no time.sleep)")
    recovered = logged_device.reboot_and_wait(timeout=15)
    log.info("Device back up: %s", recovered)
    assert recovered, \
        "device did not come back up (boot banner not seen) after reboot"
