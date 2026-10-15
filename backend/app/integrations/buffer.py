"""Buffer's GraphQL API: the member's channels, scheduling a video post, and asking what became of it."""

import json
import os
from datetime import datetime

import httpx

API = "https://api.buffer.com"


class BufferError(Exception):
    """Buffer refused or could not be reached. The message is written for the member."""


def text(value) -> str:
    """A string as a GraphQL literal. JSON's escapes are valid in GraphQL strings."""
    return json.dumps(str(value))


def request(api_key: str, query: str) -> dict:
    """Send one GraphQL document to Buffer and return its `data`."""
    try:
        # BUFFER_API_URL is for tests only: it points the server at a stand-in for Buffer.
        response = httpx.post(os.environ.get("BUFFER_API_URL") or API, json={"query": query}, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
    except httpx.HTTPError as exc:
        raise BufferError(f"Buffer could not be reached: {type(exc).__name__}") from exc
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code in (401, 403):
        raise BufferError("Buffer refused the API key. Check that it was copied whole and has not expired.")
    if response.status_code == 429:
        raise BufferError("Buffer’s request limit for this key has been reached. It frees up again by itself; try later.")
    problems = [item.get("message") for item in (body or {}).get("errors") or [] if isinstance(item, dict) and item.get("message")]
    if problems:
        raise BufferError(f"Buffer answered: {' · '.join(problems)[:400]}")
    if response.status_code >= 400 or not isinstance(body, dict) or not body.get("data"):
        raise BufferError(f"Buffer answered {response.status_code}: {response.text[:200]}")
    return body["data"]


def organization(api_key: str) -> str:
    profile = request(api_key, "query Organizations { account { organizations { id name } } }").get("account") or {}
    organizations = profile.get("organizations") or []
    if not organizations:
        raise BufferError("This Buffer account has no organization.")
    return organizations[0]["id"]


def channels(api_key: str, organization_id: str) -> list[dict]:
    data = request(api_key, f"query Channels {{ channels(input: {{ organizationId: {text(organization_id)} }}) {{ id name displayName service avatar }} }}")
    return data.get("channels") or []


def create_post_query(*, channel_id: str, body: str, due_at: datetime | None, video_url: str) -> str:
    """The GraphQL document for one video post: at `due_at`, or published at once when there is no time (None)."""
    when = f"mode: customScheduled dueAt: {text(due_at.strftime('%Y-%m-%dT%H:%M:%S.000Z'))}" if due_at else "mode: shareNow"
    return f"""mutation CreatePost {{
  createPost(input: {{
    text: {text(body)}
    channelId: {text(channel_id)}
    schedulingType: automatic
    {when}
    assets: [{{ video: {{ url: {text(video_url)} }} }}]
  }}) {{
    ... on PostActionSuccess {{ post {{ id status dueAt }} }}
    ... on MutationError {{ message }}
  }}
}}"""


def create_post(api_key: str, *, channel_id: str, body: str, due_at: datetime | None, video_url: str) -> dict:
    """Schedule the post, or publish it at once when `due_at` is None. Returns Buffer's post: {id, status, dueAt}."""
    result = request(api_key, create_post_query(channel_id=channel_id, body=body, due_at=due_at, video_url=video_url)).get("createPost") or {}
    post = result.get("post") or {}
    if not post.get("id"):
        raise BufferError(f"Buffer did not accept the post: {result.get('message') or 'no reason given'}")
    return post


def post(api_key: str, post_id: str) -> dict:
    data = request(api_key, f"query Post {{ post(input: {{ id: {text(post_id)} }}) {{ id status sentAt externalLink error {{ message }} }} }}")
    return data.get("post") or {}
