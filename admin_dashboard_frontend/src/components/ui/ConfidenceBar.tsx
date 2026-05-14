interface ConfidenceBarProps {
  value: number; // 0 to 1
}

export default function ConfidenceBar({ value }: ConfidenceBarProps) {
  const percentage = Math.round(value * 100);
  const isHigh = value >= 0.7; 
  const colorClass = isHigh ? 'bg-green-500' : 'bg-orange-500';
  const textColorClass = isHigh ? 'text-green-600' : 'text-orange-600';

  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden max-w-[100px]">
        <div
          className={`h-full ${colorClass} rounded-full`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className={`text-sm font-medium ${textColorClass}`}>
        {percentage}%
      </span>
    </div>
  );
}
