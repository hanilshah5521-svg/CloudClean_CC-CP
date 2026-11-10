"""Prepare a folder to push to a free Hugging Face Space (DEPLOY.md, option B).

    python scripts/make_hf_space.py ../cloudclean-space

Copies the files git tracks (plus new, not-ignored ones) — never .env, the
database, the secret key, venv or node_modules, since .gitignore excludes
them — and writes the README.md a Space needs (its settings live in the
README's front matter). Then push that folder to your Space's git repo.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_SUFFIXES = {".pdf", ".pptx", ".docx", ".xlsx", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".ico"}

SPACE_README = """---
title: CloudClean
emoji: 🧹
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
pinned: false
---

# CloudClean

Google Drive storage optimizer. Built from the repository's `Dockerfile`
(web app, API and background worker in one container).

Open it at its own address — `https://<user>-<space>.hf.space` — not inside the
Hugging Face page: Google sign-in doesn't work in an embedded frame.

Settings (Space → Settings → Variables and secrets): `PUBLIC_URL`,
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SECRET_KEY`. See DEPLOY.md.
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    target = Path(sys.argv[1]).resolve()
    if target == ROOT or ROOT in target.parents:
        print("Choose a folder outside the CloudClean folder, e.g. ../cloudclean-space")
        return 2
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in filter(None, files):
        src = ROOT / name
        if not src.is_file():  # deleted in the working tree
            continue
        # Hugging Face refuses plain binary files in a git push, and the app
        # doesn't need the project's reports and slides to run.
        if name.startswith("documentation/") or src.suffix.lower() in SKIP_SUFFIXES:
            continue
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    (target / "PROJECT_README.md").write_bytes((ROOT / "README.md").read_bytes())
    (target / "README.md").write_text(SPACE_README, encoding="utf-8")
    print(f"Copied {copied} files to {target}.")
    print("Next: push that folder to your Space (DEPLOY.md, option B, step 4).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
