"""Demo Mode: deterministic fake large Gmail messages (same shape as
gmail.normalize() returns), so the Gmail page works without an account."""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

MB = 1024 * 1024

_SENDERS = [
    "Photo Studio <prints@studio.example>", "HR Team <hr@company.example>",
    "Mom <mom@family.example>", "Project Bot <ci@builds.example>",
    "Travel Desk <bookings@travel.example>", "Professor Rao <rao@college.example>",
]
_SUBJECTS = [
    "Wedding photos (full resolution)", "Offer letter and onboarding documents",
    "Family trip videos", "Nightly build artifacts", "Your e-tickets and itinerary",
    "Lecture recordings - Unit {n}", "Scanned certificates", "Project report final draft",
    "Design review slides", "Quarterly data export",
]


def generate_demo_messages(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    messages = []
    for i in range(36):
        subject = rng.choice(_SUBJECTS).format(n=rng.randint(1, 6))
        mid = hashlib.sha1(f"demo-mail-{i}".encode()).hexdigest()[:16]
        size = int(rng.uniform(5.2, 24.5) * MB)
        messages.append({
            "message_id": f"demo-{mid}",
            "thread_id": f"demo-{mid}",
            "subject": subject,
            "sender": rng.choice(_SENDERS),
            "received_time": now - timedelta(days=rng.randint(3, 1500)),
            "size_bytes": size,
            "labels": rng.choice(["INBOX", "INBOX CATEGORY_UPDATES", "CATEGORY_PROMOTIONS", "SENT"]),
            "has_attachment": rng.random() < 0.9,
        })
    return messages
