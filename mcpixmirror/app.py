"""McPixMirror macOS menu bar application.

Entry point for the rumps-based menu bar app. Wires together:
  - DeviceDiscovery (background mDNS listener)
  - AdbConnection (state machine)
  - Security guards
  - User-facing actions (clipboard, photo, scrcpy)

Threading model:
  rumps uses AppKit and must be driven from the main thread.
  All UI updates (menu item titles, icon changes, notifications)
  happen in the timer callback (tick()), which runs on the main thread.
  The discovery listener runs in a daemon thread and posts events to
  a queue; tick() drains that queue.
"""

from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path

import rumps  # type: ignore[import]

from mcpixmirror import __version__

_ASSETS = Path(__file__).parent.parent / "assets"
from mcpixmirror.actions import ActionError, launch_scrcpy, pull_latest_photo, push_clipboard
from mcpixmirror.config import cfg, reload as reload_config
from mcpixmirror.connection import AdbConnection, ConnectionError
from mcpixmirror.discovery import DeviceDiscovery, DeviceInfo, EventKind
from mcpixmirror.security import SecurityError, on_trusted_network

def _icon(name: str) -> str | None:
    """Return absolute icon path, or None if the file doesn't exist yet."""
    p = _ASSETS / name
    return str(p) if p.exists() else None

ICON_CONNECTED = _icon("icon_connected.png")
ICON_DISCONNECTED = _icon("icon_disconnected.png")


