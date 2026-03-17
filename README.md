# McPixMirror

A macOS menu bar app that automatically connects your Mac to your Pixel over Wi-Fi (ADB Wireless Debugging) — securely and without manual reconnection after reboots.

## Features

- **Auto-discovery** — finds your Pixel via mDNS as soon as Wireless Debugging is on
- **Auto-connect** — reconnects automatically after phone reboots (handles port rotation)
- **Security-first** — only connects on trusted Wi-Fi SSIDs; pins your device's serial number
- **Push Clipboard** — sends your Mac clipboard to the phone
- **Pull Latest Photo** — grabs the newest photo from DCIM/Camera to your Desktop
- **Mirror Screen** — launches scrcpy with the correct flags (no "Multiple devices" error)

## Quick start

```bash
# 1. Install system tools
brew install android-platform-tools scrcpy python@3.13

# 2. Install McPixMirror
pip install -r requirements.txt
python -m mcpixmirror.app

# 3. On your Pixel: Settings → Developer Options → Wireless Debugging → Enable
#    Then pair once: adb pair <IP>:<pair-port>
```

See [docs/deploy.md](docs/deploy.md) for full setup and build instructions.

## Architecture

```
mcpixmirror/
├── app.py          # rumps menu bar app — wires everything together
├── discovery.py    # mDNS listener (_adb-tls-connect._tcp)
├── connection.py   # ADB state machine + mDNS double-entry fix
├── security.py     # SSID guard + device serial pinning
├── actions.py      # clipboard sync, photo pull, scrcpy launch
└── config.py       # ~/.config/mcpixmirror/config.toml
```

## Security model

1. **SSID allowlist** — ADB connections are refused on any network not in `known_ssids`
2. **Serial pinning** — on first connect you approve the device; thereafter only that serial is accepted
3. **No persistent pairing exposure** — pairing is one-time; the connect port changes every reboot (handled automatically)

## Development

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
ruff check mcpixmirror/
```

## Building a .app

```bash
./scripts/build_app.sh
```

See [docs/deploy.md](docs/deploy.md) for signing and notarization.

## License

MIT
