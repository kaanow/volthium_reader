#!/usr/bin/env bash
# Create / re-create the "Volthium Monitor" alias on the user's Desktop.
# Run this once after cloning the repo, or any time the alias gets deleted.
#
# The alias points at "Volthium Monitor.app" inside the repo, so any
# updates to the .app are picked up automatically.

set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
APP_SRC="${REPO}/Volthium Monitor.app"

if [ ! -d "$APP_SRC" ]; then
    echo "ERROR: '${APP_SRC}' not found." >&2
    exit 1
fi

osascript <<APPLESCRIPT
tell application "Finder"
    set src to POSIX file "${APP_SRC}" as alias
    set dest to path to desktop folder
    try
        delete (every item of dest whose name is "Volthium Monitor")
    end try
    try
        delete (every item of dest whose name is "Volthium Monitor.app")
    end try
    make new alias file at dest to src
end tell
APPLESCRIPT

echo "  ✓ created alias: ~/Desktop/Volthium Monitor"
echo "  double-click it to bring up the dashboard."
