import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  getPersons,
  getOpportunities,
  getTeams,
  getUnreadCount,
} from '../api/client'
import NotificationFeed from '../components/NotificationFeed'
import type { Person, Opportunity } from '../types'

interface Stats {
  persons: number
  opportunities: number
  openOpportunities: number
  teams: number
}

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string
  value: number | null
  sub?: string
  color: string
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <p className="text-sm font-medium text-gray-500">{label}</p>
      <p className={`mt-1 text-3xl font-bold tabular-nums ${color}`}>
        {value ?? '—'}
      </p>
      {sub && <p className="mt-1 text-xs text-gray-400">{sub}</p>}
    </div>
  )
}

export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const viewerParam = searchParams.get('viewer') ?? ''

  const [stats, setStats] = useState<Stats | null>(null)
  const [persons, setPersons] = useState<Person[]>([])
  const [unreadCount, setUnreadCount] = useState<number | null>(null)
  const [selectedPersonId, setSelectedPersonId] = useState<string>(viewerParam)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadStats = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [pList, oList, tList] = await Promise.all([
        getPersons(),
        getOpportunities(),
        getTeams(),
      ])
      setPersons(pList)
      setStats({
        persons: pList.length,
        opportunities: oList.length,
        openOpportunities: (oList as Opportunity[]).filter(
          o => o.status?.toLowerCase() === 'open',
        ).length,
        teams: tList.length,
      })
      if (!selectedPersonId && pList.length > 0) {
        setSelectedPersonId(pList[0].id)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load dashboard data')
    } finally {
      setLoading(false)
    }
  }, [selectedPersonId])

  useEffect(() => { loadStats() }, [loadStats])

  useEffect(() => {
    if (!selectedPersonId) return
    getUnreadCount(selectedPersonId)
      .then(r => setUnreadCount(r.count))
      .catch(() => setUnreadCount(null))
  }, [selectedPersonId])

  const handlePersonChange = (id: string) => {
    setSelectedPersonId(id)
    setSearchParams(id ? { viewer: id } : {})
  }

  return (
    <div className="space-y-6">
      {/* Stats */}
      {loading ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="h-28 animate-pulse rounded-xl bg-gray-100" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
          <button onClick={loadStats} className="ml-2 underline">Retry</button>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard
            label="Total People"
            value={stats?.persons ?? null}
            color="text-indigo-700"
          />
          <StatCard
            label="Open Opportunities"
            value={stats?.openOpportunities ?? null}
            sub={`${stats?.opportunities ?? 0} total`}
            color="text-amber-600"
          />
          <StatCard
            label="Teams"
            value={stats?.teams ?? null}
            color="text-teal-700"
          />
          <StatCard
            label="Unread Notifications"
            value={unreadCount}
            color="text-rose-600"
          />
        </div>
      )}

      {/* Notification panel */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-5 py-4">
          <h2 className="font-semibold text-gray-900">Notifications</h2>
          <div className="flex items-center gap-2">
            <label htmlFor="viewer-select" className="text-sm text-gray-500">
              Viewing as:
            </label>
            <select
              id="viewer-select"
              value={selectedPersonId}
              onChange={e => handlePersonChange(e.target.value)}
              className="rounded-md border border-gray-300 py-1 pl-2 pr-7 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">— select person —</option>
              {persons.map(p => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="p-5">
          {selectedPersonId ? (
            <NotificationFeed personId={selectedPersonId} />
          ) : (
            <p className="text-sm text-gray-400 italic">
              Select a person above to see their notifications.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
