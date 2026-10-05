"""Live updates: publish small JSON events to Redis pub/sub; the SSE endpoint relays them to browsers."""

import json
import logging
import time
from functools import lru_cache

import redis

from app.config import get_settings

CHANNEL = "cliprelay:events"
log = logging.getLogger(__name__)


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=2)


_down_until = 0.0


def publish(event_type: str, **data) -> None:
    global _down_until
    if get_settings().environment == "test" or time.monotonic() < _down_until:
        return
    try:
        get_redis().publish(CHANNEL, json.dumps({"type": event_type, **data}, default=str))
    except redis.RedisError as exc:  # live updates are best-effort; back off for 30s when Redis is down
        _down_until = time.monotonic() + 30
        log.warning("live event publish failed (Redis unavailable?): %s", exc)
