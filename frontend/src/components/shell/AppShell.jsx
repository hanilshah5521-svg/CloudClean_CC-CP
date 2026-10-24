import { Suspense, useState } from "react";
import { Outlet } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { DrawerProvider } from "../../context/drawer.jsx";
import { ScanProvider } from "../../context/scan.jsx";
import { useUser } from "../../hooks/useUser.jsx";
import Sidebar from "./Sidebar.jsx";
import TopBar from "./TopBar.jsx";
import DetailsDrawer from "./DetailsDrawer.jsx";
import { Card, SkeletonRows } from "../ui/primitives.jsx";

/** 3-panel desktop shell: sidebar | workspace | details drawer, each scrolling on its own. */
export default function AppShell() {
  const { user } = useUser();
  const [navOpen, setNavOpen] = useState(false);

  return (
    <ScanProvider>
      <DrawerProvider>
        <div className="flex h-screen overflow-hidden">
          <aside className="hidden w-60 shrink-0 border-r border-line lg:block">
            <Sidebar />
          </aside>

          <AnimatePresence>
            {navOpen && (
              <>
                <motion.div
                  className="fixed inset-0 z-40 bg-scrim/30 lg:hidden"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  onClick={() => setNavOpen(false)}
                />
                <motion.aside
                  className="fixed inset-y-0 left-0 z-50 w-60 border-r border-line lg:hidden"
                  initial={{ x: -240 }}
                  animate={{ x: 0 }}
                  exit={{ x: -240 }}
                  transition={{ duration: 0.18, ease: "easeOut" }}
                >
                  <Sidebar onNavigate={() => setNavOpen(false)} />
                </motion.aside>
              </>
            )}
          </AnimatePresence>

          <div className="flex min-w-0 flex-1 flex-col">
            {user?.is_demo && (
              <div className="shrink-0 border-b border-warn/30 bg-warn-soft px-4 py-1 text-center text-[12px] font-medium text-warn-ink">
                Demo Mode — simulated Drive, Gmail and S3 data. Nothing real is touched.
              </div>
            )}
            <TopBar onMenu={() => setNavOpen(true)} />
            <main className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-[1280px] px-4 py-5 lg:px-6">
                <Suspense fallback={<Card bodyClassName="p-0"><SkeletonRows rows={8} /></Card>}>
                  <Outlet />
                </Suspense>
              </div>
            </main>
          </div>

          <DetailsDrawer />
        </div>
      </DrawerProvider>
    </ScanProvider>
  );
}
