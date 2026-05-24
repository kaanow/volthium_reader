#!/bin/bash
# Double-click this on a Mac (Finder shows it as "Launch Volthium Monitor"
# and runs it in Terminal), or run it directly on Linux:
#     ./'Launch Volthium Monitor.command'
#
# (1) start the logger if it isn't running, (2) start the weather poller and
# the dashboard if they aren't running, (3) open the dashboard in a browser
# (best-effort on headless Linux), (4) print a phone-friendly LAN URL + QR.

set -e
cd "$(dirname "$0")"

# Battery addresses live in pack.env (committed — the two physical packs
# never change). The file holds both macOS CoreBluetooth UUIDs and Linux
# BlueZ MACs; we pick the pair that matches this OS.
. "$(dirname "$0")/pack.env"

CSV="data/pack.csv"
LOG="data/pack.log"
PORT=8421

mkdir -p data

# OS-specific shims: address pair, keepawake prefix, browser-open, LAN-IP.
KEEPAWAKE=()
case "$(uname -s)" in
    Darwin)
        ADDR_A="$ADDR_A_DARWIN"
        ADDR_B="$ADDR_B_DARWIN"
        KEEPAWAKE=(caffeinate -i)
        open_url()  { open "$1"; }
        lan_ip()    { ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null; }
        ;;
    Linux)
        ADDR_A="$ADDR_A_LINUX"
        ADDR_B="$ADDR_B_LINUX"
        if command -v systemd-inhibit >/dev/null 2>&1; then
            KEEPAWAKE=(systemd-inhibit --what=sleep --why=volthium-logger --mode=block)
        fi
        open_url()  { command -v xdg-open >/dev/null 2>&1 && xdg-open "$1" >/dev/null 2>&1 || true; }
        lan_ip()    { hostname -I 2>/dev/null | awk '{print $1}'; }
        ;;
    *)
        open_url()  { :; }
        lan_ip()    { :; }
        ;;
esac

if [ -z "${ADDR_A:-}" ] || [ -z "${ADDR_B:-}" ]; then
    echo "ERROR: pack.env has no addresses for $(uname -s)." >&2
    echo "  Run:    .venv/bin/python scripts/scan.py" >&2
    echo "  Paste:  the two V-12V200AH-* addresses into pack.env" >&2
    echo "          (ADDR_A_LINUX=… / ADDR_B_LINUX=… on this machine)" >&2
    exit 1
fi

started_logger=0
started_dashboard=0

if ! pgrep -f "scripts/log\.py.*${CSV}" > /dev/null; then
    nohup "${KEEPAWAKE[@]}" .venv/bin/python scripts/log.py \
        --a "$ADDR_A" --b "$ADDR_B" \
        --interval 10 --csv "$CSV" --log "$LOG" \
        > /dev/null 2>&1 &
    disown
    started_logger=1
fi

if ! pgrep -f "scripts/weather\.py" > /dev/null; then
    nohup .venv/bin/python scripts/weather.py --loop --interval 1800 \
        --csv data/weather.csv \
        > /dev/null 2>&1 &
    disown
fi

if ! pgrep -f "scripts/dashboard\.py.*${PORT}" > /dev/null; then
    nohup .venv/bin/python scripts/dashboard.py \
        --csv "$CSV" --weather-csv data/weather.csv \
        --port "$PORT" --host 0.0.0.0 \
        > /dev/null 2>&1 &
    disown
    started_dashboard=1
fi

# Give the dashboard a beat to bind the port before we open the browser.
sleep 1

LAN_IP=$(lan_ip)

echo ""
echo "  ┌─ Volthium Monitor ─────────────────────────────────┐"
[ $started_logger    -eq 1 ] && echo "  │  • logger:    started"    || echo "  │  • logger:    already running"
[ $started_dashboard -eq 1 ] && echo "  │  • dashboard: started"    || echo "  │  • dashboard: already running"
echo "  │"
echo "  │  on this machine:  http://localhost:${PORT}/"
if [ -n "$LAN_IP" ]; then
    echo "  │  on the LAN:       http://${LAN_IP}:${PORT}/"
fi
echo "  └────────────────────────────────────────────────────┘"

# QR code so a phone can hop on without typing the URL.
if [ -n "$LAN_IP" ] && .venv/bin/python -c "import qrcode" 2>/dev/null; then
    echo ""
    echo "  scan from your phone:"
    .venv/bin/python -c "
import qrcode
q = qrcode.QRCode(border=1)
q.add_data('http://${LAN_IP}:${PORT}/')
q.print_ascii(invert=True)
"
fi

echo "  You can close this terminal window."
echo "  To stop everything: pkill -f scripts/log.py ; pkill -f scripts/dashboard.py ; pkill -f scripts/weather.py"
echo ""

open_url "http://localhost:${PORT}/"
