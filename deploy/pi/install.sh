#!/usr/bin/env bash
# Idempotent installer for the Pi-side system config (systemd units, drop-ins,
# udev rules). Run on the Pi from the repo root after a `git pull`:
#
#   sudo bash deploy/pi/install.sh
#
# Safe to re-run; only restarts services whose config actually changed is NOT
# attempted — it always restarts the three data services (cheap: one missed
# sample). It never touches network, ZeroTier, or boot config.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSD=/etc/systemd/system

echo "== systemd units =="
install -m 0644 "$HERE/systemd/volthium-logger.service"           "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-uploader.service"         "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-events-uploader.service"  "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-usb-keepawake.service"    "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-usb-keepawake.timer"      "$SYSD/"
install -m 0755 "$HERE/bin/volthium-usb-keepawake.sh"             /usr/local/bin/
install -d "$SYSD/volthium-logger.service.d"
install -m 0644 "$HERE/systemd/volthium-logger.service.d/10-reader-env.conf" \
    "$SYSD/volthium-logger.service.d/"

# Retire the superseded tmpfs-era drop-ins (replaced by 10-reader-env.conf
# and by data/-based paths in the unit files).
rm -f "$SYSD/volthium-logger.service.d/10-tmpfs-events.conf"
rm -f "$SYSD/volthium-uploader.service.d/10-log-to-tmpfs.conf"
rmdir --ignore-fail-on-non-empty "$SYSD/volthium-uploader.service.d" 2>/dev/null || true

echo "== udev rules =="
install -m 0644 "$HERE/udev/50-volthium-ub500-usb-power.rules" /etc/udev/rules.d/
udevadm control --reload-rules
# Apply to the live dongle now (the rule itself only fires on device add).
for dev in /sys/bus/usb/devices/*; do
    [ -f "$dev/idVendor" ] || continue
    if [ "$(cat "$dev/idVendor")" = "2357" ] && [ "$(cat "$dev/idProduct")" = "0604" ]; then
        echo on > "$dev/power/control"
        echo "   autosuspend disabled on $(basename "$dev") (live)"
    fi
done

echo "== usb-keepawake timer =="
# The udev rule above only fires on device ADD; a dwc2 reset-in-place reverts
# power/control to 'auto' without re-firing it. This timer re-asserts every
# 30 s so the reset cascade can't sustain itself. See the investigation doc.
systemctl enable --now volthium-usb-keepawake.timer
echo "   volthium-usb-keepawake.timer enabled"

echo "== one-time migration: archive the pre-tmpfs event log =="
# The event log moves back from tmpfs to data/. A stale data/ble_events.jsonl
# from before the tmpfs era must not be re-uploaded (events ingest is not
# idempotent) — archive it out of the uploader's glob.
OLD=/srv/volthium_reader/data/ble_events.jsonl
if [ -f "$OLD" ] && ! systemctl show volthium-logger -p Environment | grep -q "data/ble_events.jsonl"; then
    mv "$OLD" "$OLD.pre-durable-archive"
    chown claude:users "$OLD.pre-durable-archive" 2>/dev/null || true
    echo "   archived stale $OLD"
fi

echo "== reload + restart =="
systemctl daemon-reload
systemctl restart volthium-logger volthium-uploader volthium-events-uploader
systemctl --no-pager --quiet is-active volthium-logger volthium-uploader volthium-events-uploader \
    && echo "   all services active"

echo "done."
