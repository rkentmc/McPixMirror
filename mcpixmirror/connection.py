"""ADB connection state machine.

Manages connecting and disconnecting to a single Android device via ADB
over TCP/IP (Wireless Debugging). Handles the mDNS double-entry problem
that causes scrcpy to error with "Multiple ADB devices."

The fix for the double-entry:
  After `adb connect IP:PORT` succeeds, disconnect the mDNS transport
  (identified by service_name) from the ADB server so that `adb devices`
  shows exactly one TCP/IP entry.

States:
  DISCONNECTED -> CONNECTING -> CONNECTED -> DISCONNECTING -> DISCONNECTED
"""

from __future__ import annotations

import subprocess
from enum import Enum, auto

from mcpixmirror.config import cfg
from mcpixmirror.discovery import DeviceInfo
from mcpixmirror.security import SecurityError, assert_trusted_network, assert_trusted_serial


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    DISCONNECTING = auto()


class ConnectionError(Exception):
    """Raised when an ADB operation fails."""


def _adb(*args: str, timeout: int = 10) -> str:
    """Run an adb command and return stdout. Raises ConnectionError on failure."""
    cmd = [cfg.adb_bin, *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise ConnectionError(
                f"adb {' '.join(args)} failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        return result.stdout.strip()
    except subprocess.TimeoutExpired as e:
        raise ConnectionError(f"adb {' '.join(args)} timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise ConnectionError(
            f"adb not found at {cfg.adb_bin!r}. "
            "Install with: brew install android-platform-tools"
        ) from e


class AdbConnection:
    """Manages a single ADB-over-Wi-Fi connection lifecycle."""

    def __init__(self) -> None:
        self._state = ConnectionState.DISCONNECTED
        self._device: DeviceInfo | None = None

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def device(self) -> DeviceInfo | None:
        return self._device

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    @property
    def serial(self) -> str:
        """Return the serial of the connected device, or ''."""
        return self._device.serial if self._device else ""

    @property
    def address(self) -> str:
        """Return 'IP:PORT' of the connected device, or ''."""
        if self._device:
            return f"{self._device.ip}:{self._device.port}"
        return ""

    def connect(self, device: DeviceInfo) -> None:
        """Connect to device. Raises SecurityError or ConnectionError on failure.

        Steps:
          1. Assert trusted network (SSID guard).
          2. Assert trusted serial (serial pin + first-use prompt).
          3. Disconnect any stale mDNS transport for this device.
          4. Connect by explicit IP:PORT.
          5. Verify serial post-connection (defence in depth).
        """
        if self._state == ConnectionState.CONNECTED:
            if self._device and self._device.serial == device.serial:
                return  # already connected to this device
            self.disconnect()

        self._state = ConnectionState.CONNECTING
        try:
            # Gate 1: trusted network
            assert_trusted_network()

            # Gate 2: trusted serial (prompts on first use)
            assert_trusted_serial(device.serial, device.name)

            # Remove the mDNS transport entry from the ADB server to prevent
            # the "Multiple (2) ADB devices" error in scrcpy.
            self._disconnect_mdns_transport(device.service_name)

            # Connect by explicit IP:PORT
            address = f"{device.ip}:{device.port}"
            out = _adb("connect", address)

            # ADB prints "connected to IP:PORT" or "already connected to IP:PORT"
            if "connected to" not in out.lower():
                raise ConnectionError(f"Unexpected adb connect output: {out!r}")

            # Verify: the device at this address must report the expected serial.
            # This guards against MITM or accidentally connecting to the wrong device.
            # get-serialno returns IP:PORT over TCP/IP; use getprop instead
            actual_serial = _adb("-s", address, "shell", "getprop", "ro.serialno")
            if actual_serial != device.serial:
                _adb("disconnect", address)
                raise SecurityError(
                    f"Serial mismatch after connect: expected '{device.serial}', "
                    f"got '{actual_serial}'. Connection refused."
                )

            self._device = device
            self._state = ConnectionState.CONNECTED

        except (SecurityError, ConnectionError):
            self._state = ConnectionState.DISCONNECTED
            raise

    def disconnect(self) -> None:
        """Disconnect the current ADB session. Safe to call when already disconnected."""
        if self._state == ConnectionState.DISCONNECTED:
            return

        self._state = ConnectionState.DISCONNECTING
        if self._device:
            address = f"{self._device.ip}:{self._device.port}"
            try:
                _adb("disconnect", address)
            except ConnectionError:
                pass  # best-effort; device may already be gone
        self._device = None
        self._state = ConnectionState.DISCONNECTED

    def disconnect_all(self) -> None:
        """Disconnect all TCP/IP ADB sessions. Used when leaving a trusted network."""
        self._state = ConnectionState.DISCONNECTING
        try:
            _adb("disconnect")  # disconnects all TCP/IP transports
        except ConnectionError:
            pass
        self._device = None
        self._state = ConnectionState.DISCONNECTED

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _disconnect_mdns_transport(self, service_name: str) -> None:
        """Tell the ADB server to drop the mDNS-registered transport.

        The ADB server tracks the mDNS service name as a separate transport
        from the explicit IP:PORT connection. Disconnecting it prevents scrcpy
        from seeing two entries for the same physical device.

        Failure is intentionally swallowed — the mDNS entry may not exist
        yet if this is the first connection attempt.
        """
        try:
            _adb("disconnect", service_name)
        except ConnectionError:
            pass
