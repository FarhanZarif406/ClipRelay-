import csv
import io

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser
from app.models import ActivityLog
from app.services import serializers

router = APIRouter(tags=["logs"])


def _query(user, q: str | None, level: str | None, service: str | None):
    stmt = select(ActivityLog)
    if not user.is_owner:
        stmt = stmt.where(ActivityLog.user_id == user.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(ActivityLog.message.ilike(like), ActivityLog.request_id.ilike(like), ActivityLog.event.ilike(like)))
    if level:
        stmt = stmt.where(ActivityLog.level == level)
    if service:
        stmt = stmt.where(ActivityLog.service == service)
    return stmt


@router.get("/logs")
def list_logs(
    db: DB,
    user: CurrentUser,
    q: str | None = None,
    level: str | None = None,
    service: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    limit: int | None = Query(None, ge=1, le=500),
):
    stmt = _query(user, q, level, service)
    if limit:
        page, page_size = 1, limit
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ActivityLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    services = db.scalars(select(ActivityLog.service).where(True if user.is_owner else ActivityLog.user_id == user.id).distinct().order_by(ActivityLog.service)).all()
    return {"items": [serializers.log(r) for r in rows], "total": total, "services": services}


@router.get("/logs.csv")
def export_logs(db: DB, user: CurrentUser, q: str | None = None, level: str | None = None, service: str | None = None):
    rows = db.scalars(_query(user, q, level, service).order_by(ActivityLog.id.desc()).limit(50000)).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "level", "service", "event", "message", "request_id", "job_id"])
    for r in rows:
        writer.writerow([r.created_at.isoformat(), r.level, r.service, r.event, r.message, r.request_id, r.job_id or ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="cliprelay-logs.csv"'})
