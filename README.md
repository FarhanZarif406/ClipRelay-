# ClipRelay

ClipRelay watches Instagram Business/Creator accounts you own or manage, picks up new short videos (under 60 seconds),
rewrites their title, caption and hashtags with an LLM using your own prompt templates, publishes them to your TikTok
accounts through the official Content Posting API, and then monitors each post for 24 hours, flagging anything TikTok
rejects or removes.

```
Fetched → Rewriting → (Needs approval) → Ready → Uploading → Posted → Monitoring → Clean / Violated / Failed
```

| Layer | Stack |
|---|---|
| Frontend | React 19 + TypeScript + Vite, React Router, TanStack Query (UI from the Figma Make design, unchanged) |
| API | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, JWT auth |
| Jobs | Celery + Redis. Schedules live in PostgreSQL, so you can change them in the UI without a restart |
| Media | FFmpeg / ffprobe |
| AI | Anthropic or any OpenAI-compatible API (set in `.env`) |
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
# (Settings → API keys / AI models), or put in .env as INSTAGRAM_*, TIKTOK_*, LLM_*, SMTP_*.

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

> **HTTPS is required for OAuth.** Meta and TikTok only redirect to HTTPS URLs that you have registered. In production,
> put the `frontend` service behind your TLS proxy (Caddy, Traefik, a load balancer). For local testing, run a tunnel such as
> `ngrok http 8080` or `cloudflared tunnel --url http://localhost:8080`, and set `PUBLIC_BASE_URL` and `FRONTEND_URL`
> to the tunnel URL.

### Where API keys live

Every third-party credential can be managed from the UI **without a restart**. Values saved in the app are encrypted with
`ENCRYPTION_KEY` and take priority; anything not saved there falls back to `.env`. Each card shows its source
(**Set in app** / **From .env**) and status (**Not configured · From .env · Valid · Unverified · Invalid**).

| Credential | Where in the app | `.env` fallback |
|---|---|---|
| Instagram app ID / secret | Settings → API keys | `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET` |
| TikTok client key / secret | Settings → API keys | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` |
| AI models (any number, one default) | Settings → AI models | `LLM_*` (used only when no model is added) |
| SMTP for email alerts | Settings → Notifications | `SMTP_*` |

Infrastructure settings stay in `.env` only: database, Redis, storage, `SECRET_KEY`, `ENCRYPTION_KEY`, `PUBLIC_BASE_URL`,
and OAuth scopes. Saved credentials and AI models are re-validated daily, and you get a *Token problems* alert if one stops working.

---

## 2. Create the Meta (Instagram) app

ClipRelay uses the **Instagram API with Instagram Login**, which is part of the official Graph API. It can only read
accounts that sign in through your app, so there is no scraping.

1. All source accounts must be **Instagram Professional accounts** (Business or Creator). In the Instagram app, go to
   *Settings → Account type and tools → Switch to professional account*.
2. Go to <https://developers.facebook.com/apps> → **Create app**. Pick the use case
   **"Manage messaging & content on Instagram"** (or *Other → Business*) and finish the wizard.
3. In the app dashboard, open **Instagram → API setup with Instagram login**.
4. Under **"3. Set up Instagram business login"** → **Business login settings**:
   - **OAuth redirect URIs:** `https://YOUR_DOMAIN/api/instagram/oauth/callback`
   - Save.
5. Copy the **Instagram app ID** and **Instagram app secret**. These are shown on the same page and are *not* the Facebook
   App ID. As an owner, paste them into **Settings → API keys → Instagram app** and click **Save**. The card also shows
   the exact redirect URI to register, with a Copy button. (Or set `INSTAGRAM_APP_ID` / `INSTAGRAM_APP_SECRET` in `.env`.)

   Meta has no way to check an Instagram app secret directly, so ClipRelay checks the format, saves it as **Unverified**,
   and marks it **Valid** after the next successful Instagram sign-in. Changing the app while accounts are connected asks
   for confirmation, because those accounts were authorised under the old app and must reconnect.
