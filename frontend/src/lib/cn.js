import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes, later ones winning (the shadcn/ui `cn` helper). */
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
