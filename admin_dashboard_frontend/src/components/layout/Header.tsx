"use client";

import { useRouter } from 'next/navigation';
import { clearSession } from '@/lib/auth';
import { apiLogout } from '@/lib/api';

interface HeaderProps {
  title: string;
  username?: string;
  role?: 'admin' | 'expert';
  timeRemainingMs?: number;
}

function formatTime(ms: number) {
  const totalSecs = Math.floor(ms / 1000);
  const mins = Math.floor(totalSecs / 60);
  const secs = totalSecs % 60;
  return `${mins}m ${String(secs).padStart(2, '0')}s`;
}

export default function Header({ title, username, role, timeRemainingMs = 0 }: HeaderProps) {
  const router = useRouter();

  const handleLogout = async () => {
    await apiLogout().catch(() => {});
    clearSession();
    router.push('/login');
  };

  const isExpiringSoon = timeRemainingMs > 0 && timeRemainingMs < 5 * 60 * 1000;

  return (
    <header className="h-16 px-8 flex items-center justify-between sticky top-0 z-20 shrink-0 bg-white border-b border-slate-200">
      <h2 className="text-lg font-medium text-slate-900">{title}</h2>

      <div className="flex items-center gap-4">
        {timeRemainingMs > 0 && (
          <span className={`hidden sm:inline text-xs font-medium px-2.5 py-1 rounded-full ${
            isExpiringSoon
              ? 'bg-amber-50 text-amber-700 border border-amber-200'
              : 'bg-slate-100 text-slate-500'
          }`}>
            ⏱ {formatTime(timeRemainingMs)}
          </span>
        )}

        {role && (
          <span className={`hidden sm:inline text-xs font-semibold px-2.5 py-1 rounded-full ${
            role === 'admin'
              ? 'bg-green-50 text-green-700 border border-green-200'
              : 'bg-blue-50 text-blue-700 border border-blue-200'
          }`}>
            {role === 'admin' ? '🛡 Admin' : '👤 Expert'}
          </span>
        )}

        {username && (
          <span className="hidden md:inline text-sm font-medium text-slate-700">
            {username}
          </span>
        )}

        <button
          onClick={handleLogout}
          className="px-4 py-1.5 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium transition-colors"
        >
          Logout
        </button>
      </div>
    </header>
  );
}
