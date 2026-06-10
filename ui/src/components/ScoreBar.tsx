interface Props {
  score: number   // 0-100
  showLabel?: boolean
  className?: string
}

function scoreColor(score: number): string {
  if (score >= 75) return 'bg-green-500'
  if (score >= 50) return 'bg-yellow-400'
  if (score >= 25) return 'bg-orange-400'
  return 'bg-red-400'
}

export default function ScoreBar({ score, showLabel = true, className = '' }: Props) {
  const pct = Math.min(100, Math.max(0, score))
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="flex-1 h-2 rounded-full bg-gray-200 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${scoreColor(pct)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className="w-9 text-right text-xs font-semibold tabular-nums text-gray-700">
          {Math.round(pct)}
        </span>
      )}
    </div>
  )
}
