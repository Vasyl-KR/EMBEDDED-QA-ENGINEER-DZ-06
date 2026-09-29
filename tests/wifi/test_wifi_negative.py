"""Negative Wi-Fi flows for station_WiFi (DZ-14 Part A). PRD refs:
FR-W2 (wrong password fails cleanly), FR-W3 (short password rejected
up front), FR-W7-adjacent (device survives a bad SSID)."""

import logging

import pytest

log = logging.getLogger(__name__)


@pytest.mark.wifi
def test_wrong_password(clean_wifi_after, wifi_credentials):
    ssid, _ = wifi_credentials
    log.info("Connecting to %s with a deliberately wrong password", ssid)
    ok = clean_wifi_after.wifi_connect(ssid, "definitely_wrong_pw")
    log.info("connect result: %s", ok)
    assert ok is False, "connect should fail with a wrong password"

    status = clean_wifi_after.wifi_status()
    log.info("Status after failed connect: %s", status)
    assert status["connected"] is False


@pytest.mark.wifi
def test_short_password(clean_wifi, wifi_credentials):
    ssid, _ = wifi_credentials
    log.info("Connecting to %s with a <8 char password", ssid)
    ok = clean_wifi.wifi_connect(ssid, "short")  # 5 chars, < 8
    log.info("connect result: %s", ok)
    assert ok is False, "connect should be rejected for a too-short password"

    # PRD FR-W3: rejected immediately, no connection attempt is made -
    # confirm the device is still responsive right after, not mid-retry.
    response = clean_wifi.send_command("help")
    assert any("Available commands" in line for line in response), \
        "device did not respond to 'help' right after the short-password rejection"


@pytest.mark.wifi
def test_nonexistent_ssid(clean_wifi_after):
    log.info("Connecting to a network that doesn't exist")
    ok = clean_wifi_after.wifi_connect("this-network-does-not-exist", "somepassword123")
    log.info("connect result: %s", ok)
    assert ok is False, "connect should fail for a nonexistent SSID"

    response = clean_wifi_after.send_command("help")
    assert any("Available commands" in line for line in response), \
        "device did not respond to 'help' after failing to find the SSID"
