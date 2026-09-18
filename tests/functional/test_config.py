"""Config persistence (PRD 9.2): only a saved config survives reboot.
The working copy always resets to compiled defaults on boot - `config
load` is required to pull the NVS-saved value back."""

import logging

import pytest

from conftest import TEST_LOGIN, TEST_PASSWORD

log = logging.getLogger(__name__)

DEFAULT_ALARM_THRESHOLD = 80
NEW_ALARM_THRESHOLD = 123


@pytest.mark.functional
@pytest.mark.xfail(
    reason=(
        "Firmware bug: `config save` reports 'Saved successfully', but after an "
        "actual device reboot `config load` still warns 'No saved config found in "
        "NVS' and loads defaults - the fake-NVS config does not actually survive "
        "reboot, contradicting PRD 16 ('Персистентність: Тільки конфігурація через "
        "config save' persists across reboot)."
    ),
    strict=True,
)
def test_config_persists_across_reboot(logged_device):
    dev = logged_device

    log.info("Setting alarm_threshold=%d and saving to (fake) NVS", NEW_ALARM_THRESHOLD)
    dev.set_config("alarm_threshold", NEW_ALARM_THRESHOLD)
    save_response = dev.save_config()
    assert any("Saved successfully" in line for line in save_response), \
        "config save did not confirm success"
    log.info("config save confirmed success")

    log.info("Rebooting device and waiting for boot banner")
    assert dev.reboot_and_wait(timeout=15), "device did not come back up after reboot"
    log.info("Device is back up")

    # logged_device's own login happened before the reboot and is now
    # stale (session is volatile) - log back in explicitly here.
    dev.logout()
    assert dev.login(TEST_LOGIN, TEST_PASSWORD), "could not log back in after reboot"
    log.info("Logged back in after reboot")

    # The working copy is NOT auto-loaded from NVS on boot - it resets
    # to the compiled default until `config load` is called explicitly.
    working_value = dev.get_config("alarm_threshold")
    log.info("Working config value right after boot (before 'config load'): %s", working_value)
    assert working_value == DEFAULT_ALARM_THRESHOLD

    log.info("Calling 'config load' to pull the saved value back")
    load_response = dev.load_config()
    assert not any("WARNING" in line for line in load_response), \
        "config load should not warn - a config save happened before reboot"

    loaded_value = dev.get_config("alarm_threshold")
    log.info("Config value after 'config load': %s (expected %d)", loaded_value, NEW_ALARM_THRESHOLD)
    assert loaded_value == NEW_ALARM_THRESHOLD
