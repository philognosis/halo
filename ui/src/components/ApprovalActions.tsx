import { useState } from 'react'
import {
  approveAssignment,
  rejectAssignment,
  getAssignmentStatus,
} from '../api/client'
import type { ApprovalStatus } from '../types'

interface Props {
  assignmentId: string
  approverId: string
  onDone?: (status: ApprovalStatus) => void
}

export default function ApprovalActions({ assignmentId, approverId, onDone }: Props) {
  const [status, setStatus] = useState<ApprovalStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectForm, setShowRejectForm] = useState(false)
  const [approveNotes, setApproveNotes] = useState('')

  const handleApprove = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await approveAssignment(assignmentId, approverId, approveNotes || undefined)
      setStatus(result)
      onDone?.(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approval failed')
    } finally {
      setLoading(false)
    }
  }

  const handleReject = async () => {
    if (!rejectReason.trim()) {
      setError('Please provide a reason for rejection')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const result = await rejectAssignment(assignmentId, approverId, rejectReason)
      setStatus(result)
      onDone?.(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Rejection failed')
    } finally {
      setLoading(false)
    }
  }

  const handleCheckStatus = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await getAssignmentStatus(assignmentId)
      setStatus(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Status check failed')
    } finally {
      setLoading(false)
    }
  }

  if (status) {
    const dbStatus = (status.db_status as string) ?? (status.workflow_decision as string) ?? 'pending'
    const colors: Record<string, string> = {
      approved: 'bg-green-50 border-green-200 text-green-800',
      rejected: 'bg-red-50 border-red-200 text-red-800',
      pending: 'bg-yellow-50 border-yellow-200 text-yellow-800',
      short_listed: 'bg-blue-50 border-blue-200 text-blue-800',
    }
    const cls = colors[dbStatus] ?? colors.pending
    return (
      <div className={`rounded-lg border p-3 text-sm font-medium ${cls}`}>
        Assignment: <span className="capitalize">{dbStatus.replace('_', ' ')}</span>
        {status.workflow_decision && (
          <p className="mt-1 font-normal opacity-80">Workflow: {String(status.workflow_decision)}</p>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {error && (
        <p className="text-xs text-red-600">{error}</p>
      )}

      {!showRejectForm ? (
        <div className="flex flex-wrap gap-2">
          <div className="flex flex-1 gap-2">
            <input
              type="text"
              placeholder="Optional approval notes…"
              value={approveNotes}
              onChange={e => setApproveNotes(e.target.value)}
              className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <button
              onClick={handleApprove}
              disabled={loading}
              className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {loading ? 'Processing…' : 'Approve'}
            </button>
          </div>
          <button
            onClick={() => setShowRejectForm(true)}
            disabled={loading}
            className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            Reject
          </button>
          <button
            onClick={handleCheckStatus}
            disabled={loading}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Check Status
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <textarea
            rows={2}
            placeholder="Reason for rejection (required)"
            value={rejectReason}
            onChange={e => setRejectReason(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-red-400 focus:outline-none focus:ring-1 focus:ring-red-400"
          />
          <div className="flex gap-2">
            <button
              onClick={handleReject}
              disabled={loading}
              className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {loading ? 'Processing…' : 'Confirm Reject'}
            </button>
            <button
              onClick={() => { setShowRejectForm(false); setError(null) }}
              disabled={loading}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
