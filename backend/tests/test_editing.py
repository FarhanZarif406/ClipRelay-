import os
import subprocess
import tempfile

import pytest
from sqlalchemy import select

from app.models import Channel, EditingLook, Job, LibraryFile, Mode, RuleSetting
from app.services import library, looks, media

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (64).to_bytes(4, "big") + (32).to_bytes(4, "big") + b"\x08\x06\x00\x00\x00" + b"\x00" * 40
MP3 = b"ID3" + b"\x00" * 200
TTF = b"\x00\x01\x00\x00" + b"\x00" * 200


def cmd_of(look, **kw):
    defaults = {"width": 1080, "height": 1920, "duration": 30.0, "has_audio": True}
    return " ".join(media.render_command("in.mp4", "out.mp4", look, **{**defaults, **kw})[0])


def test_the_default_look_and_its_checks():
    shorts, pod = looks.default_look(Mode.SHORTS), looks.default_look(Mode.PODCASTS)
    assert (shorts["speed"]["speed"], shorts["frame"]["flip"], shorts["frame"]["aspect"]) == (1.08, True, "9:16")
    assert (pod["speed"]["speed"], pod["frame"]["flip"]) == (1.0, False)
    assert looks.complete({"frame": {"aspect": "1:1"}, "junk": 1})["frame"] == {"aspect": "1:1", "position": "centre", "zoom": 1.0, "flip": True}
    for bad in ({"frame": {"aspect": "5:7"}}, {"frame": {"zoom": 2}}, {"speed": {"speed": 3}}, {"encoding": {"fps": 29}}, {"encoding": {"crf": 40}},
                {"hook": {"color": "red"}}, {"hook": {"font": "comic.ttf"}}, {"hook": {"box": {"opacity": 2}}}, {"watermark": {"position": "middle"}}, {"music": {"volume": 0}}):
        with pytest.raises(looks.LookError):
            looks.validate(bad)
    assert looks.validate({"hook": {"color": "#FFAA00"}})["hook"]["color"] == "#ffaa00"


def test_render_command_fits_the_picture_to_the_shape():
    look = looks.default_look()
    vertical = cmd_of(look)  # a Short going into a 9:16 clip is kept whole
    assert "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920" in vertical and "hflip,setpts=PTS/1.08" in vertical
    assert "atempo=1.0800,loudnorm=I=-14" in vertical and "-preset medium -crf 23 -pix_fmt yuv420p -r 30" in vertical and "-b:a 128k" in vertical
    look["frame"].update(position="left", zoom=1.2)
    wide = cmd_of(look, width=1920, height=1080)  # a widescreen video: its sides are cropped
    assert "crop=ih*9/16/1.2:ih/1.2:(iw-ow)*0.0:(ih-oh)/2,scale=1080:1920" in wide
    look["frame"]["aspect"], look["encoding"]["resolution"] = "16:9", "720x1280"
    assert "scale=1280:720:force_original_aspect_ratio=decrease" in cmd_of(look, width=1920, height=1080)
    look = looks.default_look()
    look["speed"].update(speed=1.0)
    look["frame"]["flip"] = False
    look["encoding"]["loudnorm"] = False
    plain = cmd_of(look)
    assert "hflip" not in plain and "setpts" not in plain and "[0:a]anull[aout]" in plain


def test_adjustments_become_filters():
    assert media.adjust_filters(looks.default_look()["adjust"]) == []  # all at 0: the picture is left as it is
    look = looks.validate({"adjust": {"brightness": 50, "contrast": -40, "saturation": -100, "shadows": 100, "highlights": -100, "warmth": 50, "tint": 20, "hue": -30, "sharpness": 100, "vignette": 50, "grain": 50}})
    assert media.adjust_filters(look["adjust"]) == [
        "eq=brightness=0.15:contrast=0.8:saturation=0.0", "curves=all='0/0 0.25/0.4 0.75/0.6 1/1'", "colorbalance=rm=0.15:gm=-0.06:bm=-0.15",
        "hue=h=-30", "unsharp=5:5:1.5:5:5:0", "vignette=angle=0.6", "noise=alls=15:allf=t+u",
    ]
    cmd = cmd_of(look)
    assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,eq=brightness=0.15" in cmd and "noise=alls=15:allf=t+u,hflip" in cmd  # after the fit, before the flip
    for bad in ({"adjust": {"brightness": 101}}, {"adjust": {"hue": 200}}, {"adjust": {"grain": -1}}, {"adjust": {"contrast": 1.5}}):
        with pytest.raises(looks.LookError):
            looks.validate(bad)
    assert "adjusted" in looks.summary(look) and "adjusted" not in looks.summary(looks.default_look())


