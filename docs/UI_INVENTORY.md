# ClipRelay — UI Inventory, Data Model & API

Source: Figma Make project `JvgexabPi2WLl18UkTLSrq` (single-file React app `src/App.tsx` + `src/index.css`).
The original Figma Make source is preserved verbatim in [`design-reference/figma-make-src/`](design-reference/figma-make-src/).

## 0. Assets

| File | Size | Usage in code |
|---|---|---|
| `design-reference/ebdd3b23….png` | 2530×2244 | Full-res screenshot of Dashboard (reference only) |
| `design-reference/806998d2….png` | 2530×3142 | Full-res screenshot of Dashboard incl. lower cards (reference only) |
| `design-reference/4140c414….png` | 317×393 | Thumbnail of Dashboard (reference only) |
| `design-reference/5b3e9147….png` | 317×281 | Thumbnail (reference only) |

`App.tsx` references **no** image files — all icons are inline SVG paths (`iconPaths`), avatars are
initials on CSS gradients, and video thumbnails are CSS gradients (`.video-thumb.v0–v4`). The PNGs are
design references and are not bundled into the app. No temporary Figma URLs exist in code.

## 1. Screens & navigation

The prototype used a `useState<Screen>` switch. The real app uses React Router:

| Sidebar item | Icon | Route | Sidebar adornment |
|---|---|---|---|
| Dashboard | grid | `/` | — |
| Daily Report | logs | `/report` | — |
| Instagram Sources | instagram | `/sources` | — |
| TikTok Accounts | tiktok | `/tiktok` | — |
| Automation Rules | rules | `/rules` | — |
| Prompt Studio | sparkles | `/prompts` | — |
| Jobs Queue | queue | `/jobs` | count badge (`16`) → **pending jobs count** |
| Compliance Audit | shield | `/audit` | red dot → **unacknowledged violations exist** |
| Logs | logs | `/logs` | — |
| Settings | settings | `/settings` | — |
| *(new)* Login | — | `/login` | Not in design; built from existing `.modal`/`.card` tokens |

Shell: fixed sidebar (248px; 216px <1150px; off-canvas drawer <820px with scrim + `mobile-close`),
sticky topbar (menu button, mobile brand, global search with ⌘K, **Run now**, notifications bell
with red dot, theme toggle, profile button). Sidebar bottom: **Monthly usage** card (opens onboarding
wizard) and **Need help?** link.

Overlays: `AddModal` (add Instagram accounts), `JobDrawer` (job detail), `Onboarding` (4-step wizard), `toast`.

## 2. Per-screen inventory

### Dashboard
- **PageHeader** "Good morning, Alex" + **Run now** (primary).
- **Alert banner**: "2 TikTok tokens need attention", detail line, **Review accounts →**, close ✕.
- **KPI grid (5)**: Videos fetched / Published / Pending / Failed / Removed by audit — value, meta delta vs yesterday, 10-bar sparkline, ⋯ icon.
- **Publishing performance** chart: line+area SVG, y labels, 7 x labels, **7 days / 30 days** segmented control.
- **Job status** donut (conic-gradient) + legend (Published/Pending/Failed/Removed) + total.
- **Recent activity** list (icon, tone, title, description, relative time) + **View all →** (→ Logs).
- **Next scheduled run**: HH:MM:SS countdown, interval ("Every 30 minutes"), Active badge, scanning avatars, "6 sources", **View automation rule**.
- **Removed by language filter** table: Video thumb, title, Source, Detected language, Language confidence bar, Removed (relative), Reason. Summary: removed today, acceptance rate, "Hindi + Urdu only" badge.
- **Total uploads by connected account** grid: avatar, handle, uploaded today, lifetime total + **Open daily report →**.

Mock → real: all numbers from `GET /api/dashboard/summary`; chart from `GET /api/dashboard/performance?days=7|30`;
activity from `GET /api/logs?limit=4`; rejected videos from `GET /api/videos?status=rejected&limit=5`.

