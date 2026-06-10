import { useEffect, useState, useCallback } from 'react'
import { getTeams, postTeamShape, getTeamApprovalStatus } from '../api/client'
import type { Team, TeamShapeResponse, ApprovalStatus } from '../types'
import AdaptiveResponse from '../components/AdaptiveResponse'

type PanelMode = 'shape' | 'status'

interface PanelState {
  teamId: string
  mode: PanelMode
  shapeResult: TeamShapeResponse | null
  statusResult: ApprovalStatus | null
  loading: boolean
  error: string | null
}

export default function TeamsPage() {
  const [teams, setTeams] = useState<Team[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [panel, setPanel] = useState<PanelState | null>(null)

  useEffect(() => {
    setLoading(true)
    getTeams()
      .then(setTeams)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load teams'))
      .finally(() => setLoading(false))
  }, [])

  const handleTeamShape = useCallback(async (team: Team) => {
    if (!team.project_id) {
      setPanel({
        teamId: team.id,
        mode: 'shape',
        shapeResult: null,
        statusResult: null,
        loading: false,
        error: 'This team has no linked project for team shaping.',
      })
      return
    }
    setPanel({ teamId: team.id, mode: 'shape', shapeResult: null, statusResult: null, loading: true, error: null })
    try {
      const result = await postTeamShape(team.project_id)
      setPanel(prev => prev ? { ...prev, shapeResult: result, loading: false } : prev)
    } catch (e) {
      setPanel(prev => prev
        ? { ...prev, loading: false, error: e instanceof Error ? e.message : 'Team shape failed' }
        : prev
      )
    }
  }, [])

  const handleStatus = useCallback(async (team: Team) => {
    setPanel({ teamId: team.id, mode: 'status', shapeResult: null, statusResult: null, loading: true, error: null })
    try {
      const result = await getTeamApprovalStatus(team.id)
      setPanel(prev => prev ? { ...prev, statusResult: result, loading: false } : prev)
    } catch (e) {
      setPanel(prev => prev
        ? { ...prev, loading: false, error: e instanceof Error ? e.message : 'Status check failed' }
        : prev
      )
    }
  }, [])

  const filtered = teams.filter(t => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      t.name?.toLowerCase().includes(q) ||
      t.id.toLowerCase().includes(q) ||
      t.project_id?.toLowerCase().includes(q)
    )
  })

  const activeTeam = panel ? teams.find(t => t.id === panel.teamId) : null

  return (
    <div className="flex gap-6 h-full -m-6">
      {/* Main list */}
      <div className={`flex flex-1 flex-col min-w-0 overflow-hidden p-6 ${panel ? 'lg:max-w-[60%]' : ''}`}>
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
                placeholder="Search teams…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <span className="text-sm text-gray-500">
              {loading ? '…' : `${filtered.length} of ${teams.length}`}
            </span>
          </div>

          {/* Table */}
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
            {loading ? (
              <div className="space-y-px">
                {[1,2,3,4].map(i => (
                  <div key={i} className="flex items-center gap-4 px-5 py-4">
                    <div className="h-4 w-40 animate-pulse rounded bg-gray-100" />
                    <div className="h-4 w-24 animate-pulse rounded bg-gray-100 ml-auto" />
                  </div>
                ))}
              </div>
            ) : error ? (
              <div className="p-6 text-sm text-red-600">{error}</div>
            ) : filtered.length === 0 ? (
              <div className="px-5 py-10 text-center text-sm text-gray-400">
                {search ? 'No teams match your search.' : 'No teams found.'}
              </div>
            ) : (
              <table className="min-w-full divide-y divide-gray-100">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="py-3 pl-5 pr-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Team
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hidden sm:table-cell">
                      Project
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hidden md:table-cell">
                      Members
                    </th>
                    <th className="py-3 pl-3 pr-5 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {filtered.map(team => {
                    const isActive = panel?.teamId === team.id
                    return (
                      <tr
                        key={team.id}
                        className={`transition-colors ${isActive ? 'bg-indigo-50' : 'hover:bg-gray-50'}`}
                      >
                        <td className="py-3 pl-5 pr-3">
                          <p className="font-medium text-gray-900">{team.name}</p>
                          <p className="text-xs text-gray-400 mt-0.5">{team.id}</p>
                        </td>
                        <td className="px-3 py-3 text-sm text-gray-600 hidden sm:table-cell">
                          {team.project_id ?? '—'}
                        </td>
                        <td className="px-3 py-3 text-sm text-gray-600 hidden md:table-cell">
                          {Array.isArray(team.members) ? team.members.length : '—'}
                        </td>
                        <td className="py-3 pl-3 pr-5">
                          <div className="flex justify-end gap-2">
                            <button
                              onClick={() => handleTeamShape(team)}
                              disabled={isActive && panel?.loading && panel.mode === 'shape'}
                              className="rounded-md bg-teal-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-50"
                            >
                              {isActive && panel?.loading && panel.mode === 'shape'
                                ? 'Loading…'
                                : 'Team Shape'}
                            </button>
                            <button
                              onClick={() => handleStatus(team)}
                              disabled={isActive && panel?.loading && panel.mode === 'status'}
                              className="rounded-md bg-amber-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                            >
                              {isActive && panel?.loading && panel.mode === 'status'
                                ? 'Loading…'
                                : 'Staffing Status'}
                            </button>
                          </div>
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

      {/* Side panel */}
      {panel && (
        <div className="hidden lg:flex w-80 xl:w-96 flex-shrink-0 flex-col border-l border-gray-200 bg-white overflow-hidden">
          <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-semibold text-gray-900">
                  {panel.mode === 'shape' ? 'Team Shape' : 'Staffing Status'}
                </h2>
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                  panel.mode === 'shape'
                    ? 'bg-teal-100 text-teal-800'
                    : 'bg-amber-100 text-amber-800'
                }`}>
                  {panel.mode === 'shape' ? 'TEAM_SHAPE' : 'STATUS'}
                </span>
              </div>
              <p className="text-xs text-gray-500 mt-0.5 truncate">
                {activeTeam?.name ?? panel.teamId}
              </p>
            </div>
            <button
              onClick={() => setPanel(null)}
              className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              aria-label="Close panel"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {panel.loading ? (
              <div className="space-y-3">
                {[1,2,3].map(i => (
                  <div key={i} className="h-20 animate-pulse rounded-lg bg-gray-100" />
                ))}
              </div>
            ) : panel.error ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {panel.error}
              </div>
            ) : panel.mode === 'shape' && panel.shapeResult ? (
              <AdaptiveResponse
                intent="TEAM_SHAPE"
                response={`Recommended team structure for project ${panel.shapeResult.project_id}: ${panel.shapeResult.total_fte} total FTE.`}
                data={panel.shapeResult}
              />
            ) : panel.mode === 'status' && panel.statusResult ? (
              <AdaptiveResponse
                intent="STATUS"
                response={`Staffing status for team ${activeTeam?.name ?? panel.teamId}.`}
                data={panel.statusResult}
              />
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}
