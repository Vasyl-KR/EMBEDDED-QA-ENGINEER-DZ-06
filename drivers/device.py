"""Serial driver for SENTRY SWM-2 (fw_7, ESP32-S3, UART 115200 8N1).

All protocol details (framing, ANSI/log-prefix stripping, error codes,
background telemetry noise, boot-ready pattern) live here. Test files only
call these methods and look at `Response` objects - they never touch the
serial port or parse raw log lines themselves.
"""

import logging
import re
import time
from dataclasses import dataclass, field

import serial
import serial.tools.list_ports

log = logging.getLogger(__name__)

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# ESP-IDF log prefix, e.g. "I (12345) sentry: " - stripped so tests match the message itself.
LOG_PREFIX_RE = re.compile(r"^[IWEDV] \(\d+\) [\w.-]+:\s*")
TAG_RE = re.compile(r"^[IWEDV] \(\d+\) ([\w.-]+):")
# PRD error / warning codes: E704, W303 ... (the "E (123)" log prefix has a space, so it never matches).
CODE_RE = re.compile(r"\b([EW]\d{3})\b")

# PRD section 0: periodic simulator / background telemetry is informational noise, not command output.
NOISE_TAGS = ("[NAV]", "[ACU]", "[PWR]", "[HW]")
# Unsolicited link notices that can show up in the middle of any command's output.
NOISE_PATTERNS = ("fleet network reachable", "synced via NTP", "Certificate validated")

# USB-UART bridge chips seen on ESP32 dev boards in this course:
# Silicon Labs CP210x (0x10C4), FTDI FT232 (0x0403), WCH CH343 (0x1A86).
KNOWN_UART_BRIDGE_VIDS = {0x10C4, 0x0403, 0x1A86}

# SENTRY Guard defaults (PRD section 10): PIN 1234, zone 50 cm; GUARD_TEST_PIN is the PIN the PIN-change tests use.
GUARD_DEFAULT_PIN = "1234"
GUARD_TEST_PIN = "4321"
GUARD_DEFAULT_ZONE = 50

# Printed once boot finishes and the CLI accepts commands (fw_7 README: "ready. state 1 NORMAL (patrol)").
BOOT_READY_PATTERN = "ready. state 1 NORMAL"


def find_port():
    """Device name of the first COM port that looks like an ESP32 dev board's
    USB-UART bridge (by VID or 'CP210' in the description), or None.

    Filtering by VID (instead of grabbing the first port) matters as soon as
    another serial device is plugged in. The port is never hardcoded.
    """
    for p in serial.tools.list_ports.comports():
        if p.vid in KNOWN_UART_BRIDGE_VIDS or "cp210" in (p.description or "").lower():
            return p.device
    return None


def mask_secrets(cmd):
    """Command text for logs: account passwords and PINs never reach the log / HTML report."""
    parts = cmd.split()
    if not parts:
        return cmd
    head = parts[0].lower()
    if head in ("register", "login") and len(parts) >= 3:
        return f"{parts[0]} {parts[1]} ***"
    if head in ("passwd", "sudo"):
        return f"{parts[0]} ***"
    if head == "guard" and len(parts) > 1 and parts[1].lower() == "pin":
        return "guard pin *** ***"
    if head == "guard" and len(parts) > 2 and parts[1].lower() == "disarm":
        return "guard disarm ***"
    return cmd


def is_noise(line):
    """Background telemetry / unsolicited notices / ESP-IDF internals - not an answer to a command.
    Answers come from the `sentry` log tag (or are prefix-less prompts and help text)."""
    tag = TAG_RE.match(line)
    if tag and tag.group(1) != "sentry":
        return True
    msg = LOG_PREFIX_RE.sub("", line)
    return any(t in msg for t in NOISE_TAGS) or any(p in msg for p in NOISE_PATTERNS)


def parse_version(text):
    """'2.3.0' / 'v2.3.0' -> (2, 3, 0)."""
    return tuple(int(x) for x in re.search(r"(\d+)\.(\d+)\.(\d+)", text).groups())


