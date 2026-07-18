#!/bin/sh
# Re-assert USB-autosuspend-disable for the TP-Link UB500 (RTL8761B).
#
# The udev rule (50-volthium-ub500-usb-power.rules) only fires on device
# ADD. A dwc2 reset-in-place (`usb 1-1.5: reset full-speed USB device`)
# does NOT re-fire ADD, so power/control silently reverts to 'auto' after
# every reset — re-enabling the autosuspend/scan-cadence race that causes
# the NEXT reset. Each reset thus disables the protection meant to prevent
# it, and resets cluster. See docs/investigations/2026-07-16-bt-wedge-
# causation.md (the 2026-07-18 02:09Z/03:18Z UB500 reset cluster).
#
# This runs on a 30 s timer and re-asserts power/control=on whenever it has
# drifted, closing the window a reset reopens. Matches by VID:PID so it
# follows the dongle across bus-path / hci-index changes.
set -eu

VID=2357
PID=0604

for dev in /sys/bus/usb/devices/*; do
    [ -r "$dev/idVendor" ] || continue
    [ "$(cat "$dev/idVendor" 2>/dev/null)" = "$VID" ] || continue
    [ "$(cat "$dev/idProduct" 2>/dev/null)" = "$PID" ] || continue
    ctrl="$dev/power/control"
    [ -w "$ctrl" ] || continue
    if [ "$(cat "$ctrl" 2>/dev/null)" != "on" ]; then
        echo on > "$ctrl"
        logger -t volthium-usb-keepawake \
            "re-asserted power/control=on for $(basename "$dev") (had drifted to auto)"
    fi
done
