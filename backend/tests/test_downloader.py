import os
import time

import pytest
import yt_dlp

from app.services import downloader, sources

COOKIES = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t{exp}\tSID\tabc\n#HttpOnly_.google.com\tTRUE\t/\tTRUE\t0\tHSID\tdef\n.example.com\tTRUE\t/\tFALSE\t1\tx\ty\n"


@pytest.fixture(autouse=True)
def clean():
    downloader.reset_state()
    downloader.remove_cookies()
    yield
    downloader.remove_cookies()


def test_strategies_put_saved_settings_first_then_the_fallbacks():
    plain = downloader.strategies(with_cookies=False)
    assert plain[0] == {"cookies": False, "player_client": "", "ipv6": False} and len(plain) == len({str(s) for s in plain})  # no way is tried twice
    assert [downloader.strategy_label(s) for s in plain[:4]] == ["default client, without cookies", "web_embedded client, without cookies", "default client, without cookies, over IPv6", "web_embedded client, without cookies, over IPv6"]
    assert not any(s["cookies"] for s in plain) and plain[-1]["player_client"] == "mweb"  # low-quality clients last
    with_file = downloader.strategies(with_cookies=True, client="web_safari")
    assert with_file[0] == {"cookies": True, "player_client": "web_safari", "ipv6": False} and with_file[1] == {"cookies": False, "player_client": "", "ipv6": False}
    # The way that last worked moves to the front — unless it needs a cookies file that is gone.
    remembered = {"cookies": False, "player_client": "android_vr", "ipv6": False}
    assert downloader.strategies(with_cookies=False, remembered=remembered)[0] == remembered
    assert downloader.strategies(with_cookies=False, remembered={"cookies": True, "player_client": "", "ipv6": False})[0]["cookies"] is False


def test_a_refused_download_tries_the_other_ways_and_remembers_the_one_that_works(db):
    tried = []

    def attempt(access):
        tried.append(access)
        if len(tried) < 3:
            raise yt_dlp.utils.DownloadError("ERROR: Sign in to confirm you’re not a bot")
        return "file"

    assert downloader.try_each(attempt) == "file" and len(tried) == 3
    assert tried[2].get("source_address") == "::" and "source_address" not in tried[0]  # the third way is over IPv6
    assert downloader.working_route() == "default client, without cookies, over IPv6"
    tried.clear()
    assert downloader.try_each(lambda access: tried.append(access) or "again") == "again"
    assert len(tried) == 1 and tried[0].get("source_address") == "::"  # straight to the way that worked


def test_when_every_way_fails_the_error_says_so_and_then_only_one_way_is_tried_for_a_while(db):
    calls = []

    def refuse(access):
        calls.append(1)
        raise yt_dlp.utils.DownloadError("ERROR: Sign in to confirm you’re not a bot")

    with pytest.raises(downloader.DownloaderError) as failure:
        downloader.try_each(refuse)
    assert "Tried 7 ways of reaching YouTube; none worked." in str(failure.value) and "Attempt 7" in failure.value.detail and len(calls) == 7
    calls.clear()
    with pytest.raises(downloader.DownloaderError) as failure:
        downloader.try_each(refuse)
    assert len(calls) == 1 and "Tried" not in str(failure.value)  # a blocked server does not spend minutes on every video

    class Stop(Exception):
        pass

    def stopped(access):
        raise Stop()

    downloader.reset_state()
    with pytest.raises(Stop):  # the operator's Stop is not a refusal: no other way is tried
        downloader.try_each(stopped)


def test_cookies_file_is_checked_stored_and_never_returned(client, auth, member_auth):
    soon = int(time.time()) + 86400
    for bad, message in ((b"hello world", "not a cookies.txt"), (b"# only a comment\n", "holds no cookies"), (b".example.com\tTRUE\t/\tFALSE\t1\tx\ty\n", "no YouTube cookies")):
        r = client.post("/api/integrations/source/cookies", headers=auth, content=bad)
        assert r.status_code == 422 and message in r.json()["detail"]
    assert client.post("/api/integrations/source/cookies", headers=auth, content=b"x" * 1_000_001).status_code == 422
    r = client.post("/api/integrations/source/cookies", headers=auth, content=COOKIES.format(exp=soon).encode())
    assert r.status_code == 200 and r.json()["present"] is True and r.json()["count"] == 3 and r.json()["expired"] is False
    info = client.get("/api/integrations/source", headers=auth)
    assert info.json()["cookies"] is True and "abc" not in info.text and os.path.isfile(downloader.cookies_path())
    with downloader.access_options({"cookies": True, "player_client": "tv,mweb", "ipv6": False}) as access:
        copy = access["cookiefile"]
        assert copy != downloader.cookies_path() and os.path.isfile(copy) and access["extractor_args"] == {"youtube": {"player_client": ["tv", "mweb"]}}
    assert not os.path.exists(copy)  # each run gets its own copy, removed afterwards
    client.post("/api/integrations/source/cookies", headers=auth, content=COOKIES.format(exp=5).encode())
    assert client.get("/api/integrations/source", headers=auth).json()["cookies_file"]["expired"] is True
    assert client.delete("/api/integrations/source/cookies", headers=auth).status_code == 204
    assert client.get("/api/integrations/source", headers=auth).json()["cookies_file"] == {"present": False}
    # Members cannot see or change any of it.
    for method, path in (("get", ""), ("put", ""), ("post", "/cookies"), ("delete", "/cookies"), ("post", "/update"), ("post", "/test"), ("post", "/diagnose")):
        assert getattr(client, method)(f"/api/integrations/source{path}", headers=member_auth).status_code == 403, path


