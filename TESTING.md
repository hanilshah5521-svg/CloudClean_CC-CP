# Testing CloudClean

Thanks for testing! CloudClean finds wasted space in **Google Drive** — duplicates, compressible
files, old files worth archiving — across one or several linked Google accounts, and fixes it
safely: every change is confirmed first and can be undone. **Demo Mode** needs no Google account and
touches nothing real, so start there.

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
| 1 | Dashboard | Click **Run Scan** (top right) | Storage split into Drive / Drive Trash / Gmail + Photos, an Optimization Score, and a list of recommendations — each explaining its numbers |
| 2 | Duplicates | Move one exact-copy group to Trash | Toast confirms; the group disappears. Groups marked **Versions** (same name, different content) can't be trashed until you tick "I've compared them" |
| 3 | Compression | **Compress Now** on a PDF or JPEG | Size drops; message says the file keeps its link and the original stays restorable |
| 4 | Compression | **Compress video** on an MP4 | Runs as a background job (progress bar while it runs; in Demo Mode it finishes almost at once) |
| 5 | Dashboard | Open the **Archive inactive files** recommendation, then **Archive N into one ZIP** | Confirms first; one ZIP replaces them; History lists each file plus one *Archive created* row, and the space saved is counted once |
| 6 | Organize | **Organize** a suggested group (e.g. budget_1…10.xlsx → *Budgets*), then **Undo** it in History | Files move into one folder (links unchanged); Undo moves them back |
| 7 | History | **Undo** a compression, **Restore** a trashed file | Status changes to *reverted*; the file is back |
| 7a | History | On a compressed file, **Free space now** | Confirms first; deletes the kept original and frees its space (Undo is no longer possible after) |
| 8 | Profile menu (top right) | **Add a simulated account** twice | Three accounts listed; a fourth can't be added. **Run Scan** now scans all three |
| 9 | Accounts | Look at the storage per account and **Copies across accounts**; filter by one account | Each group holds the same file in two or more accounts; the suggested copy to keep is in the account with the most free space |
| 10 | Accounts | **Remove** the other copies of one group | Confirms first; the group disappears. Switch to the account that held a copy (profile menu) — its History shows the removal, and **Restore** works |
| 11 | Profile menu | Switch accounts | Every page shows that account's data; the Dashboard says which account you're viewing |
| 12 | Accounts / Settings → Account | Remove a linked account | Confirms first; you can't remove the account you're working in |
| 13 | Duplicates / Compression | Look for **Open in Drive** links | Disabled in Demo Mode, with a note why (the files only exist in a real Drive) |
| 14 | Profile menu | Change the theme to **Dark**, then **System** | The whole app, including charts, switches theme; the choice survives a reload |
| 15 | Settings | Change thresholds / add an auto-compression rule | Saved; the next **Run Scan** uses them |
| 16 | Start page | Click **Connect Google Drive** (no keys configured) | A friendly "Google sign-in isn't set up" message — not an error page |

## 4. Testing with real accounts (optional)

**Google Drive** needs an OAuth client. Either create your own (README → *Connecting a real
Google Drive*, about 10 minutes) and put `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in a `.env`
file here (copy `.env.example`), or ask the project owner to add your Google accounts as test users
and send you the client details privately. To test multiple accounts, sign in with one, then use
**Add Google account** in the profile menu for the others — each one must be a test user. Real
actions are still confirmed and undoable — try them on files you don't care about first. The
**Open in Drive** links open each file in the right account.

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
- **"This folder's path is too long"** / an install error mentioning *Long Path support* — move the folder to e.g. `C:\CloudClean`, delete `backend\venv`, and run the script again.
- **Port 8000 or 5173 already in use** — close whatever uses it (or an earlier CloudClean run) and start again.
- **Blank page** — wait a few seconds after the first start and refresh; the web app compiles on first load.
- **Windows "protected your PC" prompt for the .bat** — choose *More info → Run anyway* (it only runs the commands you can read in the file).
- **Start over** — delete `backend/venv`, `frontend/node_modules` and `backend/data/cloudclean.db*`.
