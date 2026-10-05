"""Shared HTTP helper: retries transient failures with exponential backoff + jitter."""

import logging
import random
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body


class AuthError(ApiError):
    """Token is invalid/expired — retrying won't help; the account needs reconnecting or refreshing."""


class RateLimitError(ApiError):
    pass


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    return min(cap, base * 2**attempt) * (0.5 + random.random() / 2)


def request(
    method: str,
    url: str,
    *,
    retries: int = 4,
    base_delay: float = 1.0,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
    **kwargs,
) -> httpx.Response:
    """Perform an HTTP request, retrying network errors and 429/5xx with exponential backoff."""
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        for attempt in range(retries + 1):
            try:
                response = client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt >= retries:
                    raise ApiError(f"Network error calling {url}: {exc}") from exc
                delay = backoff_delay(attempt, base_delay)
                log.warning("network error %s, retrying in %.1fs", exc, delay)
                time.sleep(delay)
                continue
            if response.status_code in RETRY_STATUS and attempt < retries:
                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else backoff_delay(attempt, base_delay)
                log.warning("%s %s -> %s, retrying in %.1fs", method, url, response.status_code, delay)
                time.sleep(delay)
                continue
            return response
        raise ApiError(f"Exhausted retries for {url}")  # pragma: no cover
    finally:
        if owns_client:
            client.close()
