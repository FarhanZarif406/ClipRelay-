"""Where the helper keeps its settings, its key, the member's cached files and its work folder."""

import json
import os
import platform
import socket
import sys
import threading

from cliprelay_helper import APP_NAME


def data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def sub(name: str) -> str:
    path = os.path.join(data_dir(), name)
    os.makedirs(path, exist_ok=True)
    return path


def platform_name() -> str:
    return {"win32": "windows", "darwin": "mac"}.get(sys.platform, "other")


def default_name() -> str:
    host = socket.gethostname().split(".")[0] or "My computer"
    return f"{host} ({platform.system() or 'PC'})"[:80]


class Settings:
    """settings.json: the server address, the helper's key (a secret: readable only by this user), the PC's name."""

    def __init__(self):
        self.path = os.path.join(data_dir(), "settings.json")
        self._lock = threading.Lock()
        self.values = {"server": "", "token": "", "name": default_name(), "paused": False, "account": "", "language": "en"}
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.values.update(json.load(fh))
        except (OSError, ValueError):
            pass

    def get(self, key: str, default=None):
        with self._lock:
            return self.values.get(key, default)

    def update(self, **changes) -> None:
        with self._lock:
            self.values.update(changes)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.values, fh, indent=2)
            if os.name == "posix":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)

    @property
    def connected(self) -> bool:
        return bool(self.get("server") and self.get("token"))
