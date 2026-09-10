"""Automated reproductions of two SENTRY-C1 firmware bugs.

Run directly (not via pytest): `python test_bugs.py`
"""

import time

from device_driver import DeviceDriver, find_port

LOGIN = "qauser"
PASSWORD = "qapass123"


def test_sensor_history_missing_entries():
    """`sensor history` must keep the last 10 readings once more than 10
    have been collected (PRD 7.3: 10-slot ring buffer)."""
    port = find_port()
    assert port, "No COM port found - is the device connected?"

    print(f"\n[Test 1] Using port {port}")
    with DeviceDriver(port) as dev:
        dev.send_command("logout")  # clear any leftover session from a previous run
        assert dev.login(LOGIN, PASSWORD), "Login failed, cannot proceed"

        dev.send_command("sensor start")
        time.sleep(28)  # default sensor_interval=3000ms -> >8 readings needs ~24-27s
        dev.send_command("sensor stop")

        response = dev.send_command("sensor history")
        lines = [l for l in response if "[Sensor]" in l and "] temp:" in l]

        print(f"[Test 1] sensor history returned {len(lines)} entries:")
        for l in lines:
            print(f"    {l}")

        assert len(lines) == 10, f"Expected 10 entries in sensor history, got {len(lines)}"


def test_login_lockout_blocks_correct_password():
    """Bug/behavior: after 3 failed login attempts the account should lock
    for 30s, and a correct-password attempt during that window must still
    be rejected as 'locked', not accepted."""
    port = find_port()
    assert port, "No COM port found - is the device connected?"

    print(f"\n[Test 2] Using port {port}")
    with DeviceDriver(port) as dev:
        dev.send_command("logout")  # clear any leftover session from a previous run
        dev.send_command(f"register {LOGIN} {PASSWORD}")

        for attempt in range(1, 4):
            response = dev.send_command(f"login {LOGIN} wrongpass")
            print(f"[Test 2] Attempt {attempt}: {response}")

        response = dev.send_command(f"login {LOGIN} {PASSWORD}")
        print(f"[Test 2] Correct-password attempt during lock: {response}")

        text = " ".join(response).lower()
        is_locked = "locked" in text
        session_started = any("Session Started" in l for l in response)

        assert is_locked, "Expected 'locked' message after 3 failed attempts"
        assert not session_started, "Session must not start while account is locked"


if __name__ == "__main__":
    tests = [test_sensor_history_missing_entries, test_login_lockout_blocks_correct_password]
    results = []
    for test in tests:
        try:
            test()
            results.append((test.__name__, "PASS"))
        except AssertionError as e:
            results.append((test.__name__, f"FAIL: {e}"))
        except Exception as e:
            results.append((test.__name__, f"ERROR: {e}"))

    print("\n=== Summary ===")
    for name, result in results:
        print(f"{name}: {result}")
