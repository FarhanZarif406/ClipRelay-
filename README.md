# ClipRelay

ClipRelay watches a set of YouTube channels that publish short-form video and republishes every new upload to TikTok,
with only a light edit in between. When a watched channel posts a new short, ClipRelay detects it, reads its details,
downloads the file, applies two small edits (a slight speed-up and a horizontal flip), rewrites the caption for TikTok,
and then either holds it for one-click approval or publishes it straight away.

YouTube is the only source. Only add channels whose videos you have the right to republish.

```
Detected → Downloading → Rendering → (Writing caption) → (Needs approval) → Ready → Uploading → Posted → Monitoring
                                                                              → Clean / Violated / Failed
```

The caption is written alongside the download and the edit, because it needs only the video's details, not the file.
A video that fails the duration or cap check is never discarded: it is held under **Skipped** with its reason and can be
processed by hand.

| Layer | Stack |
|---|---|
| Frontend | React 19 + TypeScript + Vite, React Router, TanStack Query (UI from the Figma Make design, unchanged) |
| API | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, JWT auth |
| Jobs | Celery + Redis. Schedules live in PostgreSQL, so you can change them in the UI without a restart |
| Media | FFmpeg (edit) and yt-dlp (download) |
| AI | Gemini, Anthropic or any OpenAI-compatible API, added in Settings → AI models |
| Storage | Local folder or any S3-compatible bucket |
| Deploy | Docker + docker-compose |

---

## 1. Quick start (Docker)

```bash
cp .env.example .env
# Generate the two secrets:
python -c "import secrets;print('SECRET_KEY='+secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet;print('ENCRYPTION_KEY='+Fernet.generate_key().decode())"
# Paste them into .env and set PUBLIC_BASE_URL / FRONTEND_URL. API keys can be added later in the app
# (Settings → API keys / AI models), or put in .env as TIKTOK_*, LLM_*, SMTP_*.

docker compose up -d --build
```

Open **http://localhost:8080**. The first visitor creates the **owner** account; after that, registration is closed and
owners add team members under **Settings → Team members**. Owners manage API keys, AI models and the team; members run
the automation and only see whether keys are configured. Owners can promote or demote others (a workspace always keeps
at least one owner). You can also create users from the CLI (the first user created this way becomes the owner):

```bash
docker compose exec backend python -m app.cli create-user you@example.com 'a-strong-password' "Your Name"
```

Services: `postgres`, `redis`, `backend` (FastAPI, which runs migrations on start), `worker` (Celery), `beat`
(the scheduler tick), and `frontend` (nginx serving the SPA and proxying `/api`).

> **HTTPS is required for OAuth.** TikTok only redirects to HTTPS URLs that you have registered. In production,
> put the `frontend` service behind your TLS proxy (Caddy, Traefik, a load balancer). For local testing, run a tunnel such as
> `ngrok http 8080` or `cloudflared tunnel --url http://localhost:8080`, and set `PUBLIC_BASE_URL` and `FRONTEND_URL`
> to the tunnel URL.

### Integrations page
The **Integrations** page in the app has everything in one place, with step-by-step instructions: the TikTok app keys,
the AI model for captions (Gemini), the optional YouTube Data API key, and the status of the downloader (yt-dlp) and the
editor (FFmpeg). Each has a **Test** button: the editor test renders a real two-second clip with the current edit, and
the downloader test reads a real YouTube video. The edit itself (speed, flip, audio) is on the **Editing Rules** page.

### Where API keys live

Every third-party credential can be managed from the UI **without a restart**. Values saved in the app are encrypted with
`ENCRYPTION_KEY` and take priority; anything not saved there falls back to `.env`. Each card shows its source
(**Set in app** / **From .env**) and status (**Not configured · From .env · Valid · Unverified · Invalid**).

