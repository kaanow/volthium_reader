#!/usr/bin/env bash
# Pull the Xanbus + Modbus capture corpus OFF the barge Pi to this machine, so
# the heavy correlation/decode (xanbus_decode.py) runs here and NEVER on the
# 1 GB Pi. See CLAUDE.md — decoding on the Pi caused the 2026-07-26 outage.
#
# Safe on the Pi by construction:
#   - read-only: rsync only *reads* files over SSH, never writes/executes there.
#   - near-zero Pi memory: rsync's sender cost scales with the file *count*
#     (~a thousand tiny names), not their contents; each file streams through.
#   - only the ROTATED, immutable *.jsonl.gz are pulled — never the live
#     .jsonl the writer is appending to — so there's no race and no partial file.
#   - --ignore-existing: rotated gz never change, so each is transferred exactly
#     once; re-runs are cheap and only fetch new windows.
#
# Usage:
#   scripts/pull_captures.sh [dest_dir]      # default dest: ./captures
# Then decode locally (caps raised — this box has RAM):
#   python3 scripts/xanbus_decode.py --data-dir <dest_dir> --hours 24 \
#       --max-frames 5000000
set -euo pipefail

DEST="${1:-captures}"
# SSH fallback chain (see memory kwpi-ssh-paths): kwpi.zt DNS flaps; fall back to
# the ZeroTier IPs. First host that answers wins.
HOSTS=(kwpi.zt 10.42.100.200 192.168.192.101)
USER=kaan
REMOTE=/srv/volthium_reader/data

host=""
for h in "${HOSTS[@]}"; do
    if ssh -o ConnectTimeout=8 -o BatchMode=yes "${USER}@${h}" true 2>/dev/null; then
        host="$h"; break
    fi
done
if [ -z "$host" ]; then
    echo "ERROR: no Pi host reachable (tried: ${HOSTS[*]})" >&2
    exit 1
fi
echo "== pulling from ${USER}@${host} into ${DEST}/ =="

mkdir -p "${DEST}/xanbus" "${DEST}/modbus"

# --ignore-existing: rotated gz are immutable -> transfer each once.
# --prune-empty-dirs + include filters: pull ONLY the closed *.jsonl.gz.
# Conservative flags: work on stock macOS rsync 2.6.9 and modern rsync alike.
common=(-az --ignore-existing --stats -e "ssh -o ConnectTimeout=8")
rsync "${common[@]}" \
    --include='xanbus-*.jsonl.gz' --exclude='*' \
    "${USER}@${host}:${REMOTE}/xanbus/" "${DEST}/xanbus/"
rsync "${common[@]}" \
    --include='modbus-*.jsonl.gz' --exclude='*' \
    "${USER}@${host}:${REMOTE}/modbus/" "${DEST}/modbus/"

echo "== local corpus now: =="
du -sh "${DEST}/xanbus" "${DEST}/modbus" 2>/dev/null || true
echo "xanbus files: $(ls -1 "${DEST}/xanbus"/*.gz 2>/dev/null | wc -l | tr -d ' ')"
echo "modbus files: $(ls -1 "${DEST}/modbus"/*.gz 2>/dev/null | wc -l | tr -d ' ')"
echo
echo "next: python3 scripts/xanbus_decode.py --data-dir ${DEST} --hours 24 --max-frames 5000000"
