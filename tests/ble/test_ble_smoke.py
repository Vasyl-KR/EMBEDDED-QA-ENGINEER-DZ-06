"""BLE + UART dual-channel smoke test for SENTRY-BLE (DZ-14 Part B).

Confirms hardware + radio + two observation channels work together:
writing the LED characteristic over BLE must be visible on the UART
log for both directions (PRD FR-G4). bleak is async - wrapped in
asyncio.run() per DZ-14's own suggestion, no extra pytest-asyncio
config needed for a single test.
"""

import asyncio
import logging

import pytest
from bleak import BleakClient, BleakScanner

log = logging.getLogger(__name__)

DEVICE_NAME = "SENTRY-BLE"
LED_CHAR_UUID = "00001525-1212-efde-1523-785feabcd123"
SCAN_TIMEOUT = 10
UART_LOG_TIMEOUT = 5

async def _run_dual_channel_led_test(device):
    log.info("Scanning for BLE device %r", DEVICE_NAME)
    ble_device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=SCAN_TIMEOUT)
    assert ble_device is not None, f"{DEVICE_NAME} not found in BLE scan"

    async with BleakClient(ble_device) as client:
        log.info("Connected to %s over BLE", DEVICE_NAME)

        log.info("Writing 0x01 to the LED characteristic")
        await client.write_gatt_char(LED_CHAR_UUID, bytearray([0x01]), response=True)
        assert device.wait_for("LED ON!", UART_LOG_TIMEOUT), \
            "UART log did not show 'LED ON!' after the BLE write"

        # FOR DEBUGGING: Hold here so a human watching the board can actually see the LED
        # lit - the UART assert above already proved it turned on; this
        # pause is only for manual/visual confirmation, not test logic.
        #log.debug("Holding LED on for %.1fs for manual visual check", 1.5)
        #await asyncio.sleep(1.5)

        log.info("Writing 0x00 to the LED characteristic")
        await client.write_gatt_char(LED_CHAR_UUID, bytearray([0x00]), response=True)
        assert device.wait_for("LED OFF!", UART_LOG_TIMEOUT), \
            "UART log did not show 'LED OFF!' after the BLE write"

    log.info("Disconnected")


@pytest.mark.ble
def test_ble_led_dual_channel(device):
    asyncio.run(_run_dual_channel_led_test(device))
