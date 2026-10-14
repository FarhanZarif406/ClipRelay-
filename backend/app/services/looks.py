"""Editing looks: everything that decides how a clip looks and sounds, as one nested value.

A member has one default look per workspace and any number of named presets; a channel can use a preset.
Sections: frame (shape, crop, zoom, flip), speed, encoding (quality and audio), music, hook text, watermark.
"""

import copy
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, EditingLook, Mode, RuleSetting, Video, utcnow

ASPECTS = ("9:16", "4:5", "3:4", "2:3", "1:1", "4:3", "3:2", "16:9", "21:9")
POSITIONS = ("left", "centre", "right")
RESOLUTIONS = ("1080x1920", "720x1280")
FRAME_RATES = (24, 25, 30, 60)
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
AUDIO_BITRATES = (96, 128, 192)
WATERMARK_PLACES = ("tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br")
HOOK_SOURCES = ("ai", "title")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
FONT_RE = re.compile(r"^(default|custom:\d+)$")
NAME_RE = re.compile(r"^[^\r\n]{1,60}$")

DEFAULT_LOOK = {
    "frame": {"aspect": "9:16", "position": "centre", "zoom": 1.0, "flip": True},
    "speed": {"speed": 1.08, "keep_pitch": True},
    "encoding": {"resolution": "1080x1920", "fps": 30, "preset": "medium", "crf": 23, "loudnorm": True, "audio_bitrate": 128, "keep_audio": True},
    "music": {"enabled": False, "volume": 0.25},
    "hook": {
        "enabled": False, "source": "ai", "duration": 3.0, "font": "default", "font_size": 48,
        "color": "#ffffff", "stroke_color": "#000000", "stroke_width": 4, "x": 50, "y": 15,
        "box": {"enabled": False, "color": "#000000", "opacity": 0.6, "width": 86, "height": 12, "radius": 30, "x": 50, "y": 15},
    },
    "watermark": {"enabled": False, "position": "br", "opacity": 0.8, "size": 16},
}
# Podcast clips are not sped up or mirrored unless the member asks for it.
PODCAST_CHANGES = {"speed": {"speed": 1.0}, "frame": {"flip": False}}


class LookError(ValueError):
    pass


def _merge(base, patch):
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return copy.deepcopy(base if patch is None else patch)
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if key in base:
            out[key] = _merge(base[key], value)
    return out


def default_look(mode: str = Mode.SHORTS) -> dict:
    return _merge(DEFAULT_LOOK, PODCAST_CHANGES) if mode == Mode.PODCASTS else copy.deepcopy(DEFAULT_LOOK)


def complete(look, mode: str = Mode.SHORTS) -> dict:
    """A stored look with anything missing filled from the defaults, so older looks keep working."""
    return _merge(default_look(mode), look if isinstance(look, dict) else {})


def _number(value, low, high, label, *, whole=False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise LookError(f"{label} must be a number.")
    if not low <= value <= high:
        raise LookError(f"{label} must be between {low:g} and {high:g}.")
    if whole and int(value) != value:
        raise LookError(f"{label} must be a whole number.")
    return int(value) if whole else float(value)


def _choice(value, options, label):
    if value not in options:
        raise LookError(f"{label} must be one of: {', '.join(map(str, options))}.")
    return value


def _flag(value, label) -> bool:
    if not isinstance(value, bool):
        raise LookError(f"{label} must be on or off.")
    return value


def _color(value, label) -> str:
    if not isinstance(value, str) or not COLOR_RE.match(value):
        raise LookError(f"{label} must be a colour like #ffffff.")
    return value.lower()


def validate(look, mode: str = Mode.SHORTS) -> dict:
    """Check every setting of a look; returns the completed, tidied look or raises LookError."""
    if not isinstance(look, dict):
        raise LookError("The editing rules are missing.")
    v = complete(look, mode)
    f, s, e, m, h, w = v["frame"], v["speed"], v["encoding"], v["music"], v["hook"], v["watermark"]
    f["aspect"] = _choice(f["aspect"], ASPECTS, "Aspect ratio")
    f["position"] = _choice(f["position"], POSITIONS, "Crop position")
    f["zoom"] = round(_number(f["zoom"], 1.0, 1.3, "Zoom"), 2)
    f["flip"] = _flag(f["flip"], "Horizontal flip")
    s["speed"] = round(_number(s["speed"], 1.0, 1.5, "Playback speed"), 2)
    s["keep_pitch"] = _flag(s["keep_pitch"], "Match audio pitch")
    e["resolution"] = _choice(e["resolution"], RESOLUTIONS, "Resolution")
    e["fps"] = _choice(e["fps"], FRAME_RATES, "Frame rate")
    e["preset"] = _choice(e["preset"], PRESETS, "Encoder preset")
    e["crf"] = _number(e["crf"], 18, 28, "Quality (CRF)", whole=True)
    e["loudnorm"] = _flag(e["loudnorm"], "Normalise loudness")
    e["audio_bitrate"] = _choice(e["audio_bitrate"], AUDIO_BITRATES, "Audio bitrate")
    e["keep_audio"] = _flag(e["keep_audio"], "Keep the original sound")
    m["enabled"] = _flag(m["enabled"], "Background music")
    m["volume"] = round(_number(m["volume"], 0.02, 1.0, "Music volume"), 2)
    h["enabled"] = _flag(h["enabled"], "Hook text")
    h["source"] = _choice(h["source"], HOOK_SOURCES, "Hook words")
    h["duration"] = _number(h["duration"], 1, 10, "Hook duration")
    if not isinstance(h["font"], str) or not FONT_RE.match(h["font"]):
        raise LookError("Choose a font from the list.")
    h["font_size"] = _number(h["font_size"], 16, 160, "Font size", whole=True)
    h["color"] = _color(h["color"], "Text colour")
    h["stroke_color"] = _color(h["stroke_color"], "Outline colour")
    h["stroke_width"] = _number(h["stroke_width"], 0, 12, "Outline width", whole=True)
    h["x"] = _number(h["x"], 0, 100, "Text position (left to right)")
    h["y"] = _number(h["y"], 0, 100, "Text position (top to bottom)")
    b = h["box"]
    b["enabled"] = _flag(b["enabled"], "Background behind the text")
    b["color"] = _color(b["color"], "Background colour")
    b["opacity"] = round(_number(b["opacity"], 0, 1, "Background opacity"), 2)
    b["width"] = _number(b["width"], 10, 100, "Background width")
    b["height"] = _number(b["height"], 3, 60, "Background height")
    b["radius"] = _number(b["radius"], 0, 100, "Background roundness")
    b["x"] = _number(b["x"], 0, 100, "Background position (left to right)")
    b["y"] = _number(b["y"], 0, 100, "Background position (top to bottom)")
    w["enabled"] = _flag(w["enabled"], "Watermark")
    w["position"] = _choice(w["position"], WATERMARK_PLACES, "Watermark position")
    w["opacity"] = round(_number(w["opacity"], 0.1, 1, "Watermark opacity"), 2)
    w["size"] = _number(w["size"], 5, 40, "Watermark size", whole=True)
    return v


def check_name(db: Session, user_id: int, mode: str, name, *, preset_id: int | None = None) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name.strip()):
        raise LookError("Give the preset a name of up to 60 characters.")
    name = name.strip()
    if name.lower() == "default":
        raise LookError("“Default” is the name of the built-in rules. Choose another name.")
    taken = db.scalar(select(EditingLook).where(EditingLook.user_id == user_id, EditingLook.mode == mode, EditingLook.name.is_not(None), EditingLook.name.ilike(name)))
    if taken and taken.id != preset_id:
        raise LookError("You already have a preset with that name.")
    return name


