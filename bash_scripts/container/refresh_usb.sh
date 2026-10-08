#!/bin/bash
# refresh_usb.sh — Scan for Kinect v2 devices and create /dev/bus/usb nodes
# Run inside the container (privileged container required)

set -e

echo "=== USB Device Refresh ==="
echo "Scanning for Kinect v2 devices (045e:02c4, 045e:02d8, 045e:02d9)..."

FOUND=0

for dev in /sys/bus/usb/devices/*/idVendor; do
    [ -f "$dev" ] || continue
    vendor=$(cat "$dev")
    if [ "$vendor" != "045e" ]; then
        continue
    fi

    dir=$(dirname "$dev")
    prod=$(cat "$dir/idProduct" 2>/dev/null || true)
    case "$prod" in
        02c4|02d8|02d9) ;;
        *) continue ;;
    esac

    busnum=$(cat "$dir/busnum")
    devnum=$(cat "$dir/devnum")
    devfile=$(cat "$dir/dev" 2>/dev/null || true)
    major=$(echo "$devfile" | cut -d: -f1)
    minor=$(echo "$devfile" | cut -d: -f2)
    nodepath="/dev/bus/usb/$busnum/$devnum"

    echo "  Found Kinect v2: bus=$busnum dev=$devnum ($major:$minor)  product=$prod"

    if [ -e "$nodepath" ]; then
        echo "    Device node already exists: $nodepath"
    else
        echo "    Creating device node: $nodepath"
        sudo mkdir -p "/dev/bus/usb/$busnum"
        sudo mknod "$nodepath" c "$major" "$minor" 2>/dev/null || {
            echo "    WARNING: Could not create $nodepath (no mknod capability?)"
            continue
        }
        sudo chmod 666 "$nodepath"
        echo "    Done."
    fi
    FOUND=$((FOUND + 1))
done

if [ "$FOUND" -eq 0 ]; then
    echo "No Kinect v2 devices found on the USB bus."
    echo "Check host with: lsusb | grep Microsoft"
    exit 1
fi

echo ""
echo "Refresh complete. $FOUND device(s) ready."
echo "You can now re-run: launch_kinect"