| Credential | Where in the app | `.env` fallback |
|---|---|---|
| TikTok client key / secret | Settings → API keys | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` |
| AI models (any number, one default) | Settings → AI models | `LLM_*` (used only when no model is added) |
| SMTP for email alerts | Settings → Notifications | `SMTP_*` |

Infrastructure settings stay in `.env` only: database, Redis, storage, `SECRET_KEY`, `ENCRYPTION_KEY`, `PUBLIC_BASE_URL`,
and OAuth scopes. Saved credentials and AI models are re-validated daily, and you get a *Token problems* alert if one stops working.

---

## 2. Channels and detection

Open **Channels → Add channel**, paste the channel's URL or `@handle`, click **Find channel**, pick the TikTok account
it posts to, and click **Add channel**. Channels are added one at a time.

- **Only new uploads are republished.** Videos published before the channel was added (or while it was switched off)
  are ignored.
- **Push notifications.** When `PUBLIC_BASE_URL` is a public HTTPS address, ClipRelay subscribes to YouTube's push hub
  (PubSubHubbub) at `{PUBLIC_BASE_URL}/api/youtube/webhook`. Subscriptions expire, so they are renewed every day.
- **Polling fallback.** Every channel's uploads feed is also checked every few minutes (*Polling interval* in
  Settings), so a missed push never means a missed video. On a local install polling is the only method.
- **One video, once.** `videos.youtube_video_id` is unique. YouTube sends a notification again whenever a title or
  description is edited; the repeat finds the existing row and nothing happens.
- **No API key is required.** With `YOUTUBE_API_KEY` set, lookups use the YouTube Data API; without it they read the
  public channel page and yt-dlp.

Downloads use **yt-dlp**, which is outside YouTube's terms of service — YouTube offers no download mechanism, so this is
an accepted condition, not a solved problem. The downloader sits behind an adapter (`backend/app/services/sources.py`,
`VIDEO_SOURCE_ADAPTER`), so it can be replaced, for example by the client supplying the original files.

---

## 3. Create the TikTok app

1. Go to <https://developers.tiktok.com> → **Manage apps → Connect an app** (you may need to create an organization first).
2. Fill in the **basic information**: icon, name, category, description, **Terms of Service URL**, **Privacy Policy URL**, and
   **Platforms → Web** with your website URL.
3. **Add products:**
   - **Login Kit.** Set the **Redirect URI** (Web) to `https://YOUR_DOMAIN/api/tiktok/oauth/callback`. It must match exactly.
   - **Content Posting API.** Upload-to-inbox works straight away; turn on **Direct Post** as well for later.
4. **Scopes.** Request these:
   | Scope | Why |
   |---|---|
   | `user.info.basic` | Account display name and avatar |
   | `video.upload` | Send videos to the account's TikTok inbox (the launch mode) |
   | `video.publish` | Direct-post videos, once the app is audited |
   | `video.list` | Confirm a published video is still live (violation check) |
   | `user.info.profile` *(optional)* | Show the real `@username`. Add it to `TIKTOK_SCOPES` once approved |
5. Copy the **Client key** and **Client secret** into **Settings → API keys → TikTok app** (owner only) and click
   **Validate** then **Save**. ClipRelay checks them with TikTok's `client_credentials` grant. (Or set
   `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` in `.env`.)
6. **Inbox mode first.** Until TikTok's audit is approved, every direct post is forced private and the API gives no
   signal that this is happening. So ClipRelay launches with *Publish mode* = `inbox` (Settings → Pipeline rules): the
   video lands in the account's TikTok inbox and a person finishes the post in the TikTok app. **Submit the audit
   application early**, and switch *Publish mode* to `direct` once it is approved. Accounts connected before
   `video.upload` was added to the scopes must be reconnected.
7. **Sandbox and audit.** While the app is in Sandbox, add your TikTok accounts as **target users**. **Unaudited apps can
   only post with `SELF_ONLY` (private) visibility.** ClipRelay picks a privacy level from what TikTok's
   `creator_info` returns, so private posting works automatically. To post publicly, submit the app for TikTok's
   Content Posting **audit**, then turn on **App audited** on the TikTok card. Until then, *TikTok Accounts* shows a reminder
   that posts will be private.
