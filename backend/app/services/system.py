"""The main switch: one switch, kept by the admin, that stops the whole tool for every member.

Off: no channel is checked, push notifications are ignored, nothing is downloaded, edited, captioned or handed to
Buffer, and Buffer is not asked about posts. Videos that were on their way are paused where they were.
On again: those videos carry on from where they stopped, and channels are watched from that moment, so uploads
made while the switch was off are left alone. Posts already scheduled at Buffer stay there: Buffer publishes them.
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Channel, Job, JobStatus, User, utcnow
from app.services import activity, pipeline, workspace_settings

KEY = "system"
OFF_REASON = "Paused because the admin switched the system off"


def state(db: Session) -> dict:
    value = workspace_settings.get(db, KEY)
    return {"on": value.get("on", True) is not False, "changed_at": value.get("changed_at"), "changed_by": value.get("changed_by")}


def is_on(db: Session) -> bool:
    return state(db)["on"]


def switch(db: Session, on: bool, user: User) -> dict:
    """Turn the system on or off. Nothing happens when it is already that way."""
    current = workspace_settings.get(db, KEY)
    if (current.get("on", True) is not False) == on:
        return state(db)
    now = utcnow()
    paused_ids: list[int] = []
    if not on:
        # Every video on its way is held where it is; a download or an edit that runs stops within seconds.
        for job in db.scalars(select(Job).where(Job.status.in_(JobStatus.PAUSABLE))).unique():
            if job.video.is_podcast_source:
                continue  # a podcast being split finishes that step; its clips are not started while the system is off
            pipeline.pause_job(db, job, reason=OFF_REASON)
            paused_ids.append(job.id)
    else:
        # Uploads made while the switch was off are left alone: every channel is watched from now on.
        db.execute(update(Channel).values(monitoring_since=now).execution_options(synchronize_session=False))
        for job_id in current.get("paused_jobs") or []:
            job = db.get(Job, job_id)
            if job and job.status == JobStatus.PAUSED:  # one resumed or cancelled by hand meanwhile is left as it is
                try:
                    pipeline.resume_job(db, job, reason="Resumed because the admin switched the system on")
                except ValueError:
                    continue
    value = {"on": on, "changed_at": now.isoformat(), "changed_by": user.email, "paused_jobs": paused_ids}
    workspace_settings.update(db, KEY, value)
    activity.record(db, "System", f"{user.email} switched the system {'on' if on else 'off'}" + (f" · {len(paused_ids)} video(s) paused" if paused_ids else ""),
                    level="info" if on else "warning", event="system_on" if on else "system_off", user_id=user.id)
    return state(db)
