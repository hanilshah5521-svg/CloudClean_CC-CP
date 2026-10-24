"""Fill a connected account's Gmail with large test emails, so CloudClean's
Gmail & Photos page has something real to find and clean.

    cd backend
    venv/Scripts/python ../scripts/seed_gmail_test_emails.py you@gmail.com            # Windows
    venv/bin/python ../scripts/seed_gmail_test_emails.py you@gmail.com --dry-run      # macOS/Linux

The account must already be connected in CloudClean with the Gmail permission.
Messages are added with Gmail's `messages.insert` — nothing is SENT, no one
else receives anything. They go under a "CloudClean Test" label (not the
Inbox, unless --inbox), with dates spread over the last three years so the
"Older than 1/2 years" filters have something to show. Attachments are random
bytes named test-attachment-N.bin.

They use real storage (about --count x average size). Clean up from
CloudClean's Gmail page (that's the feature under test) or in Gmail: search
label:cloudclean-test, select all, delete — Gmail empties Trash after 30 days.
"""
from __future__ import annotations

import argparse
import io
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

LABEL_NAME = "CloudClean Test"
SUBJECTS = [
    "Trip photos (full resolution)", "Lecture recordings - Unit {n}", "Project report final draft",
    "Scanned certificates", "Design review slides", "Quarterly data export", "Wedding album - part {n}",
    "Lab submission files", "Team offsite videos", "Backup of old laptop documents",
]
SENDERS = [
    "Photo Studio <studio@example.com>", "Professor Rao <rao@college.example.com>",
    "Project Bot <ci@builds.example.com>", "Travel Desk <bookings@travel.example.com>",
    "Family <family@example.com>",
]


def build_message(to: str, index: int, attachment_mb: float, sent: datetime, rng: random.Random) -> bytes:
    msg = EmailMessage()
    msg["From"] = rng.choice(SENDERS)
    msg["To"] = to
    msg["Subject"] = "[CloudClean test] " + rng.choice(SUBJECTS).format(n=rng.randint(1, 6))
    msg["Date"] = format_datetime(sent)
    msg.set_content(
        "This is a test email added by CloudClean's seed_gmail_test_emails.py script.\n"
        "It was never sent; it only exists in this mailbox, to test finding and cleaning large emails.\n"
        "Safe to delete."
    )
    msg.add_attachment(os.urandom(int(attachment_mb * 1024 * 1024)), maintype="application",
                       subtype="octet-stream", filename=f"test-attachment-{index}.bin")
    return msg.as_bytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("email", help="a Google account already connected in CloudClean")
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--min-mb", type=float, default=4.0, help="smallest attachment (MB)")
    ap.add_argument("--max-mb", type=float, default=12.0, help="largest attachment (MB; keep under 20)")
    ap.add_argument("--inbox", action="store_true", help="also show them in the Inbox")
    ap.add_argument("--dry-run", action="store_true", help="show what would be added, add nothing")
    args = ap.parse_args()
    if not 1 <= args.count <= 50 or not 0.1 <= args.min_mb <= args.max_mb <= 20:
        ap.error("use 1-50 emails and attachment sizes between 0.1 and 20 MB")

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload

    import app.models.s3  # noqa: F401  (all tables registered)
    from app.core.database import SessionLocal
    from app.integrations.google_drive import GMAIL_SCOPE, authorized_credentials
    from app.models import User

    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    plan = []
    for i in range(1, args.count + 1):
        size = round(rng.uniform(args.min_mb, args.max_mb), 1)
        sent = now - timedelta(days=rng.randint(3, 3 * 365), hours=rng.randint(0, 23))
        plan.append((i, size, sent))
    # base64 encoding makes each email ~1.37x its attachment size
    total_mb = sum(size for _, size, _ in plan) * 1.37
    print(f"{args.count} test emails for {args.email}, ~{total_mb:.0f} MB of Gmail storage, label '{LABEL_NAME}'"
          + (" + Inbox" if args.inbox else ""))
    for i, size, sent in plan:
        print(f"  #{i:>2}  {size:4.1f} MB attachment  dated {sent:%Y-%m-%d}")
    if args.dry_run:
        print("Dry run: nothing added.")
        return 0

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == args.email, User.is_demo.is_(False)).first()
        if user is None:
            print(f"{args.email} isn't connected in CloudClean. Connect it (Connect Google Drive) first.")
            return 1
        if GMAIL_SCOPE not in (user.granted_scopes or "").split():
            print("This account didn't grant Gmail access. Reconnect it and tick the Gmail permission.")
            return 1
        gmail = build("gmail", "v1", credentials=authorized_credentials(user), cache_discovery=False)

    labels = gmail.users().labels().list(userId="me").execute().get("labels", [])
    label = next((lb for lb in labels if lb["name"] == LABEL_NAME), None) or gmail.users().labels().create(
        userId="me", body={"name": LABEL_NAME, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    ).execute()
    label_ids = [label["id"]] + (["INBOX"] if args.inbox else [])

    for i, size, sent in plan:
        raw = build_message(args.email, i, size, sent, rng)
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype="message/rfc822", resumable=True)
        gmail.users().messages().insert(userId="me", body={"labelIds": label_ids}, media_body=media,
                                        internalDateSource="dateHeader").execute()
        print(f"  added #{i:>2} ({len(raw) / 1024 / 1024:.1f} MB)")
    print(f"Done. In Gmail: search label:{LABEL_NAME.lower().replace(' ', '-')}. "
          f"In CloudClean: Dashboard -> Re-analyze, then open Gmail & Photos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
