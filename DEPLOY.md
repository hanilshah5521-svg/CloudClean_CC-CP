# Deploying CloudClean for free

CloudClean runs as **one service on one address**. The API serves the web app, and a background
worker runs alongside it (analysis, video compression, nightly rules). Google sign-in needs that
address to be **HTTPS**, except for `http://localhost`. Every option below is free and gives you
an HTTPS address.

| | A. Your PC + Tailscale Funnel | B. Hugging Face Space | C. Oracle Cloud Always Free |
|---|---|---|---|
| Cost | Free, no card | Free, no card | Free, but a card is needed to verify identity (not charged) |
| Address | Fixed: `https://<pc>.<tailnet>.ts.net` | Fixed: `https://<user>-<space>.hf.space` | Your VM, plus a free tunnel or domain |
| Online when | Your PC is on and awake | Always; sleeps after 48 h without visits, wakes on the next visit | Always |
| Data (History, Undo, rules) | Kept: it's your existing database | **Reset whenever the Space restarts or rebuilds** | Kept on the VM's disk |
| Video compression | Your PC's CPU | 2 shared CPUs, fine | 4 ARM cores, fine |
| Your time | ~30 min | ~45 min | ~1.5–2 h |
| Best for | Demos, using it yourself with your real data | A link others can open any time (temporary) | Long-term, always on |

Not recommended: Render / Koyeb free tiers sleep after ~15 min idle and wipe the disk, so History
and nightly rules wouldn't survive. Railway is no longer free.

## Settings every option uses

Put these in `.env` (option A) or the host's secret settings (options B and C). Never commit them.

| Setting | Value |
|---|---|
| `PUBLIC_URL` | The https address people open, e.g. `https://laptop.tail1234.ts.net`. It also sets the OAuth redirect (`<PUBLIC_URL>/auth/callback`), the frontend URL and secure cookies. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Your OAuth client (README → *Connecting a real Google Drive*) |
| `SECRET_KEY` | Option A: leave blank, so your existing `backend/data/.secret_key` keeps working. B and C: a long random value, from `python -c "import secrets; print(secrets.token_hex(32))"`. Changing it later means every account must sign in again. |
| `GMAIL_ENABLED` | `false` (fewer permissions asked at sign-in) |

**Google Cloud Console** (same project as now):
1. Google Auth Platform → Clients → your client → **Authorized redirect URIs** → add
   `<PUBLIC_URL>/auth/callback`. Keep the localhost one for development.
2. Audience → **Test users**: every Google account that will sign in or be linked (max 100).
3. Optional: Audience → **Publish app** (to "In production") without submitting for verification.
   Users still see the "unverified app" warning and the 100-user limit, but sign-ins should no
   longer expire every 7 days, as they do in Testing mode. Check Google's current rules in the
   console before relying on this.

## A. Your PC + Tailscale Funnel (keeps your current data)

1. Install Tailscale: `winget install tailscale.tailscale`, then sign in (any Google account works).
2. Publish port 8000 over HTTPS:
   ```bash
   tailscale funnel --bg 8000
   ```
   The first time, it prints a link to turn on HTTPS and Funnel for your tailnet: open it and
   approve. It then shows your address, e.g. `https://laptop.tail1234.ts.net`.
3. Add to `.env` in the CloudClean folder: `PUBLIC_URL=https://laptop.tail1234.ts.net`. Add the
   redirect URI in Google Cloud Console (above).
4. Double-click `scripts\start-production-windows.bat`. It builds the web app once, then opens two
   windows: the API (which also serves the app) and the worker.
5. Open your `https://…ts.net` address on any device and sign in.

To stop: close the two windows. `tailscale funnel --bg 8000 off` unpublishes the address. Keep
the PC awake (Windows Settings → Power → Sleep: Never while plugged in) or the site goes offline,
and nightly rules only run while it's on.

*Alternative: ngrok (free account).* `ngrok http 8000` publishes the app on your account's free
fixed address (`https://<name>.ngrok-free.dev`). Visitors see an ngrok warning page once and click
**Visit Site**. The free plan has a monthly bandwidth cap, which is plenty for Demo Mode and light
use.

*One-off alternative without an account:* `cloudflared tunnel --url http://localhost:8000` gives a
random `https://….trycloudflare.com` address. It changes on every run, so you'd update
`PUBLIC_URL` and the Google redirect URI each time.

## B. Hugging Face Space (always reachable, temporary data)

1. Create a free account at https://huggingface.co and a **write** access token (Settings →
   Access Tokens).
2. **New Space** → name `cloudclean` → SDK **Docker** → template **Blank** → visibility
   **Public**. A private Space's address needs a Hugging Face login, which blocks Google's
   redirect. A public Space shows the code, but never your secrets.
3. Space → Settings → **Variables and secrets**: add `PUBLIC_URL`
   (`https://<user>-cloudclean.hf.space`), `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `SECRET_KEY` and `GMAIL_ENABLED=false` as secrets. Add the redirect URI in Google Cloud Console.
4. Push the code:
   ```bash
   python scripts/make_hf_space.py ../cloudclean-space
   ```
   ```bash
   cd ../cloudclean-space && git init -b main && git add . && git commit -m "CloudClean" && git push --force https://huggingface.co/spaces/<user>/cloudclean main
   ```
   Use your Hugging Face username and the access token as the password. The first build takes
   about 5–10 minutes (Space → Logs).
5. Open `https://<user>-cloudclean.hf.space` directly, not the huggingface.co page around it.

Limits: the free Space disk isn't persistent. A restart (after 48 h idle, a rebuild, or
maintenance) empties the database, so History, Undo, rules and linked accounts start over. Your
Drive files are unaffected. One catch: a compression's kept original (Drive's "Keep forever"
version) is then never auto-deleted. Remove it in Drive → the file → Manage versions if you want
the space back. Fine for a demo; use A or C to keep data.

## C. Oracle Cloud Always Free VM (always on, data kept)

1. Sign up at https://www.oracle.com/cloud/free/ (the card is only for verification). Create an
   **Ampere A1** instance (up to 4 OCPU / 24 GB RAM free) with Ubuntu, and add your SSH key.
2. On the VM, install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. Copy the project there (git clone or `scp`), create `.env` with the settings above, then:
   ```bash
   sudo docker build -t cloudclean . && sudo docker run -d --name cloudclean --restart unless-stopped -p 127.0.0.1:8000:8000 -v cloudclean_data:/app/data --env-file .env cloudclean
   ```
4. HTTPS: install Tailscale on the VM and run `sudo tailscale funnel --bg 8000`, as in option A.
   Its `ts.net` address is your `PUBLIC_URL`. Restart the container after setting it.
5. Back up `cloudclean_data` now and then: it holds History, which Undo needs.

## The container (all options except A)

`Dockerfile` builds the web app, installs ffmpeg, and starts both the worker and the API
(`docker/start.sh`, which restarts the worker if it stops). Data lives in `/app/data`: mount a
volume there to keep it. Check it with `GET /health`. Local development is unchanged: it still
uses `docker-compose.yml` or `scripts/start-windows.bat`.
