"""The icon next to the clock: its colour says what the helper is doing; its menu opens the window, pauses or quits."""

from cliprelay_helper.logo import mark

LABELS = {
    "idle": "Ready: waiting for the next video", "downloading": "Downloading", "editing": "Editing", "sending": "Sending the video",
    "paused": "Paused", "offline": "ClipRelay cannot be reached", "not_connected": "Not connected: open the window", "starting": "Starting…",
}


def mood(state: dict, connected: bool, paused: bool) -> str:
    if not connected:
        return "bad"
    if paused or state.get("stage") == "offline":
        return "warn"
    return "work" if state.get("stage") in ("downloading", "editing", "sending") else "ok"


def picture(colour: str):
    """The ClipRelay mark with a small dot saying how the helper is: green ready, white working, amber paused, red not connected."""
    return mark(64, colour)


def run(settings, worker, window, on_quit) -> bool:
    """Show the icon and block until Quit. False when this computer has no tray (the window is used alone)."""
    try:
        import pystray
    except Exception:  # noqa: BLE001
        return False

    def status_text(_item=None) -> str:
        state = worker.snapshot()
        text = LABELS.get("paused" if settings.get("paused") else state.get("stage"), state.get("stage", ""))
        if state.get("percent") is not None and state.get("stage") in ("downloading", "editing"):
            text += f" · {state['percent']}%"
        return text

    def toggle_pause(icon, _item):
        settings.update(paused=not settings.get("paused"))
        worker.wake.set()
        refresh()

    def quit_app(icon, _item):
        icon.stop()
        on_quit()

    def open_site(_icon, _item):
        import webbrowser

        if settings.get("server"):
            webbrowser.open(settings.get("server"))

    def open_window(_icon=None, _item=None):
        import webbrowser

        webbrowser.open(window.link)

    menu = pystray.Menu(
        pystray.MenuItem(status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open helper window", open_window, default=True),
        pystray.MenuItem("Open ClipRelay website", open_site, enabled=lambda _i: bool(settings.get("server"))),
        pystray.MenuItem(lambda _i: "Resume" if settings.get("paused") else "Pause", toggle_pause, enabled=lambda _i: settings.connected),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("cliprelay-helper", picture("ok"), "ClipRelay Helper", menu)
    last = {"mood": None}

    def refresh():
        current = mood(worker.snapshot(), settings.connected, bool(settings.get("paused")))
        if current != last["mood"]:
            last["mood"] = current
            icon.icon = picture(current)
        icon.title = f"ClipRelay Helper · {status_text()}"
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    worker.listeners.append(refresh)
    icon.run(setup=lambda i: (setattr(i, "visible", True), refresh()))
    return True