8. **Rate limits.** The video init endpoint allows about 6 requests per minute per user token, and TikTok caps the number of
   API posts per creator per day. ClipRelay enforces a per-account **daily cap** (default 7, counted from midnight Asia/Karachi)
   and exponential backoff on `rate_limit_exceeded` / HTTP 429.

Click **Connect account** in *TikTok Accounts* to run Login Kit OAuth. Access tokens (24 h) are refreshed automatically
with the refresh token (365 days). Accounts are shown as **Expiring** 3 days before the refresh token expires and as
**Expired** after that. Expired accounts need **Reconnect**.

---

## 4. LLM and storage

**AI models** (Settings → AI models, owner only). Add as many as you like: **Anthropic, OpenAI, Google Gemini,
OpenRouter, Groq, Mistral**, or any **custom** OpenAI-compatible endpoint (with a base URL). Paste the key, click
**Validate** to load that provider's model list, pick a model, and save. One model is the workspace default. Each model
has **Test** (sends "Reply with the single word OK."), **Edit** (leave the key blank to keep it), **Set default** and
**Remove**. When no model has been added, ClipRelay uses the `.env` values:

```ini
LLM_PROVIDER=anthropic          # or: openai (any OpenAI-compatible API; set LLM_BASE_URL for others)
LLM_MODEL=claude-sonnet-5-5
LLM_API_KEY=sk-...
```

If `LLM_API_KEY` is set when you upgrade, the migration adds it as the default AI model automatically.

**Prompt Studio** templates have three parts (Title / Caption / Hashtags). You can use the variables `{title}`, `{caption}`,
`{tags}` and `{niche}` (`{original_title}`, `{original_caption}` and `{original_tags}` also work). A part left
empty keeps the original text. Every save creates a version you can restore, and **Test prompt** runs the template
against a real caption. Each template can also pick its own **model** from the dropdown under the editor. The default
option uses the workspace default.

### Email alerts

Alerts always appear in the dashboard. Under **Settings → Notifications** you can also add a webhook (Slack, Discord or
any HTTPS endpoint) and/or **alert email addresses**. For email, fill in the **Email (SMTP)** card. The **Gmail preset**
fills `smtp.gmail.com:587` with STARTTLS; use your Gmail address as the username and from address, and a 16-character
**app password** (Google Account → Security → 2-Step Verification → App passwords). Click **Send test email** to confirm.
Violations, failed jobs and token problems are emailed according to the toggles on that tab.

**Storage.** `STORAGE_BACKEND=local` stores files under `STORAGE_LOCAL_PATH` (a Docker volume in compose).
`STORAGE_BACKEND=s3` works with AWS S3, Cloudflare R2, MinIO and Backblaze B2. Set `S3_ENDPOINT_URL` for non-AWS providers.

---

## 5. How it works

### Scheduling (no restarts needed)
Celery **beat** fires only one lightweight task, `tick`, every `SCHEDULER_TICK_SECONDS` (default 30 s). Each tick reads
PostgreSQL:
- **Channels** whose poll is due have their uploads feed checked.
- **Detected** jobs are sent to download and render, and to the caption rewrite, side by side. A stage that failed is
  retried from where it broke: three attempts with a growing delay, then the job is marked failed.
- **Ready** jobs are uploaded straight away, subject only to the daily caps. There is no schedule: the pipeline runs
  around the clock. A job with no connected TikTok account waits ("Waiting for account") and goes out once one is connected.
- **Monitoring** jobs whose next checkpoint is due are re-checked.

Because windows, caps and checkpoints are all rows in the database, changes made in the UI apply on the next tick.

### Rules (Settings → Pipeline rules)
Nothing is hardcoded. Every rule is a row in the `pipeline_settings` table, read at job time, so a change applies to
the next job without a restart. Each rule has a global value, and a channel can override most of them (Settings →
Channel overrides). Every change is recorded with who made it and when (Settings → Change history).

