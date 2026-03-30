#!/usr/bin/env python3
"""
Kiwix Captive Portal Server
Serves a welcome page on port 80 and logs device info when users click through to Kiwix.

Flow:
  1. Device connects → OS captive portal probe gets our welcome page → popup appears
  2. User taps "Enter Library" → JS POSTs device info to /log_access
  3. JS then loads /dismiss which returns OS-specific "success" → popup closes
  4. User opens their real browser → any URL hits our server (DNS hijacked) →
     server sees their IP was already authenticated → 302 redirect to Kiwix
"""

import http.server
import json
import os
import csv
import sys
import subprocess
import urllib.parse
import threading
import time
from datetime import datetime

KIWIX_URL = "http://10.42.0.1:8080"
LOG_DIR = "/var/log/kiwix-portal"
LOG_FILE = os.path.join(LOG_DIR, "access_log.csv")
PORT = 80

# Track IPs that have clicked "Enter Library" so when they open their
# real browser we redirect them straight to Kiwix instead of showing
# the welcome page again. Entries expire after 24 hours.
authenticated_ips = {}  # ip -> timestamp
AUTH_EXPIRY_SECONDS = 86400  # 24 hours


def cleanup_expired_ips():
    """Remove expired IPs from the authenticated set."""
    now = time.time()
    expired = [ip for ip, ts in authenticated_ips.items() if now - ts > AUTH_EXPIRY_SECONDS]
    for ip in expired:
        del authenticated_ips[ip]


WELCOME_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome - ApachePi Library</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            text-align: center;
            padding: 2rem;
            max-width: 600px;
        }
        .logo {
            font-size: 4rem;
            margin-bottom: 1rem;
        }
        h1 {
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }
        .subtitle {
            font-size: 1.1rem;
            opacity: 0.85;
            margin-bottom: 2rem;
            line-height: 1.5;
        }
        .enter-btn {
            display: inline-block;
            padding: 1rem 3rem;
            font-size: 1.2rem;
            font-weight: 600;
            color: #fff;
            background: #e04006;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
            transition: background 0.2s, transform 0.1s;
        }
        .enter-btn:hover { background: #c53600; transform: scale(1.03); }
        .enter-btn:active { transform: scale(0.98); }
        .footer {
            margin-top: 2rem;
            font-size: 0.85rem;
            opacity: 0.6;
        }
        .spinner {
            display: none;
            margin: 1rem auto;
            width: 32px; height: 32px;
            border: 3px solid rgba(255,255,255,0.3);
            border-top-color: #fff;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .done-msg {
            display: none;
            margin-top: 1.5rem;
            padding: 1rem;
            background: rgba(255,255,255,0.1);
            border-radius: 8px;
            line-height: 1.6;
        }
        .done-msg strong {
            font-size: 1.1rem;
        }
        .geo-note {
            font-size: 0.75rem;
            opacity: 0.5;
            margin-top: 1rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">&#128218;</div>
        <h1>Welcome to ApachePi Library</h1>
        <p class="subtitle">
            You are connected to a local knowledge server powered by Kiwix on ApachePi.<br>
            Tap the button below to get started.
        </p>
        <button class="enter-btn" id="enterBtn" onclick="enterLibrary()">Enter Library</button>
        <div class="spinner" id="spinner"></div>
        <div class="done-msg" id="doneMsg">
            <strong>You're connected!</strong><br>
            Close this popup, then open your browser.<br>
            The library will load automatically.
        </div>
        <p class="footer">Powered by Kiwix on ApachePi</p>
        <p class="geo-note">Location data may be collected for usage analytics.</p>
    </div>

    <script>
    function enterLibrary() {
        var btn = document.getElementById('enterBtn');
        var spinner = document.getElementById('spinner');
        var doneMsg = document.getElementById('doneMsg');
        btn.style.display = 'none';
        spinner.style.display = 'block';

        var info = {
            userAgent: navigator.userAgent,
            platform: navigator.platform,
            language: navigator.language,
            screenWidth: screen.width,
            screenHeight: screen.height,
            timestamp: new Date().toISOString(),
            geo_lat: '',
            geo_lon: '',
            geo_accuracy: ''
        };

        function sendLog() {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', 'http://10.42.0.1/log_access', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            var done = false;
            function onDone() {
                if (!done) {
                    done = true;
                    spinner.style.display = 'none';
                    doneMsg.style.display = 'block';
                }
            }
            xhr.onload = function() { onDone(); };
            xhr.onerror = function() { onDone(); };
            setTimeout(onDone, 4000);
            xhr.send(JSON.stringify(info));
        }

        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                function(pos) {
                    info.geo_lat = pos.coords.latitude;
                    info.geo_lon = pos.coords.longitude;
                    info.geo_accuracy = pos.coords.accuracy;
                    sendLog();
                },
                function(err) {
                    sendLog();
                },
                { timeout: 5000, maximumAge: 300000 }
            );
        } else {
            sendLog();
        }
    }
    </script>
