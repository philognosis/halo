// ── Core domain types ────────────────────────────────────────────────────────

export type AvailabilityPhase =
  | 'Available'
  | 'PartiallyAllocated'
  | 'FullyAllocated'
  | 'OnLeave'

export interface Person {
  id: string
  name: string
  role?: string
  skills?: string[]
  availability_phase?: AvailabilityPhase
  email?: string
  department?: string
  [key: string]: unknown
}

export interface Opportunity {
  id: string
  title: string
  status?: string
  required_skills?: string[]
  team_id?: string
  project_id?: string
  [key: string]: unknown
}

export interface Team {
  id: string
  name: string
  project_id?: string
  members?: string[]
  [key: string]: unknown
}

export interface Project {
  id: string
  name: string
  status?: string
  [key: string]: unknown
}

// ── Candidate (from recommend + SEARCH intent) ───────────────────────────────

export interface Candidate {
  person_id: string
  name: string
  score: number
  gate_passed: boolean
  factors: Record<string, number>
  explanation?: string
  availability_phase?: AvailabilityPhase
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export type ChatIntent =
  | 'SEARCH'
  | 'COMPARE'
  | 'SHORTLIST'
  | 'TEAM_SHAPE'
  | 'STATUS'
  | 'GREETING'
  | 'UNKNOWN'

export interface ChatContext {
  project_id?: string
  opportunity_id?: string
  person_id?: string
}

export interface ChatRequest {
  message: string
  context?: ChatContext
}

export interface ChatResponse {
  intent: ChatIntent
  response: string
  data?: unknown
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  intent?: ChatIntent
  data?: unknown
  timestamp: Date
}

// ── Comparison ───────────────────────────────────────────────────────────────

export interface ComparisonResponse {
  persons: Person[]
  comparison: Record<string, Record<string, number | string>>
}

// ── Team Shape ───────────────────────────────────────────────────────────────

export interface TeamRole {
  role: string
  count: number
  rationale: string
}

export interface TeamShapeResponse {
  project_id: string
  roles: TeamRole[]
  total_fte: number
}

// ── Notifications ─────────────────────────────────────────────────────────────

export interface Notification {
  id: string
  event_id?: string
  recipient_id: string
  type: string
  title: string
  body: string
  metadata?: unknown
  is_read: boolean
  read_at?: string
  created_at: string
  expires_at?: string
}

// ── Approvals ────────────────────────────────────────────────────────────────

export interface ApprovalStatus {
  workflow_id?: string
  workflow_decision?: string | null
  db_status?: string | null
  // team staffing status query result (different shape from team status endpoint)
  [key: string]: unknown
}

// ── Recommendations ──────────────────────────────────────────────────────────

export interface RecommendResponse {
  opportunity_id: string
  candidates: Candidate[]
}

// ── Health ───────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string
  [key: string]: unknown
}
