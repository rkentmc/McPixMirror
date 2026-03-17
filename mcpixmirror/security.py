"""Security guards: trusted-network check and device serial pinning.

Two independent gates must pass before any ADB connection is allowed:
  1. SSID guard  — the Mac must be on a known, trusted Wi-Fi network.
  2. Serial pin  — the discovered device serial must match the stored serial
                   (or no serial is stored yet, triggering a first-use prompt).

Neither gate is bypassed in any code path.
"""

from __future__ import annotations

import re
import subprocess

from mcpixmirror.config import cfg


class SecurityError(Exception):
    """Raised when a security check fails."""


# ------------------------------------------------------------------ #
# SSID guard                                                           #
# ------------------------------------------------------------------ #


def current_ssid() -> str:
    """Return the SSID of the current Wi-Fi network, or '' if not associated.

    Uses `networksetup -getairportnetwork en0` which is available on all
    macOS versions and requires no elevated permissions.
    """
    try:
        result = subprocess.run(
            ["networksetup", "-getairportnetwork", "en0"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Output format: "Current Wi-Fi Network: MyNetwork"
        # Or: "You are not associated with an AirPort network."
        match = re.search(r"Current Wi-Fi Network:\s*(.+)", result.stdout)
        if match:
            return match.group(1).strip()
        return ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def on_trusted_network() -> bool:
    """Return True only if the current SSID is in the known_ssids allowlist."""
    if not cfg.security.known_ssids:
        # No SSIDs configured yet — fail safe (deny all).
        return False
    ssid = current_ssid()
    return ssid in cfg.security.known_ssids


def assert_trusted_network() -> None:
    """Raise SecurityError if not on a trusted network."""
    if not on_trusted_network():
        ssid = current_ssid()
        if ssid:
            raise SecurityError(
                f"SSID '{ssid}' is not in the trusted list. "
                "Add it in Settings to enable ADB connections."
            )
        raise SecurityError(
            "Not connected to Wi-Fi or SSID unavailable. "
            "Connect to a trusted network first."
        )


# ------------------------------------------------------------------ #
# Serial pinning                                                       #
# ------------------------------------------------------------------ #


def is_known_serial(serial: str) -> bool:
    """Return True if serial matches the stored trusted serial."""
    stored = cfg.security.known_serial
    return bool(stored) and stored == serial


def first_use_serial_pin(serial: str, device_name: str) -> bool:
    """Prompt the user to trust a new device serial on first connection.

    Returns True if the user accepts (serial is saved), False otherwise.

    This is called once per lifetime of the installation when known_serial
    is empty. After the user confirms, the serial is persisted to config.
    """
    # Import here to avoid AppKit import at module level in tests.
    import rumps  # type: ignore[import]

    response = rumps.alert(
        title="Trust this device?",
        message=(
            f"McPixMirror wants to connect to:\n\n"
            f"  Device: {device_name}\n"
            f"  Serial: {serial}\n\n"
            "Once trusted, only this device will be allowed to connect. "
            "You can change this in Settings."
        ),
        ok="Trust Device",
        cancel="Cancel",
    )
    if response:  # rumps.alert returns 1 for OK, 0 for Cancel
        cfg.known_serial = serial  # also saves to disk
        return True
    return False


def assert_trusted_serial(serial: str, device_name: str) -> None:
    """Raise SecurityError if the serial is not trusted.

    On first use (no serial stored), triggers the trust prompt.
    """
    if not cfg.security.known_serial:
        # First-ever connection — prompt the user.
        if not first_use_serial_pin(serial, device_name):
            raise SecurityError("Device not trusted by user.")
        return

    if not is_known_serial(serial):
        raise SecurityError(
            f"Serial '{serial}' does not match the trusted device "
            f"('{cfg.security.known_serial}'). Connection refused."
        )
