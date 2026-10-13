"""Podcasts workspace: choose the best moments of a long video and turn each into a clip.

A podcast is never downloaded whole. Its transcript is read first, an AI model picks the moments, and
only those sections are downloaded. Each clip then becomes a video of its own with its own job, so from
there on (edit, caption, review, publish) it travels the same pipeline as a short.
"""

import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.integrations import llm, youtube
from app.integrations.http import ApiError
from app.models import CaptionStatus, Job, JobStatus, Video, VideoStatus
from app.services import activity, pipeline, rules
from app.services.activity import job_event

log = logging.getLogger(__name__)

LINE_SECONDS = 20  # the transcript is given to the model in lines of about this length
MAX_TRANSCRIPT_CHARS = 90_000
SYSTEM = "You are a video editor who finds the most engaging self-contained moments in podcast transcripts. You answer with JSON only."


@dataclass
class Moment:
    start: float
    end: float
    title: str
    text: str = ""  # what is said in the clip, used to write its caption


def clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60:02d}:{seconds % 60:02d}"


def transcript_lines(segments: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Merge caption fragments into lines of about LINE_SECONDS, each starting at a real caption start."""
    lines: list[tuple[float, str]] = []
    start, parts = None, []
    for at, text in segments:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if start is None:
            start = at
        if at - start >= LINE_SECONDS and parts:
            lines.append((start, " ".join(parts)))
            start, parts = at, []
        parts.append(text)
    if parts and start is not None:
        lines.append((start, " ".join(parts)))
    return lines


def text_between(segments: list[tuple[float, str]], start: float, end: float) -> str:
    return re.sub(r"\s+", " ", " ".join(text for at, text in segments if start - 1 <= at < end)).strip()[:1500]


def even_moments(title: str, duration: float, count: int, length: float) -> list[Moment]:
    """The fallback when there is no transcript or no working AI model: clips spread evenly across the video."""
    length = min(length, max(5.0, duration / (count + 1)))
    out = []
    for i in range(count):
        centre = duration * (i + 1) / (count + 1)
        start = max(0.0, min(duration - length, centre - length / 2))
        out.append(Moment(round(start, 1), round(start + length, 1), f"{title} (part {i + 1})"[:150]))
    return out


def _valid(raw: list, duration: float, count: int, shortest: float, longest: float) -> list[Moment]:
    """Keep what the model returned only where it makes sense: inside the video, the right length, not overlapping."""
    out: list[Moment] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        start = max(0.0, min(start, duration - shortest))
        end = min(duration, max(end, start + shortest))
        end = min(end, start + longest)
        if end - start < shortest - 0.5 or any(start < m.end and m.start < end for m in out):
            continue
        out.append(Moment(round(start, 1), round(end, 1), str(item.get("title") or "").strip()[:150]))
        if len(out) == count:
            break
    return sorted(out, key=lambda m: m.start)


def pick_moments(title: str, duration: float, segments: list[tuple[float, str]], *, count: int, shortest: float, longest: float) -> tuple[list[Moment], str]:
    """Return (moments, how they were chosen): "ai", or the reason the even fallback was used."""
    fallback = even_moments(title, duration, count, longest)
    lines = transcript_lines(segments)
    if not lines:
        return fallback, "this video has no subtitles to read"
    script = "\n".join(f"[{int(at)}] {text}" for at, text in lines)
    if len(script) > MAX_TRANSCRIPT_CHARS:  # a very long podcast: shorten every line rather than drop the ending
        width = max(40, MAX_TRANSCRIPT_CHARS // len(lines) - 8)
        script = "\n".join(f"[{int(at)}] {text[:width]}" for at, text in lines)
    prompt = (
        f"Podcast title: {title}\nLength: {int(duration)} seconds.\n\n"
        f"Below is the transcript. The number in brackets is the time in seconds at which that line starts.\n\n{script}\n\n"
        f"Choose the {count} most engaging moments for short vertical clips. Each moment must:\n"
        f"- be between {int(shortest)} and {int(longest)} seconds long,\n"
        "- start at the beginning of a thought and end when it is complete, so it makes sense without the rest,\n"
        "- not overlap another moment.\n\n"
        'Respond with JSON only: [{"start": <seconds>, "end": <seconds>, "title": "<short hook for the clip, in the language of the podcast>"}]'
    )
    try:
        raw = llm.complete(prompt, system=SYSTEM, max_tokens=900)
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            raise ValueError(f"the model did not return a list: {raw[:100]}")
        moments = _valid(json.loads(match.group(0)), duration, count, shortest, longest)
    except (ApiError, RuntimeError, ValueError) as exc:
        return fallback, f"the AI model failed ({str(exc)[:160]})"
    if not moments:
        return fallback, "the AI model returned no usable moments"
    if len(moments) < count:  # top up with evenly spread clips that do not collide with the chosen ones
        for extra in fallback:
            if len(moments) == count:
                break
            if not any(extra.start < m.end and m.start < extra.end for m in moments):
                moments.append(extra)
        moments.sort(key=lambda m: m.start)
    for moment in moments:
        moment.title = moment.title or title[:150]
        moment.text = text_between(segments, moment.start, moment.end)
    return moments, "ai"


def split(db: Session, job: Job) -> str:
    """Analyse one podcast and create a clip (a video with its own job) for every chosen moment."""
    video = job.video
    values = rules.for_video(db, video)
    count, shortest, longest = int(values["clips_per_video"]), float(values["clip_min_seconds"]), float(values["clip_max_seconds"])
    job.next_check_at = pipeline.utcnow() + pipeline.PROCESS_LEASE
    if job.status != JobStatus.DOWNLOADING:
        job_event(db, job, JobStatus.DOWNLOADING, "Reading the podcast's transcript")
    db.commit()
    try:
        segments = youtube.transcript(video.youtube_video_id)
    except ApiError as exc:
        return pipeline._stage_failed(db, job, "Transcript", str(exc))
    moments, how = pick_moments(video.original_title, float(video.duration_sec or 0), segments, count=count, shortest=shortest, longest=longest)
    if how != "ai":
        activity.record(db, "Podcasts", f"Podcast #{video.id}: clips were spread evenly because {how}", level="warning", event="clips_fallback", job_id=job.id)

    for index, moment in enumerate(moments, start=1):
        clip = Video(
            channel_id=video.channel_id, mode=video.mode, user_id=video.user_id, parent_id=video.id, status=VideoStatus.ACCEPTED,
            permalink=f"{youtube.watch_url(video.youtube_video_id)}&t={int(moment.start)}s", thumbnail_url=video.thumbnail_url, posted_at=video.posted_at,
            original_title=moment.title or f"{video.original_title} (part {index})", original_caption=moment.text or video.original_title,
            original_tags=video.original_tags or [], duration_sec=round(moment.end - moment.start, 1),
            clip_start=moment.start, clip_end=moment.end, forced=video.forced,
        )
        db.add(clip)
        db.flush()
        clip.channel, clip.parent = video.channel, video
        clip_job = pipeline.create_job(db, clip, pipeline.pick_account(db, clip))
        clip_job.next_check_at = None  # picked up by the next scheduler tick
    job.next_check_at = None
    job.attempts = 0
    job.error = None
    job.caption_status = CaptionStatus.DONE
    chosen = "chosen by AI" if how == "ai" else "spread evenly"
    job_event(db, job, JobStatus.CLIPPED, f"{len(moments)} clips {chosen}: " + ", ".join(f"{clock(m.start)}–{clock(m.end)}" for m in moments))
    activity.record(db, "Podcasts", f"Podcast #{video.id} “{video.original_title[:50]}”: {len(moments)} clips {chosen}", event="podcast_clipped", job_id=job.id)
    return job.status
