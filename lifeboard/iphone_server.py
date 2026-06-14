"""Tiny HTTP server exposing the rendered wallpaper PNG for an iOS Shortcut to fetch."""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import OUTPUT_DIR


class IPhoneServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> tuple[str, int]:
        if self._server:
            return self._server.server_address

        png_path = os.path.join(OUTPUT_DIR, "wallpaper_phone.png")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path.split("?", 1)[0] not in ("/wallpaper.png", "/wallpaper_phone.png", "/"):
                    self.send_error(404)
                    return
                if not os.path.exists(png_path):
                    self.send_error(404, "wallpaper not yet rendered")
                    return

                stat = os.stat(png_path)
                etag = f'"{int(stat.st_mtime)}-{stat.st_size}"'
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return

                with open(png_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self._server.server_address

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None