@dataclass
class Response:
    """Everything the device printed after one command."""

    command: str
    raw: list = field(default_factory=list)

    @property
    def lines(self):
        """Output lines without the echoed command and without background telemetry."""
        out = []
        for line in self.raw:
            msg = LOG_PREFIX_RE.sub("", line)
            if msg.strip() == self.command.strip() or is_noise(line):
                continue
            out.append(msg)
        return out

    @property
    def text(self):
        return "\n".join(self.lines)

    @property
    def codes(self):
        """PRD codes seen in the output, in order: ['E704', ...]."""
        return CODE_RE.findall(self.text)

    def stamps(self, pattern):
        """Device timestamps (ms, from the 'I (12345) tag:' log prefix) of the
        lines matching `pattern` - for timing checks without wall-clock sleeps."""
        out = []
        for line in self.raw:
            m = re.match(r"^[IWEDV] \((\d+)\)", line)
            if m and re.search(pattern, line):
                out.append(int(m.group(1)))
        return out

    def gaps(self, pattern):
        """Differences (ms) between consecutive matching lines."""
        t = self.stamps(pattern)
        return [b - a for a, b in zip(t, t[1:])]

    def has(self, pattern):
        return re.search(pattern, self.text) is not None

    def has_raw(self, pattern):
        """Search ALL printed lines (prefix-stripped), including ESP-IDF internals that `.text` filters out
        (e.g. the boot banner `App version: 2.1.0`)."""
        return any(re.search(pattern, LOG_PREFIX_RE.sub("", line)) for line in self.raw)

    def find(self, pattern):
        return re.search(pattern, self.text)

    def has_code(self, code):
        return code in self.codes

    def __str__(self):
        return f"{mask_secrets(self.command)!r} -> {self.lines}"


@dataclass
class OtaRun:
    """Result of one flashing OTA command: the process log, the boot log after the reboot, and whether it booted."""

    process: Response
    boot: Response = None
    booted: bool = False

    @property
    def succeeded(self):
        return self.process.has(r"success:")

    def progress(self):
        """Progress percentages printed during the download, in order."""
        return [int(x) for x in re.findall(r"(\d+)%", self.process.text)]


