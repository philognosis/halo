import { useState } from 'react'
import type {
  ChatIntent,
  Candidate,
  ComparisonResponse,
  TeamShapeResponse,
  ApprovalStatus,
} from '../types'
import ScoreBar from './ScoreBar'
import AvailabilityBadge from './AvailabilityBadge'

interface Props {
  intent: ChatIntent
  response: string
  data?: unknown
}

// ── Intent badge ──────────────────────────────────────────────────────────────

const INTENT_STYLE: Record<ChatIntent, string> = {
  SEARCH:     'bg-blue-100 text-blue-800',
  SHORTLIST:  'bg-indigo-100 text-indigo-800',
  COMPARE:    'bg-purple-100 text-purple-800',
  TEAM_SHAPE: 'bg-teal-100 text-teal-800',
  STATUS:     'bg-orange-100 text-orange-800',
  GREETING:   'bg-gray-100 text-gray-700',
  UNKNOWN:    'bg-gray-100 text-gray-700',
}

function IntentBadge({ intent }: { intent: ChatIntent }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${INTENT_STYLE[intent]}`}>
      {intent}
    </span>
  )
}

// ── Candidate card ────────────────────────────────────────────────────────────

function CandidateCard({ candidate }: { candidate: Candidate }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-gray-900 truncate">{candidate.name}</h3>
            {candidate.availability_phase && (
              <AvailabilityBadge phase={candidate.availability_phase} />
            )}
            {candidate.gate_passed ? (
              <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 ring-1 ring-green-200">
                Gate Passed
              </span>
            ) : (
              <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-red-100 text-red-700 ring-1 ring-red-200">
                Gate Failed
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-gray-400">ID: {candidate.person_id}</p>
        </div>
        <div className="flex-shrink-0 text-right">
          <span className="text-2xl font-bold tabular-nums text-gray-900">
            {Math.round(candidate.score)}
          </span>
          <span className="text-xs text-gray-400">/100</span>
        </div>
      </div>

      <ScoreBar score={candidate.score} showLabel={false} className="mt-3" />

      {Object.keys(candidate.factors).length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
          {Object.entries(candidate.factors).map(([k, v]) => (
            <div key={k}>
              <div className="flex justify-between text-xs text-gray-500 mb-0.5">
                <span className="truncate capitalize">{k.replace(/_/g, ' ')}</span>
                <span className="font-medium text-gray-700">{Math.round(v * 100)}</span>
              </div>
              <ScoreBar score={v * 100} showLabel={false} />
            </div>
          ))}
        </div>
      )}

      {candidate.explanation && (
        <div className="mt-3">
          <button
            onClick={() => setExpanded(x => !x)}
            className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800"
          >
            <svg
              className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            {expanded ? 'Hide' : 'Show'} explanation
          </button>
          {expanded && (
            <p className="mt-2 text-sm text-gray-600 leading-relaxed border-l-2 border-indigo-200 pl-3">
              {candidate.explanation}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Candidate list (SEARCH / SHORTLIST) ───────────────────────────────────────

function CandidateList({ candidates }: { candidates: Candidate[] }) {
  if (!candidates.length) {
    return (
      <p className="text-sm text-gray-500 italic">No candidates found.</p>
    )
  }
  return (
    <div className="space-y-3">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        {candidates.length} candidate{candidates.length !== 1 ? 's' : ''}
      </p>
      {candidates.map(c => (
        <CandidateCard key={c.person_id} candidate={c} />
      ))}
    </div>
  )
}

// ── Comparison table (COMPARE) ────────────────────────────────────────────────

function ComparisonTable({ data }: { data: ComparisonResponse }) {
  const { persons, comparison } = data
  const factors = Object.keys(comparison)

  if (!persons.length) {
    return <p className="text-sm text-gray-500 italic">No comparison data.</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="py-3 pl-4 pr-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Factor
            </th>
            {persons.map(p => (
              <th
                key={p.id}
                className="px-3 py-3 text-center text-xs font-semibold text-gray-700"
              >
                {p.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {factors.map(factor => (
            <tr key={factor} className="hover:bg-gray-50">
              <td className="whitespace-nowrap py-2.5 pl-4 pr-3 text-xs font-medium text-gray-600 capitalize">
                {factor.replace(/_/g, ' ')}
              </td>
              {persons.map(p => {
                const val = comparison[factor]?.[p.id]
                const num = typeof val === 'number' ? val : null
                return (
                  <td key={p.id} className="px-3 py-2.5 text-center">
                    {num !== null ? (
                      <div className="flex flex-col items-center gap-1">
                        <ScoreBar score={num * 100} showLabel className="w-20" />
                      </div>
                    ) : (
                      <span className="text-gray-400">{String(val ?? '—')}</span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Team shape (TEAM_SHAPE) ───────────────────────────────────────────────────

function TeamShapeView({ data }: { data: TeamShapeResponse }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Recommended Roles
        </span>
        <span className="text-sm font-medium text-gray-700">
          Total FTE: <span className="font-bold text-indigo-700">{data.total_fte}</span>
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {data.roles.map((role, i) => (
          <div
            key={i}
            className="rounded-lg border border-teal-100 bg-teal-50 p-4"
          >
            <div className="flex items-start justify-between gap-2">
              <h4 className="font-semibold text-gray-900">{role.role}</h4>
              <span className="rounded-full bg-teal-600 px-2.5 py-0.5 text-xs font-bold text-white">
                ×{role.count}
              </span>
            </div>
            {role.rationale && (
              <p className="mt-2 text-xs text-gray-600 leading-relaxed">
                {role.rationale}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Status card (STATUS) ──────────────────────────────────────────────────────

function StatusCard({ data }: { data: ApprovalStatus }) {
  const dbStatus = (data.db_status as string) ?? (data.workflow_decision as string) ?? 'pending'
  const colors: Record<string, string> = {
    approved: 'border-green-200 bg-green-50 text-green-900',
    rejected: 'border-red-200 bg-red-50 text-red-900',
    pending:  'border-yellow-200 bg-yellow-50 text-yellow-900',
    short_listed: 'border-blue-200 bg-blue-50 text-blue-900',
  }
  const cls = colors[dbStatus] ?? colors.pending
  const workflowId = data.workflow_id as string | undefined
  return (
    <div className={`rounded-lg border p-4 ${cls}`}>
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold uppercase tracking-wide">{dbStatus}</span>
        {workflowId && <span className="text-xs opacity-70">· {workflowId}</span>}
      </div>
      {data.workflow_decision && (
        <p className="mt-1 text-sm opacity-80">Workflow: {String(data.workflow_decision)}</p>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function AdaptiveResponse({ intent, response, data }: Props) {
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2">
        <IntentBadge intent={intent} />
      </div>

      {response && (
        <p className="text-sm text-gray-700 leading-relaxed">{response}</p>
      )}

      {data != null && (() => {
        if (intent === 'SEARCH' || intent === 'SHORTLIST') {
          const candidates = Array.isArray(data)
            ? (data as Candidate[])
            : Array.isArray((data as { candidates?: Candidate[] })?.candidates)
            ? (data as { candidates: Candidate[] }).candidates
            : []
          return <CandidateList candidates={candidates} />
        }

        if (intent === 'COMPARE') {
          const d = data as ComparisonResponse
          if (d?.persons && d?.comparison) {
            return <ComparisonTable data={d} />
          }
        }

        if (intent === 'TEAM_SHAPE') {
          const d = data as TeamShapeResponse
          if (d?.roles) {
            return <TeamShapeView data={d} />
          }
        }

        if (intent === 'STATUS') {
          const d = data as ApprovalStatus
          if (d?.status) {
            return <StatusCard data={d} />
          }
        }

        // Fallback: pretty-print JSON
        return (
          <pre className="rounded-lg bg-gray-900 p-4 text-xs text-green-300 overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(data, null, 2)}
          </pre>
        )
      })()}
    </div>
  )
}
