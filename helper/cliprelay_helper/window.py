"""The helper's window: a small page on this computer only (127.0.0.1), opened in the browser from the tray icon.

It connects the PC with the code from the website and shows what the helper is doing. A random key in the link
keeps other web pages from using it.
"""

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cliprelay_helper import VERSION
from cliprelay_helper.client import Client, ServerError, clean_address
from cliprelay_helper.page import PAGE
from cliprelay_helper.store import Settings, data_dir, platform_name
from cliprelay_helper.system import set_start_with_computer, starts_with_computer

PORT = 47613


def _key_file() -> str:
    return os.path.join(data_dir(), "window.key")


def running_link() -> str | None:
    """The window of a helper that already runs on this computer, if one does."""
    try:
        with open(_key_file(), encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError:
        return None
    return f"http://127.0.0.1:{PORT}/?k={key}" if key else None


class Window:
    def __init__(self, settings: Settings, worker):
        self.settings = settings
        self.worker = worker
        self.key = secrets.token_urlsafe(18)
        self.server: ThreadingHTTPServer | None = None

    @property
    def link(self) -> str:
        return f"http://127.0.0.1:{PORT}/?k={self.key}"

    def start(self) -> bool:
        """False when another helper already has the window's place (it is running)."""
        window = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _ok(self) -> bool:
                query = parse_qs(urlparse(self.path).query)
                return secrets.compare_digest((query.get("k") or [""])[0], window.key)

            def _send(self, code: int, body: bytes, kind: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, value: dict, code: int = 200) -> None:
                self._send(code, json.dumps(value, default=str).encode(), "application/json")

            def do_GET(self):
                if not self._ok():
                    return self._send(403, b"Open this window from the ClipRelay Helper icon.", "text/plain")
                path = urlparse(self.path).path
                if path == "/":
                    return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                if path == "/state":
                    return self._json(window.state())
                return self._send(404, b"", "text/plain")

            def do_POST(self):
                if not self._ok() or self.headers.get("X-Helper") != "1":  # a page elsewhere cannot set this header without asking
                    return self._json({"error": "Not allowed"}, 403)
                size = min(int(self.headers.get("Content-Length") or 0), 10_000)
                try:
                    body = json.loads(self.rfile.read(size) or b"{}")
                except ValueError:
                    body = {}
                try:
                    return self._json(window.act(urlparse(self.path).path, body))
                except ServerError as exc:
                    return self._json({"error": str(exc)}, 400)

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        except OSError:
            return False
        with open(_key_file(), "w", encoding="utf-8") as fh:
            fh.write(self.key)
        if os.name == "posix":
            os.chmod(_key_file(), 0o600)
        threading.Thread(target=self.server.serve_forever, name="window", daemon=True).start()
        return True

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()

    def state(self) -> dict:
        s = self.settings
        return {
            **self.worker.snapshot(), "version": VERSION, "platform": platform_name(),
            "connected": s.connected, "server": s.get("server"), "name": s.get("name"), "account": s.get("account"),
            "paused": bool(s.get("paused")), "language": s.get("language") or "en", "starts_with_computer": starts_with_computer(),
        }

    def act(self, path: str, body: dict) -> dict:
        s = self.settings
        if path == "/connect":
            server = clean_address(body.get("server") or s.get("server"))
            if not server:
                raise ServerError("Type your ClipRelay address (it is shown on the website: PC Helper).")
            name = (body.get("name") or s.get("name")).strip()[:80]
            answer = Client.connect(server, (body.get("code") or "").strip(), name)
            s.update(server=server, token=answer["token"], name=name, account=answer.get("account", ""), paused=False)
            set_start_with_computer(True)  # a connected PC is ready again after a restart
            self.worker.wake.set()
        elif path == "/pause":
            s.update(paused=bool(body.get("paused")))
            self.worker.wake.set()
        elif path == "/autostart":
            set_start_with_computer(bool(body.get("on")))
        elif path == "/language":
            s.update(language="ur" if body.get("language") == "ur" else "en", language_chosen=True)
        elif path == "/disconnect":
            Client(s).disconnect()
            s.update(token="", account="")
            self.worker.wake.set()
        return self.state()

