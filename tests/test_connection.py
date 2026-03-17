"""Tests for mcpixmirror.connection — ADB state machine."""

from unittest.mock import MagicMock, call, patch

import pytest

from mcpixmirror.connection import AdbConnection, ConnectionError, ConnectionState, _adb
from mcpixmirror.discovery import DeviceInfo
from mcpixmirror.security import SecurityError

DEVICE = DeviceInfo(
    serial="27021FDH200461",
    ip="192.168.1.212",
    port=40235,
    name="Pixel 7",
    service_name="adb-27021FDH200461-Idi6fc._adb-tls-connect._tcp.local.",
)


def _patched_connect(mock_adb, device=DEVICE):
    """Helper: run connect() with a mock _adb that simulates success."""
    conn = AdbConnection()
    with patch("mcpixmirror.connection.assert_trusted_network"), patch(
        "mcpixmirror.connection.assert_trusted_serial"
    ):
        mock_adb.side_effect = [
            "",  # disconnect mDNS transport (best-effort)
            "connected to 192.168.1.212:40235",  # adb connect
            device.serial,  # adb -s IP:PORT shell getprop ro.serialno
        ]
        conn.connect(device)
    return conn


# ------------------------------------------------------------------ #
# _adb helper                                                          #
# ------------------------------------------------------------------ #


def test_adb_returns_stdout_on_success():
    with patch("mcpixmirror.connection.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="27021FDH200461\n", stderr="")
        result = _adb("get-serialno")
        assert result == "27021FDH200461"


def test_adb_raises_on_nonzero_exit():
    with patch("mcpixmirror.connection.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")
        with pytest.raises(ConnectionError, match="error msg"):
            _adb("connect", "1.2.3.4:9999")


def test_adb_raises_when_binary_missing():
    with patch(
        "mcpixmirror.connection.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        with pytest.raises(ConnectionError, match="adb not found"):
            _adb("devices")


# ------------------------------------------------------------------ #
# AdbConnection.connect                                                #
# ------------------------------------------------------------------ #


def test_connect_succeeds_and_sets_state():
    with patch("mcpixmirror.connection._adb") as mock_adb:
        conn = _patched_connect(mock_adb)

    assert conn.state == ConnectionState.CONNECTED
    assert conn.device == DEVICE
    assert conn.address == "192.168.1.212:40235"
    assert conn.serial == "27021FDH200461"


def test_connect_disconnects_mdns_transport_first():
    """The mDNS transport must be disconnected before connecting by IP."""
    with patch("mcpixmirror.connection._adb") as mock_adb, patch(
        "mcpixmirror.connection.assert_trusted_network"
    ), patch("mcpixmirror.connection.assert_trusted_serial"):
        mock_adb.side_effect = [
            "",  # disconnect mDNS
            "connected to 192.168.1.212:40235",
            DEVICE.serial,
        ]
        conn = AdbConnection()
        conn.connect(DEVICE)

    # First call must be disconnect of the mDNS service name
    first_call_args = mock_adb.call_args_list[0]
    assert first_call_args == call("disconnect", DEVICE.service_name)


def test_connect_raises_security_error_when_serial_mismatch():
    with patch("mcpixmirror.connection._adb") as mock_adb, patch(
        "mcpixmirror.connection.assert_trusted_network"
    ), patch("mcpixmirror.connection.assert_trusted_serial"):
        mock_adb.side_effect = [
            "",  # disconnect mDNS
            "connected to 192.168.1.212:40235",
            "WRONG_SERIAL",  # serial mismatch!
            "",  # adb disconnect address (cleanup after mismatch)
        ]
        conn = AdbConnection()
        with pytest.raises(SecurityError, match="Serial mismatch"):
            conn.connect(DEVICE)

    assert conn.state == ConnectionState.DISCONNECTED


def test_connect_aborts_on_untrusted_network():
    conn = AdbConnection()
    with patch(
        "mcpixmirror.connection.assert_trusted_network",
        side_effect=SecurityError("Untrusted"),
    ):
        with pytest.raises(SecurityError):
            conn.connect(DEVICE)
    assert conn.state == ConnectionState.DISCONNECTED


def test_connect_is_noop_when_already_connected_to_same_device():
    with patch("mcpixmirror.connection._adb") as mock_adb:
        conn = _patched_connect(mock_adb)
        call_count_before = mock_adb.call_count

        # Second connect to same device — should be a no-op
        with patch("mcpixmirror.connection.assert_trusted_network"), patch(
            "mcpixmirror.connection.assert_trusted_serial"
        ):
            conn.connect(DEVICE)

        assert mock_adb.call_count == call_count_before  # no new adb calls


# ------------------------------------------------------------------ #
# AdbConnection.disconnect                                             #
# ------------------------------------------------------------------ #


def test_disconnect_sends_adb_disconnect():
    with patch("mcpixmirror.connection._adb") as mock_adb:
        conn = _patched_connect(mock_adb)
        mock_adb.side_effect = [""]  # for the disconnect call
        conn.disconnect()

    assert conn.state == ConnectionState.DISCONNECTED
    assert conn.device is None
    # Last call should be disconnect IP:PORT
    last_call = mock_adb.call_args_list[-1]
    assert last_call == call("disconnect", "192.168.1.212:40235")


def test_disconnect_is_safe_when_already_disconnected():
    conn = AdbConnection()
    # Should not raise
    conn.disconnect()
    assert conn.state == ConnectionState.DISCONNECTED


def test_disconnect_swallows_adb_error():
    """Device may already be offline — disconnect errors must not propagate."""
    with patch("mcpixmirror.connection._adb") as mock_adb:
        conn = _patched_connect(mock_adb)
        mock_adb.side_effect = ConnectionError("device offline")
        conn.disconnect()  # must not raise

    assert conn.state == ConnectionState.DISCONNECTED


# ------------------------------------------------------------------ #
# AdbConnection.disconnect_all                                         #
# ------------------------------------------------------------------ #


def test_disconnect_all_calls_adb_disconnect_no_args():
    with patch("mcpixmirror.connection._adb") as mock_adb:
        conn = _patched_connect(mock_adb)
        mock_adb.side_effect = [""]  # for the disconnect_all call
        conn.disconnect_all()

    last_call = mock_adb.call_args_list[-1]
    assert last_call == call("disconnect")
    assert conn.state == ConnectionState.DISCONNECTED
