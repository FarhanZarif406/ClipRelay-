"""Integrations (members) and the workspace Integrations page (owners): every account's own AI models.

The owners share one set (no user); every member has their own, and with none they get no AI. An owner can also
manage a member's set for them with ?for_user=<account id>.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from app.api.credentials import mask
from app.api.deps import DB, CurrentUser
from app.integrations import llm
from app.integrations.http import ApiError
from app.models import LLMProvider, User, utcnow
from app.schemas.llm import ProviderIn, ProviderUpdate, ValidateProviderIn
from app.security import decrypt, encrypt
from app.services import activity, credentials, llm_registry

router = APIRouter(prefix="/llm-providers", tags=["ai-models"])
TEST_PROMPT = "Reply with the single word OK."


def _scope(db, user: User, for_user: int | None) -> int | None:
    """Whose models a request is about: None for the owners' set, else a member's id."""
    if for_user is None:
        return None if user.is_owner else user.id
    if not user.is_owner:
        raise HTTPException(403, "Only owners can manage another account's AI models")
    target = db.get(User, for_user)
    if not target or not target.is_active:
        raise HTTPException(404, "Account not found")
    return None if target.is_owner else target.id


def _in(scope: int | None):
    return LLMProvider.user_id.is_(None) if scope is None else LLMProvider.user_id == scope


def _item(row: LLMProvider, user: User) -> dict:
    item = {
        "id": row.id, "label": row.label, "provider": row.provider, "model": row.model, "base_url": row.base_url,
        "max_tokens": row.max_tokens, "temperature": row.temperature, "is_default": row.is_default, "status": row.status,
        "last_error": row.last_error, "last_tested_at": row.last_tested_at, "updated_at": row.updated_at,
    }
    if user.is_owner or row.user_id == user.id:  # a member sees the end of their own key
        try:
            item["masked_key"] = mask(decrypt(row.api_key_enc) or "")
        except RuntimeError:
            item["masked_key"] = "unreadable — re-enter the key"
    return item


def _get(db, provider_id: int, scope: int | None) -> LLMProvider:
    row = db.get(LLMProvider, provider_id)
    if not row or row.user_id != scope:
        raise HTTPException(404, "AI model not found")
    return row


def _models_or_400(cfg: llm.LLMConfig) -> list[str]:
    try:
        return llm.list_models(cfg)
    except ApiError as exc:
        raise HTTPException(400, f"Validation failed: {exc}") from exc


def _changed(db) -> None:
    db.commit()
    credentials.changed()  # clears the LLM cache here and in workers


@router.get("")
def list_providers(db: DB, user: CurrentUser, for_user: int | None = None):
    scope = _scope(db, user, for_user)
    rows = db.scalars(select(LLMProvider).where(_in(scope)).order_by(LLMProvider.is_default.desc(), LLMProvider.id)).all()
    env = llm_registry.env_config() if scope is None else None  # .env is the owners' fallback only
    return {
        "items": [_item(r, user) for r in rows],
        "providers": list(llm.PROVIDERS),
        "env_fallback": {"configured": env is not None, "provider": env.provider if env else None, "model": env.model if env else None, "active": not rows},
    }


@router.post("/validate")
def validate(body: ValidateProviderIn, db: DB, user: CurrentUser, for_user: int | None = None):
    scope = _scope(db, user, for_user)
    key = body.api_key.strip()
    if not key and body.provider_id:
        key = decrypt(_get(db, body.provider_id, scope).api_key_enc) or ""
    models = _models_or_400(llm.LLMConfig(provider=body.provider, api_key=key, model="", base_url=(body.base_url or "").strip() or None))
    return {"models": models}


@router.post("", status_code=201)
def create(body: ProviderIn, db: DB, user: CurrentUser, for_user: int | None = None):
    scope = _scope(db, user, for_user)
    cfg = llm.LLMConfig(provider=body.provider, api_key=body.api_key.strip(), model=body.model, base_url=(body.base_url or "").strip() or None)
    _models_or_400(cfg)
    first = db.scalar(select(LLMProvider.id).where(_in(scope)).limit(1)) is None
    row = LLMProvider(
        user_id=scope, label=body.label.strip(), provider=body.provider, api_key_enc=encrypt(cfg.api_key), base_url=cfg.base_url, model=body.model,
        max_tokens=body.max_tokens, temperature=body.temperature, is_default=first, status="valid", last_tested_at=utcnow(),
    )
    db.add(row)
    db.flush()
    activity.record(db, "Settings", f"AI model “{row.label}” ({row.provider} · {row.model}) added by {user.email}", event="llm_added")
    _changed(db)
    return _item(row, user)


@router.patch("/{provider_id}")
def edit(provider_id: int, body: ProviderUpdate, db: DB, user: CurrentUser, for_user: int | None = None):
    row = _get(db, provider_id, _scope(db, user, for_user))
    data = body.model_dump(exclude_unset=True)
    new_key = (data.pop("api_key", None) or "").strip()
    connection_changed = bool(new_key) or ("provider" in data and data["provider"] != row.provider) or ("base_url" in data and (data["base_url"] or None) != row.base_url)
    if data.pop("clear_temperature", False):
        row.temperature = None
    for field in ("label", "provider", "model", "max_tokens", "temperature"):
        if data.get(field) is not None:
            setattr(row, field, data[field])
    if "base_url" in data:
        row.base_url = (data["base_url"] or "").strip() or None
    if row.provider == "custom" and not row.base_url:
        raise HTTPException(422, "A base URL is required for custom providers")
    if connection_changed:
        key = new_key or decrypt(row.api_key_enc) or ""
        _models_or_400(llm.LLMConfig(provider=row.provider, api_key=key, model=row.model, base_url=row.base_url))
        if new_key:
            row.api_key_enc = encrypt(new_key)
        row.status, row.last_error, row.last_tested_at = "valid", None, utcnow()
    activity.record(db, "Settings", f"AI model “{row.label}” updated by {user.email}" + (" (new key)" if new_key else ""), event="llm_updated")
    _changed(db)
    return _item(row, user)


@router.post("/{provider_id}/default")
def make_default(provider_id: int, db: DB, user: CurrentUser, for_user: int | None = None):
    scope = _scope(db, user, for_user)
    row = _get(db, provider_id, scope)
    db.execute(update(LLMProvider).where(_in(scope)).values(is_default=False))
    row.is_default = True
    activity.record(db, "Settings", f"“{row.label}” set as the default AI model by {user.email}", event="llm_default")
    _changed(db)
    return _item(row, user)


@router.post("/{provider_id}/test")
def test(provider_id: int, db: DB, user: CurrentUser, for_user: int | None = None):
    row = _get(db, provider_id, _scope(db, user, for_user))
    try:
        reply = llm.complete_with(llm_registry.to_config(row), TEST_PROMPT, max_tokens=10)
        ok, message = True, f"{row.model} replied: {reply[:40]}"
        row.status, row.last_error = "valid", None
    except (ApiError, RuntimeError) as exc:
        ok, message = False, str(exc)[:300]
        row.status, row.last_error = "invalid", message
    row.last_tested_at = utcnow()
    activity.record(db, "Settings", f"AI model “{row.label}” tested: {'ok' if ok else 'failed'}", event="llm_tested", level="info" if ok else "warning")
    _changed(db)
    return {"ok": ok, "message": message, "item": _item(row, user)}


@router.delete("/{provider_id}")
def delete(provider_id: int, db: DB, user: CurrentUser, new_default_id: int | None = None, for_user: int | None = None):
    scope = _scope(db, user, for_user)
    row = _get(db, provider_id, scope)
    others = db.scalars(select(LLMProvider).where(_in(scope), LLMProvider.id != row.id)).all()
    if row.is_default and others:
        replacement = next((o for o in others if o.id == new_default_id), None)
        if replacement is None:
            raise HTTPException(409, {"code": "choose_default", "message": "Choose which AI model becomes the default first."})
        replacement.is_default = True
    label = row.label
    db.delete(row)
    env = llm_registry.env_config() if scope is None else None
    fallback = None if others else ("env" if env else "none")
    activity.record(db, "Settings", f"AI model “{label}” removed by {user.email}" + (" — using LLM_* from .env" if fallback == "env" else " — no AI model configured" if fallback == "none" else ""), event="llm_removed", level="warning" if fallback == "none" else "info")
    _changed(db)
    return {"fallback": fallback}
