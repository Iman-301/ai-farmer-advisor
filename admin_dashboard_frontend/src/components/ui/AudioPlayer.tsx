interface AudioPlayerProps {
  src: string;
  label?: string;
  detail?: string;
  autoPlay?: boolean;
  compact?: boolean;
  className?: string;
}

export default function AudioPlayer({
  src,
  label = 'Recording',
  detail,
  autoPlay = false,
  compact = false,
  className = '',
}: AudioPlayerProps) {
  return (
    <div
      className={`rounded-lg border border-slate-200 bg-white shadow-sm ${
        compact ? 'p-3' : 'p-4'
      } ${className}`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="min-w-0 sm:w-40 shrink-0">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
            {label}
          </p>
          {detail && (
            <p className="mt-1 truncate text-xs text-slate-400">{detail}</p>
          )}
        </div>
        <audio
          controls
          autoPlay={autoPlay}
          src={src}
          className="h-10 w-full flex-1 accent-green-600"
        />
      </div>
    </div>
  );
}
