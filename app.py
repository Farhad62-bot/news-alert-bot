"""
Web service wrapper for Render's free tier.

Render's free Web Services need to respond on an HTTP port to be
considered "alive" — this file adds a tiny built-in health endpoint
and runs your existing news_alert.run_loop() in the background at the
same time. Deploy THIS file as the Start Command (not news_alert.py
directly) when using a Web Service instead of a Cron Job.
"""

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import news_alert  # reuses everything already in news_alert.py


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"BERLIN NEWS BOT is running.\n")

    def log_message(self, format, *args):
        pass  # keep Render's logs clean, no per-request spam


def start_health_server():
    port = int(os.environ.get("PORT", 10000))  # Render sets PORT automatically
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health check server listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    # Run the news-checking loop in the background...
    news_thread = threading.Thread(target=news_alert.run_loop, daemon=True)
    news_thread.start()

    # ...while the main thread keeps an HTTP port open so Render sees
    # this service as healthy and (with an external pinger) never
    # spins it down.
    start_health_server()