class DeviceDriver:
    def __init__(self, port):
        self.port = port
        self._ser = None

    # ---- connection ---------------------------------------------------

    def open(self):
        # Short per-read timeout: lets command() detect "device went quiet"
        # instead of blocking for seconds inside readline().
        self._ser = serial.Serial(
            port=self.port,
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
        )
        self._ser.reset_input_buffer()

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()

    # ---- low-level protocol primitives ----------------------------------

    @staticmethod
    def _clean(raw):
        line = raw.decode("utf-8", errors="replace")
        return ANSI_RE.sub("", line).strip("\r\n").strip()

    def _write(self, text):
        self._ser.write(f"{text}\r\n".encode("utf-8"))

    def _read_line(self):
        raw = self._ser.readline()
        return self._clean(raw) if raw else None

    def sync(self):
        """Terminate whatever half-line the board may have received while the
        port was being opened (otherwise the first command can come back with
        W006 'non-latin characters ignored') and discard the reaction."""
        self._write("")
        self.drain(1.0)

    def drain(self, seconds=1.0):
        """Read and return everything printed during `seconds` (background logs, boot output)."""
        lines = []
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            line = self._read_line()
            if line:
                lines.append(line)
        return lines

    def command(self, cmd, timeout=5.0, quiet=0.8, until=None, first_wait=3.0, tail=0.0):
        """Send `cmd` and collect the output.

        The board echoes the command at once but prints the answer about a
        second later, and background notices can arrive in between - so the
        quiet period only starts after the first *real* answer line (not the
        echo, not telemetry noise). Stops when (a) the `until` regex is seen,
        (b) the device was quiet for `quiet` s after its answer, (c) no answer
        at all arrived within `first_wait` s, or (d) `timeout` expires. Slow
        commands (ping, connect, OTA) should pass `until=` and a bigger
        `timeout` / `first_wait`. `tail` keeps reading that many seconds after the `until` match (lines that
        follow the answer within milliseconds, e.g. the relay closing after `guard disarm`).
        """
        self._ser.reset_input_buffer()
        log.info("-> %s", mask_secrets(cmd))
        self._write(cmd)
        raw = []
        got_answer = False
        start = last = time.monotonic()
        matched_at = None
        while time.monotonic() - start < timeout:
            line = self._read_line()
            now = time.monotonic()
            if matched_at is not None and now - matched_at >= tail:
                break
            if line:
                raw.append(line)
                msg = LOG_PREFIX_RE.sub("", line)
                if msg.strip() != cmd.strip() and not is_noise(line):
                    got_answer = True
                    last = now
                    if until and matched_at is None and re.search(until, msg):
                        matched_at = now
                        if not tail:
                            break
            elif matched_at is None:
                if got_answer and not until and now - last >= quiet:
                    break
                if not got_answer and now - start >= first_wait and not until:
                    break
        resp = Response(cmd, raw)
        self._log_response(resp)
        return resp

    def _log_response(self, resp):
        """INFO: the answer without noise (what the tester reads); DEBUG: every raw line with ESP timestamps."""
        shown = mask_secrets(resp.command)
        lines = resp.lines
        if not lines:
            log.info("<- (no answer)")
        for line in lines:
            log.info("<- %s", mask_secrets(line) if line.strip() == resp.command.strip() else line)
        for raw in resp.raw:
            log.debug("   raw: %s", shown if raw.strip() == resp.command.strip() else raw)

    def send(self, cmd):
        """Write a command without reading the answer (reboot, long streams)."""
        self._ser.reset_input_buffer()
        log.info("-> %s (not waiting for the answer)", mask_secrets(cmd))
        self._write(cmd)

    def wait_for(self, pattern, timeout):
        """Read lines until the regex `pattern` shows up. Returns the matching
        (prefix-stripped) line, or None on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._read_line()
            if not line:
                continue
            msg = LOG_PREFIX_RE.sub("", line)
            if re.search(pattern, msg):
                log.info("<- %s  (waited for /%s/)", msg, pattern)
                return msg
        log.warning("did not see /%s/ within %s s", pattern, timeout)
        return None

    def wait_for_any(self, patterns, timeout):
        """Like wait_for for branching flows: returns the first pattern that
        matched (or None on timeout)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._read_line()
            if not line:
                continue
            msg = LOG_PREFIX_RE.sub("", line)
            for pattern in patterns:
                if re.search(pattern, msg):
                    return pattern
        return None

    def collect(self, seconds):
        """Lines (prefix-stripped, noise-free) printed during `seconds`, as a Response."""
        resp = Response("", self.drain(seconds))
        log.info("observing the output for %.1f s: %d lines", seconds, len(resp.lines))
        for line in resp.lines:
            log.info("<- %s", line)
        for raw in resp.raw:
            log.debug("   raw: %s", raw)
        return resp

    # ---- reboot ---------------------------------------------------------

    def reboot_and_wait(self, timeout=30):
        """`reboot` (3-2-1 countdown) and wait for the real boot-complete line
        instead of sleeping. Written directly so command()'s read does not
        swallow the boot log."""
        log.info("rebooting the board: reboot and waiting for `%s`", BOOT_READY_PATTERN)
        self.send("reboot")
        return self.wait_for(re.escape(BOOT_READY_PATTERN), timeout) is not None

    def capture_until(self, pattern, timeout):
        """Read everything printed until the regex `pattern` shows up (or `timeout`). Returns (Response, found).
        Used for flows where the board reboots and the whole boot log matters (OTA self-check, boot banner)."""
        raw = []
        found = False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._read_line()
            if not line:
                continue
            raw.append(line)
            if re.search(pattern, LOG_PREFIX_RE.sub("", line)):
                found = True
                break
        resp = Response("", raw)
        log.info("captured %d lines until /%s/ (%s)", len(raw), pattern, "found" if found else "NOT found")
        for line in resp.lines:
            log.info("<- %s", line)
        for line in raw:
            log.debug("   raw: %s", line)
        return resp, found

    def reboot_and_capture(self, timeout=60):
        """`reboot` and the whole boot log up to the boot-ready line: (Response, found)."""
        log.info("rebooting the board: reboot and capturing the boot log")
        self.send("reboot")
        return self.capture_until(re.escape(BOOT_READY_PATTERN), timeout)

    def wait_responsive(self, timeout=120):
        """Wait until the board answers `version` again (after a reboot, a failed OTA or a dropped download).
        Returns True when it answers within `timeout` s."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._write("")
            self.drain(1.0)
            if self.version()["fw"] is not None:
                return True
        log.warning("the board did not become responsive within %s s", timeout)
        return False

    # ---- system / version -----------------------------------------------

    def version(self):
        """`version` -> dict(fw=(2,1,0), partition='ota_0', address='0x20000', state='valid', response)."""
        resp = self.command("version", until=r"partition:.*state")
        fw = resp.find(r"fw v(\d+\.\d+\.\d+)")
        part = resp.find(r"partition:\s*(ota_\d)\s*@\s*(0x[0-9a-fA-F]+),\s*state:\s*([\w ]+)")
        return {
            "fw": parse_version(fw.group(1)) if fw else None,
            "partition": part.group(1) if part else None,
            "address": part.group(2) if part else None,
            "state": part.group(3).strip() if part else None,
            "response": resp,
        }

    def uptime_seconds(self):
        """`uptime` -> seconds (e.g. `uptime: 0h 57m 36s`), or None."""
        m = self.command("uptime").find(r"uptime:\s*(\d+)h\s*(\d+)m\s*(\d+)s")
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else None

    # ---- Wi-Fi / account ----------------------------------------------------

    def whoami(self):
        return self.command("whoami")

    def net(self):
        return self.command("net")

    def lamp(self, action):
        """`lamp on/off/toggle`."""
        return self.command(f"lamp {action}")

    def health_now(self):
        """`health now`: waits for the telemetry report line."""
        return self.command("health now", timeout=10, until=r"\[TELEMETRY")

    def is_logged_in(self):
        return self.whoami().has(r"user:\s*\S+")

    def connect_wifi(self, ssid, password, timeout=40):
        """Interactive `connect`: SSID prompt -> password prompt -> result.
        Returns True on success (`connected to '<ssid>'`), False otherwise."""
        self.send("connect")
        if not self.wait_for(r"(?i)SSID", 15):
            log.warning("connect_wifi: no SSID prompt")
            return False
        self._write(ssid)
        # E1xx is only meaningful AFTER the password was sent: stale E101 lines of an earlier failed
        # `reconnect` (the board retries in the background) must not be taken for the result of this attempt.
        step = self.wait_for_any([r"(?i)password", r"connected to '"], 10)
        if step == r"(?i)password":
            self._write(password)
            step = self.wait_for_any([r"connected to '", r"\bE1\d\d\b"], timeout)
        ok = step == r"connected to '"
        if not ok:
            log.warning("connect_wifi(%r): failed at step %r", ssid, step)
        else:
            self._settle_after_connect()
        return ok

    def _settle_after_connect(self):
        """After `connected to` the board still runs the internet check and NTP sync
        and does not answer commands meanwhile - wait for that to finish
        (`time: synced` or the NTP warning W106) instead of sleeping."""
        self.wait_for_any([r"time: synced", r"\bW106\b", r"\bE105\b"], 20)

    def ensure_online(self, ssid, password):
        """Wi-Fi up: nothing to do if it is; else `reconnect` to the saved network,
        else a full `connect` (the saved network can be gone after a firmware
        update - known OTA settings-reset bug - or after `forget`)."""
        if not self.net().has_code("E002"):
            return True
        # The very first `reconnect` after a firmware update was seen to fail with E101 (wrong password) although
        # the saved password was fine; a retry succeeds - so retry before falling back to a full `connect`.
        for attempt in (1, 2, 3):
            resp = self.command("reconnect", timeout=40, until=r"connected to '|\bE\d{3}\b")
            if resp.has(r"connected to '"):
                self._settle_after_connect()
                return True
            log.warning("reconnect attempt %d failed (%s)", attempt, resp.codes)
            self.drain(3.0)  # let the board finish its own background retries
        return self.connect_wifi(ssid, password)

    def ensure_logged_in(self, login, password):
        """Logged-in session; registers the profile first when it is missing
        (wiped by a firmware update); E202 'already registered' is fine."""
        if self.is_logged_in():
            return True
        self.register(login, password)
        self.login(login, password)
        return self.is_logged_in()

    def register(self, login, password):
        return self.command(f"register {login} {password}")

    def login(self, login, password):
        return self.command(f"login {login} {password}")

    def logout(self):
        return self.command("logout")

    def set_state(self, state):
        """`state <1-4|name>`."""
        return self.command(f"state {state}")

    # ---- OTA ------------------------------------------------------------------

    def ota_status(self):
        return self.command("ota status")

    def ota_check(self):
        return self.command("ota check", timeout=40, until=r"up to date|update available|running newer|\bE\d{3}\b")

    def ota_server(self, url=None):
        """`ota server` shows the update server, `ota server <url>` / `ota server default` changes it."""
        return self.command("ota server" if url is None else f"ota server {url}", timeout=10)

    def ota_update(self, channel=None):
        """`ota update [beta]` when NOTHING is expected to be flashed ('already up to date'): returns as soon as the
        board answers or starts downloading. Use ota_flash() for a real update."""
        cmd = "ota update" if channel is None else f"ota update {channel}"
        return self.command(cmd, timeout=40, until=r"already up to date|downloading|success:|\bE\d{3}\b")

    def ota_flash(self, cmd, timeout=240):
        """Run an OTA command that flashes a new image (`ota update beta`, `ota install X.Y.Z [force]`):
        collects the process log up to `success:` (or an error / 'already up to date'), then - after the
        board rebooted - the whole boot log up to the boot-ready line. Returns an OtaRun.
        After it the session is gone (reboot): restore Wi-Fi and login before the next command."""
        process = self.command(cmd, timeout=timeout, until=r"success:|already up to date|\bE\d{3}\b")
        boot, ready = None, False
        if process.has(r"success:"):
            boot, ready = self.capture_until(re.escape(BOOT_READY_PATTERN), 90)
        return OtaRun(process=process, boot=boot, booted=ready)

    # ---- Guard / alerts (2.3.0 only; E099 on 2.1.0) ---------------------------------

    def guard_status(self, cmd="guard status"):
        """`guard status`, or its short form `guard`."""
        return self.command(cmd, until=r"\[WATCH\] \w+, zone|\bE\d{3}\b", tail=0.4)

    def guard_state(self, cmd="guard status"):
        """`guard status` parsed: dict(state='disarmed|ARMED|INTRUSION|ALARM|...', zone=50, distance=88.4, response)."""
        resp = self.guard_status(cmd)
        m = resp.find(r"\[WATCH\] (" + r"\w+), zone (\d+) cm, last distance (-?[\d.]+) cm")
        if not m:
            return dict(state=None, zone=None, distance=None, response=resp)
        return dict(state=m.group(1), zone=int(m.group(2)), distance=float(m.group(3)), response=resp)

    def guard_zone(self, value=""):
        """`guard zone <value>` exactly as given (valid or not)."""
        return self.command(f"guard zone {value}".strip(), until=r"\[WATCH\] zone <|\bE\d{3}\b", tail=0.4)

    def guard_arm(self, wait_for=r"ARMED\.", timeout=15):
        """`guard arm`. By default waits for the end of the exit delay (`ARMED. Perimeter zone ...`) and returns
        everything printed meanwhile (the countdown with device timestamps). `wait_for=None` only reads the
        answer to the command (errors, `W801 guard already ARMED`); another pattern waits for that line instead."""
        if wait_for is None:
            return self.command("guard arm", until=r"\[WATCH\] arming|\bE\d{3}\b|\bW\d{3}\b", tail=0.4)
        self.send("guard arm")
        resp, _ = self.capture_until(wait_for, timeout)
        return resp

    def guard_disarm(self, pin):
        return self.command(f"guard disarm {pin}".strip(), until=r"disarmed \(|\bE\d{3}\b|\bW\d{3}\b", tail=0.6)

    def guard_panic(self):
        return self.command("guard panic", until=r"GENERAL ALARM|\bE\d{3}\b|\bW\d{3}\b", tail=0.8)

    def guard_pin(self, old, new):
        return self.command(f"guard pin {old} {new}".strip(), until=r"PIN changed|\bE\d{3}\b", tail=0.4)

    def guard_log(self):
        return self.command("guard log", timeout=8, quiet=1.0)

    @staticmethod
    def guard_events(resp):
        """`guard log` parsed: [(number, 'HH:MM:SS', 'text'), ...] in the order printed."""
        return [(int(n), stamp, text.strip())
                for n, stamp, text in re.findall(r"^(" + r"\d+)\.\s+([0-9-]{2}:[0-9-]{2}:[0-9-]{2})\s+(.+)$", resp.text, flags=re.M)]

    @staticmethod
    def attempts(resp):
        """N from `E803 wrong PIN. Attempts: N/3`, or None."""
        m = resp.find(r"Attempts: (" + r"\d+)/3")
        return int(m.group(1)) if m else None

    def guard_reset(self):
        """Known Guard state: disarmed, default PIN and zone, relay closed, NORMAL, no alerts. Used before / after
        every Guard test - a test may end in ARMED / ALARM, with a changed PIN or zone, in VERBOSE (CRITICAL alert)."""
        st = self.guard_state()
        if st["state"] not in (None, "disarmed"):
            resp = self.guard_disarm(GUARD_DEFAULT_PIN)
            if resp.has_code("E803"):  # a test left the test PIN
                self.guard_disarm(GUARD_TEST_PIN)
            if self.guard_state()["state"] not in (None, "disarmed"):  # still arming: finish the exit delay first
                self.drain(12.0)
                self.guard_disarm(GUARD_DEFAULT_PIN)
        if self.guard_pin(GUARD_DEFAULT_PIN, GUARD_DEFAULT_PIN).has_code("E803"):
            self.guard_pin(GUARD_TEST_PIN, GUARD_DEFAULT_PIN)
        if st["zone"] != GUARD_DEFAULT_ZONE:
            self.guard_zone(GUARD_DEFAULT_ZONE)
        if self.relay_state() != "closed":
            self.relay("off")
        if self.system_state() != 1:
            self.set_state(1)
        self.alert_ack_all()
        self.alert_clear()

    def alert_list(self):
        return self.command("alert list", until=r"\[CIC\] ", tail=0.8)

    @staticmethod
    def alerts(resp):
        """`alert list` parsed: (unacked_count, [dict(id, level, acked, source, text), ...])."""
        header = resp.find(r"(" + r"\d+) unacknowledged")
        rows = [dict(id=int(i), level=lvl, acked=star != "*", source=src, text=txt.strip())
                for i, lvl, star, src, txt in re.findall(
                    r"^#(" + r"\d+)\s+[0-9-]{2}:[0-9-]{2}:[0-9-]{2}\s+(INFO|WARNING|CRITICAL)\s+(\*?)\s*(\w+)\s+(.+)$", resp.text, flags=re.M)]
        return (int(header.group(1)) if header else 0), rows

    def alert_ack_all(self):
        return self.command("alert ack all", until=r"\[CIC\]|\b[EW]\d{3}\b", tail=0.3)

    def alert_clear(self):
        return self.command("alert clear", until=r"\[CIC\]|\b[EW]\d{3}\b", tail=0.3)

    # ---- relay / system state (used by Guard checks) ------------------------------

    def relay(self, action):
        """`relay on|off|toggle`."""
        return self.command(f"relay {action}", until=r"\[VALVE\]|\bE\d{3}\b|\bW\d{3}\b", tail=0.3)

    def relay_state(self):
        """'open' / 'closed' from `relay status` (the relay is called valve in the log), or None."""
        resp = self.command("relay status", until=r"\[VALVE\] (OPEN|closed)|\bE\d{3}\b", tail=0.2)
        m = resp.find(r"\[VALVE\] (OPEN|closed)")
        return m.group(1).lower() if m else None

    def system_state(self):
        """System state number (1 NORMAL, 2 DEBUG, 3 VERBOSE, 4 EMERGENCY) from `state`, or None."""
        resp = self.command("state", until=r"state: \d|\bE\d{3}\b", tail=0.2)
        m = resp.find(r"state: (" + r"\d)")
        return int(m.group(1)) if m else None

    # ---- active sonar (HC-SR04) ---------------------------------------------

    def distance(self, count=None, timeout=15):
        """One `distance` / `distance N` run; waits for the single ping line or the final average."""
        if count is None:
            # Alarm / collision lines come right AFTER the ping line, so wait for quiet, not for the ping.
            return self.command("distance", timeout=timeout)
        return self.command(f"distance {count}", timeout=timeout, until=r"\bE\d{3}\b|avg .* cm \(")

    def calibrate(self, ref_cm):
        """`distance calibrate <ref>`: the sensor reads `ref` afterwards (offset = ref - measured)."""
        return self.command(f"distance calibrate {ref_cm}", timeout=10, until=r"calibrated:|\bE\d{3}\b")

    @staticmethod
    def events(resp):
        """Which sonar events one measurement produced: alarm / cleared / collision."""
        return {
            "alarm": resp.has(r"PROXIMITY ALARM"),
            "cleared": resp.has(r"proximity alarm cleared"),
            "collision": resp.has(r"\[COLLISION\] contact too close"),
        }

    def measure_at(self, ref_cm):
        """Make the sensor read `ref_cm` (calibration) and take one measurement; returns the events dict."""
        self.calibrate(ref_cm)
        return self.events(self.distance())

    def distance_raw(self, args):
        """`distance <args>` exactly as given - for negative tests with invalid input."""
        return self.command(f"distance {args}".strip())

    def calibrate_raw(self, arg):
        """`distance calibrate <arg>` exactly as given (invalid references)."""
        return self.command(f"distance calibrate {arg}".strip(), timeout=4.0)

    def calibrate_reset(self):
        """`distance calibrate reset` - the form written in PRD DS-3."""
        return self.command("distance calibrate reset")

    def reset_calibration(self):
        """`distance reset` - clears the calibration offset."""
        return self.command("distance reset")

    def set_alarm(self, threshold):
        """`distance alarm <cm>` (any value, valid or not)."""
        return self.command(f"distance alarm {threshold}")

    def alarm_off(self):
        return self.command("distance alarm off")

    def set_filter(self, state):
        """`distance filter <on/off/...>` (any value, valid or not)."""
        return self.command(f"distance filter {state}")

    def stats(self):
        return self.command("distance stats")

    def history(self):
        return self.command("distance history")

    def start_log(self, interval=None, wait=False):
        """`distance log [ms]`. Default: fire and forget (the stream keeps printing, read it with
        collect()); `wait=True` waits for the answer to the command itself (negative tests)."""
        cmd = "distance log" if interval is None else f"distance log {interval}"
        if wait:
            return self.command(cmd, timeout=3.0)
        self.send(cmd)
        return None

    def stop_log(self, wait=True):
        """`distance stop`. `wait=False` only sends it (the printed tail is read with collect())."""
        if wait:
            return self.command("distance stop")
        self.send("distance stop")
        return None

    def sonar_reset(self):
        """Known sonar state: no running log, alarm off, calibration reset, filter on."""
        self.command("distance stop", quiet=0.4)
        self.command("distance alarm off", quiet=0.4)
        self.command("distance reset", quiet=0.4)
        self.command("distance filter on", quiet=0.4)

    @staticmethod
    def echo_cm(resp):
        """Distance (cm) from the last `ping: echo X cm` line of a response, or None."""
        found = re.findall(r"ping: echo ([\d.]+) cm", resp.text)
        return float(found[-1]) if found else None
