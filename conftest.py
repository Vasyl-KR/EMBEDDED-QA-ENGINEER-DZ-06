import pytest

from drivers.device import DeviceDriver, find_port

TEST_LOGIN = "qauser"
TEST_PASSWORD = "qapass123"


@pytest.fixture(scope="session")
def port():
    p = find_port()
    if not p:
        pytest.skip("No SENTRY-C1 device found (VID autodetect found nothing)")
    return p


@pytest.fixture(scope="session")
def device(port):
    # Opening the serial connection is the expensive part, so it is done
    # once per test run (session scope), not once per test.
    dev = DeviceDriver(port)
    dev.open()
    yield dev
    dev.close()


@pytest.fixture
def logged_device(device):
    # Cheap, function-scoped: forces a known clean auth state before every
    # test that needs one, without reopening the serial connection.
    device.logout()
    assert device.login(TEST_LOGIN, TEST_PASSWORD), "Test setup: login failed"
    yield device
    device.logout()
