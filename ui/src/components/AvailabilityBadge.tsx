import type { AvailabilityPhase } from '../types'

interface Props {
  phase?: AvailabilityPhase | string
  className?: string
}

const CONFIG: Record<string, { label: string; classes: string }> = {
  Available: {
    label: 'Available',
    classes: 'bg-green-100 text-green-800 ring-1 ring-green-200',
  },
  PartiallyAllocated: {
    label: 'Partial',
    classes: 'bg-yellow-100 text-yellow-800 ring-1 ring-yellow-200',
  },
  FullyAllocated: {
    label: 'Full',
    classes: 'bg-red-100 text-red-800 ring-1 ring-red-200',
  },
  OnLeave: {
    label: 'On Leave',
    classes: 'bg-gray-100 text-gray-700 ring-1 ring-gray-200',
  },
}

export default function AvailabilityBadge({ phase, className = '' }: Props) {
  const cfg = phase ? CONFIG[phase] : undefined
  if (!cfg) {
    return (
      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-gray-100 text-gray-500 ${className}`}>
        Unknown
      </span>
    )
  }
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cfg.classes} ${className}`}>
      {cfg.label}
    </span>
  )
}
