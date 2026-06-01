"use client";

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Users,
  PhoneCall,
  BookOpen,
  HeadphonesIcon,
  TrendingUp,
  Bell,
  ShieldCheck,
  Activity,
  BarChart2,
} from 'lucide-react';

import type { UserRole } from '@/types';

interface NavItem {
  label: string;
  path: string;
  icon: React.ReactNode;
  roles: UserRole[];
}

const allNavItems: NavItem[] = [
  { label: 'Dashboard',       path: '/',               icon: <LayoutDashboard size={16} />, roles: ['admin', 'da', 'expert'] },
  { label: 'Users',           path: '/users',          icon: <ShieldCheck size={16} />,     roles: ['admin'] },
  { label: 'Farmer Profiles', path: '/farmers',        icon: <Users size={16} />,           roles: ['admin', 'da'] },
  { label: 'Call Logs',       path: '/calls',          icon: <PhoneCall size={16} />,       roles: ['admin', 'da', 'expert'] },
  { label: 'Helpdesk',        path: '/helpdesk',       icon: <HeadphonesIcon size={16} />,  roles: ['admin', 'da', 'expert'] },
  { label: 'Knowledge Base',  path: '/knowledge-base', icon: <BookOpen size={16} />,        roles: ['admin'] },
  { label: 'Market Prices',   path: '/market-prices',  icon: <TrendingUp size={16} />,      roles: ['admin', 'da'] },
  { label: 'Alerts',          path: '/alerts',         icon: <Bell size={16} />,            roles: ['admin', 'da'] },
  { label: 'Monitoring',      path: '/monitoring',     icon: <Activity size={16} />,        roles: ['admin', 'da', 'expert'] },
  { label: 'Analytics',       path: '/analytics',      icon: <BarChart2 size={16} />,       roles: ['admin', 'da'] },
];

type SidebarProps = {
  role: UserRole | null;
};

export default function Sidebar({ role }: SidebarProps) {
  const pathname = usePathname();
  const navItems = allNavItems.filter((item) => !role || item.roles.includes(role));

  return (
    <aside className="flex flex-col h-full">
      <div className="h-16 px-6 flex items-center mb-4 mt-2 border-b border-slate-100">
        <h1 className="text-base font-semibold text-green-700 leading-tight">
          Farmer Advisory<br />
          <span className="text-xs font-normal text-slate-400">Admin Panel</span>
        </h1>
      </div>

      <nav className="flex-1 px-4 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          const isActive =
            pathname === item.path ||
            (item.path !== '/' && pathname.startsWith(item.path));

          return (
            <Link
              key={item.path}
              href={item.path}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-green-50 text-green-700'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
              }`}
            >
              <span className={isActive ? 'text-green-600' : 'text-slate-400'}>
                {item.icon}
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {role && (
        <div className="px-6 py-4 border-t border-slate-100">
          <p className="text-xs text-slate-400 font-medium uppercase tracking-wide">
            {role === 'admin'
              ? 'Administrator'
              : role === 'da'
              ? 'Development Agent'
              : 'Expert'}
          </p>
        </div>
      )}
    </aside>
  );
}
