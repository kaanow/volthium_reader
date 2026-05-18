#!/usr/bin/env bash
# One-command regenerate of both netlists. Run from hardware/kicad/.
#
# Requires:
#   - KiCad 8 installed (for symbol/footprint libraries)
#   - .venv/ at the repo root with skidl installed (see ../../requirements-hw.txt)
#   - Env vars for KiCad lib paths exported (auto-detected on macOS below)

set -euo pipefail

cd "$(dirname "$0")"
REPO=$(cd ../.. && pwd)

# --- locate KiCad libraries (best-effort autodetection) ---
detect_kicad_paths() {
    local roots=(
        "/Applications/KiCad/KiCad.app/Contents/SharedSupport"
        "/usr/share/kicad"
        "/usr/local/share/kicad"
        "/opt/homebrew/share/kicad"
    )
    for r in "${roots[@]}"; do
        if [ -d "$r/symbols" ]; then
            export KICAD8_SYMBOL_DIR="$r/symbols"
            export KICAD8_FOOTPRINT_DIR="$r/footprints"
            export KICAD_SYMBOL_DIR="$r/symbols"
            echo "  Found KiCad libs at: $r"
            return 0
        fi
    done
    echo "  WARNING: could not find KiCad libraries; SKiDL will run in best-effort mode."
    return 1
}

echo "=== Volthium hardware regenerate ==="
detect_kicad_paths || true

PY=$REPO/.venv/bin/python
if [ ! -x "$PY" ]; then
    echo "ERROR: $PY not found. Run from repo root:"
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/pip install -r requirements.txt -r requirements-hw.txt"
    exit 1
fi

mkdir -p outputs

echo
echo "--- battery_side.py ---"
"$PY" battery_side.py

echo
echo "--- display_side.py ---"
"$PY" display_side.py

echo
echo "=== done — outputs/ contains the netlists ==="
ls -la outputs/