class McPixMirrorApp(rumps.App):
    def __init__(self) -> None:
        # Use icon if available; fall back to text title in the menu bar
        super().__init__(
            "McPixMirror" if ICON_DISCONNECTED is None else "",
            icon=ICON_DISCONNECTED,
            quit_button=None,  # We add our own so we can clean up first
        )

        # State
        self._conn = AdbConnection()
        self._discovery = DeviceDiscovery()
        self._pending_device: DeviceInfo | None = None  # discovered but not yet connected

        # Menu structure
        self._status_item = rumps.MenuItem("Status: Searching…", callback=None)
        self._status_item.set_callback(None)  # non-clickable

        self._push_clip = rumps.MenuItem("Push Clipboard to Phone", callback=self._on_push_clipboard)
        self._pull_photo = rumps.MenuItem("Pull Latest Photo", callback=self._on_pull_photo)
        self._mirror = rumps.MenuItem("Mirror Screen (scrcpy)", callback=self._on_mirror)

        self._disconnect_item = rumps.MenuItem("Disconnect", callback=self._on_disconnect)

        self.menu = [
            self._status_item,
            None,
            self._push_clip,
            self._pull_photo,
            self._mirror,
            None,
            self._disconnect_item,
            rumps.MenuItem("Settings…", callback=self._on_settings),
            None,
            rumps.MenuItem(f"McPixMirror v{__version__}", callback=None),
            rumps.MenuItem("Quit", callback=self._on_quit),
        ]

        self._update_menu_state()

        # Start background discovery
        self._discovery.start()

        # Poll timer — drains the discovery queue and checks connection health
        self._timer = rumps.Timer(self._tick, cfg.behavior.poll_interval_seconds)
        self._timer.start()

    # ------------------------------------------------------------------ #
    # Timer callback (main thread)                                         #
    # ------------------------------------------------------------------ #

    def _tick(self, _: rumps.Timer) -> None:
        """Called every poll_interval_seconds on the main thread."""
        try:
            self._process_discovery_events()
            self._check_security_and_auto_connect()
            self._update_menu_state()
        except Exception:
            # Never crash the timer — log and continue
            traceback.print_exc()

    def _process_discovery_events(self) -> None:
        """Drain mDNS events from the discovery queue."""
        for event in self._discovery.poll():
            if event.kind == EventKind.ADDED:
                self._pending_device = event.device
            elif event.kind == EventKind.REMOVED:
                # Device went offline — if it's our connected device, disconnect
                if self._conn.is_connected and self._conn.serial == event.device.serial:
                    self._conn.disconnect()
                    self._notify("Pixel Disconnected", "Wireless Debugging stopped.")
                if self._pending_device and self._pending_device.serial == event.device.serial:
                    self._pending_device = None

    def _check_security_and_auto_connect(self) -> None:
        """Enforce security policy and trigger auto-connect if conditions are met."""
        if not on_trusted_network():
            # Left the trusted network — force disconnect
            if self._conn.is_connected:
                self._conn.disconnect_all()
                self._notify("ADB Disconnected", "Left trusted Wi-Fi network.")
            return

        if not cfg.behavior.auto_connect:
            return

        if self._conn.is_connected:
            return  # already good

        if self._pending_device is None:
            return  # nothing discovered yet

        # Attempt auto-connect
        try:
            self._conn.connect(self._pending_device)
            self._notify(
                "Connected",
                f"{self._pending_device.name} ready.",
            )
        except SecurityError as e:
            self._notify("Security Block", str(e))
            self._pending_device = None  # don't retry this device
        except ConnectionError as e:
            # Will retry next tick
            print(f"[McPixMirror] Connection attempt failed: {e}")

    # ------------------------------------------------------------------ #
    # Menu item callbacks                                                  #
    # ------------------------------------------------------------------ #

    def _on_push_clipboard(self, _: rumps.MenuItem) -> None:
        try:
            msg = push_clipboard(self._conn)
            self._notify("Clipboard Pushed", msg)
        except ActionError as e:
            self._notify("Clipboard Error", str(e))

    def _on_pull_photo(self, _: rumps.MenuItem) -> None:
        try:
            msg = pull_latest_photo(self._conn)
            self._notify("Photo Saved", msg)
        except ActionError as e:
            self._notify("Photo Error", str(e))

    def _on_mirror(self, _: rumps.MenuItem) -> None:
        try:
            launch_scrcpy(self._conn)
        except ActionError as e:
            self._notify("scrcpy Error", str(e))

    def _on_disconnect(self, _: rumps.MenuItem) -> None:
        self._conn.disconnect()
        self._update_menu_state()

    def _on_settings(self, _: rumps.MenuItem) -> None:
        """Open the config file in the default text editor."""
        from mcpixmirror.config import CONFIG_FILE
        subprocess.Popen(["open", str(CONFIG_FILE)])

    def _on_quit(self, _: rumps.MenuItem) -> None:
        self._conn.disconnect()
        self._discovery.stop()
        rumps.quit_application()

    # ------------------------------------------------------------------ #
    # UI helpers                                                           #
    # ------------------------------------------------------------------ #

    def _update_menu_state(self) -> None:
        """Refresh menu item titles and icon to reflect current state."""
        connected = self._conn.is_connected
        trusted = on_trusted_network()

        if connected and self._conn.device:
            status = f"Connected: {self._conn.device.name} ({self._conn.address})"
        elif not trusted:
            status = "Status: Untrusted network"
        elif self._pending_device:
            status = f"Status: Found {self._pending_device.name} — connecting…"
        else:
            status = "Status: Searching for Pixel…"

        self._status_item.title = status

        # Enable/disable action items
        for item in (self._push_clip, self._pull_photo, self._mirror):
            item.set_callback(item.callback if connected else None)

        self._disconnect_item.set_callback(self._on_disconnect if connected else None)

        # Update icon (only if icon files exist)
        target_icon = ICON_CONNECTED if connected else ICON_DISCONNECTED
        if target_icon is not None:
            try:
                self.icon = target_icon
            except Exception:
                pass

    @staticmethod
    def _notify(title: str, message: str) -> None:
        rumps.notification(
            title="McPixMirror",
            subtitle=title,
            message=message,
        )


# ------------------------------------------------------------------ #
# Entry point                                                          #
# ------------------------------------------------------------------ #


def main() -> None:
    app = McPixMirrorApp()
    app.run()


if __name__ == "__main__":
    main()