6. **Permissions:** ClipRelay needs only `instagram_business_basic` (profile + media, including video `media_url`).
7. **Access level:**
   - *Development / Standard access*: works for Instagram accounts that have a role on the app. Add them under
     **App roles → Roles → Instagram Testers**, then accept the invite in Instagram (*Settings → Website permissions → Apps and websites → Tester invites*).
   - *Advanced access* (any account you manage): submit `instagram_business_basic` for **App Review** and complete
     **Business Verification**, then switch the app to **Live**.

**How it works in ClipRelay:** in *Instagram Sources*, click **Add accounts → Authorize with Instagram**. Each account
signs in once. Personal accounts are rejected with instructions to switch to Business or Creator. ClipRelay stores the 60-day long-lived token encrypted (Fernet) and refreshes it automatically before it
expires. In the *Add accounts* box you can then activate or reactivate authorized accounts by username or profile link.
Usernames that have not authorized the app are listed back to you with a sign-in link.

---

## 3. Create the TikTok app

1. Go to <https://developers.tiktok.com> → **Manage apps → Connect an app** (you may need to create an organization first).
2. Fill in the **basic information**: icon, name, category, description, **Terms of Service URL**, **Privacy Policy URL**, and
   **Platforms → Web** with your website URL.
3. **Add products:**
   - **Login Kit.** Set the **Redirect URI** (Web) to `https://YOUR_DOMAIN/api/tiktok/oauth/callback`. It must match exactly.
   - **Content Posting API.** Turn on **Direct Post**.
4. **Scopes.** Request these:
   | Scope | Why |
   |---|---|
   | `user.info.basic` | Account display name and avatar |
   | `video.publish` | Direct-post videos (Content Posting API) |
   | `video.list` | Confirm a published video is still live (violation check) |
   | `user.info.profile` *(optional)* | Show the real `@username`. Add it to `TIKTOK_SCOPES` once approved |
5. Copy the **Client key** and **Client secret** into **Settings → API keys → TikTok app** (owner only) and click
   **Validate** then **Save**. ClipRelay checks them with TikTok's `client_credentials` grant. (Or set
   `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` in `.env`.)
6. **Sandbox and audit.** While the app is in Sandbox, add your TikTok accounts as **target users**. **Unaudited apps can
   only post with `SELF_ONLY` (private) visibility.** ClipRelay picks a privacy level from what TikTok's
   `creator_info` returns, so private posting works automatically. To post publicly, submit the app for TikTok's
   Content Posting **audit**, then turn on **App audited** on the TikTok card. Until then, *TikTok Accounts* shows a reminder
   that posts will be private.
7. **Rate limits.** The video init endpoint allows about 6 requests per minute per user token, and TikTok caps the number of
   API posts per creator per day. ClipRelay enforces a per-account **daily cap** (default 15), a workspace **hourly cap**,
   an optional **random delay**, and exponential backoff on `rate_limit_exceeded` / HTTP 429.

Click **Connect account** in *TikTok Accounts* to run Login Kit OAuth. Access tokens (24 h) are refreshed automatically
with the refresh token (365 days). Accounts are shown as **Expiring** 3 days before the refresh token expires and as
**Expired** after that. Expired accounts need **Reconnect**.

---

## 4. LLM, language gate, storage

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
`{tags}`, `{source}` and `{niche}` (`{original_title}`, `{original_caption}` and `{original_tags}` also work). A part left
empty keeps the original text. Every save creates a version you can restore, and **Test prompt** runs the template
against a real caption. Each template can also pick its own **model** from the dropdown under the editor. The default
option uses the workspace default.

**Language gate** (optional, under *Automation Rules*). The video's title and caption are classified by the AI model
to detect their language. Videos whose language isn't in the allowed list are rejected and logged with a reason.

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
- **Sources** whose `next_run_at` has passed are claimed and fetched. Each source has its own interval
  (15 min / 30 min / 1 h / 6 h or a custom value), plus **Pause/Resume** and **Run now**.
- **Ready** jobs are sent to the upload queue, subject to the active window, weekdays, caps and random delay.
- **Monitoring** jobs whose next checkpoint is due are re-checked.

Because intervals, windows, caps and checkpoints are all rows in the database, changes made in the UI apply on the next tick.

