"""Upload test photos with duplicates to a connected account's Google Drive,
so CloudClean's Duplicates and Compression pages have real files to work on.

    cd backend
    venv/Scripts/python ../scripts/seed_drive_test_files.py you@gmail.com --dry-run   # preview
    venv/Scripts/python ../scripts/seed_drive_test_files.py you@gmail.com             # upload

The account must already be connected in CloudClean. Photos are generated
(photo-like noise and shapes, with camera EXIF), so no real pictures are used.
Everything goes into a "CloudClean Test" folder in My Drive:

  IMG_2001.jpg … IMG_2005.jpg      originals (IMG_2004/2005 stay unique: compression candidates)
  IMG_2001 (1).jpg                 exact copy  -> "identical content" duplicate group
  Copy of IMG_2002.jpg             exact copy  -> duplicate group
  IMG_2003 copy.jpg                exact copy  -> duplicate group
  Holiday.jpg + Holiday_final.jpg  same name, different photo -> "versions" (review only)

Clean up: delete the "CloudClean Test" folder in Drive (or use CloudClean itself).
"""
from __future__ import annotations

import argparse
import io
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

FOLDER_NAME = "CloudClean Test"
FOLDER_MIME = "application/vnd.google-apps.folder"


def make_photo(seed: int, size=(4000, 3000)) -> bytes:
    """A photo-like JPEG (smooth gradient + shapes + sensor-like noise), high
    quality like a phone camera saves, with EXIF so the metadata fix can be checked."""
    from PIL import Image, ImageDraw, ImageFilter

    rng = random.Random(seed)
    w, h = size
    top, bottom = [tuple(rng.randint(30, 225) for _ in range(3)) for _ in range(2)]
    img = Image.linear_gradient("L").resize(size)
    img = Image.merge("RGB", [img.point(lambda v, a=a, b=b: a + (b - a) * v // 255) for a, b in zip(top, bottom)])
    draw = ImageDraw.Draw(img)
    for _ in range(25):
        x, y, r = rng.randint(0, w), rng.randint(0, h), rng.randint(40, 400)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=tuple(rng.randint(0, 255) for _ in range(3)))
    img = img.filter(ImageFilter.GaussianBlur(6))
    noise = Image.merge("RGB", [Image.effect_noise(size, 40) for _ in range(3)])
    img = Image.blend(img, noise, 0.25)

    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = "CloudClean", "Test Camera"     # Make, Model
    exif[0x0132] = f"2025:0{1 + seed % 9}:1{seed % 10} 10:00:00"  # DateTime
    exif[0x0112] = 1                                             # Orientation: normal
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, exif=exif.tobytes())
    return buf.getvalue()


def plan_files() -> list[tuple[str, int]]:
    """(file name, photo seed). Same seed = byte-identical file."""
    files = [(f"IMG_{2000 + i}.jpg", i) for i in range(1, 6)]
    files += [("IMG_2001 (1).jpg", 1), ("Copy of IMG_2002.jpg", 2), ("IMG_2003 copy.jpg", 3)]
    files += [("Holiday.jpg", 100), ("Holiday_final.jpg", 101)]
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("email", help="a Google account already connected in CloudClean")
    ap.add_argument("--dry-run", action="store_true", help="generate and list, upload nothing")
    args = ap.parse_args()

    photos: dict[int, bytes] = {}
    files = plan_files()
    for _, seed in files:
        photos.setdefault(seed, make_photo(seed))
    total = sum(len(photos[seed]) for _, seed in files)
    print(f"{len(files)} photos for {args.email} -> My Drive/{FOLDER_NAME} (~{total / 1024 / 1024:.0f} MB)")
    for name, seed in files:
        print(f"  {name:<24} {len(photos[seed]) / 1024 / 1024:4.1f} MB")
    if args.dry_run:
        print("Dry run: nothing uploaded.")
        return 0

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload

    import app.models.s3  # noqa: F401  (all tables registered)
    from app.core.database import SessionLocal
    from app.integrations.google_drive import authorized_credentials
    from app.models import User

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == args.email, User.is_demo.is_(False)).first()
        if user is None:
            print(f"{args.email} isn't connected in CloudClean. Connect it (Connect Google Drive) first.")
            return 1
        drive = build("drive", "v3", credentials=authorized_credentials(user), cache_discovery=False)

    found = drive.files().list(
        q=f"name = '{FOLDER_NAME}' and mimeType = '{FOLDER_MIME}' and 'me' in owners and trashed = false",
        fields="files(id)", spaces="drive",
    ).execute().get("files", [])
    folder_id = found[0]["id"] if found else drive.files().create(
        body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME}, fields="id").execute()["id"]

    for name, seed in files:
        media = MediaIoBaseUpload(io.BytesIO(photos[seed]), mimetype="image/jpeg", resumable=True)
        made = drive.files().create(body={"name": name, "parents": [folder_id]}, media_body=media,
                                    fields="id,md5Checksum").execute()
        print(f"  uploaded {name:<24} md5 {made['md5Checksum'][:10]}…")
    print("Done. In CloudClean: Dashboard -> Re-analyze, then open Duplicates and Compression.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
