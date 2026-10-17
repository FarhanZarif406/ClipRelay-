"""The editing code: the backend's own app/services/media.py, so a PC edits exactly like the server.

A built helper has the file inside it (build.py copies it in). Run from the source folder, it is read straight
from the backend next door.
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.dirname(HERE)  # helper/: holds the small `app` package (app/config.py) the editing code imports
if SHIM not in sys.path:
    sys.path.insert(0, SHIM)


def _load():
    try:
        from app.services import media  # noqa: PLC0415

        return media
    except ImportError:
        pass
    backend = os.path.abspath(os.path.join(SHIM, "..", "backend", "app", "services", "media.py"))
    if not os.path.isfile(backend):
        raise ImportError("The editing code is missing: build the helper with helper/build.py")
    import app.services  # noqa: F401, PLC0415

    spec = importlib.util.spec_from_file_location("app.services.media", backend)
    module = importlib.util.module_from_spec(spec)
    sys.modules["app.services.media"] = module
    spec.loader.exec_module(module)
    return module


media = _load()
