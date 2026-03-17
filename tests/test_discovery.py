"""Tests for mcpixmirror.discovery — mDNS serial extraction and event queuing."""

import queue
from unittest.mock import MagicMock, patch

import pytest

from mcpixmirror.discovery import (
    ADB_CONNECT_TYPE,
    DeviceDiscovery,
    DeviceEvent,
    DeviceInfo,
    EventKind,
    _AdbServiceListener,
    _extract_serial,
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
    name = "somedevice._http._tcp.local."
    assert _extract_serial(name) is None


def test_extract_serial_returns_none_for_empty_string():
    assert _extract_serial("") is None


# ------------------------------------------------------------------ #
# _AdbServiceListener                                                  #
# ------------------------------------------------------------------ #


def _make_mock_service_info(ip: str, port: int, device_name: str) -> MagicMock:
    info = MagicMock()
    info.parsed_scoped_addresses.return_value = [ip]
    info.port = port
    info.properties = {b"name": device_name.encode()}
    return info


def test_listener_add_service_queues_added_event():
    q: queue.Queue[DeviceEvent] = queue.Queue()
    listener = _AdbServiceListener(q)

    service_name = "adb-27021FDH200461-Idi6fc._adb-tls-connect._tcp.local."
    mock_info = _make_mock_service_info("192.168.1.212", 40235, "Pixel 7")

    mock_zc = MagicMock()
    mock_zc.get_service_info.return_value = mock_info

    listener.add_service(mock_zc, ADB_CONNECT_TYPE, service_name)

    assert not q.empty()
    event = q.get_nowait()
    assert event.kind == EventKind.ADDED
    assert event.device.serial == "27021FDH200461"
    assert event.device.ip == "192.168.1.212"
    assert event.device.port == 40235
    assert event.device.name == "Pixel 7"
    assert event.device.service_name == service_name


def test_listener_add_service_ignores_unresolvable():
    q: queue.Queue[DeviceEvent] = queue.Queue()
    listener = _AdbServiceListener(q)

    mock_zc = MagicMock()
    mock_zc.get_service_info.return_value = None  # can't resolve

    service_name = "adb-SERIAL-XXXX._adb-tls-connect._tcp.local."
    listener.add_service(mock_zc, ADB_CONNECT_TYPE, service_name)

    assert q.empty()


def test_listener_add_service_ignores_non_adb_records():
    q: queue.Queue[DeviceEvent] = queue.Queue()
    listener = _AdbServiceListener(q)

    mock_zc = MagicMock()
    mock_zc.get_service_info.return_value = _make_mock_service_info("1.2.3.4", 80, "Printer")

    listener.add_service(mock_zc, "_http._tcp.local.", "printer._http._tcp.local.")
    assert q.empty()


def test_listener_remove_service_queues_removed_event():
    q: queue.Queue[DeviceEvent] = queue.Queue()
    listener = _AdbServiceListener(q)

    service_name = "adb-27021FDH200461-Idi6fc._adb-tls-connect._tcp.local."
    listener.remove_service(MagicMock(), ADB_CONNECT_TYPE, service_name)

    assert not q.empty()
    event = q.get_nowait()
    assert event.kind == EventKind.REMOVED
    assert event.device.serial == "27021FDH200461"


def test_listener_update_service_treats_as_re_add():
    q: queue.Queue[DeviceEvent] = queue.Queue()
    listener = _AdbServiceListener(q)

    service_name = "adb-27021FDH200461-Idi6fc._adb-tls-connect._tcp.local."
    mock_info = _make_mock_service_info("192.168.1.212", 41000, "Pixel 7")  # new port
    mock_zc = MagicMock()
    mock_zc.get_service_info.return_value = mock_info

    listener.update_service(mock_zc, ADB_CONNECT_TYPE, service_name)

    event = q.get_nowait()
    assert event.kind == EventKind.ADDED
    assert event.device.port == 41000


# ------------------------------------------------------------------ #
# DeviceDiscovery                                                      #
# ------------------------------------------------------------------ #


def test_device_discovery_poll_returns_empty_when_no_events():
    with patch("mcpixmirror.discovery.Zeroconf"), patch(
        "mcpixmirror.discovery.ServiceBrowser"
    ):
        d = DeviceDiscovery()
        d.start()
        assert d.poll() == []
        d.stop()


def test_device_discovery_start_is_idempotent():
    with patch("mcpixmirror.discovery.Zeroconf") as mock_zc, patch(
        "mcpixmirror.discovery.ServiceBrowser"
    ):
        d = DeviceDiscovery()
        d.start()
        d.start()  # second call should be a no-op
        assert mock_zc.call_count == 1
        d.stop()


def test_device_discovery_stop_cleans_up():
    with patch("mcpixmirror.discovery.Zeroconf") as mock_zc_cls, patch(
        "mcpixmirror.discovery.ServiceBrowser"
    ):
        mock_zc_instance = MagicMock()
        mock_zc_cls.return_value = mock_zc_instance

        d = DeviceDiscovery()
        d.start()
        d.stop()

        mock_zc_instance.close.assert_called_once()
        assert d._zc is None
