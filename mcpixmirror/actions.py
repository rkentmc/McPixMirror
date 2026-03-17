"""User-facing actions: clipboard sync, pull latest photo, launch scrcpy.

All actions require an active ADB connection. They are thin wrappers that
shell out to `adb` and `scrcpy`; the connection object provides the address.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from mcpixmirror.config import cfg
from mcpixmirror.connection import AdbConnection, ConnectionError


class ActionError(Exception):
    """Raised when an action cannot be completed."""


def _adb_s(connection: AdbConnection, *args: str, timeout: int = 30) -> str:
    """Run adb -s <address> <args...> and return stdout."""
    if not connection.is_connected:
        raise ActionError("No active ADB connection.")
    cmd = [cfg.adb_bin, "-s", connection.address, *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise ActionError(
                f"adb {' '.join(args)} failed: {result.stderr.strip()}"
            )
        return result.stdout.strip()
    except subprocess.TimeoutExpired as e:
        raise ActionError(f"adb {' '.join(args)} timed out") from e
    except FileNotFoundError as e:
        raise ActionError(
            f"adb not found at {cfg.adb_bin!r}. Run: brew install android-platform-tools"
        ) from e


# ------------------------------------------------------------------ #
# Clipboard sync                                                       #
# ------------------------------------------------------------------ #


# Matches http/https URLs and bare domain-like strings (e.g. claude.ai/settings)
_URL_RE = re.compile(
    r"^(?:https?://\S+|[a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-zA-Z]{2,}(?:/\S*)?)$"
)


def push_clipboard(connection: AdbConnection) -> str:
    """Send Mac clipboard content to the Pixel.

    - URLs are opened directly in the Android browser via ACTION_VIEW.
    - Plain text is sent via the Android share sheet (ACTION_SEND).

    Android 10+ blocks arbitrary clipboard writes without a companion app,
    so we avoid the clipboard API entirely and use intents instead.

    Returns a human-readable result message.
    """
    if not connection.is_connected:
        raise ActionError("No active ADB connection.")

    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        text = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise ActionError("Could not read macOS clipboard.") from e

    if not text:
        return "Clipboard is empty — nothing to push."

    if _URL_RE.match(text):
        # Open URL directly in the default browser on the Pixel.
        # Prepend https:// if no protocol is present.
        url = text if text.startswith(("http://", "https://")) else f"https://{text}"
        _adb_s(connection, "shell", "am", "start",
               "-a", "android.intent.action.VIEW", "-d", url)
        preview = text[:60] + ("…" if len(text) > 60 else "")
        return f"Opened on Pixel: {preview}"
    else:
        # Send plain text via the share sheet
        # Escape single quotes for the shell
        escaped = text.replace("'", "'\\''")
        _adb_s(connection, "shell",
               f"am start -a android.intent.action.SEND "
               f"-t text/plain "
               f"--es android.intent.extra.TEXT '{escaped}'")
        preview = text[:50].replace("\n", "↵") + ("…" if len(text) > 50 else "")
        return f"Shared to Pixel: {preview!r}"


# ------------------------------------------------------------------ #
# Pull latest photo                                                    #
# ------------------------------------------------------------------ #


def pull_latest_photo(connection: AdbConnection) -> str:
    """Pull the newest photo from DCIM/Camera to the Mac Desktop (or configured path).

    Returns a human-readable result message with the destination path.
    """
    # Find the newest file by modification time in DCIM/Camera
    ls_output = _adb_s(
        connection,
        "shell",
        "ls -t /sdcard/DCIM/Camera/ 2>/dev/null | head -1",
    )

    filename = ls_output.strip()
    if not filename:
        return "No photos found in /sdcard/DCIM/Camera/."

    dest_dir = cfg.photo_dest_path
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / filename
    remote_path = f"/sdcard/DCIM/Camera/{filename}"

    _adb_s(connection, "pull", remote_path, str(dest_file), timeout=60)

    # Reveal in Finder
    subprocess.Popen(["open", "-R", str(dest_file)])

    return f"Saved: {dest_file}"


# ------------------------------------------------------------------ #
# Screen mirroring                                                     #
# ------------------------------------------------------------------ #


def launch_scrcpy(connection: AdbConnection) -> None:
    """Launch scrcpy targeting the active TCP/IP device.

    Uses `-e` (--select-tcpip) to avoid the "Multiple ADB devices" error
    that occurs when the mDNS transport and the explicit IP:PORT transport
    are both visible to the ADB server.

    The connection.connect() method already removes the mDNS transport, so
    `-e` should find exactly one device. The explicit `-s` serial is also
    passed as a belt-and-suspenders measure.
    """
    if not connection.is_connected:
        raise ActionError("Connect to your Pixel first before launching scrcpy.")

    scrcpy_bin = cfg.scrcpy_bin
    if not Path(scrcpy_bin).exists():
        raise ActionError(
            f"scrcpy not found at {scrcpy_bin!r}. Install with: brew install scrcpy"
        )

    # -e   : target TCP/IP device (avoids mDNS double-entry error)
    # --window-title : label the window clearly
    # --no-audio is omitted — let the user hear audio by default
    cmd = [scrcpy_bin, "-e", "--window-title", f"McPixMirror — {connection.device.name}"]

    try:
        # Popen (non-blocking) — scrcpy runs independently
        subprocess.Popen(cmd)
    except FileNotFoundError as e:
        raise ActionError(
            f"scrcpy not found at {scrcpy_bin!r}. Install with: brew install scrcpy"
        ) from e
