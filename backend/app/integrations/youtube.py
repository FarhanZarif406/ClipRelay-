"""YouTube: channel lookup, the uploads feed, video metadata and PubSubHubbub push subscriptions.

With `YOUTUBE_API_KEY` set, lookups use the YouTube Data API. Without a key they fall back to the public
channel page (lookup) and yt-dlp (metadata). The uploads feed and push notifications never need a key.
"""

import hashlib
import hmac
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse

from app.config import get_settings
from app.integrations.http import ApiError, request

API = "https://www.googleapis.com/youtube/v3"
FEED_URL = "https://www.youtube.com/feeds/videos.xml"
TOPIC_URL = "https://www.youtube.com/xml/feeds/videos.xml"
HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"
LEASE_SECONDS = 5 * 24 * 3600

CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
HANDLE_RE = re.compile(r"^@?[\w.\-]{3,60}$", re.UNICODE)
ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.8",
    "Cookie": "CONSENT=YES+cb; SOCS=CAI",
}
MAX_XML_BYTES = 256 * 1024


class YouTubeError(ApiError):
    pass


@dataclass
class ChannelInfo:
    youtube_channel_id: str
    display_name: str
    handle: str | None = None
    thumbnail_url: str | None = None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/channel/{self.youtube_channel_id}"


@dataclass
class FeedEntry:
    video_id: str
    title: str
    published_at: datetime | None


@dataclass
class VideoMeta:
    video_id: str
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    published_at: datetime | None = None
    channel_id: str | None = None
    live: bool = False  # live now or scheduled: not a finished upload yet

    @property
    def url(self) -> str:
        return watch_url(self.video_id)


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def api_key() -> str:
    from app.services import credentials

    return credentials.get("youtube.api_key")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _api(path: str, **params) -> dict:
    from app.services import youtube_usage

    response = request("GET", f"{API}/{path}", params={**params, "key": api_key()}, retries=2)
    youtube_usage.note(path, response.status_code < 400)
    if response.status_code >= 400:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text[:200]
        raise YouTubeError(f"YouTube Data API error {response.status_code}: {message}", status=response.status_code)
    return response.json()


def test_key(key: str) -> dict:
    """The cheapest real call (one quota unit) with the given key; Google's own answer is reported."""
    from app.services import youtube_usage

    if not key:
        return {"ok": False, "status": 0, "reason": None, "message": "No API key saved."}
    try:
        response = request("GET", f"{API}/i18nLanguages", params={"part": "snippet", "key": key}, retries=1, timeout=10)
    except ApiError:
        return {"ok": False, "status": 0, "reason": None, "message": "Could not reach Google."}
    youtube_usage.note("i18nLanguages", response.status_code < 400)
    if response.status_code < 400:
        return {"ok": True, "status": response.status_code, "reason": None, "message": "OK"}
    try:
        error = response.json().get("error") or {}
    except ValueError:
        error = {}
    reason = ((error.get("errors") or [{}])[0].get("reason")) or error.get("status")
    return {"ok": False, "status": response.status_code, "reason": reason, "message": error.get("message") or f"Google answered HTTP {response.status_code}"}


# ---------------------------------------------------------------- channel lookup

def parse_channel_query(text: str) -> tuple[str, str]:
    """Turn what the operator typed into ("id", "UC…") | ("handle", "@name") | ("path", "/c/name")."""
    text = (text or "").strip()
    if not text:
        raise YouTubeError("Enter a channel URL or @handle")
    if CHANNEL_ID_RE.match(text):
        return "id", text
    if "/" in text or "youtube.com" in text or "youtu.be" in text:
        parsed = urlparse(text if "://" in text else f"https://{text.lstrip('/')}")
        host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
        if host not in ("youtube.com", "youtu.be"):
            raise YouTubeError("That is not a YouTube link")
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        if host == "youtu.be" or (parts and parts[0] in ("watch", "shorts", "live", "embed", "playlist")):
            raise YouTubeError("That is a video link — paste the channel's URL or @handle instead")
        if not parts:
            raise YouTubeError("Enter a channel URL or @handle")
        if parts[0] == "channel" and len(parts) > 1 and CHANNEL_ID_RE.match(parts[1]):
            return "id", parts[1]
        if parts[0].startswith("@"):
            return "handle", parts[0]
        if parts[0] in ("c", "user") and len(parts) > 1:
            return "path", f"/{parts[0]}/{parts[1]}"
        return "path", f"/{parts[0]}"
    if HANDLE_RE.match(text):
        return "handle", "@" + text.lstrip("@")
    raise YouTubeError("Enter a channel URL or @handle")


