"""The few settings the shared editing code (`app/services/media.py`, the backend's own file) reads, for the PC Helper."""

import os
from functools import lru_cache
from types import SimpleNamespace


@lru_cache
def get_settings() -> SimpleNamespace:
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()  # bundled with the helper: nothing to install
    except Exception:  # noqa: BLE001
        ffmpeg = "ffmpeg"
    return SimpleNamespace(
        ffmpeg_path=ffmpeg,
        font_file="",  # ClipRelay sends the font with every video that has hook text
        render_threads=max(1, (os.cpu_count() or 2) // 2),  # half the computer, so it stays usable meanwhile
    )
