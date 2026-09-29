"""Positive Wi-Fi flows for station_WiFi (DZ-14 Part A). PRD refs:
FR-W1 (scan), FR-W2 (connect), FR-W4 (saved creds survive reboot),
FR-W5 (status), FR-W6 (disconnect)."""

import logging
import re

import pytest

log = logging.getLogger(__name__)

BOOT_READY_PATTERN = "ready. Type 'help' for commands"


@pytest.mark.wifi
def test_scan_finds_networks(device, wifi_credentials):
    ssid, _ = wifi_credentials
    log.info("Scanning for Wi-Fi networks")
    networks = device.wifi_scan()
    log.info("Found %d networks: %s", len(networks), networks)
    assert networks, "scan returned no networks"
    log.info("Looking for test network %r in scan results", ssid)
    assert ssid in networks, f"test network {ssid!r} not found in scan results: {networks}"


@pytest.mark.wifi
def test_connect_success(clean_wifi, wifi_credentials):
    ssid, password = wifi_credentials
    log.info("Connecting to %s with valid credentials", ssid)
    assert clean_wifi.wifi_connect(ssid, password), "connect did not succeed"
    
    log.info("Checking status after connect")
    status = clean_wifi.wifi_status()
    log.info("Status after connect: %s", status)
    assert status["connected"] is True
    assert status["ssid"] == ssid
    assert re.match(r"\d+\.\d+\.\d+\.\d+", status["ip"] or ""), f"unexpected IP: {status['ip']!r}"


@pytest.mark.wifi
@pytest.mark.xfail(
    reason=(
        "Firmware bug: after `disconnect`, `status` still reports 'WiFi: connected' "
        "(with an empty SSID and IP 0.0.0.0) instead of 'WiFi: disconnected' - "
        "contradicts PRD FR-W5/FR-W6 (status must reflect the disconnected state)."
    ),
    strict=True,
)
def test_disconnect(clean_wifi, wifi_credentials):
    ssid, password = wifi_credentials
    assert clean_wifi.wifi_connect(ssid, password), "setup: connect failed"

    log.info("Disconnecting...")
    clean_wifi.wifi_disconnect()
    status = clean_wifi.wifi_status()
    log.info("Status after disconnect: %s", status)
    assert status["connected"] is False


@pytest.mark.wifi
def test_credentials_survive_reboot(clean_wifi, wifi_credentials):
    ssid, password = wifi_credentials
    log.info("Connecting with explicit credentials before reboot")
    assert clean_wifi.wifi_connect(ssid, password), "initial connect failed"

    log.info("Rebooting and waiting for the boot-ready line")
    assert clean_wifi.reboot_and_wait(timeout=15, pattern=BOOT_READY_PATTERN), \
        "device did not come back up after reboot"

    log.info("Reconnecting with empty SSID/password - should reuse saved credentials")
    assert clean_wifi.wifi_connect("", ""), "reconnect via saved credentials failed"

    status = clean_wifi.wifi_status()
    log.info("Status after saved-credentials reconnect: %s", status)
    assert status["connected"] is True
    assert status["ssid"] == ssid
