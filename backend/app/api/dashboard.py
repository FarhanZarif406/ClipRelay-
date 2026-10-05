import csv
import io
from datetime import date, datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.deps import DB, CurrentUser
from app.services import stats

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary")
def summary(db: DB, _: CurrentUser):
    return stats.summary(db)


@router.get("/dashboard/performance")
def performance(db: DB, _: CurrentUser, days: int = Query(7, ge=1, le=90)):
    return stats.performance(db, days)


@router.get("/dashboard/nav")
def nav(db: DB, _: CurrentUser):
    return stats.nav(db)


def _day(value: date | None) -> datetime:
    value = value or datetime.now(timezone.utc).date()
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


@router.get("/reports/daily")
def daily(db: DB, _: CurrentUser, day: date | None = None):
    return stats.daily_report(db, _day(day))


@router.get("/reports/daily.csv")
def daily_csv(db: DB, _: CurrentUser, day: date | None = None):
    report = stats.daily_report(db, _day(day))
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