| Rule | Default | Notes |
|---|---|---|
| `speed` | 1.08 | 1.0 to 1.5; video and audio are sped up together (`setpts` + `atempo`) |
| `horizontal_flip` | on | `hflip` |
| `keep_audio` | on | off removes the sound |
| `max_duration_seconds` / `min_duration_seconds` | 180 / 5 | short-form = up to the maximum, or any YouTube Short; anything longer is skipped as `long-form` |
| `videos_per_channel_per_day` | 3 | further uploads are held as `skipped_channel_cap` |
| `uploads_per_tiktok_account_per_day` | 7 | global only; an account can also have its own cap. Held as `skipped_account_cap` |
| `approval_required` | on | global only; the **Require approval** switch on the Review Queue page |
| `publish_mode` | inbox | global only; `inbox` or `direct` (see section 3) |
| `cap_reset_timezone` | Asia/Karachi | global only; caps reset at midnight in this timezone |
| `hashtag_count` | 8 | 0 to 15 |
| `fallback_hashtags` | fyp foryou viral trending shorts | used when the AI model fails |
| `file_retention_days` | 7 | days after publishing before the files are deleted |
| `poll_interval_minutes` | 5 | global only |

Caps are counted from the `videos` and `jobs` tables at the moment a video is detected, not kept in counters.

### Editing
The edit is deliberately minimal: a speed-up and a horizontal flip. No cropping, trimming, watermark, text or music.
The output is H.264 / AAC in an MP4 at the source resolution and frame rate. A stream that needs no change is copied,
not re-encoded.

### Caption and approval
The AI model receives the YouTube title, description, tags and channel name, and returns a TikTok caption and hashtags.
If the model fails, the job does **not** fail: the original title and the fallback hashtags are used, the job is flagged
`caption_fallback`, and the operator fixes it in the review queue. With approval on, the job waits in **Review Queue**,
where the rendered video plays inline and the caption, hashtags and TikTok account can be edited. Keyboard: `A` approve,
`E` edit caption, `R` reject, `J`/`K` next and previous. With approval off, the job is published straight away and
appears under **Published**.

### File retention
Downloaded and rendered files are deleted `file_retention_days` after publishing (or after a job was rejected or failed).
The database rows are kept forever as the record of what was published.

### Never posting the same video twice
- The database enforces a unique constraint on `(video_id, tiktok_account_id)`.
- Uploads claim jobs atomically (`UPDATE … WHERE status='ready' AND tiktok_publish_id IS NULL`), so two workers can never upload the same job.
- The TikTok `publish_id` is committed **before** the bytes are sent. A job with a `publish_id` is never initialized again.
- **Retry** first asks TikTok for the status of the existing `publish_id`. If the post went through, monitoring resumes instead of posting again.
- One YouTube video becomes exactly one TikTok post, on the channel's default account (or the least-busy account when it has none).

### 24-hour violation check
After upload, the publish status is polled until TikTok finishes processing. The post is then re-checked at
configurable checkpoints (default **1 h, 6 h, 12 h, 24 h**; *Compliance Audit → Check frequency*). A video is marked
**Violated** when:
- the publish status is `FAILED` with a moderation or spam reason (`spam_risk_*`, violations), or
- the post no longer comes back from `video/query` (TikTok removed or restricted it).

A violation saves the reason, writes an error to the activity log, sends the optional webhook, and shows alerts on the
dashboard, the bell icon and the Compliance Audit page. **Account health** (compliance rate and violation history) is in
*TikTok Accounts → ⋯ → Health & violations*.

> ⚠️ **About removal:** TikTok's public API has **no endpoint to delete a published post**. If TikTok already removed the
> video, ClipRelay records `removed_by_tiktok`. Otherwise, with *Auto-remove violations* on, it records
> `manual_required` and the alert asks you to delete the video in the TikTok app, then click **Mark removed**. The
> removal hook (`integrations/tiktok.py: delete_video`) is in one place, so it can be filled in if TikTok ever exposes such an endpoint.

### Reliability
- Every external call (TikTok, LLM, downloads, webhooks) goes through `integrations/http.py`,
  which retries network errors, 429 and 5xx with **exponential backoff and jitter** (honoring `Retry-After`).
- Celery tasks retry with backoff. Auth errors are not retried; they mark the account as needing reconnection.

