"""Talking to the member's ClipRelay server."""

import os

import httpx

from cliprelay_helper import VERSION
from cliprelay_helper.store import Settings, platform_name


class NotConnected(Exception):
    """The server no longer knows this PC (disconnected on the website): it must be connected again."""


class ServerError(Exception):
    pass


def clean_address(text: str) -> str:
    text = (text or "").strip().rstrip("/")
    if text and "://" not in text:
        text = "https://" + text
    return text


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail") or response.text)[:300]
    except ValueError:
        return response.text[:300] or f"HTTP {response.status_code}"


class Client:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _http(self, timeout: float = 30) -> httpx.Client:
        headers = {"User-Agent": f"ClipRelayHelper/{VERSION}"}
        token = self.settings.get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.Client(base_url=self.settings.get("server"), headers=headers, timeout=timeout, follow_redirects=True)

    def _call(self, method: str, path: str, timeout: float = 30, **kwargs) -> dict:
        try:
            with self._http(timeout) as http:
                response = http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ServerError(f"ClipRelay could not be reached: {exc}") from exc
        if response.status_code == 401:
            raise NotConnected(_detail(response))
        if response.status_code >= 400:
            raise ServerError(_detail(response))
        return response.json() if response.content else {}

    @staticmethod
    def connect(server: str, code: str, name: str) -> dict:
        """Exchange the code from the website for this PC's own key."""
        try:
            response = httpx.post(f"{server}/api/helper/connect", json={"code": code, "name": name, "platform": platform_name(), "version": VERSION}, timeout=30)
        except httpx.HTTPError as exc:
            raise ServerError(f"ClipRelay could not be reached at {server}: {exc}") from exc
        if response.status_code >= 400:
            raise ServerError(_detail(response))
        return response.json()

    def beat(self, paused: bool) -> dict:
        return self._call("POST", "/api/helper/beat", json={"version": VERSION, "paused": paused})

    def next_job(self) -> dict | None:
        return self._call("POST", "/api/helper/next").get("job")

    def progress(self, job_id: int, stage: str, percent: float | None) -> bool:
        """Reports how far it is; True means stop (the video was paused, stopped or moved on)."""
        return bool(self._call("POST", f"/api/helper/jobs/{job_id}/progress", json={"stage": stage, "percent": percent}).get("stop"))

    def fetch(self, path: str, dest: str) -> None:
        with self._http(120) as http, http.stream("GET", path) as response:
            if response.status_code == 409:
                raise ServerError("This video is no longer this PC's to edit")
            if response.status_code >= 400:
                raise ServerError(f"A file of this video could not be fetched (HTTP {response.status_code})")
            with open(dest + ".part", "wb") as fh:
                for chunk in response.iter_bytes(1024 * 1024):
                    fh.write(chunk)
        os.replace(dest + ".part", dest)

    def send_result(self, job_id: int, path: str) -> dict:
        with open(path, "rb") as fh:
            return self._call("POST", f"/api/helper/jobs/{job_id}/result", timeout=httpx.Timeout(60, write=1800), files={"file": ("video.mp4", fh, "video/mp4")})

    def failed(self, job_id: int, stage: str, message: str) -> None:
        self._call("POST", f"/api/helper/jobs/{job_id}/failed", json={"stage": stage, "message": message[:1900]})

    def disconnect(self) -> None:
        try:
            self._call("POST", "/api/helper/disconnect")
        except (ServerError, NotConnected):
            pass
