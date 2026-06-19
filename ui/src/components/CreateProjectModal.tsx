import { useState } from 'react'
import { createProject } from '../api/client'

const REGIONS = ['EMEA', 'Americas', 'APAC'] as const

interface Props {
  open: boolean
  onClose: () => void
  onCreated: () => void
}

interface FormState {
  unique_code: string
  client: string
  project_name: string
  start_date: string
  end_date: string
  industry: string
  sector: string
  function: string
  region: string
}

const EMPTY: FormState = {
  unique_code: '',
  client: '',
  project_name: '',
  start_date: '',
  end_date: '',
  industry: '',
  sector: '',
  function: '',
  region: '',
}

export default function CreateProjectModal({ open, onClose, onCreated }: Props) {
  const [form, setForm] = useState<FormState>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
  ) => {
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)

    const body: Record<string, unknown> = {
      unique_code: form.unique_code,
      client: form.client,
      project_name: form.project_name,
      start_date: form.start_date,
      industry: form.industry,
      sector: form.sector,
      function: form.function,
      region: form.region,
      status: 'active',
    }
    if (form.end_date) body.end_date = form.end_date

    try {
      await createProject(body)
      setForm(EMPTY)
      onCreated()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create project')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={handleBackdropClick}
    >
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4 flex-shrink-0">
          <h2 className="text-lg font-semibold text-gray-900">New Project</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            aria-label="Close"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4 overflow-y-auto">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Code + Client */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="unique_code">
                Code <span className="text-red-500">*</span>
              </label>
              <input
                id="unique_code"
                name="unique_code"
                type="text"
                value={form.unique_code}
                onChange={handleChange}
                required
                placeholder="e.g. PRJ-001"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="client">
                Client <span className="text-red-500">*</span>
              </label>
              <input
                id="client"
                name="client"
                type="text"
                value={form.client}
                onChange={handleChange}
                required
                placeholder="Client name"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          {/* Project Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="project_name">
              Project Name <span className="text-red-500">*</span>
            </label>
            <input
              id="project_name"
              name="project_name"
              type="text"
              value={form.project_name}
              onChange={handleChange}
              required
              placeholder="e.g. Digital Transformation Initiative"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          {/* Dates */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="start_date">
                Start Date <span className="text-red-500">*</span>
              </label>
              <input
                id="start_date"
                name="start_date"
                type="date"
                value={form.start_date}
                onChange={handleChange}
                required
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="end_date">
                End Date <span className="text-gray-400 text-xs">(optional)</span>
              </label>
              <input
                id="end_date"
                name="end_date"
                type="date"
                value={form.end_date}
                onChange={handleChange}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          {/* Industry + Sector */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="industry">
                Industry <span className="text-red-500">*</span>
              </label>
              <input
                id="industry"
                name="industry"
                type="text"
                value={form.industry}
                onChange={handleChange}
                required
                placeholder="e.g. Financial Services"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="sector">
                Sector <span className="text-red-500">*</span>
              </label>
              <input
                id="sector"
                name="sector"
                type="text"
                value={form.sector}
                onChange={handleChange}
                required
                placeholder="e.g. Banking"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          {/* Function + Region */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="function">
                Function <span className="text-red-500">*</span>
              </label>
              <input
                id="function"
                name="function"
                type="text"
                value={form.function}
                onChange={handleChange}
                required
                placeholder="e.g. Strategy"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="region">
                Region <span className="text-red-500">*</span>
              </label>
              <select
                id="region"
                name="region"
                value={form.region}
                onChange={handleChange}
                required
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="">Select a region…</option>
                {REGIONS.map(r => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {submitting ? 'Creating…' : 'Create Project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
