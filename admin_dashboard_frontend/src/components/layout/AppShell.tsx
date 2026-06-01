"use client";

import { useEffect, useState, useCallback } from "react";
import { usePathname, useRouter } from "next/navigation";

import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";

import {
  getSession,
  getSessionTimeRemaining,
  clearSession,
} from "@/lib/auth";

import type { SessionData, UserRole } from "@/types";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const isLogin = pathname === "/login";

  const [session, setSession] = useState<SessionData | null>(null);
  const [timeRemaining, setRemaining] = useState(0);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (isLogin) {
      setReady(true);
      return;
    }

    const currentSession = getSession();

    if (!currentSession) {
      router.replace("/login");
      return;
    }

    setSession(currentSession);
    setRemaining(getSessionTimeRemaining());
    setReady(true);
  }, [isLogin, router, pathname]);

  const handleExpiry = useCallback(() => {
    clearSession();
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    if (isLogin || !session) return;

    const id = setInterval(() => {
      const ms = getSessionTimeRemaining();

      setRemaining(ms);

      if (ms === 0) {
        clearInterval(id);
        handleExpiry();
      }
    }, 1000);

    return () => clearInterval(id);
  }, [isLogin, session, handleExpiry]);

  if (!ready) return null;

  if (isLogin) return <>{children}</>;

  const role: UserRole | null = session?.role ?? null;

  return (
    <div className="flex min-h-screen font-sans text-slate-900 bg-slate-50">
      <div className="w-64 shrink-0 hidden lg:block border-r border-slate-200 bg-white h-screen sticky top-0 z-30">
        <Sidebar role={role} />
      </div>

      <div className="flex-1 flex flex-col min-w-0 min-h-screen">
        <Header
          title={getPageTitle(pathname)}
          username={session?.username}
          role={role}
          timeRemainingMs={timeRemaining}
        />

        <main className="flex-1 p-10 animate-fade-in">
          <div className="max-w-6xl mx-auto space-y-8">{children}</div>
        </main>
      </div>
    </div>
  );
}

function getPageTitle(pathname: string) {
  const map: Record<string, string> = {
    "/": "Dashboard",
    "/da": "Development Agent Dashboard",
    "/expert": "Expert Dashboard",
    "/users": "User Management",
    "/farmers": "Farmer Profiles",
    "/calls": "Call Logs",
    "/knowledge-base": "Knowledge Base",
    "/helpdesk": "Helpdesk",
    "/market-prices": "Market Prices",
    "/alerts": "Alerts & Forecasts",
    "/monitoring": "System Monitoring",
    "/analytics": "Analytics & Reports",
  };

  if (map[pathname]) return map[pathname];
  if (pathname.startsWith("/farmers/")) return "Farmer Detail";
  if (pathname.startsWith("/calls/")) return "Call Session";
  return "Admin Panel";
}