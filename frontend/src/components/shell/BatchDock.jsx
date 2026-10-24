import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { Button } from "../ui/button.jsx";
import { formatBytes } from "../../utils/format.js";

/** Floating bar that slides up while 1+ rows are checked: "3 items selected · 412 MB · [action]". */
export default function BatchDock({ count, bytes, actionLabel, actionIcon: Icon, danger, onAction, onClear, busy }) {
  return (
    <AnimatePresence>
      {count > 0 && (
        <motion.div
          initial={{ y: 80, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 80, opacity: 0 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          className="pointer-events-none sticky bottom-4 z-30 flex justify-center"
        >
          <div className="pointer-events-auto flex items-center gap-3 rounded-lg border border-line bg-surface py-2 pl-4 pr-2 shadow-[0_6px_24px_rgb(var(--shade)/0.12)]">
            <span className="text-[13px] text-ink">
              <span className="mono font-medium">{count}</span> item{count === 1 ? "" : "s"} selected
              <span className="mx-2 text-faint">·</span>
              <span className="mono">{formatBytes(bytes)}</span>
            </span>
            <Button variant={danger ? "danger" : "primary"} size="sm" onClick={onAction} disabled={busy}>
              {Icon && <Icon className="h-3.5 w-3.5" />}
              {actionLabel}
            </Button>
            <Button variant="ghost" size="icon" onClick={onClear} aria-label="Clear selection">
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