</body>
</html>
"""


def get_mac_from_ip(ip_addr):
    """Look up MAC address from the ARP table for a given IP."""
    try:
        with open("/proc/net/arp", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip_addr:
                    mac = parts[3]
                    if mac != "00:00:00:00:00:00":
                        return mac
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["ip", "neigh", "show", ip_addr],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if "lladdr" in parts:
                idx = parts.index("lladdr")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
    except Exception:
        pass
    return "unknown"


def parse_os_from_ua(ua):
    """Extract a simple OS name from the User-Agent string."""
    ua_lower = ua.lower()
    if "iphone" in ua_lower or "ipad" in ua_lower:
        return "iOS"
    elif "mac os" in ua_lower:
        return "macOS"
    elif "android" in ua_lower:
        return "Android"
    elif "windows" in ua_lower:
        return "Windows"
    elif "linux" in ua_lower:
        return "Linux"
    elif "cros" in ua_lower:
        return "ChromeOS"
    return "Unknown"


def parse_device_name(ua):
    """Try to extract a device model from the User-Agent string."""
    if "Android" in ua:
        try:
            start = ua.index(";", ua.index("Android")) + 1
            end = ua.index("Build/", start) if "Build/" in ua[start:] else ua.index(")", start)
            return ua[start:end].strip()
        except (ValueError, IndexError):
            pass
    if "iPhone" in ua:
        return "iPhone"
    if "iPad" in ua:
        return "iPad"
    if "Macintosh" in ua:
        return "Mac"
    return "Unknown"


def ensure_log_file():
    """Create log directory and CSV file with headers if needed."""
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "date", "time", "ip_address", "mac_address", "os",
                "device_name", "user_agent", "platform", "language",
                "screen_resolution", "geo_latitude", "geo_longitude",
                "geo_accuracy_m"
            ])
        print(f"Created log file: {LOG_FILE}", flush=True)


# OS captive portal probe paths. When an authenticated device's OS
# sends these probes, we must return the expected "success" response
# so the OS marks the network as "connected" and stops showing the
# captive portal. If we redirect these, the OS thinks the portal is
# still active and falls back to cellular data.
PROBE_PATHS = {
    # Apple (CNA)
    "/hotspot-detect.html",
    "/library/test/success.html",
    # Android / Google
    "/generate_204",
    "/gen_204",
    # Windows (NCSI)
    "/connecttest.txt",
    "/ncsi.txt",
    "/redirect",
    # Firefox
    "/canonical.html",
    "/success.txt",
    # Samsung
    "/generate204",
    # Other common
    "/check_network_status.txt",
    "/connectivity-check.html",
}


class CaptivePortalHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        """Log requests to stdout so they appear in journalctl."""
        print(f"[{self.client_address[0]}] {format % args}", flush=True)

    def _serve_welcome_page(self):
        """Serve the welcome/splash page."""
        page = WELCOME_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(page)

    def _redirect_to_kiwix(self):
        """Send a 302 redirect to the Kiwix server."""
        self.send_response(302)
        self.send_header("Location", KIWIX_URL)
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def _serve_probe_success(self, path):
        """Return the expected 'success' response for OS captive portal probes.
        This tells the OS the network is working so it stops showing the popup."""
        if path in ("/generate_204", "/gen_204", "/generate204"):
            self.send_response(204)
            self.end_headers()
        elif path == "/hotspot-detect.html" or path == "/library/test/success.html":
            body = b"<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path in ("/connecttest.txt", "/ncsi.txt"):
            body = b"Microsoft Connect Test"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path in ("/canonical.html", "/success.txt"):
            body = b"success\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(204)
            self.end_headers()

    def do_GET(self):
        client_ip = self.client_address[0]
        path = urllib.parse.urlparse(self.path).path

        cleanup_expired_ips()

        is_probe = path in PROBE_PATHS

        if client_ip in authenticated_ips:
            if is_probe:
                # OS is checking connectivity. Return "success" so it
                # marks WiFi as connected and stops the captive portal.
                print(f"[{client_ip}] Probe {path} - returning success (authenticated)", flush=True)
                self._serve_probe_success(path)
            else:
                # Real browser request - redirect to Kiwix
                print(f"[{client_ip}] Browser request - redirecting to Kiwix", flush=True)
                self._redirect_to_kiwix()
            return

        # Not yet authenticated - show the welcome page for everything.
        # OS probes get our page instead of "success", triggering the popup.
        self._serve_welcome_page()

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path == "/log_access":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                data = json.loads(body) if body else {}

                client_ip = self.client_address[0]
                mac = get_mac_from_ip(client_ip)
                ua = data.get("userAgent", self.headers.get("User-Agent", ""))
                os_name = parse_os_from_ua(ua)
                device_name = parse_device_name(ua)
                now = datetime.now()
                screen = f"{data.get('screenWidth', '?')}x{data.get('screenHeight', '?')}"

                row = [
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    client_ip,
                    mac,
                    os_name,
                    device_name,
                    ua,
                    data.get("platform", ""),
                    data.get("language", ""),
                    screen,
                    data.get("geo_lat", ""),
                    data.get("geo_lon", ""),
                    data.get("geo_accuracy", ""),
                ]

                ensure_log_file()
                with open(LOG_FILE, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(row)

                # Mark this IP as authenticated so their real browser
                # gets redirected to Kiwix
                authenticated_ips[client_ip] = time.time()
                print(f"LOGGED: {client_ip} | {mac} | {os_name} | {device_name}", flush=True)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            except Exception as e:
                print(f"ERROR logging access: {e}", file=sys.stderr, flush=True)
                self.send_response(500)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()


def main():
    print(f"=== Kiwix Captive Portal ===", flush=True)
    print(f"Listening on 0.0.0.0:{PORT}", flush=True)
    print(f"Log file: {LOG_FILE}", flush=True)

    ensure_log_file()

    try:
        with open(LOG_FILE, "a") as f:
            pass
        print(f"Log file is writable: OK", flush=True)
    except Exception as e:
        print(f"WARNING: Cannot write to log file: {e}", file=sys.stderr, flush=True)

    server = http.server.HTTPServer(("0.0.0.0", PORT), CaptivePortalHandler)
    print(f"Server started. Waiting for connections...", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
