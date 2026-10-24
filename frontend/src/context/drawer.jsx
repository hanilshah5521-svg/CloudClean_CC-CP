import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";

/**
 * The right-hand details drawer. Any screen opens it with a plain description
 * of the item — no page-specific drawer code:
 *
 *   open({
 *     kind: "File",                      // small label above the title
 *     title, subtitle,
 *     badges: [{ label, tone }],
 *     fields: [{ label, value, mono, href }],
 *     reason,                            // why CloudClean suggests something
 *     body,                              // optional extra React node
 *     actions: [{ label, onClick, variant, icon }],
 *   })
 */
const DrawerContext = createContext(null);

export function DrawerProvider({ children }) {
  const [item, setItem] = useState(null);
  const location = useLocation();
  const close = useCallback(() => setItem(null), []);

  useEffect(close, [location.pathname, close]);

  const value = useMemo(() => ({ item, open: setItem, close }), [item, close]);
  return <DrawerContext.Provider value={value}>{children}</DrawerContext.Provider>;
}

export function useDrawer() {
  const ctx = useContext(DrawerContext);
  if (!ctx) throw new Error("useDrawer must be used within DrawerProvider");
  return ctx;
}
