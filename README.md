# ClipRelay

ClipRelay watches a set of YouTube channels that publish short-form video and republishes every new upload through
[Buffer](https://buffer.com), with only a light edit in between. When a watched channel posts a new short, ClipRelay detects it, reads its details,
downloads the file, edits it with the member's editing rules (shape, speed, sound, hook text, watermark, music), rewrites the caption,
and then either holds it for one-click approval or publishes it straight away.

YouTube is the only source. Only add channels whose videos you have the right to republish.

```
Detected → Downloading → Rendering → (Writing caption) → (Needs approval) → Ready → Uploading → Scheduled at Buffer
                                                                              → Posted / Failed
```

The caption is written alongside the download and the edit, because it needs only the video's details, not the file.
A video that fails the duration check is never discarded: it is held under **Skipped** with its reason and can be
processed by hand. A usable video that comes over a daily limit is held under **Not Processed** instead: it is detected
and recorded but not downloaded or edited, and **Process now** sends it on anyway.

**Language.** Every account chooses English or Roman Urdu: a board on the Dashboard and an EN / UR switch in the top
bar, kept on the account for every device. In Roman Urdu the text on screen (headings, help, buttons, messages,
placeholders) is swapped from a dictionary as pages draw it (`frontend/src/lib/ur.ts`, with patterns for lines that carry
numbers); menu, section and tab names and page titles stay in English, and so does what people typed. The server
answers its common messages (plans, limits, trial, keys, channels, sign-in) in Roman Urdu too (`backend/app/i18n.py`).
A new English line on a page shows in English until it is added to the dictionary.

**Accounts and plans.** The owner makes a login for every person on the **Accounts** page (owners only); there is no
public sign-up. Each account gets a plan, optionally until a date, and the owner can change its plan, set a new
password, suspend it (no sign-in, its channels are not watched) or delete it, and add or remove its Buffer keys for it.
Under **Plans** the owner makes plans with switches (Podcasts workspace, AI captions, AI hook text, background music,
watermark, own fonts, editing presets, test render) and limits (channels, videos per day, Buffer keys, Buffer accounts across all keys; 0 = no limit) and an auto-check interval: how often the channels are checked
as a backup to push notifications (0 = push notifications only, the lightest; Silver checks hourly). There are five plans, smallest first: Free Trial,
Bronze, Silver, Gold and Platinum. Their prices and limits, as set by the owner (Accounts → Plans changes both at any time; the price shows on each plan card):

| | Free Trial (default) | Bronze | Silver | Gold | Platinum |
|---|---|---|---|---|---|
| Price (owner sets it) | free | PKR 999 | PKR 2,999 | PKR 5,499 | PKR 8,999 |
| Plan length | 4 days | 15 days | 30 days | 30 days | 30 days |
| Videos / podcasts per day | 10 / – | 13 / – | 20 / – | 36 / 3 | 60 / 8 |
| Channels | 50 | 101 | 210 | 315 | 315 |
| Buffer keys / accounts | 1 / 3 (5 places shown) | 1 / 3 | 2 / 6 | 3 / 9 | 5 / 15 |
| Cloud videos | 3 in the trial | 30 in 15 days | 70 in 30 days | 230 in 30 days | 500 in 30 days |
| Editing | Fast (720p) | Fast (720p) | Full (1080p) | Full (1080p) | Full (1080p) |
| AI hook, watermark, own fonts | first day only | yes | yes | yes | yes |
| Music / presets / test render | – | test render | yes | yes | yes |
| Podcasts workspace | look only | look only | look only | yes | yes |
| Auto-check | push only | push only | every 60 min | every 30 min | every 15 min |
| Skipped videos kept | 8 h | 12 h | 24 h | 48 h | 72 h |

Every plan has AI captions (with the member's own key) and PC Helper editing. A switch can be on, off, or on for the
plan's first day only (counted from the day the plan is given). A plan length makes the account stop that many days
after the plan is given; the end date is filled in when the owner picks the plan. Cloud videos are counted over the
plan's length (per calendar month for a plan without one); when they run out, videos wait for the member's PC.
A member whose plan has no Podcasts can open the Podcasts window and look around (a pop-up says what it does and which
plan has it) but cannot add channels or change anything there. The owner can also change any switch or limit for one
account alone (Accounts → Edit): it is marked Custom and can be put back to the plan's.

An option a plan does not include is not hidden: it carries a small tag naming the smallest plan that has it (BRONZE,
SILVER, GOLD); it can be tried on the photo, and saving it is refused. When a trial or a plan ends, the account
can still sign in, but nothing is detected, downloaded, edited or uploaded for it; the Dashboard says so in a large
notice until the owner gives it a plan.
One plan is the default: new accounts get it, and so does an account whose plan has ended. A member sees their plan on
the Dashboard, and what it leaves out; owners are never limited.

**Fast mode.** A plan without *Full editing* makes videos the light way, which a small server handles quickly: 720p,
at most 30 fps, quick encoding (superfast), a square title box, and no sharpness, grain, vignette, highlights or
shadows. Members on such a plan can still try every option on the Editing Rules page and see it on the photo; saving a
paid option is refused with the list of what is for paid members.

**Whose keys.** The cookies file and the proxy are the owner's, for everyone's downloads. Everything else is each
account's own, so the owner does not pay for everyone: its AI models and its YouTube Data API key (on a member's own Integrations page,
which owners do not see) and its Buffer keys. A member's videos only ever use that member's keys: without an AI model of their
own, captions use the original title and the hook shows the title; without a YouTube key, videos are read through
yt-dlp, which needs none. The owner can add or remove any account's keys for it (Accounts → Keys).

**One video at a time.** To keep the server light, each member's videos go through one by one: the next is not
downloaded until the one before has been downloaded, edited, captioned and handed to Buffer, or has reached the review
queue, been paused, failed or been stopped. Each member has their own line, oldest video first; a video left waiting
for a Buffer account does not hold the line.

**A few edits at a time.** Editing is the heavy part, so only `MAX_RENDERS` videos (3 by default) are edited at once
on the whole server, across all members. Downloads have places of their own and carry on meanwhile: a video that is
downloaded while every editing place is taken keeps its file and waits ("Downloaded. Waiting for its turn to be
edited" in Live Status), and takes the next free place without downloading again. A failed edit gives its place up
while it waits to try again, and so does a paused one. Each edit uses `RENDER_THREADS` encoder threads (1 by default)
and, on Linux, runs at a lower priority, so the website, new-video checks and downloads stay quick while it works.
For a 1 vCPU / 4 GB server (Hostinger KVM 1) keep `MAX_RENDERS=3`, `RENDER_THREADS=1`; with more processors raise
`MAX_RENDERS` to about the number of vCPUs. (These places are for edits made on this server; see below.)

### Where videos are edited: the member's PC first, then Google Cloud

**PC Helper.** Each member can run the PC Helper (`helper/`), a small program for Windows and Mac. Connected with a
short code from the website (menu → PC Helper → Connect a PC), it asks the server every few seconds for the member's
next video, downloads it from YouTube over the member's own internet (no cookies or proxy are sent to a PC), edits it
with the very same FFmpeg edit (it carries the backend's `app/services/media.py`), and sends back only the finished
video. The server writes the caption and hands it to Buffer as usual. So the server neither downloads nor edits it, and
YouTube sees a home connection. The member's "one video at a time" line holds. The helper sits next to the clock,
runs below normal priority, keeps the computer awake only while it works, starts with the computer, removes every file
of a video when done, and has a small window (opened from its icon, on 127.0.0.1 only) in English or Roman Urdu.
Its key is stored only as a hash on the server; Disconnect (on the website or in the helper) stops it at once.

**Cloud editing (Google Cloud Run).** When a member's PC has not answered for 3 minutes (off, asleep, offline, paused),
its video moves on: this server downloads it (with its cookies and proxy) and Cloud Run edits it, many at a time,
with the same edit (`cloud-editor/`). Cloud Run fetches the original and the member's files from this server with a
one-job key and sends the finished video back, so this server needs its public HTTPS address. A late result from the
PC is refused: a video is never made twice. Set it up once (owner):

1. Google Cloud: make a project and add billing (Budget alert recommended), install the Google Cloud CLI, `gcloud auth login`.
2. From the ClipRelay folder: `powershell -ExecutionPolicy Bypass -File cloud-editor\deploy.ps1 -Project <project-id>`
   (or `sh cloud-editor/deploy.sh <project-id>`). It builds and starts the editor (no public access), makes the
   `cliprelay-caller` service account with the Cloud Run Invoker role, prints the Cloud Run address and writes
   `cliprelay-cloud-key.json`.
3. ClipRelay → Integrations → Cloud editing: paste the address, upload the key file (then delete it), press Test.

**When nothing can edit.** Integrations → Cloud editing decides what happens to a video when neither a PC nor the cloud
may edit it (no helper on, cloud not set up or not in the plan): **show it as failed** (default; the member presses
Retry) or **edit it on this server** (within `MAX_RENDERS`). Plans have two switches, *PC Helper editing* and
*Cloud editing* (both on for every plan for now). Live Status shows where each video is edited.

**Building the PC Helper.** `cd helper && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt &&
.venv/Scripts/python build.py` makes `dist/ClipRelay-Helper-windows.exe` (a Mac build needs a Mac). The GitHub workflow
*PC Helper* (`.github/workflows/helper.yml`) builds both; a tag `helper-v1.0.0` publishes them as a release. Members get
the program from the PC Helper page in either of two ways: put the built files (`ClipRelay-Helper-windows.exe`,
`ClipRelay-Helper-mac.zip`) in the server's `helper` folder next to the media folder (`/data/helper` on Docker,
`backend/data/helper` locally) and this server hands them out; or put links in `.env` (`HELPER_DOWNLOAD_WINDOWS`,
`HELPER_DOWNLOAD_MAC`), which win over the folder.
On first run the Windows program copies itself to `%LOCALAPPDATA%\Programs\ClipRelay Helper` (no admin rights); a Mac
user opens it once with right-click → Open, since it is not from the App Store. If no Deno or Node.js is on the
computer, the helper fetches Deno once from its official releases (yt-dlp needs it to read YouTube).

**Main switch.** The admin has a main switch at the top of the Dashboard. Off stops everything for every member: no
channel is checked and push notifications are ignored, nothing is downloaded, edited, captioned or handed to Buffer,
and videos on their way are paused where they are. Members do not see the switch, but every page tells them the system
is off. On again, the paused videos carry on, and channels are watched from that moment, so uploads made while it was
off are left alone. Posts already scheduled at Buffer still go out.

**Daily limit.** Each workspace takes only so many new uploads into processing per day. By default it matches the
Buffer accounts: the daily limits of the switched-on accounts added up (10 accounts posting 7 a day take 70 videos; in
Podcasts the sum is divided by the clips per podcast). It can be set by hand instead (rule *Daily limit* → *manual*),
and the manual number also applies while no account is switched on. Once it is used up the Dashboard says so, and new
uploads wait under Not Processed until the count starts again at midnight (rule *Timezone*). A channel's own
*Videos per channel per day* sends its extra uploads to Not Processed too.

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
# (Settings → API keys / AI models), or put in .env as LLM_*, SMTP_*.

docker compose up -d --build
```

> **Downloads and edits run in the `media-worker` service, not in `backend`.** Deploy all of `backend`, `worker`,
> `media-worker` and `beat`: without the media worker, videos are detected but never downloaded or edited, while *Test download* (which runs in `backend`) still
> works. Integrations → Video Source and Live Status warn when the worker has not checked in for three minutes, and
> show what the worker itself sees (yt-dlp version, JavaScript runtime, cookies file). On a host that runs a single
> container, set `INLINE_WORKER=true` so that container does the work itself.
>
> **A server's address is often refused by YouTube** ("Sign in to confirm you're not a bot") where a home connection
> is not. Then upload a fresh cookies file, set a proxy (a residential one works best), or run *Run diagnosis* to see
> which way still works.

Open **http://localhost:8080**. The first visitor creates the **owner** account; after that, registration is closed and
owners add team members under **Settings → Team members**. Owners manage API keys, AI models and the team; members run
the automation and only see whether keys are configured. Owners can promote or demote others (a workspace always keeps
at least one owner). You can also create users from the CLI (the first user created this way becomes the owner):

```bash
docker compose exec backend python -m app.cli create-user you@example.com 'a-strong-password' "Your Name"
```

Services: `postgres`, `redis`, `backend` (FastAPI, which runs migrations on start), `worker` (Celery: new-video
checks, captions, uploads), `media-worker` (Celery in threads: downloads and edits, `MEDIA_CONCURRENCY` places of
which `MAX_RENDERS` may be editing), `beat` (the scheduler tick), and `frontend` (nginx serving the SPA and proxying `/api`).

> **A public HTTPS address is required.** Buffer fetches each clip from this server, and YouTube sends its push
> notifications to it. In production,
> put the `frontend` service behind your TLS proxy (Caddy, Traefik, a load balancer). For local testing, run a tunnel such as
> `ngrok http 8080` or `cloudflared tunnel --url http://localhost:8080`, and set `PUBLIC_BASE_URL` and `FRONTEND_URL`
> to the tunnel URL.

### Integrations page
The **Integrations** page in the app has everything in one place, with step-by-step instructions: the YouTube
Data API key and push notifications, for captions (Gemini), and the status of the downloader (yt-dlp) and the
editor (FFmpeg). Each has a **Test** button: the editor test renders a real two-second clip with the current edit, and
the downloader test reads a real YouTube video. The edit itself is on the **Editing Rules** page.

### Video Source (the downloader)
The **Video Source** card on the Integrations page (admin only) controls how videos are downloaded:

- **Cookies file** — upload a `cookies.txt` (Netscape format, exported while signed in to youtube.com) when YouTube
  answers "Sign in to confirm you're not a bot". It is kept on the server only and never shown again.
- **Proxy** — an optional `http://user:pass@host:port` address, stored encrypted.
- **Player client** — which YouTube app yt-dlp pretends to be.
- **Update now** — upgrades yt-dlp and its JavaScript challenge solver; YouTube changes often and old versions stop
  working. It is also done by itself once a day. The update goes into a folder on the shared `/data` volume, so the
  API and every worker use it, and it survives restarts; a newer image's own yt-dlp wins over an older update.
- **Test download** and **Run diagnosis** — look one video up, or try it with every player client, with and without
  cookies and over IPv6, and say which ways work. Nothing is downloaded and no setting is changed.

When YouTube refuses a download, the other ways of asking are tried by themselves (without cookies, other player
clients, IPv6) and the one that works is remembered for the next video. Full HD is asked for first, measured on the
short side so an upright Short arrives as 1080×1920; when a video has no 1080p the best it does have is taken.

### Where API keys live

Every third-party credential can be managed from the UI **without a restart**. Values saved in the app are encrypted with
`ENCRYPTION_KEY` and take priority; anything not saved there falls back to `.env`. Each card shows its source
(**Set in app** / **From .env**) and status (**Not configured · From .env · Valid · Unverified · Invalid**).

| Credential | Where in the app | `.env` fallback |
|---|---|---|
| YouTube Data API key (optional) | Integrations → YouTube Data API | `YOUTUBE_API_KEY` |
| Buffer API keys (up to ten per member) | Buffer Settings | — |
| AI models (any number, one default) | Settings → AI models | `LLM_*` (used only when no model is added) |
| SMTP for email alerts | Settings → Notifications | `SMTP_*` |

Infrastructure settings stay in `.env` only: database, Redis, storage, `SECRET_KEY`, `ENCRYPTION_KEY`, `PUBLIC_BASE_URL`,
and OAuth scopes. Saved credentials and AI models are re-validated daily, and you get a *Token problems* alert if one stops working.

---

## 2. Channels and detection

Open **Channels**, paste the channel's URL or `@handle` into the box at the top and click **Add channel**. The channel
is looked up, saved and subscribed in one step. Its videos go to the Buffer accounts in turn (or to the one chosen
for a video in the review queue).

- **Only new uploads are republished.** Videos published before the channel was added (or while it was switched off)
  are ignored.
- **Push notifications.** With a public HTTPS address, ClipRelay subscribes each channel to YouTube's push hub
  (PubSubHubbub) at `{address}/api/youtube/webhook`. The address is set in **Integrations → YouTube Push
  Notifications** (*Public base URL*); until one is saved there, `PUBLIC_BASE_URL` from `.env` is used. The same card
  holds the **verify token** (made by itself, replaceable; sent when subscribing and checked when the hub verifies),
  the callback URL to copy, each channel's subscription state, today's notification count, and a button that
  re-subscribes only the channels that failed. Subscriptions expire, so they are renewed before they lapse.
- **Polling fallback.** Every channel's uploads feed is also checked every few minutes (*Polling interval* in
  Settings), so a missed push never means a missed video. On a local install polling is the only method.
- **One video, once.** `videos.youtube_video_id` is unique. YouTube sends a notification again whenever a title or
  description is edited; the repeat finds the existing row and nothing happens.
- **No API key is required.** With a key saved in **Integrations → YouTube Data API** (or `YOUTUBE_API_KEY` in `.env`),
  lookups use the YouTube Data API; without it they read the public channel page and yt-dlp. The card shows only the
  key's last four characters, tests it against Google (one quota unit) and counts the quota ClipRelay has used today.

Downloads use **yt-dlp**, which is outside YouTube's terms of service — YouTube offers no download mechanism, so this is
an accepted condition, not a solved problem. The downloader sits behind an adapter (`backend/app/services/sources.py`,
`VIDEO_SOURCE_ADAPTER`), so it can be replaced, for example by the client supplying the original files.

---

## Podcasts workspace

**For Podcasts** in the sidebar opens a second workspace in its own window (`/podcasts`). It turns long videos into
short clips and is kept apart from Shorts: it has its own channels, its own switch and schedule for each Buffer account, its own rules (**Clip
Rules**), its own review queue, and its own dashboard and daily report. A channel belongs to one
workspace only. API keys (YouTube, AI model) are shared and set once on the Integrations page.

How a podcast becomes clips:

1. A new upload on a podcast channel is detected the same way as a short (push or polling). Uploads shorter than
   *Shortest podcast* (300 s) are held as skipped.
2. The video's subtitles are read and the AI model picks the most engaging moments (3 by default, 30–60 s each).
   Without subtitles or a working AI model, the clips are spread evenly across the video instead.
3. Only the chosen sections are downloaded — the pieces of the stream that cover each clip — so an hour-long video is
   never downloaded whole. If a video has no such stream, the whole video is downloaded once and the clips are cut
   from it.
4. Each clip is edited with the Podcasts workspace's own **Editing Rules** (9:16 crop by default), gets its own caption, and then
   travels the normal pipeline: review queue, approval, and Buffer.

Each clip is one post, so three clips from one podcast take three of an account's posting times.

---

## Publishing through Buffer

Finished clips go out through [Buffer](https://buffer.com). Each member opens
**Buffer Settings** and saves their own Buffer API keys — up to ten, one per Buffer account (Buffer → Settings → API,
with the permissions `account:read`, `posts:read` and `posts:write`). Each key is checked with Buffer before it is
kept, stored encrypted, and only its name and last four characters are ever shown. Keys can be renamed, replaced
and removed one by one; an account two keys both reach is listed once.

- **Accounts.** The social accounts connected in Buffer are listed, each with a switch (*Clips go here*), a
  **Schedule** (time zone, start date, posting times, daily limit) and a **Live status** (uploaded and failed today,
  7 days, 30 days and in all; what is waiting; the latest clips). TikTok accounts are switched on from the start.
  Each workspace (Shorts, Podcasts) has its own switch and schedule for the same account. The accounts are
  grouped by the key that reaches them.
- **How a clip is sent.** An approved clip is handed to Buffer
  as a post scheduled for the account's next free time. The switched-on accounts of all the member's keys take
  turns: each clip goes to the one that has waited longest for a clip (the page marks it *Next turn*), so every
  account gets one before any gets a second. A clip set to one account in the review queue goes there. An account with no
  posting times publishes each clip at once (Buffer's *share now*) when it is its turn, still up to its daily limit
  and not before its start date. A full day is not a dead end: the clip goes out on the next day. Buffer fetches the video from
  `{public base URL}/api/public/clip/{token}/clip.mp4`, a private link that works only until the clip is published,
  so the server needs a public HTTPS address (Integrations → YouTube Push Notifications → *Public base URL*).
- **Afterwards.** The clip shows as *Scheduled at Buffer* (Live Status, Published). A few minutes after its time
  ClipRelay asks Buffer what became of it: published, or failed with Buffer's reason (Retry hands it over afresh).
- **Without a key** a member's finished clips wait ("Waiting for Buffer") and go out once the key is saved.

---

## 3. LLM and storage

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
Failed jobs and key problems are emailed according to the toggles on that tab.

**Storage.** `STORAGE_BACKEND=local` stores files under `STORAGE_LOCAL_PATH` (a Docker volume in compose).
`STORAGE_BACKEND=s3` works with AWS S3, Cloudflare R2, MinIO and Backblaze B2. Set `S3_ENDPOINT_URL` for non-AWS providers.

---

## 4. How it works

### Scheduling (no restarts needed)
Celery **beat** fires only one lightweight task, `tick`, every `SCHEDULER_TICK_SECONDS` (default 30 s). Each tick reads
PostgreSQL:
- **Channels** whose poll is due have their uploads feed checked.
- **Detected** jobs are sent to download and render, and to the caption rewrite, side by side. A stage that failed is
  retried from where it broke: three attempts with a growing delay, then the job is marked failed.
- **Ready** jobs are handed to Buffer straight away, for the account's next free posting time. The pipeline itself
  runs around the clock.
- **Scheduled** jobs whose time has passed are asked about: Buffer says whether the post went out.

Because windows, caps and checkpoints are all rows in the database, changes made in the UI apply on the next tick.

### Rules (Settings → Pipeline rules)
Nothing is hardcoded. Every rule is a row in the `pipeline_settings` table, read at job time, so a change applies to
the next job without a restart. Each rule has a global value, and a channel can override most of them (Settings →
Channel overrides). Every change is recorded with who made it and when (Settings → Change history).

| Rule | Default | Notes |
|---|---|---|
| `max_duration_seconds` / `min_duration_seconds` | 180 / 5 | short-form = up to the maximum, or any YouTube Short; anything longer is skipped as `long-form` |
| `videos_per_channel_per_day` | 3 | further uploads are held under Not Processed as `skipped_channel_cap` |
| `daily_limit_mode` / `daily_limit` | match accounts / 15 | global only; uploads taken per day across all channels; further ones are held under Not Processed as `skipped_daily_limit` |
| `approval_required` | on | global only; the **Require approval** switch on the Review Queue page |
| `cap_reset_timezone` | Asia/Karachi | global only; caps reset at midnight in this timezone |
| `hashtag_count` | 8 | 0 to 15 |
| `fallback_hashtags` | fyp foryou viral trending shorts | used when the AI model fails |
| `file_retention_days` | 1 | days after publishing before the edited file is deleted (1 to 3) |
| `poll_interval_minutes` | 5 | global only |

Caps are counted from the `videos` and `jobs` tables at the moment a video is detected, not kept in counters.

### Editing Rules
Each member has their own editing rules in each workspace (**Editing Rules**, in Shorts and in Podcasts), in seven
sections beside a live preview on a sample photo:

- **Frame:** aspect ratio (9:16, 4:5, 3:4, 2:3, 1:1, 4:3, 3:2, 16:9, 21:9), crop position (left, centre, right), zoom
  (100–130%) and horizontal flip. A wider source has its sides cropped; one of the same shape (a Short in a 9:16 clip)
  is kept whole.
- **Adjust:** light (brightness, contrast, highlights, shadows), colour (saturation, warmth, tint, hue) and detail
  (sharpness, vignette, grain). Everything at 0 leaves the picture as it is.
- **Speed:** 1.00–1.50x, with voices kept at their normal pitch or not.
- **Quality:** Full HD or HD, frame rate, encoder preset and CRF, with an estimated file size.
- **Audio:** keep the original sound, normalise loudness, audio bitrate.
- **Background music:** the member's own library (MP3, M4A, WAV, OGG); each clip gets the next track, at a set volume.
- **Hook text:** a line written by the AI model from the title, or the title itself, for a set number of seconds; font
  (bold by default, or the member's own TTF/OTF), size, colour, outline colour and width, position; and an optional
  rounded background with its own colour, opacity, size, roundness and position.
- **Watermark:** the member's own PNG, in one of nine places, with opacity and size.

The rules can be saved as **presets**, and each channel can be given one (*Per-channel rules*); other channels use the
Default rules. **Test on a real video** renders the first 20 seconds of a YouTube video with the rules on screen.
Hook text needs a bold font on the server: one of the usual system fonts is used, or set `FONT_FILE`. The output is
H.264 / AAC in an MP4.

### Caption and approval
The AI model receives the YouTube title, description, tags and channel name, and returns a caption and hashtags.
If the model fails, the job does **not** fail: the original title and the fallback hashtags are used, the job is flagged
`caption_fallback`, and the operator fixes it in the review queue. With approval on, the job waits in **Review Queue**,
where the rendered video plays inline and the caption, hashtags and the account it goes to can be edited. Keyboard: `A` approve,
`E` edit caption, `R` reject, `J`/`K` next and previous. With approval off, the job is published straight away and
appears under **Published**.

### File retention
The downloaded original is deleted as soon as the edit is made. The edited file is deleted `file_retention_days` (1 to
3 days) after publishing, or after a job was rejected or failed. Downloads never exceed the plan's quality: 720p in Fast
mode, Full HD otherwise (never 1440p or 4K). Logs and the videos' timelines are kept for 60 days. A test render covers 15
seconds of a video, and each member can run 5 a day.
The database rows are kept forever as the record of what was published.

### Never posting the same video twice
- One YouTube video becomes exactly one job, and one job becomes one post.
- A job is claimed atomically (`UPDATE … WHERE status='ready' AND buffer_post_id IS NULL`), so two workers can never hand
  over the same job, and a job that already has a Buffer post is never handed over again.
- **Retry** on a failed post hands the clip to Buffer afresh, as a new post.

### Reliability
- Every external call (YouTube, LLM, webhooks) goes through `integrations/http.py`,
  which retries network errors, 429 and 5xx with **exponential backoff and jitter** (honoring `Retry-After`).
- Celery tasks retry with backoff.

### Live updates
Pipeline events are published to Redis and streamed to the browser over **Server-Sent Events** (`/api/events`). The UI
refreshes affected queries as soon as an event arrives, and also polls every 15–60 s as a fallback.

---

## 5. Local development (without Docker)

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
celery -A app.workers.celery_app worker -Q media --pool threads --concurrency 6 -n media@%h --loglevel=INFO
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

## 6. Tests

```bash
cd backend
pytest -q
```

The suite (115 tests) uses SQLite and mocks **YouTube, Buffer and the LLM** with `respx`, and stubs FFmpeg and downloads. It
covers:
- auth
- channel lookup, adding a channel, the uploads feed and the push webhook
- detection: one video once, duration and cap checks, and processing a skipped video by hand
- rules: global values, channel overrides and the change history
- download and render with retries, and the caption fallback
- rewriting and manual approval
- Buffer: the key, accounts and schedules, posting times, handing a clip over, and what became of it
- backoff
- owner/member permissions
- the credential store (DB over `.env`, fallback on removal, encryption, cache busting) and its validators
  (YouTube, SMTP)
- every LLM adapter (`list_models` and `complete`, including 401/403 → auth error), default and per-template model
  resolution, and the `.env` fallback
- the daily credential check
- every API area

```bash
cd frontend && npm run build   # type-checks and builds the SPA
```

---

## 7. Project structure

```
backend/
  app/
    api/           FastAPI routers (auth, dashboard, channels, buffer, integrations, prompts, jobs, logs, settings, users, events)
    models/        SQLAlchemy 2.0 models
    schemas/       Pydantic v2 request models
    services/      detection, pipeline, rules, sources (download adapter), media (FFmpeg), buffer, slots, prompts, stats, storage, …
    integrations/  youtube.py, buffer.py, llm.py, http.py (retry/backoff)
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

## 8. Notes on republishing

- Only add channels whose videos you have the right to republish. Nothing in the app checks this; reposting someone
  else's videos invites copyright strikes and the termination of the accounts it is posted to.
- A horizontal flip is a weak originality signal. Expect lower reach on republished videos than on native uploads.
- Respect the posting rules of the networks your Buffer accounts publish to, and keep each account's daily limit modest.
- API keys are encrypted at rest with `ENCRYPTION_KEY`. Back it up, because losing it means every key has to be entered again.
