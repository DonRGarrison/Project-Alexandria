#!/bin/bash
# ============================================================
# Kiwix Captive Portal - Setup Script for Raspberry Pi 5 (PiOS)
# ============================================================
# This script:
#   1. Installs the captive portal Python server as a systemd service
#   2. Configures iptables to redirect all HTTP (port 80) and DNS traffic
#      from connected clients to the portal
#   3. Sets up dnsmasq overrides so captive-portal detection works
#   4. Makes everything persistent across reboots
#
# Prerequisites:
#   - Raspberry Pi 5 running PiOS (Bookworm)
#   - WiFi AP already configured via NetworkManager on 10.42.0.1
#   - Kiwix server running on 10.42.0.1:8080
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
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Preflight checks ---
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo)."
    exit 1
fi

echo "========================================"
echo "  Kiwix Captive Portal - Setup"
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
apt-get install -y -qq iptables iptables-persistent dnsmasq python3 > /dev/null

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
After=network-online.target NetworkManager.service
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

# --- Configure iptables ---
echo "[4/6] Configuring iptables redirect rules..."

# Flush any existing portal rules (idempotent re-run)
iptables -t nat -D PREROUTING -i "$AP_INTERFACE" -p tcp --dport 80 \
    ! -d "$PORTAL_IP" -j DNAT --to-destination "${PORTAL_IP}:${PORTAL_PORT}" 2>/dev/null || true
iptables -t nat -D PREROUTING -i "$AP_INTERFACE" -p tcp --dport 443 \
    ! -d "$PORTAL_IP" -j DNAT --to-destination "${PORTAL_IP}:${PORTAL_PORT}" 2>/dev/null || true

# Redirect HTTP traffic from clients to the portal (except traffic to the Pi itself)
iptables -t nat -A PREROUTING -i "$AP_INTERFACE" -p tcp --dport 80 \
    ! -d "$PORTAL_IP" -j DNAT --to-destination "${PORTAL_IP}:${PORTAL_PORT}"

# Redirect HTTPS to portal too (browsers will show cert error but triggers portal detection)
iptables -t nat -A PREROUTING -i "$AP_INTERFACE" -p tcp --dport 443 \
    ! -d "$PORTAL_IP" -j DNAT --to-destination "${PORTAL_IP}:${PORTAL_PORT}"

# Save iptables rules for persistence across reboots
netfilter-persistent save

# --- Configure dnsmasq for DNS hijacking ---
echo "[5/6] Configuring DNS hijacking via dnsmasq..."
cat > /etc/dnsmasq.d/captive-portal.conf <<EOF
# Kiwix Captive Portal - DNS Override
# Resolve ALL domains to the portal IP so captive portal detection triggers
# and all HTTP requests land on our welcome page.

# Only listen on the AP interface
interface=${AP_INTERFACE}
bind-interfaces

# Answer all DNS queries with the portal IP
address=/#/${PORTAL_IP}

# Except: allow Kiwix server hostname to resolve normally (if used)
# server=/kiwix.local/10.42.0.1
EOF

# Make sure dnsmasq doesn't conflict with systemd-resolved
if systemctl is-active --quiet systemd-resolved; then
    # Ensure dnsmasq only binds to AP interface (already set above)
    echo "  Note: systemd-resolved is active. dnsmasq is bound only to ${AP_INTERFACE}."
fi

systemctl enable dnsmasq
systemctl restart dnsmasq

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
echo "    sudo systemctl status kiwix-portal   # Check portal status"
echo "    sudo systemctl restart kiwix-portal   # Restart portal"
echo "    sudo journalctl -u kiwix-portal -f    # View portal logs"
echo "    cat ${LOG_DIR}/access_log.csv         # View access log"
echo ""
echo "  To uninstall, run:  sudo bash ${SCRIPT_DIR}/uninstall_captive_portal.sh"
echo ""
