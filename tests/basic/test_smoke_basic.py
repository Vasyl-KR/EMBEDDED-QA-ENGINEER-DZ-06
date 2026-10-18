"""Bring-up smoke tests: they prove the framework talks to the board and the
basic access rules (AC-1, AC-2, AU-4, OTA-1) hold. Everything else builds on this.

Every test writes its steps and the expected / actual values to the log (`log.info`);
the driver adds every command and the board's answer - all of it goes to the HTML report."""

import logging

import pytest

log = logging.getLogger(__name__)


@pytest.mark.smoke
def test_version_reports_firmware_and_partition(device):
    """TC-OTA-01: `version` -> fw v<X.Y.Z> (build ...), partition ota_N @ address, state valid."""
    log.info("Step: `version`")
    info = device.version()
    log.info("Expected: firmware version, partition ota_0/ota_1 at 0x20000/0x1A0000, state valid. "
             "Actual: fw=%s, partition=%s @ %s, state=%s", info["fw"], info["partition"], info["address"], info["state"])
    assert info["fw"] is not None, info["response"]
    assert info["partition"] in ("ota_0", "ota_1"), info["response"]
    assert info["address"] in ("0x20000", "0x1A0000", "0x1a0000"), info["response"]
    assert info["state"] == "valid", info["response"]


@pytest.mark.smoke
def test_unknown_command_gets_e001(device):
    """TC-ACC-02: unknown command -> E001 unknown command '<x>'."""
    log.info("Step: `foobar`. Expected: `E001 unknown command 'foobar'. Type 'help'`")
    resp = device.command("foobar")
    log.info("Actual codes: %s", resp.codes)
    assert resp.has_code("E001"), resp
    assert resp.has(r"unknown command 'foobar'"), resp


@pytest.mark.smoke
def test_command_requiring_login_gets_e003_without_session(online):
    """TC-ACC-01: Wi-Fi up, no login -> a [login] command answers E003."""
    log.info("Precondition: Wi-Fi is up, no session (`logout`; W211 is fine)")
    online.logout()
    log.info("Step: `lamp on`. Expected: E003 (Wi-Fi and login are required)")
    resp = online.lamp("on")
    log.info("Actual codes: %s", resp.codes)
    assert resp.has_code("E003"), resp


@pytest.mark.smoke
def test_whoami_after_login(logged_in, account):
    """TC-AUT-02: `whoami` -> `user: <login>, access: user`."""
    log.info("Precondition: logged in. Step: `whoami`. Expected: `user: <login>, access: user`")
    resp = logged_in.whoami()
    login = account[0]  # the login name only - never the whole `account` tuple (it holds the password)
    assert resp.has(rf"user:\s*{login},\s*access:\s*user"), resp
