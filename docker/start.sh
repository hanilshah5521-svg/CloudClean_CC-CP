#!/bin/sh
# One container, two processes: the background worker (analysis, videos,
# nightly rules, deleting kept originals when due) and the API + web app.
# The worker is restarted if it ever exits; the container lives as long as
# the API does.
set -e

(
  while true; do
    python -m app.worker || echo "Worker exited ($?); restarting in 5 s." >&2
    sleep 5
  done
) &

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="*"
