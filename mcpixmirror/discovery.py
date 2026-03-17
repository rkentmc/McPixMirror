"""mDNS discovery of ADB wireless debugging devices via macOS Bonjour (dns-sd).

Uses `dns-sd -B` (browse) and `dns-sd -L` (lookup) subprocess calls instead
of the Python `zeroconf` library. The zeroconf library implements its own mDNS
stack using raw sockets, which conflicts with the macOS Bonjour daemon and
causes it to miss services that dns-sd finds instantly.

By shelling out to dns-sd we use the same Bonjour daemon that the rest of macOS
uses, which is always up-to-date and requires no special permissions.

Discovery flow:
  1. `dns-sd -B _adb-tls-connect._tcp .`  → streams Add/Rmv events
  2. For each Add, `dns-sd -L <name> _adb-tls-connect._tcp .`  → hostname:port + properties
  3. `socket.getaddrinfo(hostname)` resolves Android.local. → IP address

Each record embeds the device serial in the service name:
    adb-<SERIAL>-<RANDOM>._adb-tls-connect._tcp.local.
"""

from __future__ import annotations

import queue
import re
import socket
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum, auto

ADB_SERVICE_TYPE = "_adb-tls-connect._tcp"

_SERIAL_RE = re.compile(r"^adb-([A-Z0-9]+)-[A-Za-z0-9]+\._adb-tls-connect\._tcp")

# dns-sd -B output line:
# "16:11:49.564  Add        2  14 local.  _adb-tls-connect._tcp.  adb-27021FDH200461-Idi6fc"
_BROWSE_RE = re.compile(
    r"\s+(Add|Rmv)\s+\d+\s+\d+\s+\S+\s+\S+\s+(.+)"
)

# dns-sd -L output line:
# "adb-xxx._adb-tls-connect._tcp.local. can be reached at Android.local.:33825 (interface 14)"
_LOOKUP_RE = re.compile(r"can be reached at (\S+?):(\d+)")

# Properties line: " api=36.1 name=Pixel\ 7 v=1"
_NAME_RE = re.compile(r"\bname=(.+?)(?:\s+\w+=|$)")


def _extract_serial(service_name: str) -> str | None:
    m = _SERIAL_RE.match(service_name)
    return m.group(1) if m else None


def _resolve_hostname(hostname: str) -> str:
    """Resolve a .local mDNS hostname to an IPv4 address string."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        if results:
            return results[0][4][0]
    except OSError:
        pass
    return hostname  # return as-is if resolution fails


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    ip: str
    port: int
    name: str
    service_name: str  # full mDNS service name, used to disconnect mDNS transport


class EventKind(Enum):
    ADDED = auto()
    REMOVED = auto()


@dataclass(frozen=True)
class DeviceEvent:
    kind: EventKind
    device: DeviceInfo


class DeviceDiscovery:
    """Background dns-sd watcher. Thread-safe; events are consumed via poll()."""

    def __init__(self) -> None:
        self._queue: queue.Queue[DeviceEvent] = queue.Queue()
        self._browse_proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background dns-sd browse. Safe to call multiple times."""
        if self._browse_proc is not None:
            return
        self._browse_proc = subprocess.Popen(
            ["dns-sd", "-B", ADB_SERVICE_TYPE, "."],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._thread = threading.Thread(target=self._browse_reader, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Shut down the dns-sd process cleanly."""
        if self._browse_proc is not None:
            self._browse_proc.kill()
            self._browse_proc = None
            self._thread = None

    def poll(self) -> list[DeviceEvent]:
        """Drain all pending events. Non-blocking. Call from main thread."""
        events: list[DeviceEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    # ------------------------------------------------------------------ #
    # Background threads                                                   #
    # ------------------------------------------------------------------ #

    def _browse_reader(self) -> None:
        """Read dns-sd -B output line by line. Runs in a daemon thread."""
        proc = self._browse_proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            m = _BROWSE_RE.search(line)
            if not m:
                continue
            action, raw_name = m.group(1), m.group(2).strip()

            # Reconstruct full service name for serial extraction
            service_name = f"{raw_name}.{ADB_SERVICE_TYPE}.local."
            serial = _extract_serial(service_name)
            if serial is None:
                continue

            if action == "Add":
                # Launch a lookup thread so the browse loop isn't blocked
                threading.Thread(
                    target=self._lookup,
                    args=(raw_name, serial, service_name),
                    daemon=True,
                ).start()
            elif action == "Rmv":
                self._queue.put(
                    DeviceEvent(
                        kind=EventKind.REMOVED,
                        device=DeviceInfo(
                            serial=serial,
                            ip="",
                            port=0,
                            name="",
                            service_name=service_name,
                        ),
                    )
                )

    def _lookup(self, name: str, serial: str, service_name: str) -> None:
        """Run dns-sd -L to get hostname:port and properties. Daemon thread."""
        try:
            proc = subprocess.Popen(
                ["dns-sd", "-L", name, ADB_SERVICE_TYPE, "."],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            device_name = "Android Device"
            for line in proc.stdout:  # type: ignore[union-attr]
                reach_m = _LOOKUP_RE.search(line)
                if reach_m:
                    hostname = reach_m.group(1).rstrip(".")
                    port = int(reach_m.group(2))

                    # Next line contains TXT record properties
                    props_line = next(proc.stdout, "")  # type: ignore[union-attr]
                    name_m = _NAME_RE.search(props_line)
                    if name_m:
                        device_name = name_m.group(1).replace("\\ ", " ").strip()

                    ip = _resolve_hostname(hostname)

                    self._queue.put(
                        DeviceEvent(
                            kind=EventKind.ADDED,
                            device=DeviceInfo(
                                serial=serial,
                                ip=ip,
                                port=port,
                                name=device_name,
                                service_name=service_name,
                            ),
                        )
                    )
                    break
        except Exception:
            pass
        finally:
            try:
                proc.kill()
            except Exception:
                pass