### Daily Report
- Header + **Export report** (CSV).
- Reporting period strip + "Live report" badge.
- 5 KPI cards: uploaded today, active destinations, lifetime uploads, language accepted (by language), filtered out today.
- **Today's upload pace**: 12 two-hour bins, published (primary) + failed (danger) bars.
- **Uploads by account** table: account, status badge, uploaded today, share bar %, failed, total.

Mock → real: `GET /api/reports/daily?date=YYYY-MM-DD`, `GET /api/reports/daily.csv`.

### Instagram Sources
- Header: "684 / 7,000 connected", **Add accounts**.
- Capacity card: meter, slots available, **Bulk add up to 30**.
- Toolbar: search, **Filters**, "N selected", bulk **Pause / Assign account / Delete**.
- Table: checkbox (all/one), identity (avatar+handle), Last checked, Videos found, Status toggle (Active/Paused), Check interval, Linked TikTok pill, ⋯ row menu. Mobile card variant.
- **AddModal**: method toggle (By username / By profile link), textarea (≤30 entries, counter, over-limit validation), summary (ready count, workspace slots), Cancel / **Connect N accounts**.

Real behaviour (official Graph API only): sources are Instagram Business/Creator accounts authorized via
**Instagram OAuth**. The modal activates authorized accounts by username/link; unauthorized usernames are
reported back with a **Connect with Instagram** OAuth button. Row ⋯ menu: Run now, Edit (interval preset /
custom, approval mode, prompt template, linked TikTok accounts), Delete. Per-source pause/resume = toggle.

### TikTok Accounts
- Header: "N / 20 linked", **Connect account** (→ TikTok Login Kit OAuth).
- Capacity card + meter.
- Account cards: avatar, ⋯, handle, status badge (Active/Expiring/Expired), Posts today `x / cap` meter, linked sources, **Disconnect** or **Reconnect**.
- "Connect another account" dashed card.
- **Unique parallel publishing**: routes (unique video → destination), "Duplicate guard on" badge, same-video protection note.
- OAuth card with 3-step indicator.

Real: `GET /api/tiktok-accounts`, OAuth start/callback, `DELETE`, `POST …/reconnect`, `GET /api/tiktok-accounts/routes-preview`,
⋯ → health & violation history drawer (`GET /api/tiktok-accounts/{id}/health`), daily cap / default privacy edit.

### Automation Rules
- Header: global pause toggle ("Automations live"/"All paused"), primary action.
- Rule card: WHEN (interval, active window, weekdays), IF (source is…, duration under 60 sec), LANGUAGE GATE on title + caption (allowed languages), THEN (prompt, post to), settings grid (Daily cap, Hourly cap, Random delay, Timezone).
- Schedule summary: clock face, active window, next run, estimated posts/day, **Edit schedule**.

Real: the rule card is the workspace **publishing policy** (`GET/PUT /api/settings/policy`); per-source
schedules (preset 15m / 1h / 6h / custom, pause/resume, Run now) are listed below it via `/api/sources`.

### Prompt Studio
- Header: **Version history**, **Save prompt**.
- Prompt list (+ new), active item, Default badge.
- Editor: name/description, enable toggle, tabs Title/Caption/Hashtags, **Insert variable** chips, textarea, footer (word count · model), **Test prompt**.
- Live preview: ORIGINAL → REWRITTEN + hashtags.

Variables: `{title} {caption} {tags} {source} {niche}` (aliases `{original_title} {original_caption} {original_tags}`).
Real: `/api/prompts` CRUD, `/api/prompts/{id}/versions`, `/api/prompts/{id}/test`, `/api/prompts/{id}/default`.

### Jobs Queue
- Header **Process next**; toolbar: search + filters (status, page, account, date).
- Table: thumb, source, original caption, rewritten caption, duration, target, status badge, time, ⋯. Row click → **JobDrawer**.
- JobDrawer: status badge, job #, video preview, before/after, process timeline, **Cancel job / Retry job**.

