import { createContext, useCallback, useContext, useState } from "react";
import { CircleCheck, TriangleAlert } from "lucide-react";

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const push = useCallback((message, tone = "success") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, tone }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 6000);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[60] flex w-[min(380px,calc(100vw-32px))] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => {
          const error = t.tone === "error";
          const Icon = error ? TriangleAlert : CircleCheck;
          return (
            <div
              key={t.id}
              className={`pointer-events-auto flex items-start gap-2 rounded border bg-surface px-3 py-2.5 text-[13px] text-ink shadow-[0_4px_16px_rgb(var(--shade)/0.08)] ${
                error ? "border-bad/40" : "border-line"
              }`}
            >
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${error ? "text-bad" : "text-ok"}`} strokeWidth={2} />
              <span>{t.message}</span>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
