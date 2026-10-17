"""The few settings the shared editing code (`app/services/media.py`, copied from the backend) reads."""

import os
from functools import lru_cache
from types import SimpleNamespace


@lru_cache
def get_settings() -> SimpleNamespace:
    return SimpleNamespace(
        ffmpeg_path=os.environ.get("FFMPEG_PATH", "ffmpeg"),
        font_file=os.environ.get("FONT_FILE", ""),
        render_threads=int(os.environ.get("RENDER_THREADS", "2")),
    )
