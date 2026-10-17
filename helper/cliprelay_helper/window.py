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


def ask_running_to_quit() -> bool:
    """Ask a helper that already runs here to close (a newer version is taking its place). True when it was asked."""
    link = running_link()
    if not link:
        return False
    try:
        import httpx

        httpx.post(link.replace("/?k=", "/quit?k="), headers={"X-Helper": "1"}, json={}, timeout=5)
        return True
    except Exception:  # noqa: BLE001 — none running, or it closed before answering
        return False


def _saved_key() -> str:
    """The window's key: made once and kept, so a bookmarked or reopened window keeps working after a restart."""
    try:
        with open(_key_file(), encoding="utf-8") as fh:
            key = fh.read().strip()
        if len(key) >= 20:
            return key
    except OSError:
        pass
    key = secrets.token_urlsafe(18)
    with open(_key_file(), "w", encoding="utf-8") as fh:
        fh.write(key)
    if os.name == "posix":
        os.chmod(_key_file(), 0o600)
    return key


class OnlyServer(ThreadingHTTPServer):
    """Holds the port alone. (On Windows a reusable address lets a second helper share it, and the browser then
    talks to the wrong one.) A second helper finds the port taken and shows the first one's window instead."""

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt":
            import socket

            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Window:
    def __init__(self, settings: Settings, worker):
        self.settings = settings
        self.worker = worker
        self.key = _saved_key()
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
                return self._local() and secrets.compare_digest((query.get("k") or [""])[0], window.key)

            def _send(self, code: int, body: bytes, kind: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, value: dict, code: int = 200) -> None:
                self._send(code, json.dumps(value, default=str).encode(), "application/json")

            def _local(self) -> bool:
                # Only this computer's own address: a web page using a look-alike name (DNS rebinding) is refused.
                return (self.headers.get("Host") or "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

            def do_GET(self):
                if not self._ok():
                    if self._local() and urlparse(self.path).path == "/":  # an old or bookmarked link: to the window
                        self.send_response(302)
                        self.send_header("Location", f"/?k={window.key}")
                        self.end_headers()
                        return None
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
            self.server = OnlyServer(("127.0.0.1", PORT), Handler)
        except OSError:
            return False
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
        elif path == "/quit":
            # A newer version is replacing this one: close straight away, so its file can be overwritten.
            threading.Timer(0.3, lambda: os._exit(0)).start()
            return {"ok": True}
        elif path == "/disconnect":
            Client(s).disconnect()
            s.update(token="", account="")
            self.worker.wake.set()
        return self.state()