def _channel_from_api(kind: str, value: str) -> ChannelInfo | None:
    if kind == "path":
        return None
    params = {"id": value} if kind == "id" else {"forHandle": value}
    items = _api("channels", part="snippet", **params).get("items") or []
    if not items:
        raise YouTubeError("No YouTube channel found for that URL or handle", status=404)
    snippet = items[0].get("snippet", {})
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    return ChannelInfo(items[0]["id"], snippet.get("title", ""), snippet.get("customUrl"), thumb)


def _meta(page: str, prop: str) -> str | None:
    match = re.search(rf'<meta[^>]+(?:property|name|itemprop)="{re.escape(prop)}"[^>]+content="([^"]*)"', page)
    return html.unescape(match.group(1)) if match else None


def _channel_from_page(kind: str, value: str) -> ChannelInfo:
    path = f"/channel/{value}" if kind == "id" else f"/{value}" if kind == "handle" else value
    response = request("GET", f"https://www.youtube.com{path}", headers=BROWSER_HEADERS, retries=2, follow_redirects=True)
    if response.status_code == 404:
        raise YouTubeError("No YouTube channel found for that URL or handle", status=404)
    if response.status_code >= 400:
        raise YouTubeError(f"YouTube returned HTTP {response.status_code} for that channel", status=response.status_code)
    page = response.text
    found = (
        re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', page)
        or re.search(r'"externalId":"(UC[\w-]{22})"', page)
        or re.search(r'<meta itemprop="(?:identifier|channelId)" content="(UC[\w-]{22})"', page)
    )
    if not found:
        raise YouTubeError("Could not read that channel page — check the URL or handle")
    handle = re.search(r'"(?:vanityChannelUrl|canonicalBaseUrl)":"[^"]*?/?(@[\w.\-]+)"', page)
    return ChannelInfo(
        found.group(1),
        _meta(page, "og:title") or (handle.group(1) if handle else found.group(1)),
        handle.group(1) if handle else (value if kind == "handle" else None),
        _meta(page, "og:image"),
    )


def resolve_channel(query: str) -> ChannelInfo:
    kind, value = parse_channel_query(query)
    info = _channel_from_api(kind, value) if api_key() else None
    return info or _channel_from_page(kind, value)


# ---------------------------------------------------------------- uploads feed (polling fallback)

def _parse_xml(body: bytes) -> ET.Element:
    if len(body) > MAX_XML_BYTES or b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        raise YouTubeError("Refusing to parse an unexpected XML document")
    try:
        return ET.fromstring(body)
    except ET.ParseError as exc:
        raise YouTubeError(f"Invalid XML from YouTube: {exc}") from exc


def _entries(root: ET.Element) -> list[tuple[str, str, FeedEntry]]:
    out = []
    for entry in root.findall("a:entry", ATOM):
        video_id = entry.findtext("yt:videoId", default="", namespaces=ATOM).strip()
        if not video_id:
            continue
        channel_id = entry.findtext("yt:channelId", default="", namespaces=ATOM).strip()
        published = _parse_time(entry.findtext("a:published", default="", namespaces=ATOM))
        out.append((channel_id, video_id, FeedEntry(video_id, entry.findtext("a:title", default="", namespaces=ATOM), published)))
    return out


