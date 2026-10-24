import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useState } from "react";

/**
 * Light / dark / system theme. The choice is stored per browser; "system"
 * follows the OS setting live. index.html applies the same rule before the
 * first paint, so a dark page never flashes white while React loads.
 */
const KEY = "cloudclean-theme";
const ThemeContext = createContext(null);

const darkQuery = () => window.matchMedia("(prefers-color-scheme: dark)");

function storedMode() {
  try {
    const mode = localStorage.getItem(KEY);
    return mode === "light" || mode === "dark" ? mode : "system";
  } catch {
    return "system";
  }
}

// Tokens charts need as real colors: SVG attributes can't resolve var().
const CHART_TOKENS = ["canvas", "surface", "track", "line", "ink", "sub", "faint", "accent", "ok", "warn", "bad", "tier-drive", "tier-trash", "tier-gmail", "tier-s3"];

function readColors() {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    CHART_TOKENS.map((t) => [t.replace(/-(\w)/g, (_, c) => c.toUpperCase()), `rgb(${style.getPropertyValue(`--${t}`).trim().split(/\s+/).join(", ")})`]),
  );
}

export function ThemeProvider({ children }) {
  const [mode, setModeState] = useState(storedMode);
  const [systemDark, setSystemDark] = useState(() => darkQuery().matches);
  const [colors, setColors] = useState(readColors);
  const resolved = mode === "system" ? (systemDark ? "dark" : "light") : mode;

  useLayoutEffect(() => {
    const query = darkQuery();
    const onChange = (e) => setSystemDark(e.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", resolved === "dark");
    setColors(readColors());
  }, [resolved]);

  const setMode = useCallback((next) => {
    setModeState(next);
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      // Storage blocked (private window): the choice lasts for this visit only.
    }
  }, []);

  const value = useMemo(() => ({ mode, resolved, setMode, colors }), [mode, resolved, setMode, colors]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
