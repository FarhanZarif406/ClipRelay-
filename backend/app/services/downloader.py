"""The downloader's settings and its way around YouTube refusing the server.

When the saved settings fail, the other ways of asking YouTube are tried in turn — without the cookies,
other player clients, over IPv6 — and the one that works is remembered, so the next video goes straight
to it. The cookies file is a signed-in YouTube session and the proxy address may hold a password, so
neither is ever sent back to the browser.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import ActivityLog, AppSetting, Job, JobStatus, utcnow
from app.security import decrypt, encrypt

log = logging.getLogger(__name__)

KEY = "downloader"
MAX_COOKIES_BYTES = 1_000_000
PROXY_SCHEMES = ("http", "https", "socks4", "socks4a", "socks5", "socks5h")
# The player clients offered in the app. "" is yt-dlp's own choice.
PLAYER_CLIENTS = ["", "web_safari", "web", "mweb", "tv", "tv,mweb", "web_embedded", "android_vr", "ios", "android"]
# After every way has failed, only the first is tried for a while, so a blocked server does not spend minutes on each video.
GIVE_UP_FOR = 20 * 60
GOOD_HEIGHT = 720  # below this a clip looks soft; it still counts as working

# Which version of a video is downloaded. Full HD is asked for first; when a video does not have it, the next
# choice down the list is taken, so a download never fails only because one quality or file type is missing.
SOURCE_FORMAT = "/".join([
    "bv*[vcodec^=avc1][protocol=https]+ba[ext=m4a]",  # plain H.264 with AAC: the fastest to fetch
    "bv*[protocol=https]+ba",
    "bv*+ba",
    "b",
])
# "Full HD" is measured on the short side, so an upright Short is fetched as 1080×1920 and a wide video as
# 1920×1080. (A plain height limit would give an upright video only 608×1080.)
FORMAT_SORT = ["res:1080"]

_all_failed_at = 0.0
_lock = threading.Lock()


class DownloaderError(ValueError):
    pass


# ---------------------------------------------------------------- stored settings

def _load() -> dict:
    db = SessionLocal()
    try:
        row = db.get(AppSetting, KEY)
        return dict(row.value) if row and isinstance(row.value, dict) else {}
    finally:
        db.close()


def _store(change) -> dict:
    db = SessionLocal()
    try:
        row = db.get(AppSetting, KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
        change(value)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=KEY, value=value))
        db.commit()
        return value
    finally:
        db.close()


def proxy() -> str:
    stored = _load().get("proxy_enc")
    return (decrypt(stored) or "") if stored else ""


def player_client() -> str:
    return _load().get("player_client") or ""


def hide_proxy(text: str, address: str | None = None) -> str:
    """Replace a proxy address (which may hold a password) wherever it appears in text shown to people."""
    address = proxy() if address is None else address
    return text.replace(address, "<proxy>") if address else text


def mask_proxy(address: str) -> str:
    if not address:
        return ""
    parsed = urlparse(address)
    login = f"{parsed.username}:••••@" if parsed.username else ""
    return f"{parsed.scheme}://{login}{parsed.hostname}:{parsed.port}"


def save_options(*, proxy_address: str | None = None, client: str | None = None) -> None:
    if proxy_address is not None:
        text = proxy_address.strip()
        if text and text == mask_proxy(proxy()):
            text = proxy()  # the masked address shown in the field was saved back unchanged
        if text:
            parsed = urlparse(text)
            try:
                port = parsed.port
            except ValueError as exc:
                raise DownloaderError("The proxy port is not a number") from exc
            if parsed.scheme not in PROXY_SCHEMES or not parsed.hostname or port is None:
                raise DownloaderError("Enter the proxy as http://user:pass@host:port (http, https, socks4 or socks5)")
        _store(lambda v: v.__setitem__("proxy_enc", encrypt(text)) if text else v.pop("proxy_enc", None))
    if client is not None:
        if client not in PLAYER_CLIENTS:
            raise DownloaderError("Unknown player client")
        _store(lambda v: v.__setitem__("player_client", client))


# ---------------------------------------------------------------- cookies file

def cookies_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(get_settings().storage_local_path)), "youtube-cookies.txt")


def parse_cookies(text: str) -> dict:
    """Read a Netscape-format cookies.txt: how many cookies, how many are YouTube's, and when the first expires."""
    count = relevant = 0
    earliest = None
    for raw in text.splitlines():
        line = raw[10:] if raw.startswith("#HttpOnly_") else raw  # "#HttpOnly_" marks a cookie, not a comment
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise DownloaderError("That is not a cookies.txt file. Export it in Netscape format.")
        count += 1
        if not re.search(r"(^|\.)(youtube|google)\.com$", fields[0], re.I):
            continue
        relevant += 1
        try:
            expires = int(float(fields[4]))
        except ValueError:
            expires = 0
        if expires > 0 and (earliest is None or expires < earliest):  # 0 marks a session cookie
            earliest = expires
    if count == 0:
        raise DownloaderError("That file holds no cookies.")
    if relevant == 0:
        raise DownloaderError("That file has no YouTube cookies. Export it while signed in to youtube.com.")
    return {"count": count, "relevant": relevant, "expires_at": datetime.fromtimestamp(earliest, timezone.utc) if earliest else None}