def feed(youtube_channel_id: str) -> list[FeedEntry]:
    """The channel's most recent uploads (about 15), oldest first."""
    response = request("GET", FEED_URL, params={"channel_id": youtube_channel_id}, retries=2)
    if response.status_code == 404:
        raise YouTubeError("YouTube has no uploads feed for this channel (was it deleted?)", status=404)
    if response.status_code >= 400:
        raise YouTubeError(f"YouTube feed returned HTTP {response.status_code}", status=response.status_code)
    entries = [entry for _channel, _video, entry in _entries(_parse_xml(response.content))]
    return sorted(entries, key=lambda e: e.published_at or datetime.min.replace(tzinfo=timezone.utc))


# ---------------------------------------------------------------- video metadata

ISO_DURATION_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_iso_duration(value: str) -> float | None:
    match = ISO_DURATION_RE.match(value or "")
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return float(days * 86400 + hours * 3600 + minutes * 60 + seconds)


def _video_from_api(video_id: str) -> VideoMeta:
    items = _api("videos", part="snippet,contentDetails,liveStreamingDetails", id=video_id).get("items") or []
    if not items:
        raise YouTubeError(f"YouTube video {video_id} was not found (private or deleted?)", status=404)
    snippet, details = items[0].get("snippet", {}), items[0].get("contentDetails", {})
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    live = snippet.get("liveBroadcastContent", "none") != "none"
    return VideoMeta(
        video_id, snippet.get("title", ""), snippet.get("description", ""), list(snippet.get("tags") or []),
        parse_iso_duration(details.get("duration", "")), thumb, _parse_time(snippet.get("publishedAt")), snippet.get("channelId"), live,
    )


def _video_from_ytdlp(video_id: str) -> VideoMeta:
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise YouTubeError("yt-dlp is not installed, and no YOUTUBE_API_KEY is set") from exc
    from app.services import downloader  # the saved proxy, cookies and player client apply to every lookup

    options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "socket_timeout": 30}
    try:
        with downloader.access_options() as access, yt_dlp.YoutubeDL({**options, **access}) as ydl:
            info = ydl.extract_info(watch_url(video_id), download=False, process=False)
    except yt_dlp.utils.DownloadError as exc:
        raise YouTubeError(f"Could not read YouTube video {video_id}: {str(exc)[:200]}") from exc
    published = datetime.fromtimestamp(info["timestamp"], timezone.utc) if info.get("timestamp") else None
    if published is None and info.get("upload_date"):
        published = datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc)
    return VideoMeta(
        video_id, info.get("title") or "", info.get("description") or "", list(info.get("tags") or []),
        float(info["duration"]) if info.get("duration") else None, info.get("thumbnail"), published, info.get("channel_id"),
        info.get("live_status") in ("is_live", "is_upcoming", "post_live"),
    )


def transcript(video_id: str) -> list[tuple[float, str]]:
    """What is said in the video, as (start in seconds, text). Empty when the video has no subtitles.

    Uploaded subtitles are preferred over YouTube's automatic ones, in the video's own language.
    """
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise YouTubeError("yt-dlp is not installed on the server") from exc
    from app.services import downloader  # the saved proxy, cookies and player client apply to every lookup

    options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "socket_timeout": 30}
    try:
        with downloader.access_options() as access, yt_dlp.YoutubeDL({**options, **access}) as ydl:
            info = ydl.extract_info(watch_url(video_id), download=False, process=False)
    except yt_dlp.utils.DownloadError as exc:
        raise YouTubeError(f"Could not read YouTube video {video_id}: {str(exc)[:200]}") from exc
    url = _subtitle_url(info)
    if not url:
        return []
    response = request("GET", url, headers=BROWSER_HEADERS, retries=2)
    if response.status_code >= 400:
        raise YouTubeError(f"YouTube returned HTTP {response.status_code} for the subtitles", status=response.status_code)
    try:
        events = response.json().get("events", [])
    except ValueError as exc:
        raise YouTubeError("YouTube returned subtitles in an unexpected format") from exc
    out = []
    for event in events:
        text = "".join(seg.get("utf8", "") for seg in event.get("segs") or []).replace("\n", " ").strip()
        if text:
            out.append((float(event.get("tStartMs", 0)) / 1000, text))
    return out