Real: `/api/jobs` (filters + pagination), `/api/jobs/{id}`, `POST /api/jobs/{id}/approve|retry|cancel`,
`PATCH /api/jobs/{id}` (edit rewritten text during manual approval), `POST /api/jobs/process-next`.

### Compliance Audit
- Audit items: thumb, title, status badge (Checking/Warning/Clear/Violation), "Published to … · Xh ago", checkpoint track (Published/1h/6h/12h/24h), countdown ring.
- Settings card: Auto-remove violations toggle, Check frequency (**Edit**), Notifications toggle, compliance rate.

Real: `GET /api/audit` (monitoring + recent), `GET /api/violations`, `POST /api/violations/{id}/ack`, `PUT /api/settings/audit`.

### Logs
- Header **Export CSV**; search, level filter, service filter.
- Table: timestamp (mono), level badge, service, message, request id, chevron (expand payload).

Real: `GET /api/logs`, `GET /api/logs.csv`.

### Settings
- Sub-nav: API keys / Notifications / Team members / Appearance.
- API keys rows: name, masked key, status badge, **Test connection**.
- Appearance: Dark/Light theme cards.

Real: `GET /api/settings/integrations`, `POST /api/settings/integrations/{name}/test`, `GET/PUT /api/settings/notifications`,
`GET/POST/DELETE /api/users`, theme stored in localStorage.

### Onboarding (opened from Monthly usage)
4 steps: Add source → Connect TikTok → Set AI prompt → Choose schedule. Each step shows real current
state and links to the matching page. **Finish setup** stores `onboarding_completed`.

## 3. Design tokens (from `index.css`)

| Token | Dark | Light |
|---|---|---|
| `--bg` | `#0b0d12` | `#f4f5f8` |
| `--surface` / `-2` / `-3` | `#11141b` / `#141821` / `#191e29` | `#fff` / `#fff` / `#f7f8fa` |
| `--border` / `--border-strong` | `#232938` / `#30384a` | `#e2e5eb` / `#d3d7e0` |
| `--text` / `--muted` / `--muted-2` | `#e6e8ee` / `#8a91a5` / `#666e83` | `#161923` / `#70778a` / `#969cad` |
| `--primary` (+soft) | `#6c5ce7` (14%) | same (10%) |
| `--success` / `--warning` / `--danger` | `#22c55e` / `#f59e0b` / `#ef4444` | same |
| `--shadow` | `0 16px 40px rgba(0,0,0,.24)` | `0 16px 40px rgba(28,34,48,.1)` |

- Font: **Inter** 400/500/600/700 (Google Fonts). Base sizes are compact: 7–13px UI text, 23px page title, 25px KPI.
- Radii: 7–9px controls, 11–12px cards, 14–16px modals. Avatars 9px radius with 5 gradient colours (violet, blue, orange, pink, green, dark).
- Spacing: 12px card grid gap, 30px main padding, 17–20px card padding.
- Breakpoints: 1150px, 820px, 560px.

## 4. Database schema (PostgreSQL)

