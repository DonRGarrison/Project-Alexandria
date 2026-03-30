# Kiwix Captive Portal for ApachePi

A captive portal that greets users connecting to ApachePi's Kiwix WiFi access point with a welcome page, then logs device information when they click through to the library.

## What It Does

When a device connects to your Pi's WiFi hotspot:
1. The device's captive portal detection triggers and shows the **welcome page**
2. The user taps **"Enter Library"**
3. The portal logs device info (IP, MAC, OS, device name, date/time, geolocation) to a CSV file
4. The user is redirected to the **Kiwix server** at `http://10.42.0.1:8080`

## Logged Information

Each click-through records a row in `/var/log/kiwix-portal/access_log.csv`:

| Field | Source |
|-------|--------|
| Date & Time | Server clock |
| IP Address | TCP connection |
| MAC Address | ARP table (`/proc/net/arp`) |
| OS | Parsed from User-Agent |
| Device Name | Parsed from User-Agent |
| User-Agent | Browser header |
| Platform | JavaScript `navigator.platform` |
| Language | JavaScript `navigator.language` |
| Screen Resolution | JavaScript `screen.width`/`height` |
| Geolocation | Browser Geolocation API (user must allow) |

## Prerequisites

- Raspberry Pi 5 (ApachePi) running Debian 13 (Trixie)
- WiFi AP configured via NetworkManager on `10.42.0.1`
- Kiwix server running on `10.42.0.1:8080`
- User: `apachepi`

## Installation

On your Pi as `apachepi@ApachePi`:

```bash
cd ~
git clone <this-repo> Project-Alexandria && cd Project-Alexandria
sudo bash setup_captive_portal.sh
```

The setup script will:
- Install dependencies (`nftables`, `python3`)
- Install the portal server to `/opt/kiwix-portal/`
- Create a systemd service (`kiwix-portal`)
- Configure nftables to redirect HTTP/HTTPS to the portal
- Configure NetworkManager's built-in dnsmasq to resolve all DNS to `10.42.0.1`

## Usage

```bash
# Check status
sudo systemctl status kiwix-portal

# View live logs
sudo journalctl -u kiwix-portal -f

# View access log
cat /var/log/kiwix-portal/access_log.csv

# View firewall rules
sudo nft list table ip captive_portal

# Restart
sudo systemctl restart kiwix-portal
```

## Uninstall

```bash
sudo bash uninstall_captive_portal.sh
```

## Configuration

Edit the top of `captive_portal.py` to change:
- `KIWIX_URL` - Kiwix server address
- `LOG_DIR` / `LOG_FILE` - log location
- `PORT` - portal listen port

Edit the top of `setup_captive_portal.sh` to change:
- `AP_INTERFACE` - WiFi interface name (default: `wlan0`)
- `PORTAL_IP` - AP IP address (default: `10.42.0.1`)
