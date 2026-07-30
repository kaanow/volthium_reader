#!/usr/bin/env bash
# Idempotent installer for the Pi-side system config (systemd units, drop-ins,
# udev rules). Run on the Pi from the repo root after a `git pull`:
#
#   cd /srv/volthium_reader && sudo bash deploy/pi/install.sh
#
# Safe to re-run. This is also the deterministic RECOVERY step after a reboot /
# power-cycle: it guarantees the wired RS485 stack is installed, the stable
# serial symlinks exist, telemetry is OOM-protected, and the right services are
# enabled — regardless of whatever ad-hoc state was or wasn't on the box.
# It never touches network, ZeroTier, or boot config.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSD=/etc/systemd/system

echo "== systemd units =="
# Primary wired telemetry path + the two decode-capture services.
install -m 0644 "$HERE/systemd/volthium-rs485-logger.service"     "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-xanbus-capture.service"   "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-modbus-poll.service"      "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-uploader.service"         "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-events-uploader.service"  "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-xanbus-telemetry.service" "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-usb-keepawake.service"    "$SYSD/"
install -m 0644 "$HERE/systemd/volthium-usb-keepawake.timer"      "$SYSD/"
install -m 0755 "$HERE/bin/volthium-usb-keepawake.sh"             /usr/local/bin/
# BLE logger kept as a DORMANT fallback (file present, not enabled). See
# deploy/pi/README.md for the RS485<->BLE flip.
install -m 0644 "$HERE/systemd/volthium-logger.service"           "$SYSD/"
install -d "$SYSD/volthium-logger.service.d"
install -m 0644 "$HERE/systemd/volthium-logger.service.d/10-reader-env.conf" \
    "$SYSD/volthium-logger.service.d/"

# Retire the superseded tmpfs-era drop-ins.
rm -f "$SYSD/volthium-logger.service.d/10-tmpfs-events.conf"
rm -f "$SYSD/volthium-uploader.service.d/10-log-to-tmpfs.conf"
rmdir --ignore-fail-on-non-empty "$SYSD/volthium-uploader.service.d" 2>/dev/null || true

echo "== udev rules =="
install -m 0644 "$HERE/udev/50-volthium-ub500-usb-power.rules" /etc/udev/rules.d/
# RS485 stable names (/dev/ttyRS485-a|b by USB *port path*, immune to ttyUSB
# renumbering) + autosuspend-off for the wired adapters. Without this the
# rs485-logger can't find its serial ports after a reboot.
install -m 0644 "$HERE/udev/99-volthium-rs485.rules" /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger --subsystem-match=tty --action=add
# Apply UB500 autosuspend-off to the live dongle now (rule only fires on add).
for dev in /sys/bus/usb/devices/*; do
    [ -f "$dev/idVendor" ] || continue
    if [ "$(cat "$dev/idVendor")" = "2357" ] && [ "$(cat "$dev/idProduct")" = "0604" ]; then
        echo on > "$dev/power/control"
        echo "   autosuspend disabled on $(basename "$dev") (live)"
    fi
done

echo "== one-time migration: archive the pre-tmpfs event log =="
OLD=/srv/volthium_reader/data/ble_events.jsonl
if [ -f "$OLD" ] && ! systemctl show volthium-logger -p Environment | grep -q "data/ble_events.jsonl"; then
    mv "$OLD" "$OLD.pre-durable-archive"
    chown claude:users "$OLD.pre-durable-archive" 2>/dev/null || true
    echo "   archived stale $OLD"
fi

echo "== reload + enable + restart =="
systemctl daemon-reload
# Enable the boot-critical set so a bare power-cycle recovers with no human.
systemctl enable volthium-rs485-logger volthium-xanbus-capture \
    volthium-modbus-poll volthium-uploader volthium-events-uploader \
    volthium-xanbus-telemetry volthium-usb-keepawake.timer
# BLE logger is the dormant fallback — present but must NOT auto-start
# (Conflicts= with the RS485 logger; run exactly one).
systemctl disable volthium-logger 2>/dev/null || true
systemctl stop volthium-logger 2>/dev/null || true
# (Re)start the live data path. Brief (~one sample) gap on a running system.
systemctl restart volthium-rs485-logger volthium-xanbus-capture \
    volthium-modbus-poll volthium-uploader volthium-events-uploader \
    volthium-xanbus-telemetry
systemctl start volthium-usb-keepawake.timer

echo "== status =="
for s in volthium-rs485-logger volthium-xanbus-capture volthium-modbus-poll \
         volthium-uploader volthium-events-uploader volthium-xanbus-telemetry; do
    printf "   %-32s %s\n" "$s" "$(systemctl is-active "$s")"
done
echo "done."
