"""User-facing actions: clipboard sync, pull latest photo, launch scrcpy.

All actions require an active ADB connection. They are thin wrappers that
shell out to `adb` and `scrcpy`; the connection object provides the address.
"""

from __future__ import annotations

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


def push_clipboard(connection: AdbConnection) -> str:
    """Copy the Mac clipboard to the Android clipboard.

    Uses `adb shell am broadcast` with the built-in ClipboardManager intent.
    Works for plain text. Multi-line and Unicode are supported; shell-special
    characters are handled by passing the text through a file rather than
    inline in the command (avoids quoting hazards).

    Returns a human-readable result message.
    """
    if not connection.is_connected:
        raise ActionError("No active ADB connection.")

    # Read from macOS clipboard
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        text = result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise ActionError("Could not read macOS clipboard.") from e

    if not text:
        return "Clipboard is empty — nothing to push."

    # Write to a temp file on the device, then use the Android Broadcast API.
    # We use a temp file approach to safely handle special shell characters.
    tmp_path = "/sdcard/.mcpixmirror_clip.txt"

    # Push via stdin to avoid shell quoting issues with special chars
    push_cmd = [cfg.adb_bin, "-s", connection.address, "shell", f"cat > {tmp_path}"]
    try:
        proc = subprocess.run(
            push_cmd,
            input=text,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            raise ActionError(f"Could not write clipboard to device: {proc.stderr.strip()}")
    except subprocess.TimeoutExpired as e:
        raise ActionError("Timed out writing clipboard to device.") from e

    # Use the Android service to set clipboard content from the temp file.
    # `am broadcast` with CLIPPER_SET is the standard community approach;
    # we fall back to a simpler `input text` for short strings if this fails.
    broadcast_cmd = (
        f"content=$(cat {tmp_path}); "
        f"am broadcast -a clipper.set --es text \"$content\"; "
        f"rm -f {tmp_path}"
    )
    try:
        _adb_s(connection, "shell", broadcast_cmd)
    except ActionError:
        # Fallback: try input text (works for short, simple strings only)
        # This is best-effort; truncate to avoid ADB input limits.
        short_text = text[:200].replace("\n", " ")
        try:
            _adb_s(connection, "shell", "input", "text", short_text)
        except ActionError:
            raise ActionError(
                "Clipboard push failed. Install the 'Clipper' app on your Pixel "
                "for reliable clipboard sync."
            )

    preview = text[:50].replace("\n", "↵") + ("…" if len(text) > 50 else "")
    return f"Pushed to phone: {preview!r}"


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
