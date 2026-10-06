import os
import subprocess
import tempfile

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, OwnerUser
from app.config import get_settings
from app.integrations import instagram, llm, tiktok, transcription
from app.integrations.http import ApiError
from app.models import InstagramSource, TikTokAccount, TikTokStatus
from app.schemas import AuditIn, NotificationsIn, PolicyIn
from app.security import decrypt
from app.services import activity, credentials, notify, workspace_settings
from app.services.storage import get_storage

router = APIRouter(prefix="/settings", tags=["settings"])


def _save(db, key: str, body) -> dict:
    value = workspace_settings.update(db, key, body.model_dump(exclude_none=True))
    activity.record(db, "Settings", f"{key.capitalize()} settings updated", event=f"{key}_updated", payload=body.model_dump(exclude_none=True))
    db.commit()
    return value


@router.get("/policy")
def get_policy(db: DB, _: CurrentUser):
    return workspace_settings.get(db, "policy")


@router.put("/policy")
def put_policy(body: PolicyIn, db: DB, _: CurrentUser):
    return _save(db, "policy", body)


@router.get("/audit")
def get_audit(db: DB, _: CurrentUser):
    return workspace_settings.get(db, "audit")


@router.put("/audit")
def put_audit(body: AuditIn, db: DB, _: CurrentUser):
    return _save(db, "audit", body)


@router.get("/notifications")
def get_notifications(db: DB, _: CurrentUser):
    return workspace_settings.get(db, "notifications")


@router.put("/notifications")
def put_notifications(body: NotificationsIn, db: DB, _: CurrentUser):
    return _save(db, "notifications", body)


@router.post("/notifications/test")
def test_notification(db: DB, _: CurrentUser):
    if not workspace_settings.get(db, "notifications").get("webhook_url"):
        raise HTTPException(400, "Set a webhook URL first")
    ok = notify.send(db, "violation", "Test notification — your webhook is connected.")
    return {"ok": ok, "message": "Sent" if ok else "Webhook call failed or notifications are disabled"}


@router.post("/onboarding/complete")
def complete_onboarding(db: DB, _: CurrentUser):
    value = workspace_settings.update(db, "onboarding", {"completed": True})
    db.commit()
    return value


def _mask(value: str, prefix: int = 6) -> str:
    if not value:
        return "Not configured"
    return f"{value[:prefix]}••••••••••••{value[-4:]}" if len(value) > prefix + 4 else "••••••••"


@router.get("/integrations")
def integrations(user: CurrentUser):
    """Status of every integration. Masked values are only included for owners."""
    s = get_settings()
    ig_id, tt_key = credentials.get("instagram.app_id"), credentials.get("tiktok.client_key")
    llm_cfg = llm.resolve()
    rows = [
        ("llm", f"AI model · {llm_cfg.label or llm_cfg.provider} · {llm_cfg.model}" if llm_cfg else "AI model", llm_cfg.api_key if llm_cfg else "", ("env" if llm_cfg and llm_cfg.id is None else "app") if llm_cfg else None),
        ("instagram", "Instagram Graph API", ig_id and credentials.get("instagram.app_secret") and ig_id, credentials.source("instagram.app_id")),
        ("tiktok", "TikTok Content Posting API", tt_key and credentials.get("tiktok.client_secret") and tt_key, credentials.source("tiktok.client_key")),
        ("storage", f"Storage · {s.storage_backend}", s.s3_bucket if s.storage_backend == "s3" else os.path.abspath(s.storage_local_path), "env"),
        ("transcription", "Transcription (language gate)", credentials.get("transcription.api_key"), credentials.source("transcription.api_key")),
        ("ffmpeg", "FFmpeg / ffprobe", s.ffprobe_path, "env"),
    ]
    out = []
    for key, name, value, origin in rows:
        item = {"key": key, "name": name, "configured": bool(value), "source": origin if value else None}
        if user.is_owner:
            item["masked"] = value if key in ("storage", "ffmpeg") else _mask(value or "")
        else:
            item["masked"] = "Configured" if value else "Needs setup"
        out.append(item)
    return out


@router.post("/integrations/{key}/test")
def test_integration(key: str, db: DB, _: OwnerUser):
    s = get_settings()
    try:
        if key == "llm":
            reply = llm.complete("Reply with the single word OK.", max_tokens=5)
            message = f"{llm.resolve().model} replied: {reply[:20]}"
        elif key == "instagram":
            if not credentials.get("instagram.app_id"):
                raise ApiError("Instagram App ID is not set")
            source = db.scalar(select(InstagramSource).where(InstagramSource.access_token_enc.is_not(None)).limit(1))
            if not source:
                message = "App credentials set · connect an account to verify tokens"
            else:
                profile = instagram.get_profile(decrypt(source.access_token_enc) or "")
                message = f"Token valid for @{profile.get('username')}"
        elif key == "tiktok":
            if not credentials.get("tiktok.client_key"):
                raise ApiError("TikTok client key is not set")
            account = db.scalar(select(TikTokAccount).where(TikTokAccount.status == TikTokStatus.ACTIVE).limit(1))
            if not account:
                message = "App credentials set · connect an account to verify tokens"
            else:
                from app.services.tokens import tiktok_token

                creator = tiktok.creator_info(tiktok_token(db, account))
                db.commit()
                message = f"Token valid for @{creator.get('creator_username', account.username)}"
        elif key == "storage":
            storage = get_storage()
            if hasattr(storage, "test"):
                storage.test()
            else:
                fd, path = tempfile.mkstemp()
                os.close(fd)
                with open(path, "w") as fh:
                    fh.write("ok")
                storage.save(path, ".healthcheck")
                storage.delete(".healthcheck")
            message = "Storage is writable"
        elif key == "transcription":
            if not transcription.enabled():
                raise ApiError("Transcription API key is not set (captions are used for language detection instead)")
            message = "Transcription key configured"
        elif key == "ffmpeg":
            out = subprocess.run([s.ffprobe_path, "-version"], capture_output=True, text=True, timeout=10, check=True).stdout
            message = out.split("\n", 1)[0][:80]
        else:
            raise HTTPException(404, "Unknown integration")
    except (ApiError, OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return {"ok": False, "message": str(exc)[:300]}
    except Exception as exc:  # e.g. boto errors
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:250]}"}
    return {"ok": True, "message": message}
