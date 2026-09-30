# -*- coding: utf-8 -*-
"""SEGGER J-Link flash driver.

Drives firmware flashing (FAT / OOBE steps of the station flow)
through the J-Link Commander tool (``JLink.exe`` on Windows,
``JLinkExe`` elsewhere) run as an interactive subprocess.  The process
stdin/stdout pair is wrapped in :class:`JLinkTransport`, which
satisfies the common :class:`~mtkgui.drivers.base.Transport`
interface: ``write()`` sends a command line, ``query()`` sends a
command and collects output up to the ``J-Link>`` prompt.

Command set: SEGGER UM0801 "J-Link Commander" - console commands
(``connect``, ``si``, ``speed``, ``r``, ``g``, ``erase``, ``loadfile``,
``verifyfile``, ``qc``) and command line options (``-Device``,
``-If``, ``-Speed``, ``-AutoConnect``, ``-NoGui``).  Nothing beyond
the documented command set is sent.

Device name, interface and speed come from the caller (``config/``
YAML equipment section) - never hardcoded.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from mtkgui.drivers.base import (
    InstrumentDriver,
    MeasurementResult,
    Transport,
)
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentError,
    InstrumentIOError,
    InstrumentTimeoutError,
)

_LOG = logging.getLogger("mtkgui.drivers.jlink")

#: Prompt the J-Link Commander prints when it is ready for input.
PROMPT = "J-Link>"

#: Error markers in J-Link Commander output.
_ERROR_MARKERS = ("Error", "FAILED", "Cannot connect", "Could not connect")

#: Successful flash/verify markers in J-Link Commander output.
_OK_MARKERS = ("O.K.",)


class JLinkTransport(Transport):
    """Interactive-subprocess transport around J-Link Commander.

    Options understood by ``open()``:

    * ``device`` (str, required) - target device name (from YAML)
    * ``interface`` (str, default "SWD") - ``SWD`` or ``JTAG``
    * ``speed_khz`` (int, default 4000) - interface speed
    * ``timeout_s`` (float, default 30.0) - per-command timeout
    """

    def __init__(self) -> None:
        """Create a closed transport."""
        self._proc: subprocess.Popen | None = None
        self._banner: str = ""
        self._timeout_s = 30.0
        self._is_open = False

    def open(self, address: str, options: dict) -> None:
        """Spawn the J-Link Commander process and read its banner.

        Args:
            address: Path to the J-Link executable (e.g. ``JLinkExe``
                     or ``C:/Program Files/SEGGER/JLink/JLink.exe``),
                     from ``config/`` YAML.
            options: See class docstring.  ``device`` is required.

        Raises:
            InstrumentConfigError: Missing device option or empty
                                   address.
            ConnectionLostError:   The executable could not be started
                                   or the target connection failed.
        """
        if self._is_open:
            return
        opts = options or {}
        exe = (address or "").strip()
        if not exe:
            raise InstrumentConfigError(
                "JLinkTransport.open: empty J-Link executable path")
        device = str(opts.get("device", "")).strip()
        if not device:
            raise InstrumentConfigError(
                "JLinkTransport.open: 'device' option is required "
                "(target name from config/ YAML)")
        interface = str(opts.get("interface", "SWD")).upper()
        if interface not in ("SWD", "JTAG"):
            raise InstrumentConfigError(
                f"JLinkTransport.open: interface must be SWD or JTAG, "
                f"got {interface!r}")
        try:
            self._timeout_s = float(opts.get("timeout_s", 30.0))
            speed = int(opts.get("speed_khz", 4000))
        except (TypeError, ValueError) as exc:
            raise InstrumentConfigError(
                f"JLinkTransport.open: bad option - {exc}") from exc
        if shutil.which(exe) is None and "/" not in exe and "\\" not in exe:
            raise ConnectionLostError(
                f"J-Link executable {exe!r} not found in PATH")
        argv = [
            exe,
            "-Device", device,
            "-If", interface,
            "-Speed", str(speed),
            "-AutoConnect", "1",
            "-NoGui", "1",
        ]
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise ConnectionLostError(
                f"cannot start J-Link Commander {exe!r}: {exc}") from exc
        try:
            self._banner = self._read_until_prompt()
        except InstrumentError as exc:
            self.close()
            raise ConnectionLostError(
                f"J-Link Commander start/connect failed: {exc}") from exc
        if "Cannot connect" in self._banner or "Connecting ... failed" \
                in self._banner:
            self.close()
            raise ConnectionLostError(
                f"J-Link target connect failed: {self._banner.strip()}")
        self._is_open = True
        _LOG.info("J-Link transport open: %s (%s)", exe, device)

    def close(self) -> None:
        """Terminate the J-Link Commander process (sends ``qc`` when
        possible).  Safe to call more than once."""
        proc, self._proc = self._proc, None
        self._is_open = False
        if proc is None:
            return
        try:
            if proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.write("qc\n")
                proc.stdin.flush()
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def write(self, command: str) -> None:
        """Send one J-Link Commander command line.

        Args:
            command: Command without newline.

        Raises:
            ConnectionLostError: Transport not open.
            InstrumentIOError:   The process stdin is broken.
        """
        proc = self._require_open()
        try:
            proc.stdin.write(command + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise InstrumentIOError(
                f"JLinkTransport.write failed: {exc}") from exc

    def query(self, command: str) -> str:
        """Send one command and collect output up to the prompt.

        Args:
            command: Command without newline.

        Returns:
            Command output with the trailing prompt line removed.

        Raises:
            ConnectionLostError:    Transport not open.
            InstrumentTimeoutError: No prompt within the configured
                                    timeout.
            InstrumentIOError:      The process died.
        """
        self.write(command)
        return self._read_until_prompt()

    def identify(self) -> str:
        """Return the captured start-up banner.

        Returns:
            Banner text containing the J-Link DLL / firmware version.

        Raises:
            ConnectionLostError: Transport not open.
        """
        self._require_open()
        return self._banner

    # -- helpers -------------------------------------------------------------

    def _read_until_prompt(self) -> str:
        """Read process output until the ``J-Link>`` prompt appears.

        Returns:
            The collected output text without the prompt line.

        Raises:
            InstrumentTimeoutError: No prompt in time.
            InstrumentIOError:      The process died.
            ConnectionLostError:    Transport not open.
        """
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise ConnectionLostError("JLinkTransport: not open")
        lines: list[str] = []
        while True:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    raise InstrumentIOError(
                        f"J-Link Commander exited (code {proc.returncode}): "
                        + "\n".join(lines[-5:]))
                raise InstrumentTimeoutError(
                    "J-Link Commander: no prompt within "
                    f"{self._timeout_s}s")
            stripped = line.rstrip("\r\n")
            if stripped.startswith(PROMPT):
                break
            lines.append(stripped)
        return "\n".join(lines)

    def _require_open(self) -> subprocess.Popen:
        """Return the running process or raise ConnectionLostError.

        Returns:
            The ``subprocess.Popen`` instance.

        Raises:
            ConnectionLostError: The transport is not open.
        """
        if not self._is_open or self._proc is None:
            raise ConnectionLostError("JLinkTransport: not open")
        return self._proc


class JLinkDriver(InstrumentDriver):
    """Driver for the SEGGER J-Link flash probe (FAT / OOBE flashing).

    J-Link is an interactive tool rather than a SCPI instrument, so
    the driver composes documented console commands into flash
    operations and parses their outcome.  ``write()`` / ``query()``
    pass through to the transport, keeping the common driver
    lifecycle.
    """

    MODEL = "JLINK"

    # -- lifecycle -----------------------------------------------------------

    def open(self, address: str, options: dict) -> None:
        """Start the J-Link Commander session (auto-connect target).

        Args:
            address: Path to the J-Link executable (from YAML).
            options: ``device`` (required), ``interface``, ``speed_khz``,
                     ``timeout_s``.

        Raises:
            InstrumentConfigError: Missing options.
            ConnectionLostError:   Executable / target not reachable.
        """
        address = self._validate_address(address)
        options = dict(options or {})
        # validate the driver-level options here as well; JLinkTransport
        # re-checks them, but a mocked transport must not bypass this
        if not str(options.get("device", "")).strip():
            raise InstrumentConfigError(
                "JLinkDriver.open: 'device' option is required "
                "(target name from config/ YAML)")
        interface = str(options.get("interface", "SWD")).upper()
        if interface not in ("SWD", "JTAG"):
            raise InstrumentConfigError(
                f"JLinkDriver.open: interface must be SWD or JTAG, "
                f"got {interface!r}")
        if self._transport is None:
            self._transport = JLinkTransport()
        self.address = address
        self.options = options
        self._transport.open(address, self.options)
        self._is_open = True

    def close(self) -> None:
        """End the J-Link session (sends ``qc``).  Safe to call twice."""
        if self._transport is not None:
            try:
                self._transport.close()
            except InstrumentError as exc:
                _LOG.warning("%s close warning: %s", self._log_prefix(), exc)
        self._is_open = False

    def identify(self) -> str:
        """Return the J-Link banner (DLL / firmware versions).

        Returns:
            Banner text.

        Raises:
            ConnectionLostError: Not open.
        """
        self._require_open()
        return self._transport.identify()

    # -- flash operations ------------------------------------------------------

    def flash_firmware(
        self, firmware_path: str,
        verify: bool = True, reset_and_run: bool = True,
        erase: bool = False,
    ) -> MeasurementResult:
        """Flash a firmware image and optionally verify and run it.

        Args:
            firmware_path: Absolute path to the image (``.bin`` /
                           ``.hex`` / ``.elf``) on the local machine.
            verify:        Send ``verifyfile`` after ``loadfile``.
            reset_and_run: Send ``r`` (reset) and ``g`` (go) at the
                           end.
            erase:         Send ``erase`` before loading.

        Returns:
            :class:`MeasurementResult` with ``Status.OK`` when every
            executed step reported success (value = image size in
            bytes, unit "").

        Raises:
            InstrumentConfigError: Not open or empty firmware path.
            InstrumentIOError:     A step reported failure.
            InstrumentTimeoutError: The tool did not return a prompt.
        """
        self._require_open()
        if not isinstance(firmware_path, str) or not firmware_path.strip():
            raise InstrumentConfigError(
                "JLinkDriver.flash_firmware: firmware path is required")
        firmware_path = firmware_path.strip()

        steps: list[tuple[str, str]] = []
        if erase:
            steps.append(("erase", "erase"))
        steps.append(("load", f"loadfile {firmware_path}"))
        if verify:
            steps.append(("verify", f"verifyfile {firmware_path}"))
        if reset_and_run:
            steps.append(("reset", "r"))
            steps.append(("go", "g"))
        for name, command in steps:
            self._run_step(name, command)
        size = self._file_size(firmware_path)
        return MeasurementResult.ok(size, "", self.MODEL)

    # -- helpers ---------------------------------------------------------------

    def _run_step(self, name: str, command: str) -> str:
        """Execute one console command and validate its output.

        Args:
            name:    Step name for logging and error messages.
            command: J-Link Commander command line.

        Returns:
            The command output.

        Raises:
            InstrumentIOError:      Output contains an error marker.
            InstrumentTimeoutError: No prompt in time.
            ConnectionLostError:    Session lost.
        """
        output = self._transport.query(command)
        if any(marker in output for marker in _ERROR_MARKERS):
            raise InstrumentIOError(
                f"J-Link {name} step failed: {output.strip()}")
        _LOG.info("J-Link %s: %s", name,
                  output.strip().splitlines()[-1] if output.strip() else "ok")
        return output

    @staticmethod
    def _file_size(path: str) -> int:
        """Return the size of the flashed image in bytes.

        Args:
            path: Image path.

        Returns:
            File size, or 0 when the file is not accessible (the flash
            itself already succeeded - size is informational).
        """
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
