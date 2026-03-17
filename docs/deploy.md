# Deployment Guide

## First-time setup (developer)

### 1. Install system dependencies

```bash
brew install android-platform-tools scrcpy python@3.13
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
# For development/testing:
pip install -r requirements-dev.txt
```

### 3. Pair your Pixel (one-time)

On your Pixel 7:
1. **Settings → Developer Options → Wireless Debugging → Enable**
2. Tap **"Pair device with pairing code"**
3. Note the IP address, pairing port (e.g. `192.168.1.212:34415`), and the 6-digit code

On your Mac:
```bash
adb pair 192.168.1.212:34415
# Enter the 6-digit code when prompted
# Output: Successfully paired to ...
```

> **Do not** use the pairing port to `adb connect`. The pairing port closes immediately
> after success. McPixMirror reads the persistent connect port via mDNS automatically.

### 4. Run McPixMirror

```bash
python -m mcpixmirror.app
# or, after pip install -e .:
mcpixmirror
```

On first launch:
- A dialog will ask you to **Trust** your Pixel. Click "Trust Device."
- The serial is saved to `~/.config/mcpixmirror/config.toml`.

### 5. Add your Wi-Fi SSID

Edit `~/.config/mcpixmirror/config.toml`:

```toml
[security]
known_ssids = ["YourHomeNetwork"]
```

Or use **Settings…** in the menu bar (opens the file in your default editor).

---

## Building a distributable .app

```bash
./scripts/build_app.sh
```

Output: `McPixMirror-0.1.0.dmg`

### Bypassing Gatekeeper (unsigned build)

The MVP is not notarized. Users must right-click → Open on first launch,
or run:

```bash
xattr -d com.apple.quarantine /Applications/McPixMirror.app
```

### Code-signing for wider distribution

1. Obtain an **Apple Developer ID Application** certificate.
2. Uncomment the signing steps in `.github/workflows/release.yml`.
3. Add `APPLE_CERT_BASE64` and `APPLE_CERT_PASSWORD` to GitHub Actions secrets.
4. For notarization, also add `APPLE_TEAM_ID`, `APPLE_ID`, and `APPLE_APP_PASSWORD`.

---

## Releasing a new version

```bash
# Bump version in pyproject.toml and mcpixmirror/__init__.py
git tag v0.2.0
git push origin v0.2.0
```

GitHub Actions (`release.yml`) will:
1. Run the full CI suite.
2. Build the `.dmg`.
3. Create a GitHub Release with the artifact attached.

---

## Troubleshooting

### "adb not found"

```bash
brew install android-platform-tools
# then update config if adb is not at /opt/homebrew/bin/adb:
# [paths]
# adb = "/usr/local/bin/adb"
```

### "scrcpy: Multiple (2) ADB devices"

McPixMirror should prevent this by disconnecting the mDNS transport before
connecting by IP. If it still occurs, run manually:

```bash
adb disconnect  # clears all TCP/IP connections
# then restart McPixMirror
```

### Port changed after phone reboot

This is expected. Wireless Debugging assigns a new port on each restart.
McPixMirror detects the new port via mDNS and reconnects automatically.
No action needed.

### "SSID not in trusted list"

Open `~/.config/mcpixmirror/config.toml` and add your SSID:

```toml
[security]
known_ssids = ["YourSSID"]
```

### ADB keeps disconnecting

Check that **Wireless Debugging** is still enabled on the Pixel
(Developer Options → Wireless Debugging). Some Android power-management
settings disable it when the screen is off. Enable "Stay awake" in
Developer Options if this is a persistent issue.