def cookies_info() -> dict:
    """What the page may know about the uploaded cookies file: never its contents."""
    path = cookies_path()
    if not os.path.isfile(path):
        return {"present": False}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            parsed = parse_cookies(fh.read())
    except DownloaderError:
        parsed = {"count": 0, "expires_at": None}
    expires = parsed.get("expires_at")
    return {
        "present": True, "count": parsed.get("count", 0), "expires_at": expires,
        "expired": bool(expires and expires < utcnow()),
        "updated_at": datetime.fromtimestamp(os.path.getmtime(path), timezone.utc),
    }


def save_cookies(content: bytes) -> dict:
    if len(content) > MAX_COOKIES_BYTES:
        raise DownloaderError("That file is too large. The limit is 1 MB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DownloaderError("That is not a cookies.txt file. Export it in Netscape format.") from exc
    parse_cookies(text)
    path = cookies_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    head = "" if text.lstrip().startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")) else "# Netscape HTTP Cookie File\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(head + text.replace("\r\n", "\n"))
    try:
        os.chmod(path, 0o600)  # readable by the server's own user only (no effect on Windows)
    except OSError:
        pass
    return cookies_info()


def remove_cookies() -> None:
    try:
        os.remove(cookies_path())
    except FileNotFoundError:
        pass


def has_cookies() -> bool:
    return os.path.isfile(cookies_path())


# ---------------------------------------------------------------- ways of asking YouTube

def strategy_label(strategy: dict) -> str:
    """ "default client, without cookies, over IPv6". """
    parts = [f"{strategy['player_client']} client" if strategy["player_client"] else "default client", "with cookies" if strategy["cookies"] else "without cookies"]
    return ", ".join(parts + (["over IPv6"] if strategy["ipv6"] else []))


def strategies(*, with_cookies: bool, client: str = "", remembered: dict | None = None) -> list[dict]:
    """Every way a download is attempted, in order.

    The saved settings come first. When YouTube refuses them the others are tried: without the cookies,
    other player clients, and over IPv6. The ones that only offer low quality come last. `remembered`
    is the way that worked last time; it moves to the front.
    """
    def way(cookies: bool, player: str, ipv6: bool = False) -> dict:
        return {"cookies": cookies, "player_client": player, "ipv6": ipv6}

    ordered = [way(with_cookies, client), way(False, ""), way(False, "web_embedded"), way(False, "", True), way(False, "web_embedded", True)]
    if with_cookies:
        ordered += [way(True, ""), way(True, "web_safari"), way(True, "web_embedded"), way(True, "web_creator"), way(True, "", True), way(True, "mweb")]
    ordered += [way(False, "android_vr"), way(False, "tv_simply"), way(False, "mweb")]  # usually 360p only, but a soft clip is better than none
    first = [remembered] if remembered and (with_cookies or not remembered.get("cookies")) else []
    unique: list[dict] = []
    for strategy in first + ordered:
        strategy = {"cookies": bool(strategy.get("cookies")), "player_client": strategy.get("player_client") or "", "ipv6": bool(strategy.get("ipv6"))}
        if strategy not in unique:
            unique.append(strategy)
    return unique


def remembered() -> dict | None:
    value = _load().get("strategy")
    return value if isinstance(value, dict) else None


def working_route() -> str | None:
    """The way that last worked, in words, or None. Shown on the Integrations page."""
    strategy = remembered()
    return strategy_label({"cookies": bool(strategy.get("cookies")), "player_client": strategy.get("player_client") or "", "ipv6": bool(strategy.get("ipv6"))}) if strategy else None


def node_path() -> str | None:
    return shutil.which("node")


@contextmanager
def access_options(strategy: dict | None = None):
    """yt-dlp options that decide how YouTube is reached: proxy, cookies, player client, IPv6, JavaScript runtime.

    Without a `strategy` the saved settings are used (or the way that last worked). The cookies file is
    copied for the run, because yt-dlp rewrites it when it finishes and downloads run side by side.
    """
    if strategy is None:
        strategy = remembered() or {"cookies": has_cookies(), "player_client": player_client(), "ipv6": False}
    options: dict = {}
    address = proxy()
    if address:
        options["proxy"] = address
    if strategy.get("player_client"):
        options["extractor_args"] = {"youtube": {"player_client": strategy["player_client"].split(",")}}
    if strategy.get("ipv6"):
        options["source_address"] = "::"  # a server's IPv6 address is often trusted when its IPv4 one is not
    node = node_path()
    if node:
        # Recent yt-dlp versions need a JavaScript runtime to read YouTube and look only for Deno by themselves.
        options["js_runtimes"] = {"deno": {}, "node": {"path": node}}
    copy = None
    if strategy.get("cookies") and has_cookies():
        fd, copy = tempfile.mkstemp(suffix=".txt", prefix="cliprelay-cookies-")
        os.close(fd)
        shutil.copyfile(cookies_path(), copy)
        options["cookiefile"] = copy
    try:
        yield options
    finally:
        if copy and os.path.exists(copy):
            os.remove(copy)


def try_each(attempt, *, stop_on=()):
    """Run `attempt(access options)` with each way of reaching YouTube until one works; return its result.

    Raises DownloaderError when every way failed: the message is YouTube's answer to the saved settings,
    and `detail` lists each attempt. Exceptions listed in `stop_on` are not failures and pass straight through.
    """
    global _all_failed_at
    import yt_dlp

    ways = strategies(with_cookies=has_cookies(), client=player_client(), remembered=remembered())
    if time.time() - _all_failed_at < GIVE_UP_FOR:
        ways = ways[:1]
    failures = []
    for strategy in ways:
        try:
            with access_options(strategy) as options:
                result = attempt(options)
        except stop_on:
            raise
        except yt_dlp.utils.DownloadError as exc:
            failures.append((strategy_label(strategy), hide_proxy(str(exc).replace("ERROR: ", "").strip())))
            continue
        _store(lambda v: v.__setitem__("strategy", strategy))
        with _lock:
            _all_failed_at = 0.0
        if failures:
            log.info("download worked %s after %d refused attempt(s)", strategy_label(strategy), len(failures))
        return result
    if len(ways) > 1:
        with _lock:
            _all_failed_at = time.time()
    message = failures[0][1] + (f" | Tried {len(failures)} ways of reaching YouTube; none worked." if len(ways) > 1 else "")
    error = DownloaderError(message)
    error.detail = "\n\n".join(f"── Attempt {i}: {label} ──\n{text}" for i, (label, text) in enumerate(failures, start=1))
    raise error


def reset_state() -> None:
    """For tests: forget that every way failed."""
    global _all_failed_at
    _all_failed_at = 0.0


# ---------------------------------------------------------------- facts, test, update

def version() -> str:
    try:
        import yt_dlp

        return yt_dlp.version.__version__
    except ImportError:
        return ""


def info() -> dict:
    db = SessionLocal()
    try:
        since = utcnow() - timedelta(hours=24)
        completed = db.scalar(select(func.count(ActivityLog.id)).where(ActivityLog.event == "rendered", ActivityLog.created_at >= since)) or 0
        failed = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.FAILED, Job.updated_at >= since, Job.error.like("Download failed%"))) or 0
    finally:
        db.close()
    address = proxy()
    return {
        "installed": bool(version()), "version": version() or None,
        "cookies": has_cookies(), "cookies_file": cookies_info(),
        "options": {"proxy": mask_proxy(address), "proxy_set": bool(address), "player_client": player_client()},
        "player_clients": PLAYER_CLIENTS,
        "stats": {"completed": completed, "failed_downloads": failed},
        "working_route": working_route(),
        "js_runtime": "node" if node_path() else None,
    }


