"""Tests for mcpixmirror.discovery — dns-sd serial extraction and event queuing."""

import queue
from unittest.mock import MagicMock, patch, call
import subprocess

import pytest

from mcpixmirror.discovery import (
    ADB_SERVICE_TYPE,
    DeviceDiscovery,
    DeviceEvent,
    DeviceInfo,
    EventKind,
    _extract_serial,
    _resolve_hostname,
)


# ------------------------------------------------------------------ #
# _extract_serial                                                      #
# ------------------------------------------------------------------ #


def test_extract_serial_parses_standard_name():
    name = "adb-27021FDH200461-Idi6fc._adb-tls-connect._tcp.local."
    assert _extract_serial(name) == "27021FDH200461"


def test_extract_serial_parses_short_serial():
    name = "adb-ABC123-XXXX._adb-tls-connect._tcp.local."
    assert _extract_serial(name) == "ABC123"


def test_extract_serial_returns_none_for_unrelated_service():
    assert _extract_serial("somedevice._http._tcp.local.") is None


def test_extract_serial_returns_none_for_empty_string():
    assert _extract_serial("") is None


# ------------------------------------------------------------------ #
# _resolve_hostname                                                    #
# ------------------------------------------------------------------ #


def test_resolve_hostname_returns_ip():
    with patch("mcpixmirror.discovery.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("192.168.1.212", 0))]
        assert _resolve_hostname("Android.local") == "192.168.1.212"


def test_resolve_hostname_returns_hostname_on_failure():
    with patch("mcpixmirror.discovery.socket.getaddrinfo", side_effect=OSError):
        assert _resolve_hostname("Android.local") == "Android.local"


# ------------------------------------------------------------------ #
# DeviceDiscovery                                                      #
# ------------------------------------------------------------------ #


def _make_discovery_with_browse_output(lines: list[str]) -> DeviceDiscovery:
    """Helper: create a DeviceDiscovery whose browse process emits the given lines."""
    mock_proc = MagicMock()
    mock_proc.stdout = iter(lines)
    mock_proc.kill = MagicMock()

    with patch("mcpixmirror.discovery.subprocess.Popen", return_value=mock_proc):
        d = DeviceDiscovery()
        d.start()
    return d


def test_discovery_start_is_idempotent():
    with patch("mcpixmirror.discovery.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(stdout=iter([]), kill=MagicMock())
        d = DeviceDiscovery()
        d.start()
        d.start()  # second call should be no-op
        assert mock_popen.call_count == 1
        d.stop()


def test_discovery_stop_kills_process():
    with patch("mcpixmirror.discovery.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock(stdout=iter([]), kill=MagicMock())
        mock_popen.return_value = mock_proc
        d = DeviceDiscovery()
        d.start()
        d.stop()
        mock_proc.kill.assert_called_once()
        assert d._browse_proc is None


def test_poll_returns_empty_when_no_events():
    with patch("mcpixmirror.discovery.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(stdout=iter([]), kill=MagicMock())
        d = DeviceDiscovery()
        d.start()
        assert d.poll() == []
        d.stop()


def test_browse_reader_queues_removed_event():
    """Rmv lines should immediately queue a REMOVED event (no lookup needed)."""
    rmv_line = (
        "16:12:00.000  Rmv        2  14 local.  "
        "_adb-tls-connect._tcp.  adb-27021FDH200461-Idi6fc\n"
    )
    import time

    with patch("mcpixmirror.discovery.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock(stdout=iter([rmv_line]), kill=MagicMock())
        mock_popen.return_value = mock_proc
        d = DeviceDiscovery()
        d.start()
        time.sleep(0.2)  # let the reader thread process the line
        events = d.poll()
        d.stop()

    assert len(events) == 1
    assert events[0].kind == EventKind.REMOVED
    assert events[0].device.serial == "27021FDH200461"


def test_lookup_queues_added_event():
    """Add lines should trigger a lookup and queue an ADDED event."""
    import time

    add_line = (
        "16:12:00.000  Add        2  14 local.  "
        "_adb-tls-connect._tcp.  adb-27021FDH200461-Idi6fc\n"
    )
    lookup_lines = [
        "Lookup adb-27021FDH200461-Idi6fc._adb-tls-connect._tcp.local\n",
        "  adb-27021FDH200461-Idi6fc._adb-tls-connect._tcp.local. "
        "can be reached at Android.local.:33825 (interface 14)\n",
        " api=36.1 name=Pixel\\ 7 v=1\n",
    ]

    browse_proc = MagicMock(stdout=iter([add_line]), kill=MagicMock())
    lookup_proc = MagicMock(stdout=iter(lookup_lines), kill=MagicMock())

    call_count = [0]

    def popen_side_effect(cmd, **kwargs):
        call_count[0] += 1
        return browse_proc if call_count[0] == 1 else lookup_proc

    with patch("mcpixmirror.discovery.subprocess.Popen", side_effect=popen_side_effect), \
         patch("mcpixmirror.discovery._resolve_hostname", return_value="192.168.1.212"):
        d = DeviceDiscovery()
        d.start()
        time.sleep(0.3)
        events = d.poll()
        d.stop()

    assert len(events) == 1
    e = events[0]
    assert e.kind == EventKind.ADDED
    assert e.device.serial == "27021FDH200461"
    assert e.device.ip == "192.168.1.212"
    assert e.device.port == 33825
    assert e.device.name == "Pixel 7"
