"""Gmail API v1 integration — finds the large messages eating the shared
Google storage quota. Metadata only: message bodies and attachments are
never downloaded. The only write is moving a message to Gmail's Trash (and
back); nothing is ever permanently deleted."""
from __future__ import annotations

from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

METADATA_HEADERS = ["Subject", "From"]
BATCH_SIZE = 50  # Gmail's recommended upper bound per batch request
MAX_MESSAGES = 2000  # bound one scan; the largest messages matter most anyway


class GmailClient:
    def __init__(self, creds: Credentials):
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _list_ids(self, query: str, limit: int) -> list[str]:
        ids: list[str] = []
        token = None
        while len(ids) < limit:
            resp = self._service.users().messages().list(
                userId="me", q=query, maxResults=min(500, limit - len(ids)), pageToken=token,
            ).execute()
            ids.extend(m["id"] for m in resp.get("messages", []))
            token = resp.get("nextPageToken")
            if not token:
                break
        return ids

    def large_messages(self, min_mb: int, limit: int = MAX_MESSAGES) -> list[dict]:
        """Messages larger than `min_mb` MB (Gmail's own `larger:` operator),
        normalized to plain dicts."""
        ids = self._list_ids(f"larger:{min_mb}M", limit)
        with_attachment = set(self._list_ids(f"larger:{min_mb}M has:attachment", limit))
        raw: dict[str, dict] = {}

        def collect(request_id, response, exception):
            if exception is None:
                raw[response["id"]] = response

        for start in range(0, len(ids), BATCH_SIZE):
            batch = self._service.new_batch_http_request(callback=collect)
            for message_id in ids[start:start + BATCH_SIZE]:
                batch.add(self._service.users().messages().get(
                    userId="me", id=message_id, format="metadata", metadataHeaders=METADATA_HEADERS,
                ))
            batch.execute()

        return [normalize(raw[i], i in with_attachment) for i in ids if i in raw]

    def trash(self, message_id: str) -> None:
        self._service.users().messages().trash(userId="me", id=message_id).execute()

    def untrash(self, message_id: str) -> None:
        self._service.users().messages().untrash(userId="me", id=message_id).execute()


def normalize(msg: dict, has_attachment: bool) -> dict:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    received = None
    if msg.get("internalDate"):
        received = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc).replace(tzinfo=None)
    return {
        "message_id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": headers.get("subject", "(no subject)")[:1000],
        "sender": headers.get("from", "")[:500],
        "received_time": received,
        "size_bytes": int(msg.get("sizeEstimate", 0)),
        "labels": " ".join(msg.get("labelIds", [])),
        "has_attachment": has_attachment,
    }
