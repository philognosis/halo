import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getPerson, getPersons, postCompare } from '../api/client'
import type { Person, ComparisonResponse } from '../types'
import AvailabilityBadge from '../components/AvailabilityBadge'
import NotificationFeed from '../components/NotificationFeed'
import AdaptiveResponse from '../components/AdaptiveResponse'

export default function PersonDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [person, setPerson] = useState<Person | null>(null)
  const [allPersons, setAllPersons] = useState<Person[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Compare state
  const [compareIds, setCompareIds] = useState<string[]>([])
  const [comparing, setComparing] = useState(false)
  const [compareResult, setCompareResult] = useState<ComparisonResponse | null>(null)
  const [compareError, setCompareError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const [p, all] = await Promise.all([getPerson(id), getPersons()])
      setPerson(p)
      setAllPersons(all.filter(x => x.id !== id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load person')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  const handleCompare = async () => {
    if (!id || compareIds.length === 0) return
    setComparing(true)
    setCompareError(null)
    setCompareResult(null)
    try {
      const result = await postCompare([id, ...compareIds])
      setCompareResult(result)
    } catch (e) {
      setCompareError(e instanceof Error ? e.message : 'Comparison failed')
    } finally {
      setComparing(false)
    }
  }

  const toggleCompareId = (pid: string) => {
    setCompareIds(prev =>
      prev.includes(pid) ? prev.filter(x => x !== pid) : [...prev, pid]
    )
  }

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-32 rounded-xl bg-gray-100" />
        <div className="h-64 rounded-xl bg-gray-100" />
      </div>
    )
  }

  if (error || !person) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {error ?? 'Person not found.'}
        <button onClick={() => navigate('/people')} className="ml-3 underline">Back to People</button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Back */}
      <button
        onClick={() => navigate('/people')}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        Back to People
      </button>

      {/* Profile card */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-start gap-4">
          <div className="flex h-16 w-16 flex-shrink-0 items-center justify-center rounded-full bg-indigo-100 text-2xl font-bold text-indigo-600">
            {person.name.charAt(0).toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-xl font-bold text-gray-900">{person.name}</h2>
              <AvailabilityBadge phase={person.availability_phase} />
            </div>
            {person.role && (
              <p className="mt-0.5 text-sm text-gray-600">{person.role}</p>
            )}
            {person.email && (
              <p className="mt-0.5 text-xs text-gray-400">{person.email}</p>
            )}
            {person.band && (
              <p className="mt-0.5 text-xs text-gray-500">
                Band: <span className="font-medium">{person.band}</span>
              </p>
            )}
          </div>
          <div className="flex-shrink-0 text-xs text-gray-400">
            ID: {person.id}
          </div>
        </div>

        {/* Skills */}
        {person.skills && person.skills.length > 0 && (
          <div className="mt-5 border-t border-gray-100 pt-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Skills</h3>
            <div className="flex flex-wrap gap-1.5">
              {person.skills.map((skill, i) => (
                <span
                  key={typeof skill === 'string' ? skill : skill.skill_name ?? i}
                  className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-medium text-indigo-700 ring-1 ring-indigo-100"
                >
                  {typeof skill === 'string' ? skill : skill.skill_name ?? '—'}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Extra fields */}
        {Object.entries(person)
          .filter(([k]) => !['id','name','role','email','department','skills','availability_phase'].includes(k))
          .filter(([, v]) => v != null && v !== '' && typeof v !== 'object')
          .length > 0 && (
          <div className="mt-4 border-t border-gray-100 pt-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Additional Info</h3>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3 text-sm">
              {Object.entries(person)
                .filter(([k]) => !['id','name','role','email','department','skills','availability_phase'].includes(k))
                .filter(([, v]) => v != null && v !== '' && typeof v !== 'object')
                .map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-xs text-gray-400 capitalize">{k.replace(/_/g, ' ')}</dt>
                    <dd className="font-medium text-gray-800">{String(v)}</dd>
                  </div>
                ))}
            </dl>
          </div>
        )}
      </div>

      {/* Compare action */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-5 py-4">
          <h3 className="font-semibold text-gray-900">Compare with Others</h3>
          <p className="text-xs text-gray-500 mt-0.5">Select one or more people to compare against {person.name}</p>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 max-h-48 overflow-y-auto pr-1">
            {allPersons.map(p => (
              <label
                key={p.id}
                className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 text-sm transition-colors ${
                  compareIds.includes(p.id)
                    ? 'border-indigo-300 bg-indigo-50 text-indigo-800'
                    : 'border-gray-200 hover:border-gray-300 text-gray-700'
                }`}
              >
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 accent-indigo-600"
                  checked={compareIds.includes(p.id)}
                  onChange={() => toggleCompareId(p.id)}
                />
                <span className="truncate">{p.name}</span>
              </label>
            ))}
          </div>

          <button
            onClick={handleCompare}
            disabled={compareIds.length === 0 || comparing}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {comparing
              ? 'Comparing…'
              : `Compare${compareIds.length > 0 ? ` (${compareIds.length + 1} people)` : ''}`}
          </button>

          {compareError && (
            <p className="text-sm text-red-600">{compareError}</p>
          )}

          {compareResult && (
            <div className="mt-2">
              <AdaptiveResponse
                intent="COMPARE"
                response=""
                data={compareResult}
              />
            </div>
          )}
        </div>
      </div>

      {/* Notifications */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-5 py-4">
          <h3 className="font-semibold text-gray-900">Notifications</h3>
        </div>
        <div className="p-5">
          <NotificationFeed personId={person.id} />
        </div>
      </div>
    </div>
  )
}
