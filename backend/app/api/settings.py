import os
import shutil
import subprocess
import tempfile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, OwnerUser
from app.config import get_settings
from app.integrations import llm, tiktok, youtube
from app.integrations.http import ApiError
from app.models import TikTokAccount, TikTokStatus
from app.schemas import AuditIn, NotificationsIn, PolicyIn
from app.services import activity, credentials, mailer, media, notify, rules, workspace_settings
from app.services.storage import get_storage

router = APIRouter(prefix="/settings", tags=["settings"])


def _save(db, key: str, body) -> dict:
    value = workspace_settings.update(db, key, body.model_dump(exclude_none=True))
    activity.record(db, "Settings", f"{key.capitalize()} settings updated", event=f"{key}_updated", payload=body.model_dump(exclude_none=True))
    db.commit()
    return value


class RulesIn(BaseModel):
    values: dict[str, bool | int | float | str | None]


@router.get("/rules")
def get_rules(db: DB, _: CurrentUser):
    """The pipeline rules: what each one is, and its current global value."""
    return {"definitions": rules.describe(), "values": rules.global_values(db)}


@router.put("/rules")
def put_rules(body: RulesIn, db: DB, user: CurrentUser):
    """Change global rules. They apply to the next job; a null value resets a rule to its default."""
    try:
        changes = rules.set_values(db, body.values, user=user)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if changes:
        activity.record(db, "Settings", f"{user.email} changed {', '.join(c.key for c in changes)}", event="rules_updated")
    db.commit()
    return {"definitions": rules.describe(), "values": rules.global_values(db)}


@router.get("/rules/history")
def rules_history(db: DB, _: CurrentUser, channel_id: int | None = None, limit: int = 50):
    """Who changed which rule, and when."""
    return rules.history(db, channel_id=channel_id, limit=min(max(limit, 1), 200))


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


@router.post("/notifications/test-email")
def test_email(db: DB, _: CurrentUser):
    to = notify.recipients(workspace_settings.get(db, "notifications"))
    if not to:
        raise HTTPException(400, "Add an alert email address first")
    if not mailer.configured():
        raise HTTPException(400, "Configure SMTP first (host and from address)")
    try:
        mailer.send(to, "ClipRelay: test email", "This is a test alert from ClipRelay. Email notifications are working.\n\n— ClipRelay")
    except Exception as exc:
        activity.record(db, "Settings", f"Test email failed: {type(exc).__name__}", level="warning", event="email_test")
        db.commit()
        return {"ok": False, "message": f"Sending failed: {exc}"[:300]}
    activity.record(db, "Settings", f"Test email sent to {len(to)} recipient(s)", event="email_test")
    db.commit()
    return {"ok": True, "message": f"Sent to {', '.join(to)}"}


@router.post("/onboarding/complete")
def complete_onboarding(db: DB, _: CurrentUser):
    value = workspace_settings.update(db, "onboarding", {"completed": True})
    db.commit()
    return value


def _ytdlp_version() -> str:
    try:
        import yt_dlp

        return yt_dlp.version.__version__
    except ImportError:
        return ""


def _test_editor() -> str:
    """Make a two-second clip and run the real edit on it (speed-up, flip, sound), so the whole editor is proven."""
    exe = media.ffmpeg_exe()
    version = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=10, check=True).stdout.split("\n", 1)[0]
    fd, src = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    out = None
    try:
        subprocess.run(
            [exe, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=30:duration=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src],
            capture_output=True, text=True, timeout=60, check=True,
        )
        out = media.render(src, speed=1.08, flip=True, keep_audio=True)
        result = media.probe(out)
    except media.RenderError as exc:
        raise RuntimeError(f"FFmpeg is installed but the edit failed: {exc}") from exc
    finally:
        for path in (src, out):
            if path and os.path.exists(path):
                os.remove(path)
    words = version.split()
    return f"FFmpeg {words[2] if len(words) > 2 else ''} edited a test clip: 2.00s → {result.duration:.2f}s at 1.08x, flipped, sound kept"


def _mask(value: str, prefix: int = 6) -> str:
    if not value:
        return "Not configured"
    return f"{value[:prefix]}••••••••••••{value[-4:]}" if len(value) > prefix + 4 else "••••••••"


@router.get("/integrations")
def integrations(user: CurrentUser):
    """Status of every integration. Masked values are only included for owners."""
    s = get_settings()
    tt_key = credentials.get("tiktok.client_key")
    llm_cfg = llm.resolve()
    rows = [
        ("llm", f"AI model · {llm_cfg.label or llm_cfg.provider} · {llm_cfg.model}" if llm_cfg else "AI model", llm_cfg.api_key if llm_cfg else "", ("env" if llm_cfg and llm_cfg.id is None else "app") if llm_cfg else None),
        ("tiktok", "TikTok Content Posting API", tt_key and credentials.get("tiktok.client_secret") and tt_key, credentials.source("tiktok.client_key")),
        ("storage", f"Storage · {s.storage_backend}", s.s3_bucket if s.storage_backend == "s3" else os.path.abspath(s.storage_local_path), "env"),
        ("ytdlp", "Downloader · yt-dlp" + (f" {_ytdlp_version()}" if _ytdlp_version() else ""), _ytdlp_version() and "Installed with the backend (Python package)", "env"),
        ("ffmpeg", "Editor · FFmpeg", shutil.which(media.ffmpeg_exe()) or (media.ffmpeg_exe() if os.path.isfile(media.ffmpeg_exe()) else ""), "env"),
    ]
    out = []
    for key, name, value, origin in rows:
        item = {"key": key, "name": name, "configured": bool(value), "source": origin if value else None}
        if user.is_owner:
            item["masked"] = (value or "Not installed") if key in ("storage", "ffmpeg", "ytdlp") else _mask(value or "")
        else:
            item["masked"] = "Configured" if value else "Needs setup"
        out.append(item)
    return out


@router.post("/integrations/{key}/test")
def test_integration(key: str, db: DB, _: OwnerUser):
    try:
        if key == "llm":
            reply = llm.complete("Reply with the single word OK.", max_tokens=5)
            message = f"{llm.resolve().model} replied: {reply[:20]}"
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
        elif key == "ffmpeg":
            message = _test_editor()
        elif key == "ytdlp":
            meta = youtube._video_from_ytdlp("jNQXAC9IVRw")  # the first video ever uploaded to YouTube
            message = f"yt-dlp {_ytdlp_version()} read a YouTube video: “{meta.title}” ({meta.duration_seconds:.0f}s)"
        else:
            raise HTTPException(404, "Unknown integration")
    except (ApiError, OSError, subprocess.SubprocessError, RuntimeError, media.ProbeError) as exc:
        return {"ok": False, "message": str(exc)[:300]}
    except Exception as exc:  # e.g. boto errors
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:250]}"}
    return {"ok": True, "message": message}