### Fetch and filter
For each run, ClipRelay lists the account's latest media (Graph API), keeps only `VIDEO` items, and **skips media it has
already seen** (unique `source_id + ig_media_id`). It downloads each new video, runs **ffprobe**, and accepts it only if
the duration is **strictly under 60 s**. Rejected videos are stored with a reason ("Duration 72.4s is not under 60s",
"Not Hindi or Urdu", …) and appear on the dashboard and in the logs.

### Rewrite and approval
The source's prompt template (or the workspace default) rewrites the title, caption and hashtags. Each source is set to
**Auto-post** or **Manual approval**. In manual mode, jobs wait in *Needs approval*, and you can edit the text, target
account and privacy in the job drawer before you click **Approve & post**.

### Never posting the same video twice
- The database enforces a unique constraint on `(video_id, tiktok_account_id)`.
- Uploads claim jobs atomically (`UPDATE … WHERE status='ready' AND tiktok_publish_id IS NULL`), so two workers can never upload the same job.
- The TikTok `publish_id` is committed **before** the bytes are sent. A job with a `publish_id` is never initialized again.
- **Retry** first asks TikTok for the status of the existing `publish_id`. If the post went through, monitoring resumes instead of posting again.
- With *one unique account per video* (the default), each video is assigned to the least-loaded linked account.

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
- Every external call (Instagram, TikTok, LLM, downloads, webhooks) goes through `integrations/http.py`,
  which retries network errors, 429 and 5xx with **exponential backoff and jitter** (honoring `Retry-After`).
- Celery tasks retry with backoff. Auth errors are not retried; they mark the account as needing reconnection.
- Each source has a Redis lock, so two runs of the same source never overlap.

### Live updates
Pipeline events are published to Redis and streamed to the browser over **Server-Sent Events** (`/api/events`). The UI
refreshes affected queries as soon as an event arrives, and also polls every 15–60 s as a fallback.

---

## 6. Local development (without Docker)

Requirements: Python 3.12+, Node 20+, FFmpeg, PostgreSQL 14+, Redis 6+.

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
celery -A app.workers.celery_app worker -Q default,fetch,uploads --loglevel=INFO   # Windows: add --pool=solo
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

The suite (88 tests) uses SQLite and mocks **Instagram, TikTok and the LLM** with `respx`, and stubs ffprobe and downloads. It
covers:
- auth
- fetch, duration and language filtering, and skipping already-processed videos
- unique-account assignment
- rewriting and manual approval
- uploading with chunk headers, plus the never-twice guarantees
- daily caps and rate-limit deferral
- violation detection, checkpoints and retry safety
- token refresh and expiry
- backoff
- owner/member permissions
- the credential store (DB over `.env`, fallback on removal, encryption, cache busting) and its validators
  (TikTok `client_credentials`, SMTP)
- rejection of personal Instagram accounts
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
    api/           FastAPI routers (auth, dashboard, sources, tiktok, prompts, jobs, audit, logs, settings, users, events)
    models/        SQLAlchemy 2.0 models
    schemas/       Pydantic v2 request models
    services/      pipeline, scheduler tick, tokens, prompts, stats, storage, media (ffprobe), activity log, notifications
    integrations/  instagram.py, tiktok.py, llm.py, http.py (retry/backoff)
    workers/       Celery app + tasks
    cli.py         gen-key / create-user
  alembic/         migrations
  tests/           pytest suite (mocked external APIs)
frontend/
  src/
    pages/         one file per screen from the design
    components/    UI primitives (from the Figma Make code), layout, drawers, modals
    hooks/         auth, theme, live events (SSE), countdown
    api/           typed API client + endpoints
    styles/        additions for interactive states (menus, forms, login) using the design tokens
docs/
  UI_INVENTORY.md  screens, fields, mock→real data map, design tokens, schema, endpoints
  design-reference/  original Figma Make source + reference screenshots
```

## 9. Compliance notes

- Only connect Instagram accounts that you own or are authorized to manage, and make sure you have the rights to
  republish their content on TikTok.
- Respect TikTok's Content Posting guidelines: show creators what is being posted, honor the privacy options that
  `creator_info` returns, and don't exceed posting limits.
- Tokens are encrypted at rest with `ENCRYPTION_KEY`. Back it up, because losing it means every account has to reconnect.
