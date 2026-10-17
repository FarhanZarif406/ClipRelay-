"""Start the ClipRelay Helper: the worker, the window on this computer, and the tray icon.

  ClipRelay Helper            opens the window too (first run: to connect with the code from the website)
  ClipRelay Helper --background   as started with the computer: only the icon
"""

import logging
import os
import subprocess
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler

from cliprelay_helper import tray
from cliprelay_helper.store import Settings, data_dir
from cliprelay_helper.system import be_gentle, install_windows
from cliprelay_helper.window import Window, running_link
from cliprelay_helper.worker import Worker


def _logging() -> None:
    handler = RotatingFileHandler(os.path.join(data_dir(), "helper.log"), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    background = "--background" in sys.argv
    installed = install_windows()
    if installed:  # first run of the download: carry on from the installed copy
        subprocess.Popen([installed], close_fds=True)
        return
    _logging()
    settings = Settings()
    worker = Worker(settings)
    window = Window(settings, worker)
    if not window.start():  # it already runs: show its window instead of starting a second one
        link = running_link()
        if link and not background:
            webbrowser.open(link)
        return
    be_gentle()
    worker.start()
    if not background or not settings.connected:
        threading.Timer(1.0, lambda: webbrowser.open(window.link)).start()
    done = threading.Event()

    def quit_all():
        worker.shutdown()
        window.stop()
        done.set()

    if not tray.run(settings, worker, window, quit_all):
        try:  # no tray on this computer: the window alone, until the program is closed
            done.wait()
        except KeyboardInterrupt:
            quit_all()


if __name__ == "__main__":
    main()
