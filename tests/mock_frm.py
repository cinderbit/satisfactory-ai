"""
mock_frm.py

A tiny stand-in for the FRM HTTP API, serving the JSON fixtures in
tests/fixtures/ on the endpoints FRMClient hits. Lets us exercise the real
world_state.FRMClient over real HTTP without the game running.

Usage (standalone):
    python tests/mock_frm.py 8099
Then:
    curl http://localhost:8099/frm/resourcenode

Usage (in tests): see MockFRMServer context manager below.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# Map FRM path -> fixture file
ROUTES = {
    "/frm/resourcenode": "frm_resourcenode.json",
    "/frm/radartower":   "frm_radartower.json",
    "/frm/factory":      "frm_factory.json",
}


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        fixture = ROUTES.get(self.path)
        if fixture is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"[]")
            return
        body = _load(fixture)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence per-request logging
        pass


class MockFRMServer:
    """Context manager that runs the mock FRM server on a background thread."""

    def __init__(self, port: int = 0):
        self.httpd = HTTPServer(("127.0.0.1", port), _Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "MockFRMServer":
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    srv = HTTPServer(("127.0.0.1", port), _Handler)
    print(f"Mock FRM serving fixtures on http://127.0.0.1:{port}")
    print("Endpoints:", ", ".join(ROUTES))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
