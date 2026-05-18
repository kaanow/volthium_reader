#!/bin/bash
# Double-click this to: (1) start the logger if it isn't running, (2) start
# the dashboard if it isn't running, (3) open the dashboard in your browser.
#
# Finder shows this file as "Launch Volthium Monitor" and runs it in Terminal.

set -e
cd "$(dirname "$0")"

ADDR_A="9058AE7F-F98B-D0F6-237D-6769894DE118"
ADDR_B="6EC69980-CA43-7DEF-519B-6235C8C535B7"
CSV="data/pack.csv"
LOG="data/pack.log"
PORT=8421

mkdir -p data

started_logger=0
started_dashboard=0

if ! pgrep -f "scripts/log\.py.*${CSV}" > /dev/null; then
    nohup caffeinate -i .venv/bin/python scripts/log.py \
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

# Find the LAN IP so we can show a phone-friendly URL too.
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null)
[ -z "$LAN_IP" ] && LAN_IP=$(ipconfig getifaddr en1 2>/dev/null)

echo ""
echo "  ┌─ Volthium Monitor ─────────────────────────────────┐"
[ $started_logger    -eq 1 ] && echo "  │  • logger:    started"    || echo "  │  • logger:    already running"
[ $started_dashboard -eq 1 ] && echo "  │  • dashboard: started"    || echo "  │  • dashboard: already running"
echo "  │"
echo "  │  on this laptop:   http://localhost:${PORT}/"
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

echo "  You can close this Terminal window."
echo "  To stop everything: pkill -f scripts/log.py ; pkill -f scripts/dashboard.py"
echo ""

open "http://localhost:${PORT}/"
