import type { ReactNode } from 'react';

interface StatCardProps {
  label: string;
  value: string | number;
  icon: ReactNode;
  iconBgColorClass?: string;
  iconTextColorClass?: string;
}

export default function StatCard({ 
  label, 
  value, 
  icon,
  iconBgColorClass = 'bg-blue-50',
  iconTextColorClass = 'text-blue-600'
}: StatCardProps) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-8 flex items-start justify-between shadow-sm">
      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <p className="text-3xl font-medium text-slate-900">{value}</p>
      </div>
      <div className={`w-12 h-12 rounded-xl flex items-center justify-center shrink-0 ${iconBgColorClass} ${iconTextColorClass}`}>
        {icon}
      </div>
    </div>
  );
}
