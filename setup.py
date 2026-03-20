"""py2app build script for McPixMirror.app.

Usage:
    python3.13 setup.py py2app

Output: dist/McPixMirror.app
"""

from setuptools import setup

APP = ["mcpixmirror/app.py"]

OPTIONS = {
    "argv_emulation": False,  # must be False for menu bar apps
    "plist": {
        "CFBundleName": "McPixMirror",
        "CFBundleDisplayName": "McPixMirror",
        "CFBundleIdentifier": "com.mcpixmirror",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        # Run as a background/menu bar app — no Dock icon
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
    "packages": ["mcpixmirror", "rumps"],
    "includes": ["tomllib"],
    "excludes": ["zeroconf"],
}

setup(
    name="McPixMirror",
    app=APP,
    options={"py2app": OPTIONS},
)
