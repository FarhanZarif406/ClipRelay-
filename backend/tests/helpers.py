import httpx

ANTHROPIC = "https://api.anthropic.com/v1/messages"
CDN = "https://cdn.videos.test"


def claude(text: str):
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})
