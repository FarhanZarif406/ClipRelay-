import csv
import io
from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.deps import DB, CurrentUser, Workspace
from app.models import Mode
from app.services import stats

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary")
def summary(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    return stats.summary(db, mode, user.id)


@router.get("/dashboard/performance")
def performance(db: DB, user: CurrentUser, days: int = Query(7, ge=1, le=90), mode: Workspace = Mode.SHORTS):
    return stats.performance(db, days, mode, user.id)


@router.get("/dashboard/nav")
def nav(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    return stats.nav(db, mode, user.id)


@router.get("/pipeline/status")
def pipeline_status(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    """Live Status: what is waiting, downloading, being edited and waiting to upload right now."""
    return stats.pipeline_status(db, mode, user.id)


@router.get("/reports/daily")
def daily(db: DB, user: CurrentUser, day: date | None = None, mode: Workspace = Mode.SHORTS):
    return stats.daily_report(db, day, mode, user.id)


@router.get("/reports/daily.csv")
def daily_csv(db: DB, user: CurrentUser, day: date | None = None, mode: Workspace = Mode.SHORTS):
    report = stats.daily_report(db, day, mode, user.id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "account", "status", "uploaded_today", "share_pct", "failed_today", "total_uploaded"])
    for row in report["accounts"]:
        share = round(row["posts_today"] / report["uploaded"] * 100) if report["uploaded"] else 0
        writer.writerow([report["date"], f"@{row['username']}", row["status"], row["posts_today"], share, row["failed_today"], row["lifetime_posts"]])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="cliprelay-report-{report["date"]}.csv"'},
    )
