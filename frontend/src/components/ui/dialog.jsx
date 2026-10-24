import * as RDialog from "@radix-ui/react-dialog";
import { RotateCcw, TriangleAlert, Info, X } from "lucide-react";
import { Button } from "./button.jsx";
import { cn } from "../../lib/cn.js";

export function Modal({ open, onOpenChange, title, description, children, footer, wide }) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-50 bg-scrim/40" />
        <RDialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 flex max-h-[88vh] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg border border-line bg-surface shadow-[0_8px_30px_rgb(var(--shade)/0.12)] focus:outline-none",
            wide ? "max-w-2xl" : "max-w-md",
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <RDialog.Title className="text-[15px] font-semibold text-ink">{title}</RDialog.Title>
              {description && <RDialog.Description className="mt-1 text-[13px] text-sub">{description}</RDialog.Description>}
            </div>
            <RDialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Close">
                <X className="h-4 w-4" />
              </Button>
            </RDialog.Close>
          </div>
          {children && <div className="min-h-0 overflow-auto px-5 py-4">{children}</div>}
          {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

const CONSEQUENCE = {
  permanent: { icon: TriangleAlert, label: "Permanent", cls: "text-bad-ink" },
  undoable: { icon: RotateCcw, label: "Undoable", cls: "text-ok-ink" },
  info: { icon: Info, label: "Note", cls: "text-info-ink" },
};

/**
 * Every destructive action goes through this: it states plainly what can be
 * undone and what can't. consequences: [{ kind: "permanent"|"undoable"|"info", text }]
 */
export function ConfirmDialog({ open, title, description, consequences = [], confirmLabel = "Confirm", danger, busy, onConfirm, onCancel }) {
  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && !busy && onCancel?.()}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </>
      }
    >
      {consequences.length > 0 && (
        <ul className="space-y-2">
          {consequences.map((c, i) => {
            const meta = CONSEQUENCE[c.kind] || CONSEQUENCE.info;
            const Icon = meta.icon;
            return (
              <li key={i} className="flex items-start gap-2 text-[13px] text-ink">
                <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", meta.cls)} strokeWidth={2} />
                <span>
                  <span className={cn("mr-1 text-[11px] font-semibold uppercase tracking-[0.04em]", meta.cls)}>{meta.label}</span>
                  {c.text}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Modal>
  );
}
