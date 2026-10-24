"""Real Google OAuth + Drive API v3 integration.

Scopes:
- drive: read metadata of, update, and trash files CloudClean did NOT create
  itself — that's the whole point of the product (`drive.file` would only
  cover files the app created). Disclosed to the user on the Connect page.
- gmail.modify (optional, GMAIL_ENABLED): list large messages and move them
  to Gmail's Trash. Never `mail.google.com/`, which would allow permanent
  deletion.
- userinfo.email / .profile / openid for the account identity shown in the UI.
"""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from sqlalchemy.orm import object_session

from app.core.config import settings

# Google may grant fewer scopes than requested (the user can untick Gmail on
# the consent screen) or more (include_granted_scopes). Without this,
# oauthlib raises on any difference instead of letting us record what was granted.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
BASE_SCOPES = [
    DRIVE_SCOPE,
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"
# Chunk size for streamed downloads/uploads: bounds memory use for
# multi-GB videos (a resumable upload chunk must be a multiple of 256 KB).
STREAM_CHUNK_BYTES = 16 * 1024 * 1024

FILE_FIELDS = (
    "id,name,mimeType,size,quotaBytesUsed,md5Checksum,sha256Checksum,headRevisionId,"
    "createdTime,modifiedTime,parents,webViewLink,trashed,videoMediaMetadata"
)

# Only files the user owns use their quota, and only those can safely be
# trashed or replaced. Folders/shortcuts are containers, never "files" to
# compress or dedupe (trashing a folder trashes everything in it).
LIST_QUERY = (
    "trashed = false and 'me' in owners"
    " and mimeType != 'application/vnd.google-apps.folder'"
    " and mimeType != 'application/vnd.google-apps.shortcut'"
)


def requested_scopes() -> list[str]:
    return BASE_SCOPES + ([GMAIL_SCOPE] if settings.gmail_enabled else [])


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def build_auth_url() -> tuple[str, str, str]:
    """Returns (url, state, code_verifier). The caller must keep state and
    code_verifier in the user's session: state is checked on callback (CSRF),
    and the verifier must accompany the code exchange (PKCE)."""
    flow = Flow.from_client_config(
        _client_config(), scopes=requested_scopes(), redirect_uri=settings.google_redirect_uri,
        autogenerate_code_verifier=True,
    )
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    return url, state, flow.code_verifier


def exchange_code(code: str, state: str, code_verifier: str) -> tuple[Credentials, list[str]]:
    """Returns (credentials, scopes actually granted)."""
    flow = Flow.from_client_config(
        _client_config(), scopes=requested_scopes(), redirect_uri=settings.google_redirect_uri,
        state=state, code_verifier=code_verifier, autogenerate_code_verifier=False,
    )
    token = flow.fetch_token(code=code)
    granted = token.get("scope") or requested_scopes()
    if isinstance(granted, str):
        granted = granted.split()
    return flow.credentials, list(granted)


def credentials_from_user(user) -> Credentials:
    return Credentials(
        token=user.access_token or None,
        refresh_token=user.refresh_token or None,
        token_uri=TOKEN_URI,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        expiry=user.token_expiry,
    )


def authorized_credentials(user) -> Credentials:
    """Credentials for a User row, refreshed if expired. A refreshed access
    token is written back (encrypted) so the next request doesn't refresh again."""
    from google.auth.transport.requests import Request as GoogleAuthRequest

    if not user.refresh_token and not user.access_token:
        raise PermissionError("Google authorization is missing or expired. Please reconnect your Google account.")
    creds = credentials_from_user(user)
    if not creds.valid and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        user.access_token = creds.token or ""
        user.token_expiry = creds.expiry
        db = object_session(user)
        if db is not None:
            db.commit()
    return creds


def fetch_userinfo(creds: Credentials) -> dict:
    service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    return service.userinfo().get().execute()


class DriveClient:
    """Thin wrapper around the Drive v3 API used by CloudClean's services."""

    def __init__(self, creds: Credentials):
        self._creds = creds
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def storage_quota(self) -> dict:
        about = self._service.about().get(fields="storageQuota").execute()
        q = about.get("storageQuota", {})
        used = int(q.get("usage", 0))
        drive = int(q.get("usageInDrive", 0))
        return {
            "used_bytes": used,
            "quota_bytes": int(q.get("limit", 0)) if q.get("limit") else 15 * 1024 ** 3,
            # usageInDrive includes Drive's Trash; the remainder is Gmail + Photos.
            "drive_bytes": max(0, drive - int(q.get("usageInDriveTrash", 0))),
            "drive_trash_bytes": int(q.get("usageInDriveTrash", 0)),
            "gmail_photos_bytes": max(0, used - drive),
        }

    def list_files(self, page_token: str | None = None, page_size: int = 1000):
        """One page of the user's own non-trashed files, metadata only (no content download)."""
        resp = self._service.files().list(
            q=LIST_QUERY,
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

    def get_file(self, file_id: str) -> dict:
        return self._service.files().get(fileId=file_id, fields=FILE_FIELDS).execute()

    def download_file(self, file_id: str, mime_type: str) -> bytes:
        if mime_type.startswith("application/vnd.google-apps."):
            raise ValueError("Google Workspace-native files cannot be downloaded as binary; use export instead.")
        return self._download(self._service.files().get_media(fileId=file_id))

    def download_revision(self, file_id: str, revision_id: str) -> bytes:
        return self._download(self._service.revisions().get_media(fileId=file_id, revisionId=revision_id))

    def root_id(self) -> str:
        return self._service.files().get(fileId="root", fields="id").execute()["id"]

    def list_folders(self) -> dict[str, dict]:
        """The user's own folders: id -> {"name", "parent_id"} (metadata only)."""
        folders, token = {}, None
        while True:
            resp = self._service.files().list(
                q="mimeType = 'application/vnd.google-apps.folder' and 'me' in owners and trashed = false",
                spaces="drive", fields="nextPageToken, files(id,name,parents)", pageSize=1000, pageToken=token,
            ).execute()
            for f in resp.get("files", []):
                folders[f["id"]] = {"name": f["name"], "parent_id": (f.get("parents") or [""])[0]}
            token = resp.get("nextPageToken")
            if not token:
                return folders

    def create_folder(self, name: str, parent_id: str) -> str:
        return self._service.files().create(
            body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
            fields="id").execute()["id"]

    def folder_is_empty(self, folder_id: str) -> bool:
        resp = self._service.files().list(q=f"'{folder_id}' in parents and trashed = false",
                                          fields="files(id)", pageSize=1).execute()
        return not resp.get("files")

    def move_file(self, file_id: str, new_parent: str, old_parent: str) -> None:
        """Move without copying: the file keeps its ID, link and sharing."""
        self._service.files().update(fileId=file_id, addParents=new_parent, removeParents=old_parent,
                                     fields="id,parents").execute()

    def get_revision(self, file_id: str, revision_id: str) -> dict:
        return self._service.revisions().get(
            fileId=file_id, revisionId=revision_id, fields="id,keepForever,size,md5Checksum").execute()

    def delete_revision(self, file_id: str, revision_id: str) -> bool:
        """Permanently delete an old version of a file. Returns False if it was
        already gone. Note: Drive marks uploads "Keep forever", and that flag
        can't be turned off through the API — deleting the version is the only
        way to stop it counting toward storage."""
        try:
            self._service.revisions().delete(fileId=file_id, revisionId=revision_id).execute()
            return True
        except HttpError as exc:
            if exc.resp.status == 404:
                return False
            raise

    @staticmethod
    def _download(request) -> bytes:
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    def download_to_file(self, file_id: str, path, on_progress=None) -> None:
        """Stream a file's content to disk chunk by chunk — for videos, which
        are far too big to hold in memory. on_progress gets a 0-1 fraction."""
        self._download_to(self._service.files().get_media(fileId=file_id), path, on_progress)

    def download_revision_to_file(self, file_id: str, revision_id: str, path, on_progress=None) -> None:
        request = self._service.revisions().get_media(fileId=file_id, revisionId=revision_id)
        self._download_to(request, path, on_progress)

    @staticmethod
    def _download_to(request, path, on_progress) -> None:
        with open(path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=STREAM_CHUNK_BYTES)
            done = False
            while not done:
                status, done = downloader.next_chunk(num_retries=3)
                if on_progress and status:
                    on_progress(status.progress())

    def upload_file(self, name: str, content: bytes, mime_type: str, parent_id: str | None = None) -> dict:
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=True)
        metadata = {"name": name}
        if parent_id:
            metadata["parents"] = [parent_id]
        return self._service.files().create(
            body=metadata, media_body=media, fields=FILE_FIELDS
        ).execute()

    def replace_content(self, file_id: str, content: bytes, mime_type: str) -> dict:
        """Upload new bytes as a new revision of the SAME file. The file keeps
        its ID, so share links, permissions, comments, stars and folder
        placement all survive. Drive keeps the previous bytes as an older
        revision (restorable for ~30 days) that does not count toward quota
        unless marked keepForever."""
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=True)
        return self._service.files().update(
            fileId=file_id, media_body=media, fields=FILE_FIELDS,
        ).execute()

    def replace_content_from_file(self, file_id: str, path, mime_type: str, on_progress=None) -> dict:
        """replace_content() for a file on disk: a resumable upload sent in
        chunks (and resumed on transient errors), never read whole into memory."""
        with open(path, "rb") as fh:
            media = MediaIoBaseUpload(fh, mimetype=mime_type, chunksize=STREAM_CHUNK_BYTES, resumable=True)
            request = self._service.files().update(fileId=file_id, media_body=media, fields=FILE_FIELDS)
            response = None
            while response is None:
                status, response = request.next_chunk(num_retries=3)
                if on_progress and status:
                    on_progress(status.progress())
        return response

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


def get_client(user) -> DriveClient:
    """Real Drive client for a User row, refreshing the access token if expired."""
    return DriveClient(authorized_credentials(user))


def parse_drive_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
