import * as RTabs from "@radix-ui/react-tabs";
import * as RTooltip from "@radix-ui/react-tooltip";
import * as RSlider from "@radix-ui/react-slider";
import { cn } from "../../lib/cn.js";

export const Tabs = RTabs.Root;
export const TabsContent = RTabs.Content;

export function TabsList({ className, children }) {
  return <RTabs.List className={cn("flex gap-1 border-b border-line", className)}>{children}</RTabs.List>;
}

export function TabsTrigger({ value, count, children }) {
  return (
    <RTabs.Trigger
      value={value}
      className="tactile -mb-px border-b-2 border-transparent px-3 py-2 text-[13px] font-medium text-sub hover:text-ink data-[state=active]:border-accent data-[state=active]:text-ink"
    >
      {children}
      {count != null && <span className="mono ml-1.5 text-[11px] text-faint">{count}</span>}
    </RTabs.Trigger>
  );
}

export const TooltipProvider = RTooltip.Provider;

export function Tip({ content, children, side = "top" }) {
  if (!content) return children;
  return (
    <RTooltip.Root delayDuration={250}>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content side={side} sideOffset={6} className="z-50 max-w-xs rounded border border-line bg-ink px-2 py-1 text-[11px] text-canvas">
          {content}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}

export function Slider({ value, onChange, min, max, step = 1, label }) {
  return (
    <RSlider.Root
      className="relative flex h-5 w-full touch-none select-none items-center"
      value={[value]}
      min={min}
      max={max}
      step={step}
      onValueChange={([v]) => onChange(v)}
      aria-label={label}
    >
      <RSlider.Track className="relative h-1 grow rounded-sm bg-track">
        <RSlider.Range className="absolute h-full rounded-sm bg-accent" />
      </RSlider.Track>
      <RSlider.Thumb className="block h-4 w-4 rounded-full border border-accent bg-surface focus:outline-none focus:ring-2 focus:ring-accent/30" />
    </RSlider.Root>
  );
}

export function Checkbox({ checked, onChange, label, className, ...props }) {
  return (
    <input
      type="checkbox"
      checked={!!checked}
      onChange={(e) => onChange?.(e.target.checked)}
      aria-label={label}
      className={cn("h-3.5 w-3.5 cursor-pointer rounded-sm border-line accent-[rgb(var(--accent))]", className)}
      onClick={(e) => e.stopPropagation()}
      {...props}
    />
  );
}

export function Field({ label, hint, children, className }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1 block text-[11px] font-medium uppercase tracking-[0.04em] text-faint">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-sub">{hint}</span>}
    </label>
  );
}
