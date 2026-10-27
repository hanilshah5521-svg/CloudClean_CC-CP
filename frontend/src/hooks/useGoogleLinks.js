import { useMemo } from "react";
import { useUser } from "./useUser.jsx";
import { isDemoId } from "../components/details.js";

/** Adds ?authuser=<email> so Google opens the account CloudClean is connected
 * to — not whichever Google account is the browser's default (which would
 * show "You need access" for files in the other account). */
function withAccount(url, email) {
  if (!email) return url;
  const u = new URL(url);
  u.searchParams.set("authuser", email);
  return u.toString();
}

/**
 * Links into Google Drive and Gmail for reviewing what CloudClean found.
 * Every function returns null in Demo Mode: demo files and emails don't exist
 * in any real account.
 */
export function useGoogleLinks() {
  const { user } = useUser();
  const email = user?.email;
  const real = !!user && !user.is_demo;

  return useMemo(() => {
    // `account` (optional): the linked account that owns the file, when it isn't the one being worked in.
    const drive = (path, account) => (real ? withAccount(`https://drive.google.com/${path}`, account || email) : null);
    return {
      demo: !real,
      /** The file itself (its Drive preview, or the Docs/Sheets editor). */
      file: (f, account) =>
        real && f?.drive_id && !isDemoId(f.drive_id)
          ? withAccount(f.web_url || `https://drive.google.com/file/d/${f.drive_id}/view`, account || email)
          : null,
      fileById: (driveId) => (driveId && !isDemoId(driveId) ? drive(`file/d/${driveId}/view`) : null),
      /** The folder a file sits in ("Show in folder"). */
      folder: (folderId, account) => (folderId && !isDemoId(folderId) ? drive(`drive/folders/${folderId}`, account) : null),
      driveTrash: drive("drive/trash"),
      gmailMessage: (url) => (real && url ? withAccount(url, email) : null),
      gmailMessageById: (id) => (real && id ? withAccount(`https://mail.google.com/mail/#all/${id}`, email) : null),
      gmailTrash: real ? withAccount("https://mail.google.com/mail/#trash", email) : null,
      /** Any other Google page (storage manager, Photos), in the connected account when there is one. */
      account: (url) => (real ? withAccount(url, email) : url),
    };
  }, [real, email]);
}
