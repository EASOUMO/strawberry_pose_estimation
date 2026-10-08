#!/bin/bash
# network_setup.sh — auto-detect interfaces by MAC, survive PCI bus renumbering
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Onboard Realtek (always the "Default" internet port)
ONBOARD_MAC="18:c0:4d:e5:74:d5"

# 4-port Intel NIC — matched by MAC prefix (first 5 octets)
NIC_MAC_PREFIX="90:e2:ba:5b:72"

# Each port on the 4-port NIC, identified by last octet of MAC
#   :ec → Vicon       :ed → Realsense #1
#   :ee → Realsense #2  :ef → Velodyne LiDAR
PORT_MAC_LAST=("ec" "ed" "ee" "ef")

# Connection config: label, ip/mask, mtu, matching last-MAC-octet
declare -A CONN_LABEL  CONN_IP  CONN_MTU
# Vicon
CONN_LABEL["ec"]="Vicon";        CONN_IP["ec"]="192.168.10.102/24"; CONN_MTU["ec"]=""

# ---------------------------------------------------------------------------
require_root() {
    if [[ ${EUID} -ne 0 ]]; then
        echo -e "${RED}ERROR:${NC} run this script with sudo"
        exit 1
    fi
}

require_nmcli() {
    if ! command -v nmcli >/dev/null 2>&1; then
        echo -e "${RED}ERROR:${NC} nmcli is not installed"
        exit 1
    fi
    if ! systemctl is-active --quiet NetworkManager; then
        echo -e "${RED}ERROR:${NC} NetworkManager is not active"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Resolve interface names from MACs (handles enp5 ↔ enp6 shifts)
# ---------------------------------------------------------------------------
resolve_iface_by_mac() {
    local mac="$1"
    ip -br link show | awk -v m="$mac" '$3 == m {print $1}'
}

find_4port_iface() {
    local last_octet="$1"
    local target_mac="${NIC_MAC_PREFIX}:${last_octet}"
    resolve_iface_by_mac "$target_mac"
}

# ---------------------------------------------------------------------------
detect_interfaces() {
    echo -e "${BLUE}Scanning interfaces...${NC}"

    DEFAULT_IFACE=$(resolve_iface_by_mac "$ONBOARD_MAC")
    if [[ -z "$DEFAULT_IFACE" ]]; then
        echo -e "${YELLOW}Warning:${NC} onboard NIC ($ONBOARD_MAC) not found — using first non-4port enp*"
        DEFAULT_IFACE=$(ip -br link show | awk '/^enp/ && $3 !~ /^'"${NIC_MAC_PREFIX//./\\.}"'/ {print $1; exit}')
    fi
    echo -e "  ${GREEN}Default${NC}  → ${DEFAULT_IFACE:-NOT FOUND}"

    for octet in "${PORT_MAC_LAST[@]}"; do
        local iface
        iface=$(find_4port_iface "$octet")
        if [[ -n "$iface" ]]; then
            echo -e "  ${GREEN}${CONN_LABEL[$octet]}${NC} → ${iface}  (${CONN_IP[$octet]})"
        else
            echo -e "  ${YELLOW}${CONN_LABEL[$octet]}${NC} → NOT FOUND  (MAC ${NIC_MAC_PREFIX}:${octet})"
        fi
    done
    echo
}

# ---------------------------------------------------------------------------
apply_connection() {
    local label="$1" iface="$2" ip_mask="$3" mtu="${4:-}"
    local con_name="$label"

    if [[ -z "$iface" ]]; then
        echo -e "${YELLOW}skipping${NC} $label — interface not present"
        return
    fi

    # Create profile if missing
    if ! nmcli -t -f NAME connection show | grep -Fxq "$con_name"; then
        local extra_args=()
        [[ -n "$mtu" ]] && extra_args+=(802-3-ethernet.mtu "$mtu")

        if [[ "$ip_mask" == "dhcp" ]]; then
            nmcli connection add type ethernet con-name "$con_name" \
                ifname "$iface" autoconnect yes "${extra_args[@]}"
        else
            nmcli connection add type ethernet con-name "$con_name" \
                ifname "$iface" autoconnect yes \
                ipv4.method manual ipv4.addresses "$ip_mask" "${extra_args[@]}"
        fi
        echo -e "${GREEN}created${NC} $con_name on $iface"
    fi

    # Update binding and activate
    nmcli connection modify "$con_name" connection.interface-name "$iface"
    nmcli connection modify "$con_name" connection.autoconnect yes
    nmcli connection up "$con_name" ifname "$iface" >/dev/null 2>&1 || true
    echo -e "${GREEN}bound${NC}   $con_name → $iface"
}

# ---------------------------------------------------------------------------
create_profiles() {
    echo -e "${BLUE}Creating NetworkManager connection profiles...${NC}"

    local default_iface
    default_iface=$(resolve_iface_by_mac "$ONBOARD_MAC")
    [[ -z "$default_iface" ]] && default_iface="enp4s0"
    apply_connection "Default" "$default_iface" "dhcp"

    for octet in "${PORT_MAC_LAST[@]}"; do
        local iface
        iface=$(find_4port_iface "$octet")
        apply_connection "${CONN_LABEL[$octet]}" "$iface" "${CONN_IP[$octet]}" "${CONN_MTU[$octet]}"
    done

    echo
    echo -e "${GREEN}Profiles created.${NC} Run 'sudo ./network_setup.sh apply' to activate."
}

apply_all() {
    echo -e "${BLUE}Applying connections to detected interfaces...${NC}"

    local default_iface
    default_iface=$(resolve_iface_by_mac "$ONBOARD_MAC")
    [[ -z "$default_iface" ]] && default_iface="enp4s0"
    apply_connection "Default" "$default_iface" "dhcp"

    for octet in "${PORT_MAC_LAST[@]}"; do
        local iface
        iface=$(find_4port_iface "$octet")
        apply_connection "${CONN_LABEL[$octet]}" "$iface" "${CONN_IP[$octet]}" "${CONN_MTU[$octet]}"
    done

    echo
    echo -e "${GREEN}Done.${NC} Bindings will survive reboots regardless of PCI bus numbering."
}

reset_all() {
    echo -e "${BLUE}Unbinding all profiles...${NC}"
    for conn in "Default" "Vicon" "Realsense #1" "Realsense #2" "Velodyne"; do
        if nmcli -t -f NAME connection show | grep -Fxq "$conn"; then
            nmcli connection modify "$conn" connection.interface-name ""
            echo -e "${YELLOW}unbound${NC} $conn"
        fi
    done
}

delete_all() {
    echo -e "${RED}Deleting all connection profiles...${NC}"
    for conn in "Default" "Vicon" "Realsense #1" "Realsense #2" "Velodyne"; do
        if nmcli -t -f NAME connection show | grep -Fxq "$conn"; then
            nmcli connection delete "$conn"
            echo -e "${YELLOW}deleted${NC} $conn"
        fi
    done
}

show_status() {
    echo -e "${BLUE}Device status:${NC}"
    nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
    echo
    echo -e "${BLUE}Saved connections:${NC}"
    nmcli -f NAME,TYPE,AUTOCONNECT,DEVICE connection show
    echo
    detect_interfaces
}

# ---------------------------------------------------------------------------
main() {
    local action="${1:-apply}"

    require_root
    require_nmcli

    case "$action" in
        create)  create_profiles ;;
        apply)   apply_all ;;
        reset)   reset_all ;;
        delete)  delete_all ;;
        status)  show_status ;;
        detect)  detect_interfaces ;;
        -h|--help|help)
            echo "Usage: sudo ./network_setup.sh [create|apply|reset|delete|status|detect]"
            echo
            echo "  create  — build connection profiles using detected interfaces"
            echo "  apply   — bind profiles to detected interfaces & activate"
            echo "  reset   — unbind profiles (keep profiles)"
            echo "  delete  — remove all profiles"
            echo "  status  — show current state & interface mapping"
            echo "  detect  — just show which MAC → interface mapping was found"
            ;;
        *)  echo "Usage: sudo ./network_setup.sh [create|apply|reset|delete|status|detect]"
            exit 1 ;;
    esac
}

main "$@"
