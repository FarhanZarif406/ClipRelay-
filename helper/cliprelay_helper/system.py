"""The computer itself: low priority, staying awake while working, starting with the computer, the JavaScript runtime."""

import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile

import httpx

from cliprelay_helper import APP_NAME
from cliprelay_helper.store import sub

DENO_VERSION = "2.7.11"
RUNTIME_MINIMUMS = {"deno": (2, 3, 0), "node": (22, 0, 0)}


def be_gentle() -> None:
    """Run below normal priority, so the member's own work stays quick; FFmpeg and yt-dlp inherit it."""
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL
        else:
            os.nice(10)
    except Exception:  # noqa: BLE001 — a priority that could not be lowered is not a reason to stop
        pass


class KeepAwake:
    """While a video is being worked on, the computer does not go to sleep (the screen may still turn off)."""

    def __init__(self):
        self._mac = None

    def __enter__(self):
        try:
            if sys.platform == "win32":
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            elif sys.platform == "darwin":
                self._mac = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        except Exception:  # noqa: BLE001
            pass
        return self

    def __exit__(self, *_):
        try:
            if sys.platform == "win32":
                import ctypes

                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            elif self._mac:
                self._mac.terminate()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- starting with the computer

def _exe() -> str | None:
    """The built helper's program (None when run from source: nothing to start)."""
    return sys.executable if getattr(sys, "frozen", False) else None


def _plist() -> str:
    return os.path.expanduser("~/Library/LaunchAgents/com.cliprelay.helper.plist")


def starts_with_computer() -> bool:
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        if sys.platform == "darwin":
            return os.path.exists(_plist())
    except OSError:
        return False
    return False


def set_start_with_computer(on: bool) -> bool:
    exe = _exe()
    if not exe:
        return False
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                if on:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}" --background')
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
            return True
        if sys.platform == "darwin":
            if on:
                os.makedirs(os.path.dirname(_plist()), exist_ok=True)
                with open(_plist(), "w", encoding="utf-8") as fh:
                    fh.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.cliprelay.helper</string>
<key>ProgramArguments</key><array><string>{exe}</string><string>--background</string></array>
<key>RunAtLoad</key><true/>
</dict></plist>
""")
            elif os.path.exists(_plist()):
                os.remove(_plist())
            return True
    except OSError:
        return False
    return False


def install_windows() -> str | None:
    """First run of the downloaded .exe: copy it to the user's programs folder and start from there (no admin needed).

    Returns the installed path when the program should restart from it, else None.
    """
    exe = _exe()
    if sys.platform != "win32" or not exe:
        return None
    home = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Programs", APP_NAME)
    target = os.path.join(home, f"{APP_NAME}.exe")
    if os.path.normcase(os.path.abspath(exe)) == os.path.normcase(os.path.abspath(target)):
        return None
    import time

    from cliprelay_helper.window import ask_running_to_quit

    os.makedirs(home, exist_ok=True)
    asked = False
    for _ in range(20):  # a new version over a running one: the running helper is asked to close, then replaced
        try:
            shutil.copy2(exe, target)
            return target
        except OSError:
            if not asked:
                asked = ask_running_to_quit()
                if not asked:
                    break
            time.sleep(0.5)
    return None  # not allowed: run from where it is


# ---------------------------------------------------------------- the JavaScript runtime yt-dlp needs for YouTube

def _version(path: str) -> tuple[int, ...] | None:
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return tuple(int(x) for x in found.groups()) if found else None


def _deno_asset() -> str | None:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "deno-x86_64-pc-windows-msvc.zip"
    if sys.platform == "darwin":
        return "deno-aarch64-apple-darwin.zip" if arm else "deno-x86_64-apple-darwin.zip"
    if sys.platform.startswith("linux"):
        return "deno-aarch64-unknown-linux-gnu.zip" if arm else "deno-x86_64-unknown-linux-gnu.zip"
    return None


def js_runtimes(on_status=None) -> dict:
    """yt-dlp's js_runtimes option: Deno or Node.js already on the computer, else Deno fetched once from its official releases."""
    for name, minimum in RUNTIME_MINIMUMS.items():
        path = shutil.which(name)
        if path and (_version(path) or (0,)) >= minimum:
            return {name: {"path": path}}
    folder = sub("bin")
    deno = os.path.join(folder, "deno.exe" if sys.platform == "win32" else "deno")
    if not os.path.exists(deno):
        asset = _deno_asset()
        if not asset:
            return {"deno": {}}
        if on_status:
            on_status("Getting Deno, which reads YouTube (once, about 40 MB) …")
        url = f"https://github.com/denoland/deno/releases/download/v{DENO_VERSION}/{asset}"
        archive = os.path.join(folder, "deno.zip")
        with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=300)) as response:
            response.raise_for_status()
            with open(archive, "wb") as fh:
                for chunk in response.iter_bytes(1024 * 1024):
                    fh.write(chunk)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(folder)
        os.remove(archive)
        if os.name == "posix":
            os.chmod(deno, 0o755)
    return {"deno": {"path": deno}}


def open_url(url: str) -> None:
    import webbrowser

    webbrowser.open(url)
