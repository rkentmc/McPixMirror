#!/usr/bin/env bash
# Build McPixMirror.app for local distribution.
#
# Prerequisites:
#   brew install python@3.13
#   pip install briefcase
#
# Usage:
#   ./scripts/build_app.sh
#
# Output:
#   macOS/McPixMirror/McPixMirror.app  — runnable .app bundle
#   McPixMirror-*.dmg                  — distributable disk image

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Installing runtime dependencies"
pip install -r requirements.txt

echo "==> Installing Briefcase"
pip install briefcase

echo "==> Building .app"
briefcase build macOS

echo "==> Packaging .dmg"
briefcase package macOS

echo ""
echo "Done! Find your artifacts:"
find . -name "*.app" -o -name "*.dmg" | grep -v ".git"

echo ""
echo "To bypass Gatekeeper on first launch (unsigned build):"
echo "  xattr -d com.apple.quarantine /Applications/McPixMirror.app"
