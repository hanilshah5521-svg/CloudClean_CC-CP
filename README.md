# CloudClean

**Intelligent Google Drive Storage Optimization & Lifecycle Management Platform**

CloudClean connects to your Google Drive, analyzes file metadata, finds duplicates and compression
opportunities, and lets you safely recover storage — with every recommendation explained and every
destructive action requiring your explicit confirmation. It runs entirely on free, open-source
software; the only paid resource involved is optionally your own Google Cloud project (free tier is
enough) if you connect a real Drive. **Demo Mode needs neither.**

## Contents

- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Quick start (Demo Mode)](#quick-start-demo-mode)
- [Connecting a real Google Drive](#connecting-a-real-google-drive)
- [Running with Docker](#running-with-docker)
- [Testing](#testing)
- [How it works](#how-it-works)
- [Security & privacy](#security--privacy)
- [Known limitations](#known-limitations)

## Architecture

```
cloudclean/
  backend/            FastAPI app
    app/
      api/routes/      HTTP endpoints (auth, storage, files, analysis, analytics,
                        recommendations, duplicates, compression, archive, history, settings)
      core/            config, database session
      models/          SQLAlchemy ORM models
      schemas/         Pydantic request/response schemas
      integrations/    Google OAuth + Drive API v3 client, Demo Mode data generator
      analyzers/       duplicate detection, large-file / inactive-file rules, compression estimates
      recommendations/ the rule-based RecommendationEngine + Optimization Score
      compression/      real Pillow/pikepdf/zipfile compression
      services/        orchestration: drive_service (analyze), optimization_service (compress/
                        trash/archive/restore), storage_service (overview + savings calculator)
      security/        session auth dependency
      utils/           MIME classification
    tests/             pytest — analyzers, engine, real compression round-trips, full API flow
    data/storage_plans.json   editable Google One pricing config
  frontend/           React + Vite + Tailwind + Recharts SPA
    src/pages/         Landing, Connect, Dashboard, FileExplorer, Duplicates, Compression,
                        Analytics, History, Settings
  docker/             Dockerfiles for both services
  docker-compose.yml
  .env.example
```

**Pipeline:** Google Drive → metadata collector (paginated, no file downloads) → classification →
duplicate detection → large/inactive-file analysis → compression-potential estimate → rule-based
RecommendationEngine → SQLite cache → dashboard. Nothing changes on your Drive until you click an
action and confirm it.

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
| Tests | pytest + FastAPI TestClient | no paid CI service required |

**Explicitly not used, and why:** no OpenAI/Anthropic/Gemini API (the recommendation engine is
rule-based and explainable by design, not a model call); no pandas/numpy/scikit-learn (every
computation here is arithmetic over a few thousand rows — pulling in a dataframe library would be
pure overhead); no Celery/job queue (FastAPI's sync-route threadpool is enough for a single-user
local analysis); no Playwright suite (the flows are verified with pytest + FastAPI's TestClient
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

Open **http://localhost:5173**, click **Try Demo Mode**, then **Analyze Drive**. Everything after
that — duplicates, compression, archiving, history, restore — operates on simulated data end to end,
clearly labeled "DEMO MODE" throughout the UI.

## Connecting a real Google Drive

### 1. Create a Google Cloud project
Go to [console.cloud.google.com](https://console.cloud.google.com) → select or create a project.

### 2. Enable the Drive API
**APIs & Services → Library** → search "Google Drive API" → **Enable**.

### 3. Configure the OAuth consent screen
**APIs & Services → OAuth consent screen** → choose **External** (or Internal for a Workspace org) →
fill in app name, support email → add scopes `.../auth/drive`, `.../auth/userinfo.email`,
`.../auth/userinfo.profile` → add your own Google account under **Test users** if the app is in
Testing mode.

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
Fill in `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from the credential you just created, and
generate a `SECRET_KEY`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Restart the backend. The Connect page's "Connect Google Drive" button now redirects to Google's
real consent screen.

**Scope note:** CloudClean requests the broad `drive` scope, not `drive.file`, because it needs to
read metadata and move to Trash files it did not itself create — that is the whole point of the
product. This is disclosed on the Connect page before you authorize.

## Running with Docker

```bash
cp .env.example .env   # fill in Google credentials, or leave blank for Demo Mode only
docker-compose up --build
```
Frontend on http://localhost:5173, backend on http://localhost:8000. SQLite data persists in a
named Docker volume across restarts.

## Testing

```bash
cd backend
source venv/bin/activate
pytest -v
```

22 tests covering: duplicate detection (all three match levels), inactivity/size-tier rules,
compression-potential estimation, the recommendation engine (explainability + score bounds), *real*
compression round-trips (a JPEG is actually re-encoded and re-decoded, a PDF's page count survives
optimization, ZIP entries are sanitized against path traversal), and a full integration test that
drives the actual HTTP API through Connect → Analyze → Recommend → Optimize → Refresh against Demo
Mode.

The frontend was verified manually in-browser (not scripted with Playwright — see stack rationale
above): Demo Mode connect → analyze → view score/recommendations → confirm a duplicate trash → run
a real PDF compression → verify the byte counts in History → browse Analytics and File Explorer,
including multi-select archive.

## How it works

### Duplicate detection
Three levels, cheapest first: (1) SHA-256 content hash, when available — highest confidence; (2)
identical size + normalized filename (strips `" (1)"`, `"_final"`, `"copy of"` etc.) — handles the
`report.pdf` / `report (1).pdf` / `report_final.pdf` pattern; (3) normalized filename alone, lower
confidence, still surfaced for manual review. CloudClean recommends keeping the most recently
modified copy but never trashes anything until you confirm — you can pick a different file to keep.

### Compression
Real, on-demand, not simulated (outside Demo Mode). JPEG is re-encoded with Pillow at a configurable
quality; PNG is losslessly re-compressed; PDF is optimized with pikepdf (stream compression +
duplicate-object removal, content untouched). The original is downloaded, compressed in memory,
the optimized copy is uploaded to Drive, upload is verified with a follow-up `files.get` call, and
**only then** is the original moved to Trash. If the saving isn't meaningful (below your configured
minimum-saving %), nothing is uploaded and the original is left alone.

### Storage savings calculation
The Optimization Score (0–100) is a fully transparent deduction from 100: each inefficiency factor
(duplicate storage, compressible storage, inactive storage, large-file concentration) is capped and
weighted by documented constants in `app/recommendations/engine.py` — there is no model inference
step. Pricing shown in the Savings Calculator comes from `backend/data/storage_plans.json`
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
- Sessions are Starlette's signed-cookie `SessionMiddleware` (itsdangerous) with `SameSite=Lax`,
  giving baseline CSRF protection for free (a cross-site POST doesn't carry the cookie).
- **File content is never written to disk.** Downloads, compression, and ZIP creation all happen in
  memory (`io.BytesIO`) and are discarded once the request completes — there is no temp-file
  cleanup job because there are no temp files to clean up.
- ZIP archive entry names are sanitized (path separators stripped) before being written, so a
  crafted filename can't escape the archive on extraction.
- Unhandled exceptions are logged server-side and returned to the client as a generic message —
  stack traces never reach the browser.
- Nothing is ever permanently deleted by CloudClean. The most destructive action it takes is moving
  a file to Google Drive's own Trash, which you can restore from History.

## Known limitations

- Google Drive storage is shared with Gmail and Google Photos — CloudClean only sees and affects
  Drive files.
- Not every file can be meaningfully compressed; already-compressed formats (zip, mp4, mp3, etc.)
  are explicitly flagged rather than falsely promised savings.
- Google Workspace-native files (Docs/Sheets/Slides) have no binary size and can't be compressed
  like ordinary files.
- Compression estimates (shown before you click Compress) can differ from the actual result — the
  UI always distinguishes "estimated" from "actual" and never presents one as the other.
- Moving a file to Trash doesn't necessarily reclaim quota instantly in every account configuration.
- Google API quotas/rate limits can affect large Drives; CloudClean pages through file listings
  rather than fetching everything at once, but very large accounts may still take a while to analyze.
- A file being old is never treated as proof it's unnecessary — inactive-file language throughout
  the app says "potentially inactive," and archiving (not deletion) is the only action offered.
