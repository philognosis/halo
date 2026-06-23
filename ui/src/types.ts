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
  band?: string
  region?: string
  office?: string
  status?: string
  email?: string
  location?: string
  hire_date?: string
  role_category?: string
  total_experience_months?: number
  experience_in_role_months?: number
  skills?: Array<{ skill_id?: string; skill_name?: string; skill_type?: string; proficiency_level?: string; years_experience?: number }>
  certifications?: Array<{ name?: string; issuer?: string; expiry_date?: string; is_valid?: boolean }>
  qualifications?: Array<{ degree?: string; institution?: string; field_of_study?: string; level?: string }>
  languages?: Array<{ language_code?: string; language_name?: string; proficiency?: string }>
  availability?: {
    availability_phase?: AvailabilityPhase
    allocated_pct?: number
    available_pct?: number
    active_assignment_count?: number
    next_available_date?: string
  }
  availability_phase?: AvailabilityPhase
  allocated_pct?: number
}

export interface Opportunity {
  id: string
  role_title?: string
  title?: string
  description?: string
  band_required?: string
  start_date?: string
  end_date?: string
  status?: string
  required_skills?: string[]
  team_id?: string
  project_id?: string
  role_category?: string
  region?: string
}

export interface Team {
  id: string
  name: string
  project_id?: string
  team_lead_id?: string
  members?: string[]
  opportunities?: Array<{ id: string; role_title?: string; status?: string }>
}

export interface Project {
  id: string
  unique_code?: string
  client?: string
  project_name?: string
  name?: string
  start_date?: string
  end_date?: string
  industry?: string
  sector?: string
  function?: string
  region?: string
  status?: string
  leadership?: Array<{ person_id: string; role: string; person_name?: string }>
  teams?: Array<{ id: string; name: string }>
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
  status?: string
  approved_count?: number
  rejected_count?: number
  shortlisted_count?: number
  pending_count?: number
}

// ── Recommendations ──────────────────────────────────────────────────────────

export interface RecommendResponse {
  opportunity_id: string
  candidates: Candidate[]
}

// ── Health ───────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string
  version?: string
}
