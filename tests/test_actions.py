"""Tests for mcpixmirror.actions — clipboard sync, photo pull, scrcpy launch."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcpixmirror.actions import ActionError, launch_scrcpy, pull_latest_photo, push_clipboard
from mcpixmirror.connection import AdbConnection


def _connected_mock() -> AdbConnection:
    """Return a mock AdbConnection that reports as connected."""
    conn = MagicMock(spec=AdbConnection)
    conn.is_connected = True
    conn.address = "192.168.1.212:40235"
    conn.device = MagicMock(name="Pixel 7")
    conn.device.name = "Pixel 7"
    return conn


def _disconnected_mock() -> AdbConnection:
    conn = MagicMock(spec=AdbConnection)
    conn.is_connected = False
    return conn


# ------------------------------------------------------------------ #
# push_clipboard                                                       #
# ------------------------------------------------------------------ #


def test_push_clipboard_returns_message_on_success():
    conn = _connected_mock()
    with patch("mcpixmirror.actions.subprocess.run") as mock_run, patch(
        "mcpixmirror.actions._adb_s", return_value=""
    ):
        mock_run.return_value = MagicMock(stdout="https://example.com", returncode=0)
        result = push_clipboard(conn)
    assert "example.com" in result


def test_push_clipboard_returns_empty_message_when_clipboard_empty():
    conn = _connected_mock()
    with patch("mcpixmirror.actions.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = push_clipboard(conn)
    assert "empty" in result.lower()


def test_push_clipboard_raises_when_not_connected():
    conn = _disconnected_mock()
    with pytest.raises(ActionError, match="No active ADB connection"):
        push_clipboard(conn)


# ------------------------------------------------------------------ #
# pull_latest_photo                                                    #
# ------------------------------------------------------------------ #


def test_pull_latest_photo_success(tmp_path):
    conn = _connected_mock()
    with patch("mcpixmirror.actions._adb_s") as mock_adb_s, patch(
        "mcpixmirror.actions.cfg"
    ) as mock_cfg, patch("mcpixmirror.actions.subprocess.Popen"):
        mock_cfg.adb_bin = "/usr/bin/adb"
        mock_cfg.photo_dest_path = tmp_path
        mock_adb_s.side_effect = [
            "IMG_20260317_120000.jpg\n",  # ls output
            "",  # pull output
        ]
        result = pull_latest_photo(conn)
    assert "IMG_20260317_120000.jpg" in result


def test_pull_latest_photo_raises_when_no_photos():
    conn = _connected_mock()
    with patch("mcpixmirror.actions._adb_s", return_value=""), patch(
        "mcpixmirror.actions.cfg"
    ) as mock_cfg:
        mock_cfg.photo_dest_path = Path("/tmp")
        result = pull_latest_photo(conn)
    assert "No photos" in result


def test_pull_latest_photo_raises_when_not_connected():
    conn = _disconnected_mock()
    with pytest.raises(ActionError, match="No active ADB connection"):
        pull_latest_photo(conn)


# ------------------------------------------------------------------ #
# launch_scrcpy                                                        #
# ------------------------------------------------------------------ #


def test_launch_scrcpy_calls_popen_with_e_flag(tmp_path):
    conn = _connected_mock()
    scrcpy_bin = str(tmp_path / "scrcpy")
    # Create a fake scrcpy binary so Path.exists() returns True
    Path(scrcpy_bin).touch()

    with patch("mcpixmirror.actions.cfg") as mock_cfg, patch(
        "mcpixmirror.actions.subprocess.Popen"
    ) as mock_popen:
        mock_cfg.scrcpy_bin = scrcpy_bin
        launch_scrcpy(conn)

    call_args = mock_popen.call_args[0][0]
    assert "-e" in call_args
    assert scrcpy_bin == call_args[0]


def test_launch_scrcpy_raises_when_not_connected():
    conn = _disconnected_mock()
    with pytest.raises(ActionError, match="Connect to your Pixel first"):
        launch_scrcpy(conn)


def test_launch_scrcpy_raises_when_scrcpy_missing():
    conn = _connected_mock()
    with patch("mcpixmirror.actions.cfg") as mock_cfg, patch(
        "mcpixmirror.actions.Path.exists", return_value=False
    ):
        mock_cfg.scrcpy_bin = "/nonexistent/scrcpy"
        with pytest.raises(ActionError, match="scrcpy not found"):
            launch_scrcpy(conn)
