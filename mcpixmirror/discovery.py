"""mDNS discovery of ADB wireless debugging devices.

Watches for `_adb-tls-connect._tcp.local.` Zeroconf records, which Android
advertises continuously while Wireless Debugging is enabled in Developer Options.

Each record embeds the device serial in the service name:
    adb-<SERIAL>-<RANDOM>._adb-tls-connect._tcp.local.

The listener extracts the serial, IP, port, and human-readable device name,
then pushes a DeviceEvent onto a thread-safe queue consumed by the main thread.

We do NOT watch `_adb-tls-pairing._tcp` — pairing is a one-time manual step
that only appears while the "Pair device with pairing code" dialog is open.
"""

from __future__ import annotations

import queue
import re
import socket
from dataclasses import dataclass
from enum import Enum, auto
from threading import Event
from typing import Any

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf  # type: ignore[import]

ADB_CONNECT_TYPE = "_adb-tls-connect._tcp.local."

# Matches: adb-27021FDH200461-Idi6fc._adb-tls-connect._tcp.local.
_SERIAL_RE = re.compile(r"^adb-([A-Z0-9]+)-[A-Za-z0-9]+\._adb-tls-connect\._tcp")


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    ip: str
    port: int
    name: str  # human-readable name from mDNS properties, e.g. "Pixel 7"
    service_name: str  # full mDNS service name, used to disconnect the mDNS transport


class EventKind(Enum):
    ADDED = auto()
    REMOVED = auto()


@dataclass(frozen=True)
class DeviceEvent:
    kind: EventKind
    device: DeviceInfo


def _extract_serial(service_name: str) -> str | None:
    """Pull the device serial out of an mDNS service name string."""
    m = _SERIAL_RE.match(service_name)
    return m.group(1) if m else None


class _AdbServiceListener(ServiceListener):
    """Zeroconf ServiceListener that queues DeviceEvents for the main thread."""

    def __init__(self, event_queue: "queue.Queue[DeviceEvent]") -> None:
        self._queue = event_queue

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info is None:
            return

        serial = _extract_serial(name)
        if serial is None:
            return  # not an ADB device record

        addresses = info.parsed_scoped_addresses()
        if not addresses:
            return
        ip = addresses[0]

        # mDNS properties are bytes
        props: dict[bytes, Any] = info.properties or {}
        device_name = props.get(b"name", b"Android Device").decode("utf-8", errors="replace")

        self._queue.put(
            DeviceEvent(
                kind=EventKind.ADDED,
                device=DeviceInfo(
                    serial=serial,
                    ip=ip,
                    port=info.port,
                    name=device_name,
                    service_name=name,
                ),
            )
        )

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        serial = _extract_serial(name)
        if serial is None:
            return
        # We don't have full info on removal — build a minimal DeviceInfo.
        self._queue.put(
            DeviceEvent(
                kind=EventKind.REMOVED,
                device=DeviceInfo(
                    serial=serial,
                    ip="",
                    port=0,
                    name="",
                    service_name=name,
                ),
            )
        )

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # Port may have changed (e.g. after Wireless Debugging restart without reboot).
        # Treat as a re-add.
        self.add_service(zc, type_, name)


class DeviceDiscovery:
    """Background mDNS watcher. Thread-safe; events are consumed via poll()."""

    def __init__(self) -> None:
        self._queue: queue.Queue[DeviceEvent] = queue.Queue()
        self._zc: Zeroconf | None = None
        self._browser: ServiceBrowser | None = None
        self._stop_event = Event()

    def start(self) -> None:
        """Start the background mDNS listener. Safe to call multiple times."""
        if self._zc is not None:
            return
        self._zc = Zeroconf()
        self._browser = ServiceBrowser(
            self._zc,
            ADB_CONNECT_TYPE,
            listener=_AdbServiceListener(self._queue),
        )

    def stop(self) -> None:
        """Shut down the mDNS listener cleanly."""
        if self._zc is not None:
            self._zc.close()
            self._zc = None
            self._browser = None

    def poll(self) -> list[DeviceEvent]:
        """Drain all pending events and return them. Non-blocking. Call from main thread."""
        events: list[DeviceEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events
