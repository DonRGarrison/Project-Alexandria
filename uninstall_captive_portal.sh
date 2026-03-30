#!/bin/bash
# Uninstall the Kiwix Captive Portal
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo)."
    exit 1
fi

AP_INTERFACE="wlan0"
PORTAL_IP="10.42.0.1"

echo "Stopping and disabling captive portal..."
systemctl stop kiwix-portal.service 2>/dev/null || true
systemctl disable kiwix-portal.service 2>/dev/null || true
rm -f /etc/systemd/system/kiwix-portal.service
systemctl daemon-reload

echo "Removing iptables rules..."
iptables -t nat -D PREROUTING -i "$AP_INTERFACE" -p tcp --dport 80 \
    ! -d "$PORTAL_IP" -j DNAT --to-destination "${PORTAL_IP}:80" 2>/dev/null || true
iptables -t nat -D PREROUTING -i "$AP_INTERFACE" -p tcp --dport 443 \
    ! -d "$PORTAL_IP" -j DNAT --to-destination "${PORTAL_IP}:80" 2>/dev/null || true
netfilter-persistent save 2>/dev/null || true

echo "Removing dnsmasq config..."
rm -f /etc/dnsmasq.d/captive-portal.conf
systemctl restart dnsmasq 2>/dev/null || true

echo "Removing portal files..."
rm -rf /opt/kiwix-portal

echo ""
echo "Uninstall complete. Log files preserved at /var/log/kiwix-portal/"
echo "To remove logs too: sudo rm -rf /var/log/kiwix-portal"
