#!/bin/bash
# Uninstall the Kiwix Captive Portal (Debian Trixie / nftables)
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo)."
    exit 1
fi

echo "Stopping and disabling captive portal..."
systemctl stop kiwix-portal.service 2>/dev/null || true
systemctl disable kiwix-portal.service 2>/dev/null || true
rm -f /etc/systemd/system/kiwix-portal.service
systemctl daemon-reload

echo "Removing nftables rules..."
nft delete table ip captive_portal 2>/dev/null || true
rm -f /etc/nftables.d/captive-portal.conf

echo "Removing dnsmasq config..."
rm -f /etc/dnsmasq.d/captive-portal.conf
systemctl restart dnsmasq 2>/dev/null || true

echo "Removing systemd-resolved override..."
rm -f /etc/systemd/resolved.conf.d/captive-portal.conf
systemctl restart systemd-resolved 2>/dev/null || true

echo "Removing portal files..."
rm -rf /opt/kiwix-portal

echo ""
echo "Uninstall complete. Log files preserved at /var/log/kiwix-portal/"
echo "To remove logs too: sudo rm -rf /var/log/kiwix-portal"
