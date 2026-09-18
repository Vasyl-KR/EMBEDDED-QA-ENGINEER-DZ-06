"""Serial driver for the SENTRY-C1 UART CLI (ESP32-S3, 115200 8N1).

All communication-protocol details (framing, ANSI stripping, timeouts,
command syntax) live here. Test files only call these methods - they
never touch the serial port or parse raw log lines themselves.
"""

import re
import time

import serial
import serial.tools.list_ports

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mK]')

# USB-UART bridge chips seen on ESP32 dev boards used in this course:
# Silicon Labs CP210x (0x10C4), FTDI FT232 (0x0403), and WCH CH343
# (0x1A86) - the chip on the current local SENTRY-C1 board.
KNOWN_UART_BRIDGE_VIDS = {0x10C4, 0x0403, 0x1A86}

# The line the firmware prints once boot finishes and the CLI is ready
# to accept commands (see AUTH: [Boot] in the real boot log).
BOOT_READY_PATTERN = "Device ready"


def find_port():
    """Return the device name of the first COM port that looks like an
    ESP32 dev board's USB-UART bridge (by VID or 'CP210' in the
    description), or None if none is connected.

    Filtering by VID/description (instead of just grabbing the first
    available port) matters once more than one serial device is plugged
    in - a random unrelated COM port must not be picked.
    """
    for p in serial.tools.list_ports.comports():
        if p.vid in KNOWN_UART_BRIDGE_VIDS or 'cp210' in p.description.lower():
            return p.device
    return None


class DeviceDriver:
    def __init__(self, port, timeout=2):
        self.port = port
        self.timeout = timeout
        self._ser = None

    def open(self):
        self._ser = serial.Serial(
            port=self.port,
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
        )
        # Drop whatever the device already queued up (boot log, stale data)
        self._ser.reset_input_buffer()

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()

    # __enter__/__exit__ make DeviceDriver usable as a context manager
    # (`with DeviceDriver(port) as dev:`) - __exit__ is called by Python
    # even if an exception happens inside the `with` block, so the port
    # always gets closed, without needing try/finally in every caller.
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ---- low-level protocol primitives -----------------------------

    def send_command(self, command):
        if not command.endswith('\r\n'):
            command += '\r\n'
        self._ser.write(command.encode('utf-8'))
        time.sleep(0.1)
        return self.read_lines(self.timeout)

    def read_lines(self, timeout):
        lines = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self._ser.readline()
            if not raw:
                # readline() hit its own per-call timeout with nothing new
                continue
            line = raw.decode('utf-8', errors='replace')
            line = ANSI_RE.sub('', line).strip('\r\n')
            if line:
                lines.append(line)
        return lines

    def wait_for(self, pattern, timeout):
        # Unlike read_lines (which always reads for the full timeout and
        # returns everything), wait_for stops early as soon as `pattern`
        # shows up - useful when we only care about one specific line
        # and don't want to wait needlessly.
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            raw = self._ser.readline()
            if not raw:
                continue
            line = raw.decode('utf-8', errors='replace')
            line = ANSI_RE.sub('', line).strip('\r\n')
            if pattern in line:
                return True
        return False

    def wait_for_pattern(self, pattern, timeout=10):
        """Same as wait_for - named for the reboot/boot-wait use case:
        `dev.wait_for_pattern("Device ready")` instead of a blind
        time.sleep() after issuing `reboot`."""
        return self.wait_for(pattern, timeout)

    # ---- auth ---------------------------------------------------------

    def login(self, login, password):
        self.send_command(f'register {login} {password}')
        response = self.send_command(f'login {login} {password}')
        return any('Session Started' in line for line in response)

    def logout(self):
        return self.send_command('logout')

    # ---- reboot ---------------------------------------------------------

    def reboot_and_wait(self, timeout=15):
        """Issues `reboot` and waits for the real boot-complete log line
        instead of a fixed time.sleep(), since boot time can vary.

        Writes the command directly instead of going through
        send_command(): the whole boot log streams out almost
        immediately, and send_command's own blocking read would consume
        (and discard) it before wait_for_pattern got a chance to see it.
        """
        self._ser.write(b'reboot\r\n')
        return self.wait_for_pattern(BOOT_READY_PATTERN, timeout)

    # ---- alarm ---------------------------------------------------------

    def get_alarm_status(self):
        """Returns the alarm state word (DISARMED/ARMED/TRIGGERED/CLEARED)
        parsed from `alarm status`, or None if it couldn't be found."""
        response = self.send_command('alarm status')
        for line in response:
            match = re.search(r'State:\s*(\S+)', line)
            if match:
                return match.group(1)
        return None

    # ---- config ---------------------------------------------------------

    def get_config(self, key):
        """Returns the integer value of a config key via `config get`."""
        response = self.send_command(f'config get {key}')
        for line in response:
            match = re.search(rf'{re.escape(key)}\s*=\s*(-?\d+)', line)
            if match:
                return int(match.group(1))
        return None

    def set_config(self, key, value):
        return self.send_command(f'config set {key} {value}')

    def save_config(self):
        return self.send_command('config save')

    def load_config(self):
        return self.send_command('config load')

    # ---- distance sensor ------------------------------------------------

    def get_distance_cm(self):
        """Single `distance` reading. Returns the calibrated distance in
        cm as a float, or None if the sensor reported a timeout."""
        response = self.send_command('distance')
        for line in response:
            if 'timeout' in line.lower():
                return None
            match = re.search(r'calibrated:\s*(-?\d+\.?\d*)\s*cm', line)
            if match:
                return float(match.group(1))
        return None
