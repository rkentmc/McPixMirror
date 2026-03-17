"""Security guards: trusted-network check and device serial pinning.

Two independent gates must pass before any ADB connection is allowed:
  1. Network guard — the Mac must be on a trusted network, identified by
                     the default gateway's MAC address (ARP). This works
                     on all macOS versions without location permission.
                     Falls back to SSID check (known_ssids) if gateway
                     MAC is not yet stored.
  2. Serial pin   — the discovered device serial must match the stored serial
                     (or no serial is stored yet, triggering a first-use prompt).

Neither gate is bypassed in any code path.

Why gateway MAC instead of SSID?
  macOS 13+ requires Location Services permission to read the Wi-Fi SSID
  via networksetup or CoreWLAN, and Terminal does not appear in Location
  Services until it explicitly requests location access. The router's MAC
  address is readable via ARP without any special permissions, is unique
  to the physical router, and is harder to spoof than an SSID.
"""

from __future__ import annotations

import re
import subprocess

from mcpixmirror.config import cfg


class SecurityError(Exception):
    """Raised when a security check fails."""


# ------------------------------------------------------------------ #
# Gateway MAC detection                                               #
# ------------------------------------------------------------------ #


def gateway_mac() -> str:
    """Return the MAC address of the default gateway, or '' on failure.

    Steps:
      1. `route get default` → parse the gateway IP
      2. `arp -n <gateway-ip>` → parse the MAC address

    No elevated permissions or location access required.
    """
    try:
        route = subprocess.run(
            ["route", "get", "default"],
            capture_output=True, text=True, timeout=5,
        )
        match = re.search(r"gateway:\s*(\S+)", route.stdout)
        if not match:
            return ""
        gw_ip = match.group(1)

        arp = subprocess.run(
            ["arp", "-n", gw_ip],
            capture_output=True, text=True, timeout=5,
        )
        mac_match = re.search(r"(?:ether|at)\s+([0-9a-f:]{17})", arp.stdout)
        return mac_match.group(1) if mac_match else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


# ------------------------------------------------------------------ #
# Network trust check                                                  #
# ------------------------------------------------------------------ #


def on_trusted_network() -> bool:
    """Return True if the current network is trusted.

    Trust is established by gateway MAC address stored in known_gateway_macs.
    Falls back to known_ssids list if no MACs are configured yet (first-run).
    """
    known_macs = cfg.security.known_gateway_macs

    if known_macs:
        mac = gateway_mac()
        return bool(mac) and mac in known_macs

    # Legacy / first-run fallback: SSID-based check
    if cfg.security.known_ssids:
        ssid = _current_ssid()
        return bool(ssid) and ssid in cfg.security.known_ssids

    # Nothing configured yet — fail safe
    return False


def assert_trusted_network() -> None:
    """Raise SecurityError if not on a trusted network."""
    if not on_trusted_network():
        raise SecurityError(
            "Not on a trusted network. "
            "Connect to your home network and ensure it is added in Settings."
        )


def _current_ssid() -> str:
    """Best-effort SSID read via networksetup (may return '' on macOS 13+)."""
    try:
        result = subprocess.run(
            ["networksetup", "-getairportnetwork", "en0"],
            capture_output=True, text=True, timeout=5,
        )
        match = re.search(r"Current Wi-Fi Network:\s*(.+)", result.stdout)
        return match.group(1).strip() if match else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


# ------------------------------------------------------------------ #
# First-use: learn the current network                                #
# ------------------------------------------------------------------ #


def learn_current_network() -> str:
    """Record the current gateway MAC as trusted. Returns the MAC or ''.

    Called once when the user clicks "Trust Network" in the app.
    """
    mac = gateway_mac()
    if not mac:
        return ""
    macs = cfg.security.known_gateway_macs
    if mac not in macs:
        macs.append(mac)
        cfg.save()
    return mac


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
    """
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
    if response:
        cfg.known_serial = serial
        return True
    return False


def assert_trusted_serial(serial: str, device_name: str) -> None:
    """Raise SecurityError if the serial is not trusted.

    On first use (no serial stored), triggers the trust prompt.
    """
    if not cfg.security.known_serial:
        if not first_use_serial_pin(serial, device_name):
            raise SecurityError("Device not trusted by user.")
        return

    if not is_known_serial(serial):
        raise SecurityError(
            f"Serial '{serial}' does not match the trusted device "
            f"('{cfg.security.known_serial}'). Connection refused."
        )