def test_render_command_draws_text_box_watermark_and_music():
    look = looks.validate({
        "encoding": {"keep_audio": False},
        "music": {"enabled": True, "volume": 0.3},
        "hook": {"enabled": True, "x": 50, "y": 20, "stroke_width": 4, "color": "#ffee00", "box": {"enabled": True, "color": "#112233", "x": 50, "y": 20}},
        "watermark": {"enabled": True, "position": "tl", "size": 20},
    })
    cmd = cmd_of(look, hook_files=["C:/tmp/hook-0.txt"], font_file="C:/Windows/Fonts/arialbd.ttf", watermark_file="mark.png", music_file="song.mp3")
    assert "color=c=0x112233:s=928x230" in cmd and "overlay=76:269:enable='lt(t,3.0)'" in cmd
    assert "drawtext=fontfile='C\\:/Windows/Fonts/arialbd.ttf':textfile='C\\:/tmp/hook-0.txt':fontsize=48:fontcolor=0xffee00:borderw=4:bordercolor=0x000000" in cmd
    assert "scale=216:-1[mark]" in cmd and "overlay=40:40" in cmd
    assert "-stream_loop -1 -i song.mp3" in cmd and "volume=0.3" in cmd and "[0:a]" not in cmd and "-t 27.778" in cmd
    look["music"]["enabled"] = False
    silent = cmd_of(look)  # no sound of its own and no music: silence, which upload services accept
    assert "anullsrc" in silent and "-shortest" in silent and "-b:a 64k" in silent
    assert media.drawable("Best tacos ❤️\U0001F600 ever café") == "Best tacos ever café"  # emoji would draw as empty boxes
    assert media.wrap_hook_text("This one small habit changed everything about my mornings forever", look) == ["This one small habit changed", "everything about my mornings", "forever"]


