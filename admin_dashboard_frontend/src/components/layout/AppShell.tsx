"use client";

import { useEffect, useState, useCallback } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';
import { getSession, getSessionTimeRemaining, clearSession } from '@/lib/auth';
import type { SessionData } from '@/types';

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname  = usePathname();
  const router    = useRouter();
  const isLogin   = pathname === '/login';

  const [session, setSession]         = useState<SessionData | null>(null);
  const [timeRemaining, setRemaining] = useState(0);
  const [ready, setReady]             = useState(false);  // avoid SSR flash

  // ── Auth gate ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (isLogin) { setReady(true); return; }
    const s = getSession();
    if (!s) {
      router.replace('/login');
      return;
    }
    setSession(s);
    setRemaining(getSessionTimeRemaining());
    setReady(true);
  }, [isLogin, router, pathname]);

  // ── Session countdown + auto-logout ──────────────────────────────────────
  const handleExpiry = useCallback(() => {
    clearSession();
    router.replace('/login');
  }, [router]);

  useEffect(() => {
    if (isLogin || !session) return;
    const id = setInterval(() => {
      const ms = getSessionTimeRemaining();
      setRemaining(ms);
      if (ms === 0) { clearInterval(id); handleExpiry(); }
    }, 1000);
    return () => clearInterval(id);
  }, [isLogin, session, handleExpiry]);

  // ── Render ────────────────────────────────────────────────────────────────
  if (!ready) return null;  // prevent hydration flash

  if (isLogin) return <>{children}</>;

  return (
    <div className="flex min-h-screen font-sans text-slate-900 bg-slate-50">
      {/* Sticky sidebar */}
      <div className="w-64 shrink-0 hidden lg:block border-r border-slate-200 bg-white h-screen sticky top-0 z-30">
        <Sidebar role={session?.role ?? null} />
      </div>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0 min-h-screen">
        <Header
          title={getPageTitle(pathname)}
          username={session?.username}
          role={session?.role}
          timeRemainingMs={timeRemaining}
        />
        <main className="flex-1 p-10 animate-fade-in">
          <div className="max-w-6xl mx-auto space-y-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

function getPageTitle(pathname: string) {
  const map: Record<string, string> = {
    '/':              'Dashboard',
    '/farmers':       'Farmer Profiles',
    '/calls':         'Call Logs',
    '/knowledge-base':'Knowledge Base',
    '/helpdesk':      'Helpdesk',
    '/market-prices': 'Market Prices',
    '/alerts':        'Alerts & Forecasts',
  };
  return map[pathname] ?? 'Admin Panel';
}
