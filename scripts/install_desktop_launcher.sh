#!/usr/bin/env bash
# Create / re-create a Desktop launcher for the Volthium Monitor.
#
# macOS: makes a Finder alias to "Volthium Monitor.app" — double-clickable,
#        silent, opens the dashboard in your default browser.
# Linux: writes a .desktop file pointing at "Launch Volthium Monitor.command".
#        Works on Pis / desktops that have a graphical session; on a fully
#        headless Pi, prefer a systemd unit instead (see README).
#
# Run this once after cloning the repo, or any time the launcher gets deleted.

set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
APP_SRC="${REPO}/Volthium Monitor.app"
CMD_SRC="${REPO}/Launch Volthium Monitor.command"

case "$(uname -s)" in
    Darwin)
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
        ;;

    Linux)
        if [ ! -f "$CMD_SRC" ]; then
            echo "ERROR: '${CMD_SRC}' not found." >&2
            exit 1
        fi
        DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
        APPS_DIR="$HOME/.local/share/applications"
        mkdir -p "$APPS_DIR"

        DESKTOP_FILE="$APPS_DIR/volthium-monitor.desktop"
        cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Volthium Monitor
Comment=Start the Volthium logger + dashboard and open it in a browser
Exec=bash -c "cd '${REPO}' && ./'Launch Volthium Monitor.command'"
Terminal=true
Categories=Utility;
DESKTOP
        chmod +x "$DESKTOP_FILE"
        echo "  ✓ wrote ${DESKTOP_FILE}"

        if [ -d "$DESKTOP_DIR" ]; then
            cp "$DESKTOP_FILE" "$DESKTOP_DIR/volthium-monitor.desktop"
            chmod +x "$DESKTOP_DIR/volthium-monitor.desktop"
            # GNOME / some file managers need this trust flag set:
            command -v gio >/dev/null 2>&1 && gio set "$DESKTOP_DIR/volthium-monitor.desktop" metadata::trusted true 2>/dev/null || true
            echo "  ✓ copied to ${DESKTOP_DIR}/volthium-monitor.desktop"
        else
            echo "  (no ${DESKTOP_DIR}; skipped Desktop copy — use the application menu)"
        fi

        echo ""
        echo "  Headless Pi? You probably want a systemd unit instead — see README."
        ;;

    *)
        echo "ERROR: unsupported OS '$(uname -s)'." >&2
        exit 1
        ;;
esac
