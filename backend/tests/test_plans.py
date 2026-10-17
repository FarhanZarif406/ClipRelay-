"""The owner's panel: accounts, plans, and what a plan allows."""

from datetime import timedelta

from sqlalchemy import select

from app.models import Channel, User, utcnow
from app.services import buffer, plans

LIMITED = {
    "name": "Starter", "description": "A little", "is_default": False,
    "features": {"test_render": True},  # everything else off
    "limits": {"channels": 1, "videos_per_day": 4, "buffer_keys": 1},
}


def _login(client, email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_owner_makes_plans_and_accounts(client, auth, member_auth, db):
    # Only owners see the panel.
    assert client.get("/api/accounts", headers=member_auth).status_code == 403
    assert client.post("/api/plans", headers=member_auth, json=LIMITED).status_code == 403

    made = client.post("/api/plans", headers=auth, json=LIMITED).json()
    starter = next(p for p in made["plans"] if p["name"] == "Starter")
    assert starter["features"]["podcasts"] is False and starter["limits"]["channels"] == 1
    assert client.post("/api/plans", headers=auth, json=LIMITED).status_code == 409  # names stay apart
    assert client.post("/api/plans", headers=auth, json={**LIMITED, "name": "Bad", "limits": {"channels": -1}}).status_code == 422

    created = client.post("/api/accounts", headers=auth, json={"email": "seller@example.com", "password": "Seller-pass-1", "name": "Seller", "plan_id": starter["id"]})
    assert created.status_code == 201 and created.json()["plan"] == "Starter"
    account_id = created.json()["id"]
    token = _login(client, "seller@example.com", "Seller-pass-1").json()["access_token"]
    seller = {"Authorization": f"Bearer {token}"}

    # The account sees its own plan, and the plan is enforced.
    mine = client.get("/api/plan", headers=seller).json()
    assert mine["plan"] == "Starter" and mine["features"]["ai_captions"] is False and mine["limits"]["buffer_keys"] == 1
    # No Podcasts in the plan: the workspace can be looked at, but nothing can be added or changed there.
    assert client.get("/api/channels?mode=podcasts", headers=seller).status_code == 200
    assert client.post("/api/channels?mode=podcasts", headers=seller, json={"query": "@somepodcast"}).status_code == 403
    refused = client.post("/api/library/watermark?name=logo.png", headers=seller, content=b"PNG-bytes")
    assert refused.status_code == 403 and "not part of your plan" in refused.json()["detail"]
    assert buffer.max_keys(db, account_id) == 1
    db.add(Channel(youtube_channel_id="UC" + "z" * 22, user_id=account_id, display_name="One", monitoring_since=utcnow()))
    db.commit()
    try:
        plans.check_channels(db, db.get(User, account_id))
        raise AssertionError("a second channel should be refused")
    except plans.PlanLimit as exc:
        assert "allows 1 channel" in str(exc)
    assert not plans.allows(db, account_id, "ai_hook") and plans.allows(db, account_id, "test_render")
    assert plans.limit(db, account_id, "videos_per_day") == 4

    # A plan that has run out falls back to the default plan.
    db.expire_all()
    client.patch(f"/api/accounts/{account_id}", headers=auth, json={"plan_expires_at": (utcnow() - timedelta(days=1)).isoformat()})
    assert client.get("/api/plan", headers=seller).json()["expired"] is True

    # Suspended: no way in, and the session stops working.
    assert client.patch(f"/api/accounts/{account_id}", headers=auth, json={"suspended": True}).json()["suspended"] is True
    assert _login(client, "seller@example.com", "Seller-pass-1").status_code == 403
    assert client.get("/api/plan", headers=seller).status_code == 401
    client.patch(f"/api/accounts/{account_id}", headers=auth, json={"suspended": False, "password": "New-pass-123"})
    assert _login(client, "seller@example.com", "New-pass-123").status_code == 200

    # The owner is never limited, and sees every account.
    assert client.get("/api/plan", headers=auth).json()["owner"] is True
    assert "seller@example.com" in [a["email"] for a in client.get("/api/accounts", headers=auth).json()]
    assert client.delete(f"/api/accounts/{account_id}", headers=auth).status_code == 204
    assert _login(client, "seller@example.com", "New-pass-123").status_code == 401


def test_fast_mode_lets_free_accounts_try_but_not_save_paid_editing(client, auth, db):
    made = client.post("/api/plans", headers=auth, json=LIMITED).json()
    starter = next(p for p in made["plans"] if p["name"] == "Starter")
    client.post("/api/accounts", headers=auth, json={"email": "fast@example.com", "password": "Fast-pass-123", "plan_id": starter["id"]})
    seller = {"Authorization": f"Bearer {_login(client, 'fast@example.com', 'Fast-pass-123').json()['access_token']}"}

    state = client.get("/api/editing", headers=seller).json()
    look = state["default"]
    assert state["fast_mode"] is True and look["encoding"]["resolution"] == "720x1280" and look["encoding"]["preset"] == "superfast"
    assert client.put("/api/editing", headers=seller, json={"look": look}).status_code == 200  # the Fast-mode look saves

    # Anything heavier can be tried in the page, but saving it says it is for paid members.
    heavy = {**look, "hook": {**look["hook"], "enabled": True, "source": "title", "box": {**look["hook"]["box"], "enabled": True, "radius": 24}},
             "adjust": {**look["adjust"], "grain": 30, "brightness": 10}, "encoding": {**look["encoding"], "resolution": "1080x1920"}}
    refused = client.put("/api/editing", headers=seller, json={"look": heavy})
    assert refused.status_code == 403
    detail = refused.json()["detail"]
    assert "paid members" in detail and "Rounded title box" in detail and "Grain" in detail and "1080p" in detail and "Brightness" not in detail

    # Videos are made light whatever an old saved look says.
    light = plans.light_look(heavy)
    assert light["encoding"] == {**heavy["encoding"], "resolution": "720x1280", "fps": 30, "preset": "superfast"}
    assert light["hook"]["box"]["radius"] == 0 and light["adjust"]["grain"] == 0 and light["adjust"]["brightness"] == 10
    # The owner is never in Fast mode.
    assert client.get("/api/editing", headers=auth).json()["fast_mode"] is False


def test_push_only_plans_are_not_auto_checked(db, member_auth):
    from app.models import Plan
    from app.services import detection

    member = db.scalar(select(User).where(User.role == "member"))
    push_only = Plan(name="PushOnly", features={}, limits={"auto_check_minutes": 0})
    hourly = Plan(name="Hourly", features={}, limits={"auto_check_minutes": 60})
    db.add_all([push_only, hourly])
    db.flush()
    member.plan_id = push_only.id
    channel = Channel(youtube_channel_id="UC" + "q" * 22, user_id=member.id, display_name="Q", active=True, monitoring_since=utcnow(), next_poll_at=None)
    db.add(channel)
    db.commit()

    assert channel.id not in detection.due_channels(db)  # push notifications only
    assert channel.next_poll_at > utcnow() + timedelta(minutes=50)  # looked at again in an hour, in case the plan changed
    assert plans.auto_check_minutes(db, member.id, 5) is None

    member.plan_id = hourly.id
    channel.next_poll_at = None
    db.commit()
    assert channel.id in detection.due_channels(db)
    assert plans.auto_check_minutes(db, member.id, 5) == 60  # the plan's hour, not the 5-minute rule
    assert plans.auto_check_minutes(db, None, 5) == 5  # owners keep their own rule


def test_a_free_trial_ends_and_the_account_stops_working(client, auth, db, monkeypatch):
    from app.models import Plan
    from app.services import pipeline
    from tests.test_pipeline import _make_job

    trial = Plan(name="Trial", features={"ai_captions": True}, limits={"videos_per_day": 3, "trial_days": 10})
    paid = Plan(name="Paid", features={"ai_captions": True, "watermark": True, "full_editing": True}, limits={"videos_per_day": 15})
    db.add_all([trial, paid])
    db.commit()
    made = client.post("/api/accounts", headers=auth, json={"email": "trial@example.com", "password": "Trial-pass-1", "plan_id": trial.id}).json()
    assert made["plan"] == "Trial" and made["plan_expires_at"]  # the trial's end date, 10 days out
    member = {"Authorization": f"Bearer {_login(client, 'trial@example.com', 'Trial-pass-1').json()['access_token']}"}
    mine = client.get("/api/plan", headers=member).json()
    assert mine["blocked"] is None and mine["upgrade"]["watermark"] == "Paid" and mine["upgrade"]["full_editing"] == "Paid"

    # Ten days later: the account can still sign in, but nothing works for it.
    user = db.get(User, made["id"])
    user.plan_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert _login(client, "trial@example.com", "Trial-pass-1").status_code == 200
    assert client.get("/api/plan", headers=member).json()["blocked"] == "expired"
    assert plans.blocked(db, user.id) == "expired"
    job = _make_job(db, youtube_video_id="trialvid", rendered=False)
    db.get(type(job.video), job.video_id).user_id = user.id
    db.commit()
    assert pipeline.process_video(db, job.id) == "fetched" and job.next_check_at > utcnow() + timedelta(minutes=50)  # waits

    # The owner gives it a paid plan: it works again.
    client.patch(f"/api/accounts/{user.id}", headers=auth, json={"plan_id": paid.id, "plan_expires_at": None})
    db.expire_all()
    assert plans.blocked(db, user.id) is None


def test_the_owner_changes_any_limit_for_one_account(client, auth, db):
    made = client.post("/api/plans", headers=auth, json=LIMITED).json()
    starter = next(p for p in made["plans"] if p["name"] == "Starter")
    bigger = client.post("/api/plans", headers=auth, json={**LIMITED, "name": "Bigger", "limits": {"channels": 9, "videos_per_day": 20, "buffer_keys": 3}}).json()
    bigger = next(p for p in bigger["plans"] if p["name"] == "Bigger")

    # Added with the plan, plus their own: 50 videos a day and a watermark (the plan has neither).
    full_features = {**starter["features"], "watermark": True}
    full_limits = {**starter["limits"], "videos_per_day": 50}
    created = client.post("/api/accounts", headers=auth, json={"email": "vip@example.com", "password": "Vip-pass-123", "plan_id": starter["id"],
                                                                "features": full_features, "limits": full_limits}).json()
    assert created["limits"]["videos_per_day"] == 50 and created["features"]["watermark"] is True
    assert created["limits"]["channels"] == 1 and sorted(created["custom"]) == ["videos_per_day", "watermark"]  # only what differs is kept
    user = db.get(User, created["id"])
    assert user.custom_limits == {"videos_per_day": 50} and user.custom_features == {"watermark": True}
    assert plans.limit(db, user.id, "videos_per_day") == 50 and plans.allows(db, user.id, "watermark")

    # A new plan: the hand-made changes stay; the rest follows the new plan.
    moved = client.patch(f"/api/accounts/{user.id}", headers=auth, json={"plan_id": bigger["id"]}).json()
    assert moved["plan"] == "Bigger" and moved["limits"]["channels"] == 9 and moved["limits"]["videos_per_day"] == 50

    # Fewer than the plan works too, and a value out of bounds is refused.
    fewer = client.patch(f"/api/accounts/{user.id}", headers=auth, json={"limits": {**moved["limits"], "channels": 2}}).json()
    assert fewer["limits"]["channels"] == 2
    assert client.patch(f"/api/accounts/{user.id}", headers=auth, json={"limits": {"channels": -5}}).status_code == 422

    back = client.patch(f"/api/accounts/{user.id}", headers=auth, json={"reset_custom": True}).json()
    assert back["custom"] == [] and back["limits"]["videos_per_day"] == 20 and back["features"]["watermark"] is False


def test_first_day_features_and_the_cloud_limit(client, auth, db):
    from datetime import timedelta as td

    from app.models import Job, JobStatus, Video

    trial = {"name": "Trial", "description": "", "is_default": False,
             "features": {"ai_captions": True, "watermark": "first_day", "cloud_editing": True},
             "limits": {"trial_days": 4, "cloud_videos_per_month": 2}}
    made = client.post("/api/plans", headers=auth, json=trial).json()
    plan = next(p for p in made["plans"] if p["name"] == "Trial")
    assert plan["features"]["watermark"] == "first_day"
    created = client.post("/api/accounts", headers=auth, json={"email": "try@example.com", "password": "Try-pass-123", "plan_id": plan["id"]}).json()
    user = db.get(User, created["id"])
    assert plans.allows(db, user.id, "watermark")  # the first day: on
    assert plans.effective(db, user)["first_day"] == ["watermark"]
    user.plan_started_at = utcnow() - td(days=2)  # two days in: the first day is over
    db.commit()
    assert not plans.allows(db, user.id, "watermark") and plans.allows(db, user.id, "ai_captions")
    assert plans.upgrade_map(db).get("watermark") != "Trial"  # a taste of it is not "having" it

    assert plans.cloud_left(db, user.id) == 2
    for n in range(2):
        video = Video(user_id=user.id, youtube_video_id=f"c{n}", original_title="x", original_caption="", original_tags=[], status="accepted")
        db.add(video)
        db.flush()
        db.add(Job(video_id=video.id, status=JobStatus.REWRITING, edit_place="cloud", edited_at=utcnow(), caption_status="done", rewritten_tags=[]))
    db.commit()
    assert plans.cloud_left(db, user.id) == 0


def test_first_day_features_and_the_cloud_limit(client, auth, db):
    from datetime import timedelta as td

    from app.models import Job, JobStatus, Video

    trial = {"name": "Trial", "description": "", "is_default": False,
             "features": {"ai_captions": True, "watermark": "first_day", "cloud_editing": True},
             "limits": {"trial_days": 4, "cloud_videos_per_month": 2}}
    made = client.post("/api/plans", headers=auth, json=trial).json()
    plan = next(p for p in made["plans"] if p["name"] == "Trial")
    assert plan["features"]["watermark"] == "first_day"
    created = client.post("/api/accounts", headers=auth, json={"email": "try@example.com", "password": "Try-pass-123", "plan_id": plan["id"]}).json()
    user = db.get(User, created["id"])
    assert plans.allows(db, user.id, "watermark")  # the first day: on
    assert plans.effective(db, user)["first_day"] == ["watermark"]
    user.plan_started_at = utcnow() - td(days=2)  # two days in: the first day is over
    db.commit()
    assert not plans.allows(db, user.id, "watermark") and plans.allows(db, user.id, "ai_captions")
    assert plans.upgrade_map(db).get("watermark") != "Trial"  # a taste of it is not "having" it

    assert plans.cloud_left(db, user.id) == 2
    for n in range(2):
        video = Video(user_id=user.id, youtube_video_id=f"c{n}", original_title="x", original_caption="", original_tags=[], status="accepted")
        db.add(video)
        db.flush()
        db.add(Job(video_id=video.id, status=JobStatus.REWRITING, edit_place="cloud", edited_at=utcnow(), caption_status="done", rewritten_tags=[]))
    db.commit()
    assert plans.cloud_left(db, user.id) == 0


def test_a_plan_with_a_length_ends_that_many_days_after_it_is_given(client, auth, db):
    made = client.post("/api/plans", headers=auth, json={**LIMITED, "name": "Twenty", "limits": {"trial_days": 20, "cloud_videos_per_month": 30}}).json()
    twenty = next(p for p in made["plans"] if p["name"] == "Twenty")
    created = client.post("/api/accounts", headers=auth, json={"email": "b@example.com", "password": "Bronze-pass-1"}).json()
    moved = client.patch(f"/api/accounts/{created['id']}", headers=auth, json={"plan_id": twenty["id"], "plan_expires_at": None}).json()
    from datetime import datetime

    ends = datetime.fromisoformat(moved["plan_expires_at"])
    assert 19 <= (ends - utcnow()).days <= 20  # given today: 20 days
    user = db.get(User, created["id"])
    db.refresh(user)
    assert plans.cloud_period_start(db, user) == plans.started_at(user)  # cloud videos are counted over the plan's 20 days
    assert not plans.is_trial("Twenty") and plans.is_trial("Free Trial")


def test_the_owner_sets_a_price_on_a_plan(client, auth):
    made = client.post("/api/plans", headers=auth, json={**LIMITED, "name": "Priced", "price": 999, "currency": "pkr"}).json()
    plan = next(p for p in made["plans"] if p["name"] == "Priced")
    assert plan["price"] == 999 and plan["currency"] == "PKR"
    changed = client.put(f"/api/plans/{plan['id']}", headers=auth, json={**LIMITED, "name": "Priced", "price": 1499}).json()
    assert next(p for p in changed["plans"] if p["name"] == "Priced")["price"] == 1499
    assert client.post("/api/plans", headers=auth, json={**LIMITED, "name": "Bad", "price": -5}).status_code == 422
