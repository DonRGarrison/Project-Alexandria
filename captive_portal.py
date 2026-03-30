#!/usr/bin/env python3
"""
Kiwix Captive Portal Server
Serves a welcome page on port 80 and logs device info when users click through to Kiwix.
"""

import http.server
import json
import os
import csv
import sys
import subprocess
import urllib.parse
from datetime import datetime

KIWIX_URL = "http://10.42.0.1:8080"
LOG_DIR = "/var/log/kiwix-portal"
LOG_FILE = os.path.join(LOG_DIR, "access_log.csv")
PORT = 80

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
            Tap the button below to browse the library.
        </p>
        <button class="enter-btn" id="enterBtn" onclick="enterLibrary()">Enter Library</button>
        <div class="spinner" id="spinner"></div>
        <p id="statusMsg" class="footer" style="display:none;">Opening in your browser...</p>
        <p class="footer">Powered by Kiwix on ApachePi</p>
        <p class="geo-note">Location data may be collected for usage analytics.</p>
    </div>

    <script>
    var KIWIX = '""" + KIWIX_URL + """';

    function enterLibrary() {
        var btn = document.getElementById('enterBtn');
        var spinner = document.getElementById('spinner');
        var statusMsg = document.getElementById('statusMsg');
        btn.style.display = 'none';
        spinner.style.display = 'block';
        statusMsg.style.display = 'block';

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

        function sendAndOpenBrowser() {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', 'http://10.42.0.1/log_access', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            var opened = false;
            function doOpen() {
                if (!opened) {
                    opened = true;
                    // Tell the server to return "success" to the OS captive
                    // portal checker. This causes the popup to auto-dismiss.
                    // We fetch /dismiss in the background while opening the
                    // real browser via an <a> tag click or window.open.
                    fetch('http://10.42.0.1/dismiss').catch(function(){});

                    // Create a temporary link with target=_blank to force
                    // the system's default browser to open (not the captive
                    // portal mini-browser).
                    var a = document.createElement('a');
                    a.href = KIWIX;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    document.body.appendChild(a);
                    a.click();

                    // Update status in case the popup hasn't closed yet
                    statusMsg.textContent = 'Check your browser! You can close this window.';
                }
            }
            xhr.onload = function() { doOpen(); };
            xhr.onerror = function() { doOpen(); };
            // Fallback after 4 seconds in case logging hangs
            setTimeout(doOpen, 4000);
            xhr.send(JSON.stringify(info));
        }

        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                function(pos) {
                    info.geo_lat = pos.coords.latitude;
                    info.geo_lon = pos.coords.longitude;
                    info.geo_accuracy = pos.coords.accuracy;
                    sendAndOpenBrowser();
                },
                function(err) {
                    // Geolocation denied or unavailable - proceed without it
                    sendAndOpenBrowser();
                },
                { timeout: 5000, maximumAge: 300000 }
            );
        } else {
            sendAndOpenBrowser();
        }
    }
    </script>
</body>
</html>
"""


def get_mac_from_ip(ip_addr):
    """Look up MAC address from the ARP table for a given IP."""
    # Try /proc/net/arp first
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
    # Fallback: use ip neigh command
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
    # Android devices often include model info
    if "Android" in ua:
        # Pattern: Android X.X; <device model> Build/
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

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        # After the user clicks "Enter Library", the JS calls /dismiss
        # which returns the expected captive portal "success" responses.
        # This tells the OS "internet is working" and closes the popup,
        # while the real browser opens with the Kiwix URL.
        if path == "/dismiss":
            ua = self.headers.get("User-Agent", "").lower()
            if "cros" in ua or "android" in ua:
                # Android/Chrome: expects 204 No Content
                self.send_response(204)
                self.end_headers()
            elif "iphone" in ua or "ipad" in ua or "mac" in ua or "darwin" in ua:
                # Apple: expects this exact HTML with "Success" in title
                body = b"<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif "windows" in ua:
                # Windows: expects "Microsoft Connect Test"
                body = b"Microsoft Connect Test"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(204)
                self.end_headers()
            return

        # Serve the welcome page for ALL other GET requests.
        # This ensures captive portal detection probes (Apple, Android,
        # Windows, Firefox) all receive our page instead of the expected
        # "success" response, which triggers the captive portal popup.
        self._serve_welcome_page()

    def do_HEAD(self):
        # Some captive portal detectors use HEAD requests
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def do_OPTIONS(self):
        # Handle CORS preflight for the POST from the welcome page
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

    # Verify log is writable
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
