import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, X } from "lucide-react";
import { Button } from "../ui/button.jsx";
import { ButtonLink } from "../GoogleLinks.jsx";
import { Badge } from "../ui/primitives.jsx";
import { useDrawer } from "../../context/drawer.jsx";
import { cn } from "../../lib/cn.js";

function useIsDesktop() {
  const query = "(min-width: 1024px)";
  const [desktop, setDesktop] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setDesktop(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return desktop;
}

function DrawerBody({ item, close }) {
  const [busy, setBusy] = useState(null);
  async function run(action) {
    setBusy(action.label);
    try {
      await action.onClick();
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          {item.kind && <div className="text-[11px] font-medium uppercase tracking-[0.04em] text-faint">{item.kind}</div>}
          <h2 className="mt-0.5 break-words text-[14px] font-semibold text-ink">{item.title}</h2>
          {item.subtitle && <p className="mt-0.5 break-words text-[12px] text-sub">{item.subtitle}</p>}
          {item.badges?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {item.badges.map((b) => (
                <Badge key={b.label} tone={b.tone}>{b.label}</Badge>
              ))}
            </div>
          )}
        </div>
        <Button variant="ghost" size="icon" onClick={close} aria-label="Close details">
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {item.fields?.length > 0 && (
          <dl className="divide-y divide-line rounded border border-line">
            {item.fields.map((f) => (
              <div key={f.label} className="grid grid-cols-[110px_1fr] gap-2 px-3 py-1.5 text-[12px]">
                <dt className="text-faint">{f.label}</dt>
                <dd className={cn("min-w-0 break-all text-ink", f.mono && "mono")}>
                  {f.href ? (
                    <a href={f.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent-ink hover:underline">
                      {f.value} <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : (
                    f.value ?? "—"
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {item.reason && (
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.04em] text-faint">Why</div>
            <p className="whitespace-pre-line text-[12px] leading-relaxed text-ink">{item.reason}</p>
          </div>
        )}
        {item.body}
      </div>

      {item.actions?.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-line px-4 py-3">
          {item.actions.map((a) =>
            "href" in a ? (
              <ButtonLink key={a.label} href={a.href} icon={a.icon} disabledReason={a.disabledReason}>
                {a.label}
              </ButtonLink>
            ) : (
              <Button key={a.label} variant={a.variant || "secondary"} size="sm" disabled={!!busy} onClick={() => run(a)}>
                {a.icon && <a.icon className="h-3.5 w-3.5" />}
                {busy === a.label ? "Working…" : a.label}
              </Button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

/** Right panel (340px) on desktop; bottom sheet on smaller screens. */
export default function DetailsDrawer() {
  const { item, close } = useDrawer();
  const desktop = useIsDesktop();

  useEffect(() => {
    if (!item) return undefined;
    const onKey = (e) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item, close]);

  if (desktop) {
    return (
      <AnimatePresence initial={false}>
        {item && (
          <motion.aside
            key="drawer"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 340, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="shrink-0 overflow-hidden border-l border-line bg-surface"
            aria-label="Details"
          >
            <div className="h-full w-[340px]">
              <DrawerBody item={item} close={close} />
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    );
  }
  return (
    <AnimatePresence>
      {item && (
        <>
          <motion.div
            key="scrim"
            className="fixed inset-0 z-40 bg-scrim/30"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={close}
          />
          <motion.aside
            key="sheet"
            role="dialog"
            aria-label="Details"
            className="fixed inset-x-0 bottom-0 z-50 max-h-[82vh] rounded-t-lg border-t border-line bg-surface"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ duration: 0.22, ease: "easeOut" }}
          >
            <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-line" />
            <div className="h-[calc(82vh-12px)]">
              <DrawerBody item={item} close={close} />
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