### Live updates
Pipeline events are published to Redis and streamed to the browser over **Server-Sent Events** (`/api/events`). The UI
refreshes affected queries as soon as an event arrives, and also polls every 15–60 s as a fallback.

---

## 6. Local development (without Docker)

Requirements: Python 3.12+, Node 20+, FFmpeg, PostgreSQL 14+, Redis 6+.

For a quick local run without Redis and Celery, set `INLINE_WORKER=true` in `.env`: the scheduler and the pipeline then
run inside the API process, and the worker and beat terminals below are not needed. Without FFmpeg on the PATH, the
copy bundled with `pip install imageio-ffmpeg` is used.

```bash
# infrastructure
docker compose up -d postgres redis

# backend
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env   # fill in; set DATABASE_URL/REDIS_URL to localhost, ENVIRONMENT=development
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# worker + scheduler (two more terminals, inside backend/)
celery -A app.workers.celery_app worker -Q default,uploads --loglevel=INFO   # Windows: add --pool=solo
celery -A app.workers.celery_app beat --loglevel=INFO

# frontend
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api to :8000)
```

For OAuth during local development, point a tunnel at the backend (or at the Vite dev server, which proxies `/api`) and set
`PUBLIC_BASE_URL` to the tunnel's HTTPS URL. Set `FRONTEND_URL` to wherever you open the UI.

Interactive API docs are at `http://localhost:8000/api/docs` (also linked from "Need help?" in the sidebar).

---

## 7. Tests

```bash
cd backend
pytest -q
```

The suite (107 tests) uses SQLite and mocks **YouTube, TikTok and the LLM** with `respx`, and stubs FFmpeg and downloads. It
covers:
- auth
- channel lookup, adding a channel, the uploads feed and the push webhook
- detection: one video once, duration and cap checks, and processing a skipped video by hand
- rules: global values, channel overrides and the change history
- download and render with retries, the caption fallback, and inbox mode
- rewriting and manual approval
- uploading with chunk headers, plus the never-twice guarantees
- daily caps and rate-limit deferral
- violation detection, checkpoints and retry safety
- token refresh and expiry
- backoff
- owner/member permissions
- the credential store (DB over `.env`, fallback on removal, encryption, cache busting) and its validators
  (TikTok `client_credentials`, SMTP)
- every LLM adapter (`list_models` and `complete`, including 401/403 → auth error), default and per-template model
  resolution, and the `.env` fallback
- the daily credential check
- every API area

```bash
cd frontend && npm run build   # type-checks and builds the SPA
```

---

## 8. Project structure

```
backend/
  app/
    api/           FastAPI routers (auth, dashboard, channels, tiktok, prompts, jobs, audit, logs, settings, users, events)
    models/        SQLAlchemy 2.0 models
    schemas/       Pydantic v2 request models
    services/      detection, pipeline, rules, sources (download adapter), media (FFmpeg), tokens, prompts, stats, storage, …
    integrations/  youtube.py, tiktok.py, llm.py, http.py (retry/backoff)
    workers/       Celery app + tasks
    cli.py         gen-key / create-user
  alembic/         migrations
  tests/           pytest suite (mocked external APIs)
frontend/
  src/
    pages/         one file per screen from the design
    components/    UI primitives (from the Figma Make code), layout, drawers, modals
    hooks/         auth, theme, live events (SSE)
    api/           typed API client + endpoints
    styles/        additions for interactive states (menus, forms, login) using the design tokens
docs/
  UI_INVENTORY.md  screens, fields, mock→real data map, design tokens, schema, endpoints
  design-reference/  original Figma Make source + reference screenshots (the first design, kept for reference only)
```

## 9. Compliance notes

- Only add channels whose videos you have the right to republish. Nothing in the app checks this; reposting someone
  else's videos invites copyright strikes and TikTok account termination.
- A horizontal flip is a weak originality signal. Expect lower reach on republished videos than on native uploads.
- Respect TikTok's Content Posting guidelines: show creators what is being posted, honor the privacy options that
  `creator_info` returns, and don't exceed posting limits.
- Tokens are encrypted at rest with `ENCRYPTION_KEY`. Back it up, because losing it means every account has to reconnect.
