import type {
  Person,
  Opportunity,
  Team,
  Project,
  ChatRequest,
  ChatResponse,
  RecommendResponse,
  ComparisonResponse,
  TeamShapeResponse,
  Notification,
  ApprovalStatus,
  HealthResponse,
} from '../types'

const BASE = '/api'

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const body = await res.json()
      msg = body?.detail ?? body?.message ?? msg
    } catch {
      // ignore parse errors
    }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

// ── Health ────────────────────────────────────────────────────────────────────

export const getHealth = () => request<HealthResponse>('/health')

// ── Persons ───────────────────────────────────────────────────────────────────

export const getPersons = () => request<Person[]>('/persons')
export const getPerson = (id: string) => request<Person>(`/persons/${id}`)

// ── Opportunities ─────────────────────────────────────────────────────────────

export const getOpportunities = () => request<Opportunity[]>('/opportunities')
export const getOpportunity = (id: string) => request<Opportunity>(`/opportunities/${id}`)
export const createOpportunity = (body: Record<string, unknown>) =>
  request<Opportunity>('/opportunities', { method: 'POST', body: JSON.stringify(body) })

// ── Teams ─────────────────────────────────────────────────────────────────────

export const getTeams = () => request<Team[]>('/teams')
export const getTeam = (id: string) => request<Team>(`/teams/${id}`)

// ── Projects ──────────────────────────────────────────────────────────────────

export const getProjects = () => request<Project[]>('/projects')
export const createProject = (body: Record<string, unknown>) =>
  request<Project>('/projects', { method: 'POST', body: JSON.stringify(body) })

// ── Chat ──────────────────────────────────────────────────────────────────────

export const postChat = (body: ChatRequest) =>
  request<ChatResponse>('/chat', { method: 'POST', body: JSON.stringify(body) })

// ── Agents ───────────────────────────────────────────────────────────────────

export const postRecommend = (opp_id: string) =>
  request<RecommendResponse>(`/agents/recommend/${opp_id}`, { method: 'POST', body: '{}' })

export const postCompare = (person_ids: string[], opportunity_id?: string) =>
  request<ComparisonResponse>('/agents/compare', {
    method: 'POST',
    body: JSON.stringify({ person_ids, opportunity_id }),
  })

export const postTeamShape = (proj_id: string) =>
  request<TeamShapeResponse>(`/agents/team-shape/${proj_id}`, { method: 'POST', body: '{}' })

// ── Notifications ─────────────────────────────────────────────────────────────

export const getNotifications = (person_id: string) =>
  request<Notification[]>(`/notifications/${person_id}`)

export const getUnreadCount = (person_id: string) =>
  request<{ person_id: string; unread_count: number }>(`/notifications/${person_id}/unread-count`)

export const markNotificationRead = (notif_id: string) =>
  request<Notification>(`/notifications/${notif_id}/read`, { method: 'PATCH', body: '{}' })

// ── Approvals ─────────────────────────────────────────────────────────────────

export const getAssignmentStatus = (id: string) =>
  request<ApprovalStatus>(`/approvals/assignments/${id}/status`)

export const approveAssignment = (id: string, approver_id: string, notes?: string) =>
  request<ApprovalStatus>(`/approvals/assignments/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approver_id, notes }),
  })

export const rejectAssignment = (id: string, approver_id: string, reason: string) =>
  request<ApprovalStatus>(`/approvals/assignments/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ approver_id, reason }),
  })

export const getTeamApprovalStatus = (team_id: string) =>
  request<ApprovalStatus>(`/approvals/teams/${team_id}/status`)

export const approveTeamCandidate = (team_id: string, assignment_id: string) =>
  request<ApprovalStatus>(
    `/approvals/teams/${team_id}/candidates/${assignment_id}/approve`,
    { method: 'POST', body: '{}' },
  )

export const rejectTeamCandidate = (team_id: string, assignment_id: string) =>
  request<ApprovalStatus>(
    `/approvals/teams/${team_id}/candidates/${assignment_id}/reject`,
    { method: 'POST', body: '{}' },
  )
