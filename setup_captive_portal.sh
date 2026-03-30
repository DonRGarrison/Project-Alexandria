#!/bin/bash
# ============================================================
# Kiwix Captive Portal - Setup Script for ApachePi
# Raspberry Pi 5 / Debian GNU/Linux 13 (Trixie)
# ============================================================
# This script:
#   1. Installs the captive portal Python server as a systemd service
#   2. Configures nftables to redirect all HTTP (port 80) and HTTPS
#      (port 443) traffic from connected clients to the portal
#   3. Configures NetworkManager's built-in dnsmasq to hijack DNS
#      (resolves all domains to the portal IP for captive portal detection)
#   4. Makes everything persistent across reboots
#
# Prerequisites:
#   - ApachePi: Raspberry Pi 5 running Debian 13 (Trixie)
#   - WiFi AP already configured via NetworkManager on 10.42.0.1
#   - Kiwix server running on 10.42.0.1:8080
#   - Run as: sudo bash setup_captive_portal.sh (from apachepi user)
#
# Usage:  sudo bash setup_captive_portal.sh
# ============================================================

set -euo pipefail

# --- Configuration ---
PORTAL_IP="10.42.0.1"
PORTAL_PORT=80
KIWIX_PORT=8080
AP_INTERFACE="wlan0"          # Change if your AP uses a different interface
INSTALL_DIR="/opt/kiwix-portal"
LOG_DIR="/var/log/kiwix-portal"
NFT_CONF="/etc/nftables.d/captive-portal.conf"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Preflight checks ---
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo)."
    exit 1
fi

echo "========================================"
echo "  Kiwix Captive Portal - Setup"
echo "  Debian 13 (Trixie)"
echo "========================================"
echo ""
echo "  Portal:  http://${PORTAL_IP}"
echo "  Kiwix:   http://${PORTAL_IP}:${KIWIX_PORT}"
echo "  AP Iface: ${AP_INTERFACE}"
echo ""

# --- Detect AP interface automatically if possible ---
if ! ip link show "$AP_INTERFACE" &>/dev/null; then
    echo "WARNING: Interface '${AP_INTERFACE}' not found."
    echo "Available wireless interfaces:"
    iw dev 2>/dev/null | grep Interface | awk '{print "  " $2}'
    read -rp "Enter your AP interface name: " AP_INTERFACE
    if ! ip link show "$AP_INTERFACE" &>/dev/null; then
        echo "ERROR: Interface '${AP_INTERFACE}' not found. Exiting."
        exit 1
    fi
fi

# --- Install dependencies ---
echo "[1/6] Installing dependencies..."
apt-get update -qq
apt-get install -y -qq nftables python3 > /dev/null

# --- Install portal files ---
echo "[2/6] Installing captive portal server..."
mkdir -p "$INSTALL_DIR"
cp "${SCRIPT_DIR}/captive_portal.py" "${INSTALL_DIR}/captive_portal.py"
chmod +x "${INSTALL_DIR}/captive_portal.py"
mkdir -p "$LOG_DIR"

# --- Create systemd service ---
echo "[3/6] Creating systemd service..."
cat > /etc/systemd/system/kiwix-portal.service <<EOF
[Unit]
Description=Kiwix Captive Portal
After=network-online.target NetworkManager.service nftables.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/captive_portal.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kiwix-portal.service

# --- Configure nftables ---
echo "[4/6] Configuring nftables redirect rules..."

# Create nftables drop-in directory if it doesn't exist
mkdir -p /etc/nftables.d

# Write captive portal nftables rules
cat > "$NFT_CONF" <<EOF
# Kiwix Captive Portal - nftables NAT rules
# Redirect HTTP/HTTPS from WiFi clients to the captive portal

table ip captive_portal {
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;

        # Redirect HTTP (port 80) to the portal, except traffic already
        # destined for the Pi itself
        iifname "${AP_INTERFACE}" ip daddr != ${PORTAL_IP} tcp dport 80 dnat to ${PORTAL_IP}:${PORTAL_PORT}

        # Redirect HTTPS (port 443) to the portal as well
        # (triggers captive portal detection on most devices)
        iifname "${AP_INTERFACE}" ip daddr != ${PORTAL_IP} tcp dport 443 dnat to ${PORTAL_IP}:${PORTAL_PORT}
    }
}
EOF

# Ensure main nftables.conf includes the drop-in directory.
# Trixie's default nftables.conf may not have an include directive.
if ! grep -q 'include.*/etc/nftables.d/\*' /etc/nftables.conf 2>/dev/null; then
    echo "" >> /etc/nftables.conf
    echo '# Include drop-in configs' >> /etc/nftables.conf
    echo 'include "/etc/nftables.d/*.conf"' >> /etc/nftables.conf
fi

# Flush any previous captive_portal table and apply new rules
nft delete table ip captive_portal 2>/dev/null || true
nft -f "$NFT_CONF"

# Enable nftables service so rules persist across reboots
systemctl enable nftables.service

# --- Configure DNS hijacking via NetworkManager's dnsmasq ---
echo "[5/6] Configuring DNS hijacking via NetworkManager dnsmasq..."

# NetworkManager already runs its own dnsmasq instance for the hotspot
# on 10.42.0.1:53. We add a drop-in config to make it resolve all
# domains to the portal IP (DNS hijacking for captive portal detection).
mkdir -p /etc/NetworkManager/dnsmasq-shared.d

cat > /etc/NetworkManager/dnsmasq-shared.d/captive-portal.conf <<EOF
# Kiwix Captive Portal - DNS Override
# Resolve ALL domains to the portal IP so captive portal detection triggers
# and all HTTP requests land on our welcome page.

# Answer all DNS queries with the portal IP
address=/#/${PORTAL_IP}

# Set a short TTL so devices re-query quickly
local-ttl=0
EOF

# Disable the standalone dnsmasq service if it was installed previously,
# since NetworkManager runs its own dnsmasq for the hotspot
if systemctl is-enabled dnsmasq.service 2>/dev/null | grep -q enabled; then
    echo "  Disabling standalone dnsmasq (NetworkManager runs its own)..."
    systemctl stop dnsmasq.service 2>/dev/null || true
    systemctl disable dnsmasq.service 2>/dev/null || true
fi

# Restart NetworkManager to pick up the new dnsmasq config
echo "  Restarting NetworkManager to apply DNS config..."
systemctl restart NetworkManager

# Wait briefly for NM to re-establish the hotspot and dnsmasq
sleep 3

# --- Start the portal ---
echo "[6/6] Starting captive portal..."
systemctl start kiwix-portal.service

echo ""
echo "========================================"
echo "  Setup complete!"
echo "========================================"
echo ""
echo "  Captive portal: http://${PORTAL_IP}"
echo "  Kiwix library:  http://${PORTAL_IP}:${KIWIX_PORT}"
echo "  Access log:     ${LOG_DIR}/access_log.csv"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status kiwix-portal    # Check portal status"
echo "    sudo systemctl restart kiwix-portal    # Restart portal"
echo "    sudo journalctl -u kiwix-portal -f     # View portal logs"
echo "    cat ${LOG_DIR}/access_log.csv          # View access log"
echo "    sudo nft list table ip captive_portal  # View firewall rules"
echo ""
echo "  To uninstall, run:  sudo bash ${SCRIPT_DIR}/uninstall_captive_portal.sh"
echo ""