def test_proxy_is_saved_encrypted_and_shown_without_its_password(client, auth, db):
    from app.models import AppSetting

    assert client.put("/api/integrations/source", headers=auth, json={"proxy": "user:pass@host"}).status_code == 422
    assert client.put("/api/integrations/source", headers=auth, json={"proxy": "http://host"}).status_code == 422  # no port
    r = client.put("/api/integrations/source", headers=auth, json={"proxy": "http://user:s3cret@proxy.test:8080", "player_client": "web_safari"})
    assert r.json()["options"] == {"proxy": "http://user:••••@proxy.test:8080", "proxy_set": True, "player_client": "web_safari"} and "s3cret" not in r.text
    assert "s3cret" not in str(db.get(AppSetting, "downloader").value) and downloader.proxy() == "http://user:s3cret@proxy.test:8080"
    assert downloader.hide_proxy("failed via http://user:s3cret@proxy.test:8080 today") == "failed via <proxy> today"
    # Saving the masked address back (the field was not touched) keeps the real one.
    client.put("/api/integrations/source", headers=auth, json={"proxy": "http://user:••••@proxy.test:8080"})
    assert downloader.proxy() == "http://user:s3cret@proxy.test:8080"
    with downloader.access_options({"cookies": False, "player_client": "", "ipv6": False}) as access:
        assert access["proxy"] == "http://user:s3cret@proxy.test:8080"
    assert client.put("/api/integrations/source", headers=auth, json={"proxy": ""}).json()["options"]["proxy_set"] is False
    assert client.put("/api/integrations/source", headers=auth, json={"player_client": "nokia"}).status_code == 422


def test_diagnosis_verdicts():
    row = lambda client, cookies, ok, low=False, ipv6=False: {"client": client, "cookies": cookies, "ipv6": ipv6, "ok": ok, "low": low}  # noqa: E731
    say = lambda rows, **kw: downloader.verdict(rows, **{"with_cookies": False, "with_proxy": False, "js_runtime": "node", "current": "", **kw})  # noqa: E731
    assert "work with the settings as they are now" in say([row("", False, True)])
    assert "answers the “web_embedded” client, without cookies" in say([row("", False, False), row("web_embedded", False, True)])
    assert "over IPv6" in say([row("", False, False), row("", False, True, ipv6=True)])
    assert "low quality" in say([row("", False, False), row("android_vr", False, True, low=True)])
    assert "YouTube is blocking the server" in say([row("", False, False)])
    assert "different proxy" in say([row("", False, False)], with_proxy=True)
    assert "no JavaScript runtime" in say([row("", False, True)], js_runtime=None)
    assert downloader.read_attempt(True, {"format_id": "137+140", "width": 1920, "height": 1080, "resolution": "1920x1080"}, "") == {"ok": True, "format": "137+140 1920x1080", "height": 1080, "low": False, "message": "Works"}
    assert downloader.read_attempt(True, {"format_id": "18", "width": 640, "height": 360, "resolution": "640x360"}, "")["message"] == "Works, in low quality only (640x360)"
    # An upright Short is judged by its short side: 480×854 is low quality, 1080×1920 is Full HD.
    assert downloader.read_attempt(True, {"format_id": "135", "width": 480, "height": 854, "resolution": "480x854"}, "")["low"] is True
    assert downloader.read_attempt(True, {"format_id": "137", "width": 1080, "height": 1920, "resolution": "1080x1920"}, "")["low"] is False
    assert downloader.read_attempt(False, None, "Sign in to confirm")["ok"] is False


def test_adapter_reports_what_youtube_said(monkeypatch, db):
    class Refusing:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def download(self, urls):
            raise yt_dlp.utils.DownloadError("ERROR: [youtube] abc: Sign in to confirm you’re not a bot")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Refusing)
    with pytest.raises(sources.SourceError, match="YouTube asked for a sign-in check"):
        sources.YtDlpAdapter()._download_whole("https://www.youtube.com/watch?v=abc")
