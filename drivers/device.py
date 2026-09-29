"""Serial driver for the Wi-Fi + BLE flashes (ESP32-S3, 115200 8N1).

All communication-protocol details (framing, ANSI stripping, timeouts,
command syntax) live here. Test files only call these methods - they
never touch the serial port or parse raw log lines themselves.
"""

import logging
import re
import time

import serial
import serial.tools.list_ports

log = logging.getLogger(__name__)

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mK]')

# USB-UART bridge chips seen on ESP32 dev boards used in this course:
# Silicon Labs CP210x (0x10C4), FTDI FT232 (0x0403), and WCH CH343
# (0x1A86) - the chip on the current local SENTRY-C1 board.
KNOWN_UART_BRIDGE_VIDS = {0x10C4, 0x0403, 0x1A86}

# The line each firmware prints once boot finishes and the CLI is ready
# to accept commands. Differs per firmware - reboot_and_wait() takes an
# optional override for firmwares other than SENTRY-C1.
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

    def wait_for_any(self, patterns, timeout):
        """Like wait_for, but for interactive flows that can branch:
        stops on the FIRST pattern seen and returns which one matched
        (or None on timeout). Needed because this device's CLI prompts
        don't always follow the same path - e.g. `connect` sometimes
        skips straight past the password prompt (see wifi_connect)."""
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
            for pattern in patterns:
                if pattern in line:
                    return pattern
        return None

    # ---- reboot ---------------------------------------------------------

    def reboot_and_wait(self, timeout=15, pattern=None):
        """Issues `reboot` and waits for the real boot-complete log line
        instead of a fixed time.sleep(), since boot time can vary.

        Writes the command directly instead of going through
        send_command(): the whole boot log streams out almost
        immediately, and send_command's own blocking read would consume
        (and discard) it before wait_for got a chance to see it.

        `pattern` overrides the default boot-ready line - needed because
        each firmware prints a different one (see BOOT_READY_PATTERN).
        """
        self._ser.write(b'reboot\r\n')
        return self.wait_for(pattern or BOOT_READY_PATTERN, timeout)

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

    # ---- Wi-Fi (station_WiFi firmware) ---------------------

    def wifi_scan(self):
        """Runs `scan` and returns the list of SSIDs seen.

        Writes the command directly instead of going through
        send_command(): scan takes a few seconds to enumerate networks
        (longer under the occasional CH343 slowdown seen on this rig),
        and send_command's own fixed 2s read window can cut the result
        list off before it fully arrives.
        """
        self._ser.write(b'scan\r\n')
        response = self.read_lines(10)
        return [m.group(1) for line in response if (m := re.search(r'SSID:\s*(\S+)', line))]

    def wifi_status(self):
        """Runs `status` and returns a dict: connected (bool), ssid, ip, rssi."""
        text = '\n'.join(self.send_command('status'))
        ssid = re.search(r'SSID:\s*(\S+)', text)
        ip = re.search(r'IP:\s*([\d.]+)', text)
        rssi = re.search(r'RSSI:\s*(-?\d+)\s*dBm', text)
        return {
            'connected': 'WiFi: connected' in text,
            'ssid': ssid.group(1) if ssid else None,
            'ip': ip.group(1) if ip else None,
            'rssi': int(rssi.group(1)) if rssi else None,
        }

    def wifi_disconnect(self, timeout=5):
        """Issues `disconnect` and waits for the radio-level confirmation
        line.
        """
        self._ser.write(b'disconnect\r\n')
        return self.wait_for('wifi station: disconnected', timeout)

    def wifi_connect(self, ssid, password, timeout=15):
        """Drives the interactive `connect` dialog: waits for the SSID
        prompt, sends `ssid` (empty string reuses the saved network -
        the device then skips the password prompt entirely and connects
        with the saved password), then - only if actually prompted for
        one - sends `password`. Returns True/False.
        """
        self._ser.write(b'connect\r\n')
        if not self.wait_for('Enter SSID', 10):
            log.warning("wifi_connect(%r): no 'Enter SSID' prompt within 10s", ssid)
            return False
        self._ser.write(f'{ssid}\r\n'.encode('utf-8'))

        outcome_patterns = [
            'successfully connected', 'connect to the AP fail',
            'password too short', 'connection timeout',
        ]

        if ssid:
            # A concrete SSID was given - the device may prompt for a
            # password, or it may skip straight past it (e.g. if the
            # typed SSID happens to match the saved one) and go directly
            # to an outcome. None means neither showed up in time.
            step = self.wait_for_any(['Enter password'] + outcome_patterns, 5)
            if step != 'Enter password':
                if step is None:
                    log.warning("wifi_connect(%r): no response after sending SSID within 5s", ssid)
                elif step != 'successfully connected':
                    log.warning("wifi_connect(%r): failed before a password was even needed - %r", ssid, step)
                return step == 'successfully connected'
            self._ser.write(f'{password}\r\n'.encode('utf-8'))

        result = self.wait_for_any(outcome_patterns, timeout)
        if result != 'successfully connected':
            reason = result or f'no outcome pattern seen within {timeout}s'
            log.warning("wifi_connect(%r): failed - %s", ssid, reason)
        return result == 'successfully connected'
