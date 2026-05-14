interface BadgeProps {
  label: string;
  variant: 'success' | 'warning' | 'info' | 'danger' | 'neutral';
}

export default function Badge({ label, variant }: BadgeProps) {
  const styles = {
    success: 'bg-green-50 text-green-700',
    warning: 'bg-orange-50 text-orange-700',
    info: 'bg-blue-50 text-blue-700',
    danger: 'bg-red-50 text-red-700',
    neutral: 'bg-slate-100 text-slate-700',
  };

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${styles[variant]}`}
    >
      {label}
    </span>
  );
}
