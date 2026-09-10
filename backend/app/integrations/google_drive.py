"""Real Google OAuth + Drive API v3 integration.

Minimum practical scopes only:
- drive (read/write on files the app creates/touches, needed to upload
  optimized replacements and move originals to Trash)
- userinfo.email / .profile for the account identity shown in the UI

We ask for `drive` (not `drive.file`) because CloudClean needs to read
metadata and trash files it did NOT create itself — that's the whole point
of the product. This is disclosed to the user on the Connect page.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from googleapiclient.errors import HttpError

from app.core.config import settings

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

FILE_FIELDS = (
    "id,name,mimeType,size,createdTime,modifiedTime,parents,webViewLink,trashed"
)


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def build_auth_url() -> tuple[str, str]:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=settings.google_redirect_uri)
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    return url, state


def exchange_code(code: str) -> Credentials:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=settings.google_redirect_uri)
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_from_user(user) -> Credentials:
    return Credentials(
        token=user.access_token,
        refresh_token=user.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )


def fetch_userinfo(creds: Credentials) -> dict:
    service = build("oauth2", "v2", credentials=creds)
    return service.userinfo().get().execute()


class DriveClient:
    """Thin wrapper around the Drive v3 API used by CloudClean's services."""

    def __init__(self, creds: Credentials):
        self._creds = creds
        self._service = build("drive", "v3", credentials=creds)

    def storage_quota(self) -> dict:
        about = self._service.about().get(fields="storageQuota").execute()
        q = about.get("storageQuota", {})
        return {
            "used_bytes": int(q.get("usage", 0)),
            "quota_bytes": int(q.get("limit", 0)) if q.get("limit") else 15 * 1024 ** 3,
        }

    def list_files(self, page_token: str | None = None, page_size: int = 1000):
        """One page of non-trashed files with metadata-only fields (no content download)."""
        resp = self._service.files().list(
            q="trashed = false",
            spaces="drive",
            fields=f"nextPageToken, files({FILE_FIELDS})",
            pageSize=page_size,
            pageToken=page_token,
        ).execute()
        return resp.get("files", []), resp.get("nextPageToken")

    def iter_all_files(self):
        """Generator that pages through the entire Drive, metadata only."""
        token = None
        while True:
            files, token = self.list_files(page_token=token)
            yield from files
            if not token:
                break

    def download_file(self, file_id: str, mime_type: str) -> bytes:
        if mime_type.startswith("application/vnd.google-apps."):
            raise ValueError("Google Workspace-native files cannot be downloaded as binary; use export instead.")
        request = self._service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    def upload_file(self, name: str, content: bytes, mime_type: str, parent_id: str | None = None) -> dict:
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
        metadata = {"name": name}
        if parent_id:
            metadata["parents"] = [parent_id]
        return self._service.files().create(
            body=metadata, media_body=media, fields=FILE_FIELDS
        ).execute()

    def trash_file(self, file_id: str) -> None:
        self._service.files().update(fileId=file_id, body={"trashed": True}).execute()

    def restore_file(self, file_id: str) -> None:
        self._service.files().update(fileId=file_id, body={"trashed": False}).execute()

    def verify_file_exists(self, file_id: str) -> bool:
        try:
            self._service.files().get(fileId=file_id, fields="id").execute()
            return True
        except HttpError:
            return False


def get_client(user) -> "DriveClient":
    """Real Drive client for a User row, refreshing the access token if expired."""
    from google.auth.transport.requests import Request as GoogleAuthRequest

    creds = credentials_from_user(user)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
    return DriveClient(creds)


def parse_drive_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
