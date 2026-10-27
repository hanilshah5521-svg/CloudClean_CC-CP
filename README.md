# CloudClean

**Intelligent Google Storage Optimization & Lifecycle Management Platform**

CloudClean connects to your Google accounts, analyzes Drive file metadata (Drive, Gmail and Photos
share one 15 GB quota per account), finds duplicates, compression and archiving opportunities, and
lets you safely recover storage — with every recommendation explained and every destructive action
requiring your explicit confirmation. Several Google accounts (say a personal and a college one) can
be linked into one profile: each is scanned, you switch between them from the profile menu, and
files stored in more than one account are found as **cross-account duplicates**. Every finding links
straight to the file (or the Trash) in Google Drive for review, and the UI has light and dark themes.
It runs entirely on free, open-source
software; the only paid resource involved is optionally your own Google Cloud project (free tier is
enough) if you connect a real Drive. **Demo Mode needs neither.**

> **Testing the project?** See [TESTING.md](TESTING.md): one-click start scripts and a test
> checklist. To build a shareable zip for a tester, run `python scripts/make_share_zip.py`
> (it writes `share/CloudClean-test-package.zip` and never includes `.env` or local data).

## Contents

- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Quick start (Demo Mode)](#quick-start-demo-mode)
- [Connecting a real Google Drive](#connecting-a-real-google-drive)
- [Multiple Google accounts](#multiple-google-accounts)
- [Running with Docker](#running-with-docker)
- [Background worker, video compression & rules](#background-worker-video-compression--rules)
- [Testing](#testing)
- [How it works](#how-it-works)
- [Security & privacy](#security--privacy)
- [Known limitations](#known-limitations)

## Architecture

```
cloudclean/
  backend/            FastAPI app
    app/
      api/routes/      HTTP endpoints (auth, accounts, storage, files, analysis, analytics,
                        recommendations, duplicates, compression, archive, organize, history,
                        settings, jobs, rules; gmail and s3 are API-only, with no page in the UI)
      core/            config, database session
      models/          SQLAlchemy ORM models
      schemas/         Pydantic request/response schemas
      integrations/    Google OAuth + Drive API v3 client, Demo Mode data generator
      analyzers/       duplicate detection, large-file / inactive-file rules, compression estimates
      recommendations/ the rule-based RecommendationEngine + Optimization Score
      compression/      real Pillow/pikepdf/zipfile compression, ffmpeg video re-encoding
      services/        orchestration: drive_service (analyze), account_service (linked accounts,
                        cross-account duplicates), optimization_service (compress/
                        trash/archive/restore), video_service (compress_video job), job_service
                        (the job queue), rules_service (auto-compression rules), storage_service
      security/        session auth dependency
      utils/           MIME classification, job scratch directories
      worker.py        the background worker: `python -m app.worker`
    tests/             pytest — analyzers, engine, real compression round-trips, full API flow
    data/storage_plans.json   editable Google One pricing config
  frontend/           React + Vite + Tailwind + Recharts SPA
    src/pages/         Connect, Dashboard, Accounts, Duplicates, Organize, Compression,
                        History, Analytics, Settings
    src/components/shell/  sidebar, top bar and the profile menu (account switcher, Demo Mode,
                        theme, sign out)
  docker/             Dockerfiles (the backend image also runs the worker)
  docker-compose.yml
  .env.example
```

**Pipeline:** Google Drive → metadata collector (paginated, no file downloads) → classification →
duplicate detection → large/inactive-file analysis → compression-potential estimate → rule-based
RecommendationEngine → SQLite cache → dashboard. Analysis (and anything else slow) runs as a
**background job**: the API queues it, the worker process runs it, the UI polls its progress.
Nothing changes on your Drive until you click an action and confirm it — or turn on auto-apply
for one of your own auto-compression rules.

## Technology stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite + Tailwind + Recharts | fast dev loop, no paid UI kit |
| Backend | FastAPI + Uvicorn | async-capable, typed, minimal |
| Auth | Google OAuth 2.0 (`google-auth-oauthlib`) + Starlette signed-cookie sessions | no paid auth platform, no custom crypto |
| Drive | Google Drive API v3 (`google-api-python-client`) | official, free within quota |
| DB | SQLite + SQLAlchemy | zero-config, file-based |
| Images | Pillow | real JPEG/PNG/WebP re-encoding |
| PDF | pikepdf (qpdf bindings) | real stream compression, content-preserving |
| Archives | `zipfile` (stdlib) | no dependency needed |
| Video | ffmpeg (libx264 + AAC) and ffprobe, run as subprocesses | the standard free encoder; streams from disk |
| Background jobs | a `jobs` table in SQLite + one worker process (`python -m app.worker`) | fits one small free-tier VM; no broker to run |
| Tests | pytest + FastAPI TestClient | no paid CI service required |

**Explicitly not used, and why:** no OpenAI/Anthropic/Gemini API (the recommendation engine is
rule-based and explainable by design, not a model call); no pandas/numpy/scikit-learn (every
computation here is arithmetic over a few thousand rows — pulling in a dataframe library would be
pure overhead); no Celery/Redis (the job queue is a database table claimed with an atomic
`UPDATE … WHERE status='queued'` — one worker process next to SQLite is all a single small VM needs);
no Playwright suite (the flows are verified with pytest + FastAPI's TestClient
end-to-end, and manually in a real browser — see [Testing](#testing)).

## Quick start (Demo Mode)

No Google account, no API keys, no cloud project. This is the easiest way to see CloudClean work.

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

```bash
# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**, click **Try Demo Mode**, then **Run Scan**. Everything after
that — duplicates, compression (including videos), archiving, organizing, auto-compression rules,
history, restore, and extra linked accounts (profile menu → **Add a simulated account**, up to three
in all) — operates on simulated data end to end, clearly labeled "DEMO MODE" throughout the UI.
Links into Google Drive are disabled in Demo Mode, since the files don't exist there.
Demo Mode doesn't need the background worker: its jobs only simulate, so the API runs them inline.

## Connecting a real Google Drive

### 1. Create a Google Cloud project
Go to [console.cloud.google.com](https://console.cloud.google.com) → select or create a project.

### 2. Enable the Drive API
**APIs & Services → Library** → search "Google Drive API" → **Enable**.

### 3. Configure the OAuth consent screen
**APIs & Services → OAuth consent screen** → choose **External** (or Internal for a Workspace org) →
fill in app name, support email → add scopes `.../auth/drive`, `.../auth/userinfo.email`,
`.../auth/userinfo.profile` (plus `.../auth/gmail.modify` only if you set `GMAIL_ENABLED=true`) →
add every Google account you'll sign in or link with under **Test users** if the app is in Testing mode.

### 4. Create an OAuth client
**APIs & Services → Credentials → Create Credentials → OAuth client ID** → Application type
**Web application** → add an **Authorized redirect URI**:
```
http://localhost:8000/auth/callback
```

### 5. Copy credentials into `.env`
```bash
cp .env.example .env
```
Fill in `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from the credential you just created.
`SECRET_KEY` can stay blank locally (a random key is generated once into `backend/data/.secret_key`);
for any deployment set it explicitly, and set `COOKIE_SECURE=true` when serving over HTTPS:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
`GMAIL_ENABLED` is `false` by default, so only the Drive permission is requested (see
[Gmail and Photos](#gmail-and-photos)).

Restart the backend. The Connect page's "Connect Google Drive" button (also in the profile menu at
the top right and under **Settings → Account**) now redirects to Google's real consent screen.

### 6. Start the background worker
With a real account, analysis, video compression and large undos run in the worker. Start it in a
third terminal (same virtualenv, from `backend/`):
```bash
python -m app.worker
```
Without it, jobs wait in the queue and the UI says that no worker is running.

**Scope note:** CloudClean requests the broad `drive` scope, not `drive.file`, because it needs to
read metadata and move to Trash files it did not itself create — that is the whole point of the
product. It is a *restricted* scope: fine for an app in Testing mode with listed test users, but a
public launch needs Google's verification. With `GMAIL_ENABLED=true`, `gmail.modify` is requested
too (never the `mail.google.com` scope, which would allow permanent deletion); users can untick it on
the consent screen and Drive analysis keeps working without it.

## Multiple Google accounts

Many people spread their files over several free 15 GB accounts and lose track of what is where.
CloudClean links them into one **profile**:

- **Adding an account:** profile menu (top right) → **Add Google account**. Google's account chooser
  opens (`prompt=select_account consent`), and the account you pick is linked to your profile while
  you keep working in the current one. Signing in later with *any* linked account opens the same
  profile. In Demo Mode the same button adds a **simulated account** (a "college" and a "personal"
  Drive holding copies of some of the main account's files), up to three accounts in all.
- **Switching:** the profile menu lists every linked account; picking one switches the whole app —
  Dashboard, Duplicates, Compression, History — to that account's data. Each account keeps its own
  scan, settings and History.
- **Scanning:** **Run Scan** scans every linked account (one background job each) and the progress
  bar shows them together.
- **Accounts page:** used and free space per account and across all of them (free space isn't
  poolable — each account is still capped at its own 15 GB), plus **copies across accounts**: files
  with the same content checksum and size stored in two or more accounts, filterable by account.
  CloudClean suggests keeping the copy in the account with the most free space; you can pick another,
  and removing the others moves them to *their own account's* Trash, recorded in that account's
  History, where Restore works as usual.
- **Removing an account** from the profile (Accounts page or Settings → Account) only unlinks it and
  deletes CloudClean's cached data for it — nothing in that Google account is touched. You can't
  remove the account you're currently working in; switch away first.

Links into Drive carry `?authuser=<email>`, so a file in a linked account opens in that account
even when the browser's default Google account is a different one.

## Running with Docker

```bash
cp .env.example .env   # fill in Google credentials, or leave blank for Demo Mode only
docker-compose up --build
```
Frontend on http://localhost:5173, backend on http://localhost:8000, plus a `worker` container
(the same image running `python -m app.worker`, with ffmpeg installed). SQLite data persists in a
named Docker volume shared by the API and the worker. Run exactly one worker.

## Background worker, video compression & rules

### Background jobs
Slow work never runs inside an HTTP request. `POST /api/analyze`, `POST /api/compression/{id}/video`,
`POST /api/rules/run` and Undo of a large compression create a row in the `jobs` table (`queued`)
and return it; the page then polls `GET /api/jobs/{id}` (owner only) for `progress` (0–100), the
current step, and finally `result` or `error`.

The worker (`python -m app.worker`) claims the oldest queued job with one atomic
`UPDATE jobs SET status='running' WHERE id=? AND status='queued'`, so a job can never run twice, and
runs one job at a time. SQLite runs in WAL mode so the API keeps answering progress polls while the
worker writes. A heartbeat row lets the UI tell "queued, worker busy" from "no worker running". If
the worker is killed mid-job, the job is marked **failed** (not silently retried) when it next starts,
leftover temp files are deleted, and a half-finished upload is flagged in History with the revision
holding the original. `python -m app.worker --once` runs whatever is queued and exits (handy for cron
or debugging).

**Demo Mode** jobs run **inline in the API process** as soon as they're created (they only simulate,
in well under a second), so Demo Mode needs no worker and `POST /api/analyze` returns the finished
job with the analysis summary.

### Video compression
Videos are estimated from metadata alone: Drive reports each video's width, height and duration
(`videoMediaMetadata`), so CloudClean knows its **bitrate** without downloading it, and compares it
with what H.264 at CRF ~27 typically needs at that resolution (≈2.5 Mbps at 720p, 4.5 at 1080p, 16 at
4K, plus 128 kbps audio). Phone footage (often 15–50 Mbps) shows big savings; screen recordings and
already-efficient files aren't suggested at all. Only MP4, MOV and MKV videos over 50 MB are
candidates. Clicking **Compress video** on the Compression page queues a job that:

1. records the file's current Drive revision (the original),
2. **stream-downloads** the video to a temp file (16 MB chunks — never the whole file in memory),
3. re-encodes it with ffmpeg: `libx264 -crf 27 -preset medium`, AAC 128 kbps, same resolution, same
   container, `-movflags +faststart`, at below-normal CPU priority,
4. verifies the result with ffprobe (duration within 1 s, video and every audio track present), and
   keeps the original if the saving is under your minimum-saving %,
5. uploads it with a **resumable** `files.update` as a new revision of the **same file** (same ID,
   link, sharing and folder) and verifies Drive accepted it,
6. deletes the temp files, whatever happened.

HDR, 10-bit and subtitled videos are left alone (re-encoding them to 8-bit H.264 would visibly lose
something). **Undo** in History restores the original revision — for videos that's another
background job, since it streams the original back. Drive keeps old revisions of uploaded files for
about 30 days, so Undo works for about that long.

**Installing ffmpeg** (the worker needs `ffmpeg` and `ffprobe`; Docker images already have them):

```bash
winget install ffmpeg
```
On Windows, winget puts ffmpeg on `PATH` only for terminals opened afterwards; CloudClean also looks in
winget's install folder, so a restart isn't required. Elsewhere: `sudo apt install ffmpeg` (Debian/
Ubuntu) or `brew install ffmpeg` (macOS). Or point `FFMPEG_PATH` / `FFPROBE_PATH` at the binaries.

Settings (`.env`): `VIDEO_CRF` (27), `VIDEO_PRESET` (medium), `VIDEO_THREADS` (2), `VIDEO_MAX_MB`
(4096), `JOB_TEMP_DIR` (OS temp dir). The worker needs about twice the video's size in free disk.

**On a free-tier VM** (1 vCPU / 1 GB RAM, e.g. t2.micro/t3.micro): keep `VIDEO_THREADS` at 1–2, add a
1–2 GB swap file, and expect 1080p to encode slower than real time on a single small vCPU (a
10-minute video can take well over ten minutes); `VIDEO_MAX_MB` bounds the disk a single job can use. The API stays responsive because
ffmpeg runs at lower priority in the separate worker process.

### Auto-compression rules
**Settings → Auto-compression rules** lets each user define rules such as *"compress videos larger
than 200 MB not modified in 90 days"* (also for images and PDFs). The worker evaluates every user's
enabled rules once a day at `RULES_HOUR_UTC` (default 21:00 UTC = 02:30 IST), refreshing Drive
metadata first if the last analysis is older than 20 hours; **Run rules now** does it immediately.
Matches become **suggestions** on the Compression page (Compress / Dismiss). Only an estimated
saving above your minimum counts as a match; dismissed files and files whose compression you undid
are never suggested again.

Nothing is compressed automatically unless you tick **Auto-apply** on that rule (off by default, with
a confirmation). Even then, at most `RULES_MAX_AUTO_APPLY` (3) compressions start per night, and each
job re-checks the file against Drive's live metadata first — a file edited since the rule matched it
is skipped. Every auto-applied compression appears in History with Undo, like a manual one.

## Testing

```bash
cd backend
source venv/bin/activate
pytest -v
```
(Windows: `venv\Scripts\python -m pytest -v`.)

The background-job tests cover atomic claiming, progress written while a job runs, failure
bookkeeping and rollback, crash recovery, the worker loop, `POST /api/analyze` as a job (inline in
Demo Mode, queued-then-run-by-the-worker for a real account) and the owner-only job endpoint. The
video tests run the job against a fake Drive that keeps content on disk and offers only the streaming
methods: with ffmpeg installed they generate a 2-second clip, re-encode it, check the new revision
with ffprobe and Undo it back to the original bytes (skipped without ffmpeg); the rest (failed
upload, HDR skip, temp-file cleanup, undo) use a stand-in encoder and always run. Rule tests cover
suggestions, auto-apply (off by default, capped), never redoing an undone compression, the live
re-check and the nightly schedule. The multi-account tests cover linking simulated and real
(mocked OAuth) accounts, scanning each, switching, removing, cross-account duplicates (detection,
the recommended copy to keep, the account filter, removal recorded in the owning account's History)
and isolation between profiles.

The original suite covers: duplicate detection (all three match levels), inactivity/size-tier rules,
compression-potential estimation, the recommendation engine (explainability + score bounds), *real*
compression round-trips (a JPEG is actually re-encoded and re-decoded, a PDF's page count survives
optimization, ZIP entries are sanitized against path traversal), a full integration test that
drives the actual HTTP API through Connect → Analyze → Recommend → Optimize → Refresh against Demo
Mode, plus checksum/version duplicate rules, one-saving-per-file accounting, undo of every action
type, partial-failure bookkeeping (with a fake Drive client), in-place compression + revision
restore, Gmail trash/restore, OAuth state/PKCE, token encryption, token-refresh persistence and the
SQLite column auto-migration.

The frontend was verified manually in-browser (not scripted with Playwright — see stack rationale
above): Demo Mode connect → analyze → view score/recommendations → confirm a duplicate trash → run
a real PDF compression → verify the byte counts in History → browse Analytics → archive inactive
files from the Dashboard recommendation; for multiple accounts: add two simulated accounts, scan all,
remove a cross-account copy and find it in the owning account's History; and, for background jobs: analyze from the Dashboard, compress a video
from the Compression page, add a rule in Settings (auto-apply asks for confirmation), run it, apply
one of its suggestions and Undo the compression from History.

## How it works

### Duplicate detection
Three levels: (1) **content checksum** — Drive returns `sha256Checksum`/`md5Checksum` for every
binary file as plain metadata, so exact copies are found with no downloads; (2) identical size +
normalized filename + extension, only for files Drive gives no checksum for (Docs/Sheets/Slides);
(3) same normalized name, *different* content — these are **versions** (`notes.pdf` /
`notes_final.pdf`), shown last for review, never counted as recoverable space, and the API refuses
to trash them unless you tick "I've compared them". Folders, shortcuts and generic names
("Untitled document", "scan", "image"…) are never grouped. Only files you own are analyzed —
files shared with you don't use your quota. CloudClean recommends keeping the most recently
modified copy but never trashes anything until you confirm — you can pick a different file to keep.

### Compression
Real, on-demand, not simulated (outside Demo Mode). JPEG is re-encoded with Pillow at a configurable
quality, keeping its chroma subsampling; PNG is losslessly re-compressed; WebP is re-encoded
(lossless WebP stays lossless); animated images and JPEGs holding a second image (an HDR gain map
or depth map) are skipped, because re-encoding would keep only the first frame. PDF is optimized
losslessly with pikepdf (streams re-compressed, unused objects dropped; images, fonts and text
untouched). The original is downloaded and compressed in memory,
then uploaded **as a new version of the same file** (`files.update`), so the file keeps its ID,
share links, permissions and folder. The upload is verified (new revision ID and size), and Drive
keeps the original bytes as the previous version for about 30 days — **Undo** in History restores
them. A file CloudClean already compressed is never suggested again (re-encoding a JPEG twice only
loses more quality). If the saving isn't meaningful (below your configured minimum-saving %),
nothing is uploaded and the original is left alone. Videos follow the same pattern but are streamed
through disk by the background worker — see [Video compression](#video-compression).

### Gmail and Photos
Drive, Gmail and Photos share one quota. The Dashboard splits usage into Drive, Drive Trash (which
still counts until emptied) and Gmail + Photos (Google reports those two only as one number).
CloudClean itself works on Drive only. Gmail cleanup is off by default (`GMAIL_ENABLED=false`) and
has no page in the UI; with `GMAIL_ENABLED=true` the backend still requests `gmail.modify`, lists
large messages and can move them to Gmail's Trash through the `/api/gmail` endpoints. Google Photos
can't be cleaned up by third-party apps since Google restricted the Photos Library API in March 2025.

### Reviewing in Google Drive
Duplicates, compression candidates, cross-account copies and Trash notices each have **Open in
Drive** / **Show in its Drive folder** links, so you can look at a file in Drive before acting on it, and an
**Open Drive Trash** link after moving files there.

### Organizing
The Organize page groups loose files that follow one naming pattern (`budget_1…10.xlsx`) and moves
each group into a folder of its own; links don't change, and Undo in History moves them back.

### Storage savings calculation
The Optimization Score (0–100) is a fully transparent deduction from 100: each inefficiency factor
(duplicate storage, compressible storage, inactive storage, large-file concentration) is capped and
weighted by documented constants in `app/recommendations/engine.py` — there is no model inference
step. Each file's bytes count toward at most one saving (duplicate removal, then compression, then
archiving), so "potentially recoverable" never double counts. Archive estimates are per file type:
JPEG, video, audio and existing archives are excluded because zipping them saves next to nothing. Pricing shown in the Savings Calculator comes from `backend/data/storage_plans.json`
(editable without a code change) and is always labeled an **"effective equivalent cost"**
(`plan price ÷ additional included GB`) — never presented as Google's actual per-GB billing rate,
which doesn't exist.

### Recommendation engine
`app/recommendations/engine.py`'s `RecommendationEngine` runs `analyze_compression`,
`analyze_large_file`, `analyze_duplicate`, and `analyze_archive_candidates` over your file metadata
and returns structured recommendations, each carrying a `reason` string built from the actual
numbers (file type, current size, estimated saving, months since last modified, confidence label) —
never a generic message.

## Security & privacy

- OAuth credentials only ever live in environment variables, never in frontend code or git history.
- The OAuth flow uses a `state` value checked on callback (CSRF / login-forgery protection) and
  PKCE; both are kept in the signed session cookie between redirect and callback.
- Google access and refresh tokens are **encrypted at rest** (Fernet) in the database, and a
  refreshed access token is saved back so it isn't refreshed on every request.
- There is no hard-coded fallback secret: a random `SECRET_KEY` is generated per installation if
  none is set. `COOKIE_SECURE=true` marks the session cookie HTTPS-only for deployments.
- Sessions are Starlette's signed-cookie `SessionMiddleware` (itsdangerous) with `SameSite=Lax`,
  giving baseline CSRF protection for free (a cross-site POST doesn't carry the cookie).
- **File content only touches disk for videos.** Images, PDFs and ZIP archives are downloaded,
  compressed and uploaded in memory (`io.BytesIO`). Videos (and Undo of large compressions) are too
  big for memory, so the worker streams them into a private `cloudclean-job-*` temp directory that
  is deleted when the job ends — success or failure — and swept on worker start after a crash.
- ZIP archive entry names are sanitized (path separators stripped) before being written, so a
  crafted filename can't escape the archive on extraction.
- Unhandled exceptions are logged server-side and returned to the client as a generic message —
  stack traces never reach the browser.
- Nothing is ever permanently deleted by CloudClean. The most destructive action it takes is moving
  a file (or email) to Drive's (or Gmail's) own Trash; every trash, archive and compression can be
  undone from History.
- Multi-file actions record each file as it completes, so a failure halfway through never leaves
  Drive and History disagreeing about what was trashed.

## Known limitations

- Google Drive storage is shared with Gmail and Google Photos — CloudClean only sees and affects
  Drive files.
- Not every file can be meaningfully compressed; already-compressed formats (zip, mp3, etc.) are
  explicitly flagged rather than falsely promised savings. Videos are only suggested when their
  bitrate is well above what H.264 needs, and the real saving is measured before anything is uploaded.
- Video re-encoding is lossy (CRF 27 is visually close, not identical). HDR, 10-bit and subtitled
  videos are skipped; extra data tracks (e.g. GoPro telemetry) are not carried over. Drive only keeps
  the original revision for about 30 days, so Undo is only possible for that long.
- Google Workspace-native files (Docs/Sheets/Slides) have no binary size and can't be compressed
  like ordinary files.
- Compression estimates (shown before you click Compress) can differ from the actual result — the
  UI always distinguishes "estimated" from "actual" and never presents one as the other.
- Moving a file to Trash doesn't reclaim quota until the Trash is emptied (Google does this
  automatically after 30 days); the Dashboard shows how much is waiting there.
- The worker runs one job at a time, so a long video blocks the queue behind it (by design, for a
  single small VM). Jobs can't be cancelled from the UI yet.
- Google API quotas/rate limits can affect large Drives; CloudClean pages through file listings
  rather than fetching everything at once, but very large accounts may still take a while to analyze.
- A file being old is never treated as proof it's unnecessary — inactive-file language throughout
  the app says "potentially inactive," and archiving (not deletion) is the only action offered.
- Linked accounts' free space can't be pooled, and CloudClean doesn't yet *move* files between
  accounts (Drive only allows that as an ownership transfer the other account must accept). Removing
  cross-account copies is the way to rebalance today.

## AWS S3 (backend only)

The S3 page was removed from the UI to keep CloudClean focused on Google storage, but the backend
module and its tests remain, and the `/api/s3` endpoints still work. In S3 the savings work
differently: the same bytes cost up to ~23x less depending on their *storage class*, so savings are
shown in **dollars per month** rather than GB. `POST /api/s3/connect-demo` starts a simulated account with
four buckets (nothing real is touched); `POST /api/s3/connect` takes your own AWS access key.

### How the Drive features map onto S3

| Drive feature | S3 equivalent in CloudClean |
|---|---|
| Inactive files / ZIP archiving | **Storage-class tiering** with a lifecycle rule per top-level prefix: Standard → Standard-IA (30 days) → Glacier Instant Retrieval (90 days); backup/archive prefixes go Glacier IR (30) → Deep Archive (180) |
| Duplicate detection (checksums) | Duplicates by **ETag + size** within a bucket |
| Image/PDF compression | Same compression, object rewritten under the same key |
| Drive Trash (30 days) | Versioned bucket: a **delete marker** (data kept as a noncurrent version). Otherwise: moved to `cloudclean-trash/`, which a lifecycle rule empties after 30 days |
| — (S3 only) | **Abandoned multipart uploads** (billed but invisible) → abort-after-7-days rule |
| — (S3 only) | **Piles of noncurrent versions** in versioned buckets → move them to Glacier IR after 30 days (never expired: that would permanently delete) |

Every recommendation shows its monthly saving, the one-time transition cost and the break-even time,
plus the trade-offs (retrieval fees, minimum storage durations, Deep Archive's 12-hour restores).
Each object's bytes count toward at most one saving (duplicates, then compression, then tiering).
Lifecycle rules are **previewed as JSON** and **merged** into the bucket's existing rules — S3's API
replaces the whole configuration, so CloudClean always writes back the rules it didn't create.
Every change is recorded in an S3 history with an **Undo** (removing a rule doesn't move objects
back; it only stops future transitions — the undo message says so).

### Connecting a real AWS account

1. In the AWS console, create an IAM user for CloudClean and attach a policy with only the permissions
   it needs — `GET /api/s3/iam-policy` returns it. Leave out
   the "CloudCleanOptimize" statement for a read-only analysis.
2. Create an access key for that user and send it to `POST /api/s3/connect` with your default region.
   CloudClean checks the key with AWS STS and stores it encrypted (same Fernet encryption as the
   Google tokens).

Prices come from `backend/data/s3_pricing.json` (us-east-1 list prices, labeled illustrative —
edit it for your region, e.g. `ap-south-1`). A scan costs one LIST request per 1,000 objects. On AWS
accounts with the classic free tier, S3 includes 5 GB of Standard storage and 2,000 LIST/PUT requests
a month; accounts created after 15 July 2025 get credits on AWS's newer free plan instead — check
**Billing → Free Tier** in your console.

### S3 limits to know

- S3 listings give *last modified*, not *last read*, so "not modified in 30/90 days" is the inactivity
  signal. If data is read often, prefer Intelligent-Tiering, or use S3 Storage Lens / access logs.
- Lifecycle rules run in S3's daily background pass, so changes appear within a day or two (in Demo
  Mode they apply on the next scan).
- Scans stop at 50,000 objects / 100,000 versions / 200 unfinished uploads per bucket (flagged in the
  UI); for bigger buckets, S3 Inventory reports are the scalable source.
- In versioned buckets, removed or recompressed data lingers as noncurrent versions, so those savings
  depend on the noncurrent-version rule — the estimates account for this.
- Tests: `pip install -r requirements-dev.txt` adds `moto`, which runs the real boto3 code paths
  against an in-process mock of AWS.
