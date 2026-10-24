import { forwardRef } from "react";
import { cva } from "class-variance-authority";
import { cn } from "../../lib/cn.js";

export const buttonVariants = cva(
  "tactile inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded border font-medium " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "border-accent bg-accent text-white hover:border-accent-hover hover:bg-accent-hover",
        secondary: "border-line bg-surface text-ink hover:border-line-strong",
        ghost: "border-transparent bg-transparent text-sub hover:bg-ink/[0.05] hover:text-ink",
        // Destructive: red outline that fills solid on hover.
        danger: "border-bad bg-surface text-bad-ink hover:bg-bad hover:text-white",
        ok: "border-ok bg-ok text-white hover:bg-ok/90",
      },
      size: {
        sm: "h-7 px-2.5 text-[12px]",
        md: "h-8 px-3 text-[13px]",
        lg: "h-9 px-4 text-[13px]",
        icon: "h-7 w-7 p-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export const Button = forwardRef(function Button({ className, variant, size, type = "button", ...props }, ref) {
  return <button ref={ref} type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
});