```
users                (id, email UQ, password_hash, name, workspace_name, is_active, created_at)
settings             (key PK, value JSONB, updated_at)          -- workspace policy, audit, notifications, onboarding
instagram_sources    (id, ig_user_id UQ, username UQ, name, profile_picture_url, color,
                      access_token_enc, token_expires_at, token_refreshed_at,
                      is_active, refresh_interval_minutes, next_run_at, last_checked_at, last_run_status, last_error,
                      approval_mode[auto|manual], prompt_template_id FK, videos_found, created_at, updated_at)
tiktok_accounts      (id, open_id UQ, username, display_name, avatar_url, color,
                      access_token_enc, refresh_token_enc, token_expires_at, refresh_expires_at, scopes,
                      status[active|expiring|expired|revoked], daily_cap, default_privacy, last_error,
                      created_at, updated_at)
source_tiktok_links  (source_id FK, tiktok_account_id FK)  PK(source_id, tiktok_account_id)
prompt_templates     (id, name, description, niche, title_prompt, caption_prompt, hashtags_prompt,
                      is_default, is_enabled, created_at, updated_at)
prompt_template_versions (id, template_id FK, version, snapshot JSONB, created_at)
videos               (id, source_id FK, ig_media_id, permalink, media_url, thumbnail_url, posted_at,
                      original_title, original_caption, original_tags JSONB, duration_sec, width, height,
                      local_path, storage_key, detected_language, language_confidence,
                      status[fetched|accepted|rejected], rejection_reason, created_at)
                      UQ(source_id, ig_media_id)
jobs                 (id, video_id FK, tiktok_account_id FK NULL, prompt_template_id FK NULL,
                      status[fetched|rewriting|awaiting_approval|ready|uploading|posted|monitoring|clean|violated|failed|cancelled],
                      approval_required, rewritten_title, rewritten_caption, rewritten_tags JSONB, privacy_level,
                      tiktok_publish_id, tiktok_post_id, posted_at, monitor_until, next_check_at, check_count,
                      attempts, error, violation_reason, created_at, updated_at)
                      UQ(video_id, tiktok_account_id)   -- never post the same video twice to an account
job_events           (id, job_id FK, status, message, created_at)          -- drawer timeline
violations           (id, job_id FK, tiktok_account_id FK, reason, raw JSONB, removal_status, acknowledged, detected_at)
activity_logs        (id, created_at, level, service, message, request_id, job_id NULL, payload JSONB)
```

## 5. API endpoints (`/api`, JWT bearer unless noted)

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/register` (first user / when enabled), `GET /auth/me` |
| Dashboard | `GET /dashboard/summary`, `GET /dashboard/performance?days=`, `GET /dashboard/nav` |
| Reports | `GET /reports/daily`, `GET /reports/daily.csv` |
| Instagram | `GET /instagram/oauth/start`, `GET /instagram/oauth/callback` (public), `GET /sources`, `POST /sources/bulk`, `PATCH /sources/{id}`, `POST /sources/bulk-update`, `DELETE /sources/{id}`, `POST /sources/{id}/run`, `POST /runs` (all active) |
| TikTok | `GET /tiktok/oauth/start`, `GET /tiktok/oauth/callback` (public), `GET /tiktok-accounts`, `PATCH /tiktok-accounts/{id}`, `DELETE /tiktok-accounts/{id}`, `GET /tiktok-accounts/{id}/health`, `GET /tiktok-accounts/routes-preview` |
| Prompts | `GET/POST /prompts`, `GET/PUT/DELETE /prompts/{id}`, `POST /prompts/{id}/default`, `GET /prompts/{id}/versions`, `POST /prompts/{id}/versions/{v}/restore`, `POST /prompts/test` |
| Jobs | `GET /jobs`, `GET /jobs/{id}`, `PATCH /jobs/{id}`, `POST /jobs/{id}/approve`, `POST /jobs/{id}/retry`, `POST /jobs/{id}/cancel`, `POST /jobs/process-next` |
| Videos | `GET /videos?status=` |
| Audit | `GET /audit`, `GET /violations`, `POST /violations/{id}/ack` |
| Logs | `GET /logs`, `GET /logs.csv` |
| Settings | `GET/PUT /settings/policy`, `GET/PUT /settings/audit`, `GET/PUT /settings/notifications`, `GET /settings/integrations`, `POST /settings/integrations/{name}/test`, `POST /settings/onboarding/complete` |
| Users | `GET /users`, `POST /users`, `DELETE /users/{id}` |
| Live | `GET /events?token=` (Server-Sent Events) |
| Health | `GET /health` (public) |
