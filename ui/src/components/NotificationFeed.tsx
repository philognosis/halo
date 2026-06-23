import { useEffect, useState, useCallback } from 'react'
import { getNotifications, markNotificationRead } from '../api/client'
import type { Notification } from '../types'

interface Props {
  personId: string
}

export default function NotificationFeed({ personId }: Props) {
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!personId) return
    setLoading(true)
    setError(null)
    try {
      const data = await getNotifications(personId)
      setNotifications(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load notifications')
    } finally {
      setLoading(false)
    }
  }, [personId])

  useEffect(() => { load() }, [load])

  const handleMarkRead = async (notifId: string) => {
    try {
      await markNotificationRead(notifId)
      setNotifications(prev =>
        prev.map(n => n.id === notifId ? { ...n, is_read: true } : n)
      )
    } catch {
      // silently ignore
    }
  }

  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map(i => (
          <div key={i} className="h-14 bg-gray-100 animate-pulse rounded-lg" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {error}
        <button onClick={load} className="ml-2 underline hover:no-underline">Retry</button>
      </div>
    )
  }

  if (!notifications.length) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 p-6 text-center text-sm text-gray-500">
        No notifications
      </div>
    )
  }

  return (
    <ul className="space-y-2">
      {notifications.map(n => (
        <li
          key={n.id}
          className={`flex items-start gap-3 rounded-lg border p-3 transition-colors ${
            n.is_read ? 'border-gray-100 bg-white' : 'border-indigo-100 bg-indigo-50'
          }`}
        >
          <div className="mt-1 flex-shrink-0">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                n.is_read ? 'bg-gray-300' : 'bg-indigo-500'
              }`}
            />
          </div>
          <div className="flex-1 min-w-0">
            <p className={`text-sm font-medium ${n.is_read ? 'text-gray-600' : 'text-gray-900'}`}>
              {n.title}
            </p>
            <p className={`text-sm mt-0.5 ${n.is_read ? 'text-gray-400' : 'text-gray-700'}`}>
              {n.body}
            </p>
            <p className="mt-0.5 text-xs text-gray-400">
              {new Date(n.created_at).toLocaleString()}
            </p>
          </div>
          {!n.is_read && (
            <button
              onClick={() => handleMarkRead(n.id)}
              className="flex-shrink-0 text-xs text-indigo-600 hover:text-indigo-800"
            >
              Mark read
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
