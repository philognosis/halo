import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getPersons } from '../api/client'
import type { Person } from '../types'
import AvailabilityBadge from '../components/AvailabilityBadge'

export default function PeoplePage() {
  const [persons, setPersons] = useState<Person[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true)
    getPersons()
      .then(setPersons)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load people'))
      .finally(() => setLoading(false))
  }, [])

  const filtered = persons.filter(p => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      p.name.toLowerCase().includes(q) ||
      p.role?.toLowerCase().includes(q) ||
      p.department?.toLowerCase().includes(q) ||
      p.email?.toLowerCase().includes(q)
    )
  })

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="search"
            placeholder="Search people…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
        <span className="text-sm text-gray-500">
          {loading ? '…' : `${filtered.length} of ${persons.length}`}
        </span>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        {loading ? (
          <div className="space-y-px">
            {[1,2,3,4,5].map(i => (
              <div key={i} className="flex items-center gap-4 px-5 py-3.5">
                <div className="h-4 w-40 animate-pulse rounded bg-gray-100" />
                <div className="h-4 w-24 animate-pulse rounded bg-gray-100" />
                <div className="h-4 w-20 animate-pulse rounded bg-gray-100 ml-auto" />
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="p-6 text-sm text-red-600">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-gray-400">
            {search ? 'No people match your search.' : 'No people found.'}
          </div>
        ) : (
          <table className="min-w-full divide-y divide-gray-100">
            <thead className="bg-gray-50">
              <tr>
                <th className="py-3 pl-5 pr-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Name
                </th>
                <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hidden sm:table-cell">
                  Role
                </th>
                <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hidden md:table-cell">
                  Department
                </th>
                <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Availability
                </th>
                <th className="py-3 pl-3 pr-5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Action
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map(person => (
                <tr
                  key={person.id}
                  className="group cursor-pointer hover:bg-indigo-50 transition-colors"
                  onClick={() => navigate(`/people/${person.id}`)}
                >
                  <td className="py-3 pl-5 pr-3">
                    <div>
                      <p className="font-medium text-gray-900 group-hover:text-indigo-700">
                        {person.name}
                      </p>
                      {person.email && (
                        <p className="text-xs text-gray-400 mt-0.5">{person.email}</p>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-sm text-gray-600 hidden sm:table-cell">
                    {person.role ?? '—'}
                  </td>
                  <td className="px-3 py-3 text-sm text-gray-600 hidden md:table-cell">
                    {person.department ?? '—'}
                  </td>
                  <td className="px-3 py-3">
                    <AvailabilityBadge phase={person.availability_phase} />
                  </td>
                  <td className="py-3 pl-3 pr-5 text-right">
                    <button
                      className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
                      onClick={e => {
                        e.stopPropagation()
                        navigate(`/people/${person.id}`)
                      }}
                    >
                      View →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
