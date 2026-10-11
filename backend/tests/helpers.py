import httpx

ANTHROPIC = "https://api.anthropic.com/v1/messages"
TT = "https://open.tiktokapis.com/v2"
UPLOAD_URL = "https://open-upload.tiktokapis.com/video/?upload_id=abc"
CDN = "https://cdn.videos.test"


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
