import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "../context/theme.jsx";
import { cn } from "../lib/cn.js";
import { Tip } from "./ui/controls.jsx";

const MODES = [
  { value: "light", label: "Light theme", icon: Sun },
  { value: "dark", label: "Dark theme", icon: Moon },
  { value: "system", label: "Match system setting", icon: Monitor },
];

/** Three-way light / dark / system switch. */
export default function ThemeToggle({ className }) {
  const { mode, setMode } = useTheme();
  return (
    <div role="radiogroup" aria-label="Theme" className={cn("inline-flex rounded border border-line bg-surface p-0.5", className)}>
      {MODES.map((m) => (
        <Tip key={m.value} content={m.label}>
          <button
            type="button"
            role="radio"
            aria-checked={mode === m.value}
            aria-label={m.label}
            onClick={() => setMode(m.value)}
            className={cn(
              "tactile flex h-6 w-7 items-center justify-center rounded-sm",
              mode === m.value ? "bg-accent-soft text-accent-ink" : "text-faint hover:text-ink",
            )}
          >
            <m.icon className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        </Tip>
      ))}
    </div>
  );
}
