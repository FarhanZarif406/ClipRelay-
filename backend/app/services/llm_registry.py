"""Resolves which LLM to use: a specific provider, the workspace default, or the LLM_* values in .env.

Cached for 30 s per process and cleared by the same broadcast as the credential store.
"""

import logging
import threading
import time

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.integrations.llm import LLMConfig
from app.models import LLMProvider
from app.security import decrypt
from app.services import credentials

log = logging.getLogger(__name__)
TTL = 30.0

_lock = threading.Lock()
_cache: tuple[dict[int, LLMConfig], dict[int, int | None], dict[int | None, int]] | None = None
_loaded_at = 0.0


def bust() -> None:
    global _cache
    with _lock:
        _cache = None


credentials.on_bust(bust)


def to_config(row: LLMProvider) -> LLMConfig:
    return LLMConfig(
        provider=row.provider, api_key=decrypt(row.api_key_enc) or "", model=row.model, base_url=row.base_url or None,
        max_tokens=row.max_tokens or 600, temperature=row.temperature, id=row.id, label=row.label,
    )


def _load() -> tuple[dict[int, LLMConfig], dict[int, int | None], dict[int | None, int]]:
    """Every AI model, whose it is (None: the owners'), and the default of each owner of models."""
    global _cache, _loaded_at
    with _lock:
        if _cache is not None and time.monotonic() - _loaded_at < TTL:
            return _cache
    configs: dict[int, LLMConfig] = {}
    owners: dict[int, int | None] = {}
    defaults: dict[int | None, int] = {}
    db = SessionLocal()
    try:
        for row in db.scalars(select(LLMProvider).order_by(LLMProvider.id)):
            try:
                configs[row.id] = to_config(row)
            except RuntimeError:
                log.error("LLM provider %s key could not be decrypted", row.id)
                continue
            owners[row.id] = row.user_id
            if row.is_default and row.user_id not in defaults:
                defaults[row.user_id] = row.id
    except Exception as exc:  # table missing before migrations, DB down, …
        log.warning("LLM providers unavailable, falling back to .env: %s", exc)
    finally:
        db.close()
    for provider_id, scope in owners.items():
        defaults.setdefault(scope, provider_id)  # a set without a default uses its first model
    with _lock:
        _cache, _loaded_at = (configs, owners, defaults), time.monotonic()
    return configs, owners, defaults


def env_config() -> LLMConfig | None:
    s = get_settings()
    if not s.llm_api_key:
        return None
    return LLMConfig(provider=s.llm_provider, api_key=s.llm_api_key, model=s.llm_model, base_url=s.llm_base_url or None,
                     max_tokens=s.llm_max_tokens, label=".env")


def get_config(provider_id: int | None = None) -> LLMConfig | None:
    """The AI model to use for whoever the code is acting for (app.services.acting).

    The requested one if it is theirs, else their default. A member only ever gets their own models, so with none
    there is no AI for them (None). The owners fall back to the LLM_* values in .env when they have no model.
    """
    from app.services import acting

    scope = acting.current()
    configs, owners, defaults = _load()
    if provider_id is not None and provider_id in configs and owners.get(provider_id) == scope:
        return configs[provider_id]
    if scope in defaults:
        return configs[defaults[scope]]
    return env_config() if scope is None else None
