#!/usr/bin/env bash
# Build McPixMirror.app for local distribution using py2app.
#
# Prerequisites:
#   brew install python@3.13 android-platform-tools scrcpy
#   python3.13 -m pip install rumps py2app --break-system-packages
#
# Usage:
#   ./scripts/build_app.sh
#
# Output:
#   dist/McPixMirror.app  — runnable .app bundle

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Checking dependencies"
python3.13 -c "import rumps, py2app" || {
  echo "Installing dependencies..."
  python3.13 -m pip install rumps py2app --break-system-packages -q
}

echo "==> Cleaning previous build"
rm -rf build/ dist/

echo "==> Building McPixMirror.app"
# Temporarily hide pyproject.toml — py2app 0.28 misreads its dependencies field
mv pyproject.toml pyproject.toml.bak
python3.13 setup.py py2app
mv pyproject.toml.bak pyproject.toml

echo ""
echo "Done! App bundle: dist/McPixMirror.app"
echo "To install: cp -r dist/McPixMirror.app /Applications/"
echo ""
echo "To bypass Gatekeeper on first launch (unsigned build):"
echo "  xattr -d com.apple.quarantine /Applications/McPixMirror.app"
echo ""
echo "Or right-click the app → Open to launch it the first time."