def video_id_from(url: str) -> str:
    match = re.search(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([\w-]{11})", url or "")
    if "youtu" not in (url or "") or not match:
        raise DownloaderError("Paste a YouTube video link, for example https://www.youtube.com/watch?v=…")
    return match.group(1)


def test(url: str) -> dict:
    """Look one video up without downloading it, through the configured proxy and cookies."""
    import yt_dlp

    video_id = video_id_from(url)
    try:
        with access_options({"cookies": has_cookies(), "player_client": player_client(), "ipv6": False}) as access:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True, "socket_timeout": 30, **access}) as ydl:
                data = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except yt_dlp.utils.DownloadError as exc:
        return {"ok": False, "message": hide_proxy(str(exc).replace("ERROR: ", "").strip())[:500]}
    return {"ok": True, "message": f"Reachable: “{data.get('title')}” ({round(data.get('duration') or 0)}s, {len(data.get('formats') or [])} formats)."}


def update() -> dict:
    """Upgrade yt-dlp and load the new version without a restart."""
    before = version()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", "yt-dlp"],
            capture_output=True, text=True, errors="replace", timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "The update took longer than 10 minutes and was stopped."}
    if result.returncode != 0:
        lines = [line for line in (result.stderr or result.stdout).splitlines() if line.strip()]
        return {"ok": False, "message": f"The update failed: {lines[-1][:300] if lines else 'pip gave no reason'}"}
    for name in [name for name in sys.modules if name == "yt_dlp" or name.startswith("yt_dlp.")]:
        del sys.modules[name]  # the next download imports the freshly installed version
    after = version()
    return {"ok": True, "message": f"Updated from {before} to {after}." if after != before else f"yt-dlp is up to date ({after})."}


