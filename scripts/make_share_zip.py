"""Build share/CloudClean-test-package.zip — the project as a tester gets it.

    python scripts/make_share_zip.py

Packs exactly the files git would share (tracked + new, minus .gitignore'd),
so local secrets and data never ship: .env, backend/data/.secret_key, the
SQLite database, venv/, node_modules/. Those are also refused by name as a
second line of defence, and if .env holds real Google/AWS keys, every packed
file is scanned for them. Re-run after changes; share/ itself is gitignored.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "share"
PACKAGE = "CloudClean-test-package"

REFUSED_NAMES = {".env", ".secret_key"}
REFUSED_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db-journal", ".pem", ".key")
REFUSED_DIRS = {".git", "venv", ".venv", "node_modules", "__pycache__", "dist", "share", ".pytest_cache"}
SECRET_ENV_KEYS = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "SECRET_KEY", "TOKEN_ENCRYPTION_KEY")


def shareable_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                         cwd=ROOT, capture_output=True, check=True).stdout.decode()
    return sorted(rel for rel in out.split("\0") if rel and (ROOT / rel).is_file())


def refused(rel: str) -> bool:
    path = pathlib.PurePosixPath(rel)
    return (path.name in REFUSED_NAMES or path.name.endswith(REFUSED_SUFFIXES)
            or any(part in REFUSED_DIRS for part in path.parts[:-1]))


def local_secrets() -> list[str]:
    env = ROOT / ".env"
    if not env.exists():
        return []
    values = []
    for line in env.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() in SECRET_ENV_KEYS and len(value.strip()) >= 8:
            values.append(value.strip())
    return values


def main() -> int:
    files = shareable_files()
    skipped = [f for f in files if refused(f)]
    files = [f for f in files if not refused(f)]
    secrets = [s.encode() for s in local_secrets()]

    leaks = [f for f in files if any(s in (ROOT / f).read_bytes() for s in secrets)]
    if leaks:
        print("Refusing to build: these files contain a value from your .env:", *leaks, sep="\n  ")
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    target = OUT_DIR / f"{PACKAGE}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            info = zipfile.ZipInfo.from_file(ROOT / rel, arcname=f"{PACKAGE}/{rel}")
            # Keep shell scripts executable when unzipped on macOS/Linux.
            mode = 0o755 if rel.endswith(".sh") else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (ROOT / rel).read_bytes(), compresslevel=9)

    size_mb = target.stat().st_size / 1024 ** 2
    print(f"Built {target.relative_to(ROOT)} — {len(files)} files, {size_mb:.1f} MB")
    if skipped:
        print("Left out (local-only):", *skipped, sep="\n  ")
    print("Testers: unzip, then follow TESTING.md inside the folder.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