# ---------------------------------------------------------------- stored looks

def _from_old_rules(db: Session, user_id: int, mode: str) -> dict:
    """A member's first default look carries over the speed, flip and audio they had set as rules before."""
    look = default_look(mode)
    prefix = "podcast." if mode == Mode.PODCASTS else ""
    rows = {r.key: r.value for r in db.scalars(select(RuleSetting).where(RuleSetting.user_id == user_id, RuleSetting.channel_id.is_(None), RuleSetting.key.in_([f"{prefix}speed", f"{prefix}horizontal_flip", f"{prefix}keep_audio"])))}
    if isinstance(rows.get(f"{prefix}speed"), (int, float)) and 1.0 <= rows[f"{prefix}speed"] <= 1.5:
        look["speed"]["speed"] = round(float(rows[f"{prefix}speed"]), 2)
    if isinstance(rows.get(f"{prefix}horizontal_flip"), bool):
        look["frame"]["flip"] = rows[f"{prefix}horizontal_flip"]
    if isinstance(rows.get(f"{prefix}keep_audio"), bool):
        look["encoding"]["keep_audio"] = rows[f"{prefix}keep_audio"]
    return look


def default_row(db: Session, user_id: int, mode: str) -> EditingLook:
    row = db.scalar(select(EditingLook).where(EditingLook.user_id == user_id, EditingLook.mode == mode, EditingLook.name.is_(None)))
    if row is None:
        row = EditingLook(user_id=user_id, mode=mode, name=None, look=_from_old_rules(db, user_id, mode))
        db.add(row)
        db.flush()
    return row


def presets(db: Session, user_id: int, mode: str) -> list[EditingLook]:
    rows = db.scalars(select(EditingLook).where(EditingLook.user_id == user_id, EditingLook.mode == mode, EditingLook.name.is_not(None)))
    return sorted(rows, key=lambda r: r.name.lower())


def for_video(db: Session, video: Video) -> dict:
    """The look a video is edited with: its channel's preset, or the member's default for the workspace."""
    channel = db.get(Channel, video.channel_id) if video.channel_id else (video.parent.channel if video.parent else None)
    if channel and channel.preset_id:
        preset = db.get(EditingLook, channel.preset_id)
        if preset and preset.user_id == video.user_id and preset.mode == video.mode:
            return complete(preset.look, video.mode)
    if video.user_id is None:
        return default_look(video.mode)
    return complete(default_row(db, video.user_id, video.mode).look, video.mode)


def save(row: EditingLook, look: dict) -> None:
    row.look = look
    row.updated_at = utcnow()


def summary(look: dict) -> str:
    f, s, e = look["frame"], look["speed"], look["encoding"]
    parts = [f["aspect"], f"crop {f['position']}"]
    if f["zoom"] > 1:
        parts.append(f"zoom {round(f['zoom'] * 100)}%")
    parts.append(f"{s['speed']:g}x")
    if f["flip"]:
        parts.append("flipped")
    parts.append(f"{e['resolution'].split('x')[0]}p {e['fps']}fps CRF {e['crf']}")
    if not e["keep_audio"]:
        parts.append("no original sound")
    if look["music"]["enabled"]:
        parts.append(f"music {round(look['music']['volume'] * 100)}%")
    if look["hook"]["enabled"]:
        parts.append("hook text")
    if look["watermark"]["enabled"]:
        parts.append("watermark")
    return " · ".join(parts)
