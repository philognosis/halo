import { useEffect, useState, useCallback } from 'react'
import { getOpportunities, postRecommend } from '../api/client'
import type { Opportunity, RecommendResponse } from '../types'
import AdaptiveResponse from '../components/AdaptiveResponse'

interface DrawerState {
  oppId: string
  result: RecommendResponse | null
  loading: boolean
  error: string | null
}

export default function OpportunitiesPage() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [drawer, setDrawer] = useState<DrawerState | null>(null)

  useEffect(() => {
    setLoading(true)
    getOpportunities()
      .then(setOpportunities)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load opportunities'))
      .finally(() => setLoading(false))
  }, [])

  const handleRecommend = useCallback(async (opp: Opportunity) => {
    setDrawer({ oppId: opp.id, result: null, loading: true, error: null })
    try {
      const result = await postRecommend(opp.id)
      setDrawer({ oppId: opp.id, result, loading: false, error: null })
    } catch (e) {
      setDrawer({
        oppId: opp.id,
        result: null,
        loading: false,
        error: e instanceof Error ? e.message : 'Recommendation failed',
      })
    }
  }, [])

  const filtered = opportunities.filter(o => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      o.title?.toLowerCase().includes(q) ||
      o.status?.toLowerCase().includes(q) ||
      o.id.toLowerCase().includes(q)
    )
  })

  const STATUS_BADGE: Record<string, string> = {
    open:   'bg-green-100 text-green-800',
    closed: 'bg-gray-100 text-gray-600',
    filled: 'bg-blue-100 text-blue-800',
    draft:  'bg-yellow-100 text-yellow-800',
  }

  return (
    <div className="flex gap-6 h-full -m-6">
      {/* Main list */}
      <div className={`flex flex-1 flex-col min-w-0 overflow-hidden p-6 ${drawer ? 'lg:max-w-[60%]' : ''}`}>
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
                placeholder="Search opportunities…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <span className="text-sm text-gray-500">
              {loading ? '…' : `${filtered.length} of ${opportunities.length}`}
            </span>
          </div>

          {/* Table */}
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
            {loading ? (
              <div className="space-y-px">
                {[1,2,3,4].map(i => (
                  <div key={i} className="flex items-center gap-4 px-5 py-4">
                    <div className="h-4 w-48 animate-pulse rounded bg-gray-100" />
                    <div className="h-4 w-16 animate-pulse rounded bg-gray-100 ml-auto" />
                  </div>
                ))}
              </div>
            ) : error ? (
              <div className="p-6 text-sm text-red-600">{error}</div>
            ) : filtered.length === 0 ? (
              <div className="px-5 py-10 text-center text-sm text-gray-400">
                {search ? 'No opportunities match your search.' : 'No opportunities found.'}
              </div>
            ) : (
              <table className="min-w-full divide-y divide-gray-100">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="py-3 pl-5 pr-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Title
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hidden sm:table-cell">
                      Status
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hidden md:table-cell">
                      Required Skills
                    </th>
                    <th className="py-3 pl-3 pr-5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {filtered.map(opp => {
                    const isActive = drawer?.oppId === opp.id
                    return (
                      <tr
                        key={opp.id}
                        className={`transition-colors ${isActive ? 'bg-indigo-50' : 'hover:bg-gray-50'}`}
                      >
                        <td className="py-3 pl-5 pr-3">
                          <p className="font-medium text-gray-900">{opp.title}</p>
                          <p className="text-xs text-gray-400 mt-0.5">{opp.id}</p>
                        </td>
                        <td className="px-3 py-3 hidden sm:table-cell">
                          {opp.status ? (
                            <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_BADGE[opp.status.toLowerCase()] ?? 'bg-gray-100 text-gray-600'}`}>
                              {opp.status}
                            </span>
                          ) : (
                            <span className="text-gray-400 text-sm">—</span>
                          )}
                        </td>
                        <td className="px-3 py-3 hidden md:table-cell">
                          {opp.required_skills?.length ? (
                            <div className="flex flex-wrap gap-1">
                              {opp.required_skills.slice(0, 3).map(s => (
                                <span key={s} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                                  {s}
                                </span>
                              ))}
                              {opp.required_skills.length > 3 && (
                                <span className="text-xs text-gray-400">+{opp.required_skills.length - 3}</span>
                              )}
                            </div>
                          ) : (
                            <span className="text-gray-400 text-sm">—</span>
                          )}
                        </td>
                        <td className="py-3 pl-3 pr-5 text-right">
                          <button
                            onClick={() => handleRecommend(opp)}
                            disabled={drawer?.oppId === opp.id && drawer.loading}
                            className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                          >
                            {drawer?.oppId === opp.id && drawer.loading ? 'Loading…' : 'Get Recommendations'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* Recommendation drawer */}
      {drawer && (
        <div className="hidden lg:flex w-80 xl:w-96 flex-shrink-0 flex-col border-l border-gray-200 bg-white overflow-hidden">
          <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
            <div>
              <h2 className="font-semibold text-gray-900">Recommendations</h2>
              <p className="text-xs text-gray-500 mt-0.5 truncate">
                {opportunities.find(o => o.id === drawer.oppId)?.title ?? drawer.oppId}
              </p>
            </div>
            <button
              onClick={() => setDrawer(null)}
              className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              aria-label="Close"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {drawer.loading ? (
              <div className="space-y-3">
                {[1,2,3].map(i => (
                  <div key={i} className="h-28 animate-pulse rounded-lg bg-gray-100" />
                ))}
              </div>
            ) : drawer.error ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {drawer.error}
              </div>
            ) : drawer.result ? (
              <AdaptiveResponse
                intent="SEARCH"
                response={`Found ${drawer.result.candidates.length} candidate${drawer.result.candidates.length !== 1 ? 's' : ''} for this opportunity.`}
                data={drawer.result.candidates}
              />
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}
