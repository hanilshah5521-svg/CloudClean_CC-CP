import { ExternalLink, FolderOpen, Trash2, TriangleAlert } from "lucide-react";
import { useGoogleLinks } from "../hooks/useGoogleLinks.js";
import { DEMO_LINK_REASON } from "./details.js";
import { cn } from "../lib/cn.js";
import { buttonVariants } from "./ui/button.jsx";
import { Tip } from "./ui/controls.jsx";
import { Notice } from "./ui/primitives.jsx";

/** Icon link that opens Google in a new tab; shown disabled (with why) when there's no link. */
export function IconLink({ href, label, icon: Icon, disabledReason }) {
  const cls = cn(buttonVariants({ variant: "ghost", size: "icon" }), "h-7 w-7");
  if (!href) {
    return (
      <Tip content={disabledReason}>
        <span role="link" aria-disabled="true" aria-label={`${label} (unavailable)`} className={cn(cls, "cursor-not-allowed opacity-40 hover:bg-transparent")}>
          <Icon className="h-3.5 w-3.5" />
        </span>
      </Tip>
    );
  }
  return (
    <Tip content={label}>
      <a href={href} target="_blank" rel="noreferrer" aria-label={label} onClick={(e) => e.stopPropagation()} className={cls}>
        <Icon className="h-3.5 w-3.5" />
      </a>
    </Tip>
  );
}

/** "Open in Drive" + "Show in folder" for one Drive file (needs drive_id, web_url, parent_id).
 * `account`: the linked account's email when the file isn't in the account being worked in. */
export function DriveFileLinks({ file, account }) {
  const links = useGoogleLinks();
  return (
    <span className="inline-flex items-center">
      <IconLink href={links.file(file, account)} label="Open in Google Drive" icon={ExternalLink} disabledReason={DEMO_LINK_REASON} />
      <IconLink
        href={links.folder(file.parent_id, account)}
        label="Show in its Drive folder"
        icon={FolderOpen}
        disabledReason={links.demo ? DEMO_LINK_REASON : "Not in one of your folders (shared with you)."}
      />
    </span>
  );
}

/** Text-sized button link, e.g. "Open Drive Trash" inside a notice. */
export function ButtonLink({ href, children, icon: Icon = ExternalLink, disabledReason = DEMO_LINK_REASON, className }) {
  const cls = cn(buttonVariants({ variant: "secondary", size: "sm" }), className);
  if (!href) {
    return (
      <Tip content={disabledReason}>
        <span role="link" aria-disabled="true" className={cn(cls, "cursor-not-allowed opacity-50")}>
          <Icon className="h-3.5 w-3.5" /> {children}
        </span>
      </Tip>
    );
  }
  return (
    <a href={href} target="_blank" rel="noreferrer" className={cls}>
      <Icon className="h-3.5 w-3.5" /> {children}
    </a>
  );
}

export function DriveTrashLink({ className }) {
  return (
    <ButtonLink href={useGoogleLinks().driveTrash} icon={Trash2} className={className}>
      Open Drive Trash
    </ButtonLink>
  );
}

/** Trashed files still use storage until the Trash is emptied — say so, with a link to do it. */
export function DriveTrashNotice({ children, className }) {
  return (
    <Notice tone="warn" icon={TriangleAlert} className={className}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span>{children}</span>
        <DriveTrashLink />
      </div>
    </Notice>
  );
}
