# Testing CloudClean

Thanks for testing! CloudClean finds wasted space in **Google Drive, Gmail and AWS S3** — duplicates,
compressible files, old data in expensive storage — and fixes it safely: every change is confirmed
first and can be undone. **Demo Mode** needs no Google or AWS account and touches nothing real, so
start there.

## 1. Install the two prerequisites

| Tool | Version | Get it |
|---|---|---|
| Python | 3.10 – 3.13 (3.12 recommended; 3.14 is not supported yet) | https://www.python.org/downloads/ — on Windows, tick "Add python.exe to PATH" |
| Node.js | 18 or newer (20 LTS recommended) | https://nodejs.org/ |

Optional: **ffmpeg** for real video compression (`winget install ffmpeg` on Windows,
`brew install ffmpeg` on macOS). Without it, video compression still works in Demo Mode.

## 2. Start it

Unzip the package somewhere with a **short path** — e.g. `C:\CloudClean` or your Desktop. Windows can't
install some packages inside deeply nested folders (the script checks and tells you).

- **Windows:** double-click `scripts\start-windows.bat`.
- **macOS / Linux:** in a terminal in this folder, run `bash scripts/start-mac-linux.sh`.

The first run installs packages (a few minutes). Then the browser opens **http://localhost:5173**.
Three things run: the backend API (port 8000), a background worker, and the web app (port 5173).
Stop it by closing the three CloudClean windows (Windows) or pressing Ctrl+C (macOS / Linux).

## 3. Test checklist (Demo Mode)

Click **Try Demo Mode** on the start page, then work through these. Each line says what you should see.

| # | Where | Do this | Expected |
|---|---|---|---|
| 1 | Dashboard | Click **Analyze Drive** | Storage split into Drive / Drive Trash / Gmail + Photos, an Optimization Score, and a list of recommendations — each explaining its numbers |
| 2 | Duplicates | Move one exact-copy group to Trash | Toast confirms; the group disappears. Groups marked **Versions** (same name, different content) can't be trashed until you tick "I've compared them" |
| 3 | Compression | **Compress Now** on a PDF or JPEG | Size drops; message says the file keeps its link and the original stays restorable |
| 4 | Compression | **Compress video** on an MP4 | Runs as a background job (progress bar while it runs; in Demo Mode it finishes almost at once) |
| 5 | File Explorer | Filter **Archive candidate**, select a few, **Archive Selected** | One ZIP replaces them; History lists each file plus one *Archive created* row, and the space saved is counted once |
| 6 | Gmail & Photos | Select an email, **Move to Gmail Trash** | It leaves the list; Photos card explains why Photos can't be cleaned by apps |
| 7 | History | **Undo** a compression, **Restore** a trashed file | Status changes to *reverted*; the file is back |
| 7a | History | On a compressed file, **Free space now** | Confirms first; deletes the kept original and frees its space (Undo is no longer possible after) |
| 7b | Organize | **Organize** a suggested group (e.g. budget_1…10.xlsx → *Budgets*), then **Undo** it in History | Files move into one folder (links unchanged); Undo moves them back |
| 8 | Settings | Change thresholds / add an auto-compression rule | Saved; next **Re-analyze** uses them |
| 9 | AWS S3 | **Start S3 demo** | Four buckets priced by storage class with $/month savings |
| 10 | AWS S3 | **Preview rule** on a recommendation, then **Add rule**, then **Re-scan** | Rule shown as JSON first; after re-scan the monthly cost drops (~$9.50 → ~$2.60 if you apply them all) |
| 11 | AWS S3 → S3 History | **Undo** a change | Rule removed / object restored; message explains what undo can and can't reverse |
| 12 | Start page | Click **Connect Google Drive** (no keys configured) | A friendly "Google sign-in isn't set up" message — not an error page |

## 4. Testing with real accounts (optional)

**Google Drive / Gmail** needs an OAuth client. Either create your own (README → *Connecting a real
Google Drive*, about 10 minutes) and put `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in a `.env`
file here (copy `.env.example`), or ask the project owner to add your Gmail as a test user and send
you the client details privately. Real actions are still confirmed and undoable — try them on files
you don't care about first.

**AWS S3**: create an IAM user with only the permissions shown under **Show IAM policy** on the S3
page, and paste its access key there. Listing costs one request per 1,000 objects.

## 5. Automated tests (optional)

```bash
cd backend
venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS/Linux: venv/bin/python
venv/Scripts/python -m pytest -q
```

## Reporting a problem

Please include: what you clicked, what you expected, what happened, a screenshot, and the last lines
of the **CloudClean backend** window (or terminal). Your OS, Python and Node versions help too.

## Troubleshooting

- **"Python 3.10 to 3.13 is required"** — install Python 3.12 (3.14 lacks prebuilt packages for this project's pinned versions). On macOS, use a recent macOS (14+ on Apple Silicon).
- **"This folder's path is too long"** / an install error mentioning *Long Path support* — move the folder to e.g. `C:\CloudClean`, delete `backendenv`, and run the script again.
- **Port 8000 or 5173 already in use** — close whatever uses it (or an earlier CloudClean run) and start again.
- **Blank page** — wait a few seconds after the first start and refresh; the web app compiles on first load.
- **Windows "protected your PC" prompt for the .bat** — choose *More info → Run anyway* (it only runs the commands you can read in the file).
- **Start over** — delete `backend/venv`, `frontend/node_modules` and `backend/data/cloudclean.db*`.
