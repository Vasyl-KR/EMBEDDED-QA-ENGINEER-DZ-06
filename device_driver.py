"""Serial driver for the SENTRY-C1 UART CLI (ESP32-S3, 115200 8N1)."""

import re
import time

import serial
import serial.tools.list_ports

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mK]')

# USB-UART bridge chips seen on ESP32 dev boards used in this course:
# Silicon Labs CP210x (VID 0x10C4), and the FTDI FT232 (VID 0x0403) which
# is what my local SENTRY-C1 dev board actually enumerates as.
KNOWN_UART_BRIDGE_VIDS = {0x10C4, 0x0403}


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
        # (e.g. "Blink sequence done") and don't want to wait needlessly.
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                # ran out of time without ever seeing the pattern
                break
            raw = self._ser.readline()
            if not raw:
                # readline() timed out on its own with no new data - loop
                # again and let the outer `while` check the real deadline
                continue
            line = raw.decode('utf-8', errors='replace')
            line = ANSI_RE.sub('', line).strip('\r\n')
            if pattern in line:
                return True
        return False

    def login(self, login, password):
        self.send_command(f'register {login} {password}')
        response = self.send_command(f'login {login} {password}')
        return any('Session Started' in line for line in response)
