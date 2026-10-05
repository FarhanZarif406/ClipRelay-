import httpx

GRAPH_MEDIA = "https://graph.instagram.com/v21.0/1789/media"
ANTHROPIC = "https://api.anthropic.com/v1/messages"
TT = "https://open.tiktokapis.com/v2"
UPLOAD_URL = "https://open-upload.tiktokapis.com/video/?upload_id=abc"


def ig_media(*items):
    return httpx.Response(200, json={"data": list(items)})


def ig_video(media_id: str, caption: str = "Hidden beaches in Crete #crete #travel", url: str | None = None, media_type: str = "VIDEO"):
    return {
        "id": media_id,
        "caption": caption,
        "media_type": media_type,
        "media_product_type": "REELS",
        "media_url": url or f"https://cdn.instagram.test/{media_id}.mp4",
        "permalink": f"https://instagram.com/reel/{media_id}",
        "thumbnail_url": None,
        "timestamp": "2026-10-05T10:00:00+0000",
    }


def claude(text: str):
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def tt_ok(data: dict):
    return httpx.Response(200, json={"data": data, "error": {"code": "ok", "message": "", "log_id": "x"}})


def tt_err(code: str, status: int = 400):
    return httpx.Response(status, json={"data": {}, "error": {"code": code, "message": code, "log_id": "x"}})


CREATOR = {
    "creator_username": "northbound",
    "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
    "comment_disabled": False,
    "duet_disabled": False,
    "stitch_disabled": True,
    "max_video_post_duration_sec": 600,
}