# ---------------------------------------------------------------- diagnosis

class _Collector:
    """Keeps what yt-dlp prints during one run."""

    def __init__(self):
        self.lines: list[str] = []

    def debug(self, message):
        self.lines.append(str(message))

    info = warning = error = debug


def read_attempt(ok: bool, data: dict | None, message: str) -> dict:
    """One attempt reduced to a verdict."""
    if not ok or not data:
        return {"ok": False, "format": None, "height": None, "low": False, "message": message or "No answer."}
    height = int(data.get("height") or 0)
    width = int(data.get("width") or 0)
    resolution = data.get("resolution") or (f"{width}x{height}" if height else "audio only")
    quality = min(width, height) if width and height else height  # the short side: 1080 for both 1920×1080 and 1080×1920
    picked = f"{data.get('format_id')} {resolution}"
    # A download in low quality is still a download: the clip is made, only softer.
    return {"ok": True, "format": picked, "height": quality, "low": quality < GOOD_HEIGHT, "message": "Works" if quality >= GOOD_HEIGHT else f"Works, in low quality only ({resolution})"}


def verdict(rows: list[dict], *, with_cookies: bool, with_proxy: bool, js_runtime: str | None, current: str) -> str:
    """One or two plain sentences on what the results mean."""
    if not js_runtime:
        return "yt-dlp found no JavaScript runtime. Recent yt-dlp versions need one for YouTube: install Node.js or Deno on the server, update yt-dlp with “Update now”, then run this again."
    now = next((r for r in rows if r["client"] == current and r["cookies"] == with_cookies and not r["ipv6"]), None)
    if now and now["ok"]:
        return "Downloads work with the settings as they are now. Retry the failed videos on the Published page."
    working = next((r for r in rows if r["ok"] and not r["low"]), None) or next((r for r in rows if r["ok"]), None)
    if working:
        how = ", ".join([f"the “{working['client']}” client" if working["client"] else "the default client", "with cookies" if working["cookies"] else "without cookies"] + (["over IPv6"] if working["ipv6"] else []))
        quality = " Only low quality is on offer that way, so videos will look soft." if working["low"] else ""
        return f"YouTube refuses the saved settings, but answers {how}.{quality} ClipRelay tries this by itself when a download fails, so just retry the failed videos on the Published page."
    if with_proxy:
        return "Nothing works, even through the proxy. YouTube is refusing both this server and the proxy’s address: try a different proxy, or leave the Proxy field empty."
    return "Nothing works from this server: every player client fails, with and without cookies, over IPv4 and IPv6. YouTube is blocking the server’s address. No setting in ClipRelay can change that; the ways out are a proxy, Cloudflare WARP on the server, or running ClipRelay on a home computer."


_runs: dict[str, dict] = {}