def _subtitle_url(info: dict) -> str | None:
    wanted = [info.get("language"), "en", "hi", "ur"]
    for tracks in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        languages = [code for code in wanted if code and code in tracks] + [code for code in tracks if "-orig" in code] + list(tracks)
        for code in languages:
            for track in tracks.get(code) or []:
                if track.get("ext") == "json3" and track.get("url"):
                    return track["url"]
    return None


def is_short(video_id: str) -> bool:
    """Whether YouTube itself treats the video as a Short.

    YouTube serves a Short at /shorts/<id>; for a regular video the same address redirects to /watch.
    Anything else (a consent page, a block, an outage) is not an answer, so it raises and the caller retries later.
    """
    response = request("GET", f"https://www.youtube.com/shorts/{video_id}", headers=BROWSER_HEADERS, retries=2, follow_redirects=False)
    if response.status_code == 200:
        return True
    if response.status_code in (301, 302, 303, 307, 308) and "/watch" in response.headers.get("location", ""):
        return False
    raise YouTubeError(f"Could not tell whether {video_id} is a Short (YouTube answered {response.status_code})", status=response.status_code)


def video_details(video_id: str) -> VideoMeta:
    return _video_from_api(video_id) if api_key() else _video_from_ytdlp(video_id)


# ---------------------------------------------------------------- push notifications (PubSubHubbub)

def callback_url() -> str:
    from app.services import push  # the address saved on the Integrations page, else PUBLIC_BASE_URL

    return f"{push.base_url()}/api/youtube/webhook"


def push_available() -> bool:
    """The hub can only reach a public HTTPS address, so local installs rely on polling alone."""
    from app.services import push

    return push.is_public(push.base_url())


def hub_secret() -> str:
    return hmac.new(get_settings().secret_key.encode(), b"youtube-pubsub", hashlib.sha256).hexdigest()


def topic_url(youtube_channel_id: str) -> str:
    return f"{TOPIC_URL}?channel_id={youtube_channel_id}"


def channel_id_from_topic(topic: str) -> str | None:
    values = parse_qs(urlparse(topic or "").query).get("channel_id")
    return values[0] if values else None


def subscribe(youtube_channel_id: str, *, mode: str = "subscribe", verify_token: str = "") -> None:
    """Ask the hub to (un)subscribe. The hub then calls our webhook to verify, which stores the expiry."""
    data = {
        "hub.mode": mode, "hub.topic": topic_url(youtube_channel_id), "hub.callback": callback_url(),
        "hub.verify": "async", "hub.lease_seconds": str(LEASE_SECONDS), "hub.secret": hub_secret(),
    }
    if verify_token:
        data["hub.verify_token"] = verify_token  # sent back by the hub when it verifies, and checked there
    response = request("POST", HUB_URL, retries=2, data=data)
    if response.status_code not in (202, 204):
        raise YouTubeError(f"The YouTube push hub refused the request ({response.status_code}): {response.text[:200]}", status=response.status_code)


def verify_signature(body: bytes, header: str | None) -> bool:
    if not header or "=" not in header:
        return False
    algorithm, _, sent = header.partition("=")
    if algorithm not in ("sha1", "sha256"):
        return False
    expected = hmac.new(hub_secret().encode(), body, algorithm).hexdigest()
    return hmac.compare_digest(expected, sent.strip())


def parse_notification(body: bytes) -> list[tuple[str, str]]:
    """Return (channel id, video id) for each upload or edit in a push notification. Deletions are ignored."""
    return [(channel_id, video_id) for channel_id, video_id, _entry in _entries(_parse_xml(body)) if channel_id]