@pytest.mark.skipif(not os.path.isfile(media.ffmpeg_exe()) and not __import__("shutil").which(media.ffmpeg_exe()), reason="FFmpeg is not installed")
def test_a_real_render_with_every_part_of_the_look():
    exe = media.ffmpeg_exe()
    work = tempfile.mkdtemp()
    src, mark, song = (os.path.join(work, n) for n in ("src.mp4", "mark.png", "song.wav"))
    run = lambda *args: subprocess.run([exe, "-y", "-loglevel", "error", *args], check=True, capture_output=True, timeout=120)  # noqa: E731
    run("-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src)
    run("-f", "lavfi", "-i", "color=c=red:s=120x60:d=1", "-frames:v", "1", mark)
    run("-f", "lavfi", "-i", "sine=frequency=220:duration=1", song)
    look = looks.validate({
        "encoding": {"resolution": "720x1280", "preset": "ultrafast"}, "music": {"enabled": True},
        "hook": {"enabled": True, "box": {"enabled": True, "radius": 50}}, "watermark": {"enabled": True},
        "adjust": {"brightness": 10, "contrast": 20, "highlights": -30, "shadows": 25, "saturation": 15, "warmth": 40, "tint": -10, "hue": 12, "sharpness": 50, "vignette": 40, "grain": 20},
    })
    result = media.render(src, look, hook_text="This one small habit changed everything", watermark_file=mark, music_file=song)
    info = media.probe(result.path)
    assert (info.width, info.height, info.has_audio) == (720, 1280, True) and 2.5 < info.duration < 3.0  # 3 s at 1.08x
    assert result.note is None if media.default_font() else result.note == "hook_font_missing"
    os.remove(result.path)


def test_editing_rules_presets_and_channels(client, auth, member_auth, db, channel):
    db.add(RuleSetting(key="speed", value=1.2, user_id=1))  # the speed set as a rule before is carried over
    db.commit()
    state = client.get("/api/editing", headers=auth).json()
    assert state["default"]["speed"]["speed"] == 1.2 and state["presets"] == [] and state["channels"][0]["preset_id"] is None
    assert client.get("/api/editing?mode=podcasts", headers=auth).json()["default"]["speed"]["speed"] == 1.0

    look = {**state["default"], "frame": {**state["default"]["frame"], "aspect": "1:1"}}
    assert client.put("/api/editing", headers=auth, json={"look": {**look, "encoding": {"crf": 99}}}).status_code == 422
    assert client.put("/api/editing", headers=auth, json={"look": look}).json()["default"]["frame"]["aspect"] == "1:1"

    left = {**look, "frame": {**look["frame"], "position": "left"}}
    preset = client.post("/api/editing/presets", headers=auth, json={"name": "Product demos", "look": left}).json()
    assert preset["name"] == "Product demos" and preset["channels"] == 0
    for bad in ("default", "product DEMOS", ""):
        assert client.post("/api/editing/presets", headers=auth, json={"name": bad, "look": left}).status_code == 422, bad
    assert client.patch(f"/api/editing/presets/{preset['id']}", headers=auth, json={"name": "Demos"}).json()["name"] == "Demos"

    # A channel on the preset is edited with it; everything else with the default.
    state = client.put(f"/api/editing/channels/{channel.id}", headers=auth, json={"preset_id": preset["id"]}).json()
    assert state["channels"][0]["preset_id"] == preset["id"] and state["presets"][0]["channels"] == 1
    from app.models import Video
    video = Video(user_id=1, channel_id=channel.id, mode="shorts", youtube_video_id="x1")
    db.add(video)
    db.commit()
    db.expire_all()
    assert looks.for_video(db, db.get(Video, video.id))["frame"]["position"] == "left"

    # Another member sees none of it and cannot use it.
    assert client.get("/api/editing", headers=member_auth).json()["presets"] == []
    assert client.patch(f"/api/editing/presets/{preset['id']}", headers=member_auth, json={"name": "Mine"}).status_code == 404
    assert client.put(f"/api/editing/channels/{channel.id}", headers=member_auth, json={"preset_id": None}).status_code == 404

    # Deleting the preset puts the channel back on the default rules.
    assert client.delete(f"/api/editing/presets/{preset['id']}", headers=auth).status_code == 204
    db.expire_all()
    assert db.get(Channel, channel.id).preset_id is None and looks.for_video(db, db.get(Video, video.id))["frame"]["position"] == "centre"
    assert db.scalar(select(EditingLook).where(EditingLook.name.is_not(None))) is None


def test_library_music_fonts_and_watermark(client, auth, member_auth, db, monkeypatch, tmp_path):
    monkeypatch.setattr(library, "ROOT", tmp_path)
    assert client.post("/api/library/watermark?name=logo.jpg", headers=auth, content=b"\xff\xd8\xff" + b"\x00" * 20).status_code == 422
    wm = client.post("/api/library/watermark?name=logo.png", headers=auth, content=PNG).json()
    assert wm["items"][0]["width"] == 64 and wm["items"][0]["height"] == 32
    again = client.post("/api/library/watermark?name=logo2.png", headers=auth, content=PNG).json()
    assert len(again["items"]) == 1 and again["items"][0]["name"] == "logo2"  # one watermark: a new one replaces it

    first = client.post("/api/library/music?name=one.mp3", headers=auth, content=MP3).json()
    second = client.post("/api/library/music?name=two.mp3", headers=auth, content=MP3).json()
    ids = [item["id"] for item in second["items"]]
    assert second["next_id"] == ids[0] and first["limit"] == 200
    library.mark_used(db.get(LibraryFile, ids[0]))
    db.commit()
    assert library.next_track(db, 1).id == ids[1]  # tracks take turns
    assert client.post("/api/library/fonts?name=brand.ttf", headers=auth, content=TTF).json()["items"][0]["type"] == "ttf"
    assert client.post("/api/library/fonts?name=brand.ttf", headers=auth, content=MP3).status_code == 422
    font_id = db.scalar(select(LibraryFile.id).where(LibraryFile.kind == "fonts"))
    assert library.font_file(db, 1, f"custom:{font_id}").endswith(".ttf") and library.font_file(db, 2, f"custom:{font_id}") is None

    token = client.get("/api/auth/media-token", headers=auth).json()["token"]
    track = client.get(f"/api/library/music/{ids[0]}/file?token={token}")
    assert track.status_code == 200 and track.headers["content-type"] == "audio/mpeg"
    other = client.get("/api/auth/media-token", headers=member_auth).json()["token"]
    assert client.get(f"/api/library/music/{ids[0]}/file?token={other}").status_code == 404
    assert client.get("/api/library/music", headers=member_auth).json()["items"] == []
    assert client.delete(f"/api/library/music/{ids[0]}", headers=member_auth).status_code == 404
    assert [i["id"] for i in client.delete(f"/api/library/music/{ids[0]}", headers=auth).json()["items"]] == [ids[1]]
    assert not (tmp_path / "1" / "music" / f"{ids[0]}.mp3").exists()


def test_a_render_uses_the_members_files(db, channel, fake_media, monkeypatch, tmp_path):
    from tests.test_pipeline import _make_job

    monkeypatch.setattr(library, "ROOT", tmp_path)
    track = library.add(db, 1, "music", "song.mp3", MP3)
    library.add(db, 1, "watermark", "logo.png", PNG)
    row = looks.default_row(db, 1, "shorts")
    looks.save(row, looks.validate({**row.look, "music": {"enabled": True, "volume": 0.4}, "watermark": {**row.look["watermark"], "enabled": True}, "hook": {**row.look["hook"], "enabled": True, "source": "title"}}))
    db.commit()
    job = _make_job(db, status="fetched", caption="pending", rendered=False)
    from app.services import pipeline
    pipeline.process_video(db, job.id)
    call = fake_media[-1]
    assert call["music_file"].endswith(f"{track.id}.mp3") and call["watermark_file"].endswith(".png") and call["hook_text"] == "Hidden beaches in Crete"
    assert db.get(LibraryFile, track.id).uses == 1  # the next clip gets the next track
    assert db.scalar(select(Job).where(Job.id == job.id)).status in ("rewriting", "awaiting_approval", "ready")