def _simulate(url: str, strategy: dict, *, verbose: bool = False) -> tuple[bool, dict | None, str, list[str]]:
    import yt_dlp

    collector = _Collector()
    params = {"quiet": not verbose, "verbose": verbose, "no_warnings": not verbose, "noplaylist": True, "simulate": True, "format": SOURCE_FORMAT, "format_sort": FORMAT_SORT,
              "socket_timeout": 20, "retries": 1, "extractor_retries": 1, "logger": collector}
    try:
        with access_options(strategy) as access:
            with yt_dlp.YoutubeDL({**params, **access}) as ydl:
                data = ydl.extract_info(url, download=False)
        return True, data, "", collector.lines
    except yt_dlp.utils.DownloadError as exc:
        return False, None, hide_proxy(str(exc).replace("ERROR: ", "").strip())[:400], collector.lines
    except Exception as exc:  # a broken client name, a proxy that refuses, …: still an answer for the table
        return False, None, hide_proxy(f"{type(exc).__name__}: {exc}")[:400], collector.lines


def _diagnose(run: dict, url: str) -> None:
    with_cookies, current = has_cookies(), player_client()
    run["stage"] = "Checking the current settings"
    _ok, _data, message, lines = _simulate(url, {"cookies": with_cookies, "player_client": current, "ipv6": False}, verbose=True)
    output = hide_proxy("\n".join(lines + ([f"ERROR: {message}"] if message else [])))
    run["verbose"] = output[-40_000:]
    run["command"] = "yt-dlp -v --simulate --no-playlist -f <format>" + (" --proxy <proxy>" if proxy() else "") + (" --cookies <cookies file>" if with_cookies else "") + (f" --extractor-args youtube:player_client={current}" if current else "") + f" {url}"
    run["version"] = version() or None
    found = re.search(r"JS runtimes: (.+)", output)
    runtime = found.group(1).strip() if found else ("node" if node_path() else None)
    run["js_runtime"] = None if runtime in (None, "none") else runtime

    # Every client over the usual connection, then the default client over IPv6.
    plan = []
    for cookies in ([True] if with_cookies else []) + [False]:
        plan += [{"client": client, "cookies": cookies, "ipv6": False} for client in PLAYER_CLIENTS] + [{"client": "", "cookies": cookies, "ipv6": True}]
    run["total"] = len(plan)
    for step in plan:
        run["stage"] = f"Trying {step['client'] or 'the default client'} {'with cookies' if step['cookies'] else 'without cookies'}{' over IPv6' if step['ipv6'] else ''}"
        ok, data, message, _lines = _simulate(url, {"cookies": step["cookies"], "player_client": step["client"], "ipv6": step["ipv6"]})
        run["rows"].append({**step, **read_attempt(ok, data, message)})
    run["verdict"] = verdict(run["rows"], with_cookies=with_cookies, with_proxy=bool(proxy()), js_runtime=run["js_runtime"], current=current)
    run["status"], run["stage"] = "done", None


def start_diagnosis(url: str) -> dict:
    """Start a diagnosis and return it at once; progress is read with `get_diagnosis`. Nothing is downloaded or changed."""
    video_id = video_id_from(url)
    if any(run["status"] == "running" for run in _runs.values()):
        raise DownloaderError("A diagnosis is already running. Wait for it to finish.")
    if not version():
        raise DownloaderError("yt-dlp is not installed or could not be found.")
    for key in [key for key, run in _runs.items() if time.time() - run["_at"] > 3600]:
        del _runs[key]
    run = {
        "id": uuid.uuid4().hex[:16], "status": "running", "stage": "Starting", "started_at": utcnow(), "_at": time.time(),
        "cookies": has_cookies(), "proxy": bool(proxy()), "player_client": player_client(), "rows": [], "total": 0,
    }
    _runs[run["id"]] = run

    def work():
        try:
            _diagnose(run, f"https://www.youtube.com/watch?v={video_id}")
        except Exception as exc:
            log.exception("diagnosis failed")
            run.update(status="failed", stage=None, verdict=f"The diagnosis itself failed: {exc}")

    threading.Thread(target=work, name="cliprelay-diagnosis", daemon=True).start()
    return public(run)


def get_diagnosis(run_id: str) -> dict | None:
    run = _runs.get(run_id)
    return public(run) if run else None


def public(run: dict) -> dict:
    return {key: value for key, value in run.items() if not key.startswith("_")}
