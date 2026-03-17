"""User configuration backed by ~/.config/mcpixmirror/config.toml.

Loaded once at startup; call reload() to re-read from disk.
"""

from __future__ import annotations

import sys

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "mcpixmirror"
CONFIG_FILE = CONFIG_DIR / "config.toml"

_DEFAULT_TOML = """\
[security]
# List of Wi-Fi SSIDs on which ADB connections are permitted.
known_ssids = []
# Serial number of the trusted device — populated automatically on first connect.
known_serial = ""

[paths]
# Override these if adb/scrcpy are not in the Homebrew default location.
adb = "/opt/homebrew/bin/adb"
scrcpy = "/opt/homebrew/bin/scrcpy"
# Directory where pulled photos are saved.
photo_dest = "~/Desktop"

[behavior]
# Automatically connect when the device appears on a trusted network.
auto_connect = true
# How often (seconds) the app polls network/connection state.
poll_interval_seconds = 5
"""


@dataclass
class SecurityConfig:
    known_ssids: list[str] = field(default_factory=list)
    known_serial: str = ""


@dataclass
class PathsConfig:
    adb: str = "/opt/homebrew/bin/adb"
    scrcpy: str = "/opt/homebrew/bin/scrcpy"
    photo_dest: str = "~/Desktop"


@dataclass
class BehaviorConfig:
    auto_connect: bool = True
    poll_interval_seconds: int = 5


@dataclass
class AppConfig:
    security: SecurityConfig = field(default_factory=SecurityConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)

    # ------------------------------------------------------------------ #
    # Convenience accessors                                                #
    # ------------------------------------------------------------------ #

    @property
    def adb_bin(self) -> str:
        return self.paths.adb

    @property
    def scrcpy_bin(self) -> str:
        return self.paths.scrcpy

    @property
    def photo_dest_path(self) -> Path:
        return Path(self.paths.photo_dest).expanduser()

    @property
    def known_serial(self) -> str:
        return self.security.known_serial

    @known_serial.setter
    def known_serial(self, value: str) -> None:
        self.security.known_serial = value
        self.save()

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def save(self) -> None:
        """Persist current config to disk (round-trips through TOML)."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        lines = [
            "[security]\n",
            f"known_ssids = {self.security.known_ssids!r}\n",
            f'known_serial = "{self.security.known_serial}"\n',
            "\n[paths]\n",
            f'adb = "{self.paths.adb}"\n',
            f'scrcpy = "{self.paths.scrcpy}"\n',
            f'photo_dest = "{self.paths.photo_dest}"\n',
            "\n[behavior]\n",
            f"auto_connect = {'true' if self.behavior.auto_connect else 'false'}\n",
            f"poll_interval_seconds = {self.behavior.poll_interval_seconds}\n",
        ]
        CONFIG_FILE.write_text("".join(lines))


def load() -> AppConfig:
    """Load config from disk, creating the file with defaults if absent."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(_DEFAULT_TOML)

    raw = tomllib.loads(CONFIG_FILE.read_text())

    sec = raw.get("security", {})
    pth = raw.get("paths", {})
    beh = raw.get("behavior", {})

    return AppConfig(
        security=SecurityConfig(
            known_ssids=sec.get("known_ssids", []),
            known_serial=sec.get("known_serial", ""),
        ),
        paths=PathsConfig(
            adb=pth.get("adb", "/opt/homebrew/bin/adb"),
            scrcpy=pth.get("scrcpy", "/opt/homebrew/bin/scrcpy"),
            photo_dest=pth.get("photo_dest", "~/Desktop"),
        ),
        behavior=BehaviorConfig(
            auto_connect=beh.get("auto_connect", True),
            poll_interval_seconds=beh.get("poll_interval_seconds", 5),
        ),
    )


# Module-level singleton — imported by other modules as `from mcpixmirror.config import cfg`
cfg: AppConfig = load()


def reload() -> None:
    """Re-read config from disk and update the module singleton in place."""
    global cfg
    fresh = load()
    cfg.security = fresh.security
    cfg.paths = fresh.paths
    cfg.behavior = fresh.behavior
