# Staffing System API (Phase 2)

FastAPI service for the Ontology-Driven Agentic Staffing System. It is the
HTTP front door for the human-in-the-loop (HITL) approval flow and the read
models over the operational store (PostgreSQL) and the semantic graph (Jena
Fuseki).

The API runs as a **separate process** from the Temporal worker. It owns its
own asyncpg pool, its own Temporal client, and its own `SparqlClient` bridge.
It **never imports the workflow classes** — it signals and queries workflows
by string name, so the Temporal workflow sandbox imports never enter this
process.

- Title: `Staffing System API`  ·  Version: `0.2.0`
- Interactive docs: `GET /docs`  ·  OpenAPI: `GET /openapi.json`

---

## Endpoint catalogue

| Method | Path                                                        | Purpose |
|--------|-------------------------------------------------------------|---------|
| GET    | `/`                                                         | Service banner |
| GET    | `/health`                                                   | Liveness |
| GET    | `/health/ready`                                             | Readiness — checks DB, Temporal, Fuseki (503 if any down) |
| GET    | `/persons`                                                  | List persons (filters: `region`, `band`, `status`; `limit`/`offset`) |
| GET    | `/persons/{person_id}`                                      | Full profile: person + skills + certs + quals + languages + availability |
| GET    | `/persons/{person_id}/availability`                         | `person_availability` view row |
| GET    | `/projects`                                                 | List projects (filters: `status`, `industry`) |
| GET    | `/projects/{project_id}`                                    | Project + leadership + teams |
| POST   | `/projects`                                                 | Create project → auto-fires `ProjectOnboardingWorkflow` |
| POST   | `/teams`                                                    | Create team → auto-fires `TeamStaffingWorkflow` |
| GET    | `/teams/{team_id}`                                          | Team + opportunities |
| POST   | `/opportunities`                                            | Create opportunity + required skills + quals (transaction) |
| GET    | `/opportunities/{opportunity_id}`                           | Opportunity + required skills + quals |
| GET    | `/opportunities/{opportunity_id}/candidates`               | Ontology-aware candidate search (Jena, Postgres fallback) |
| POST   | `/assignments`                                              | Shortlist a person → auto-fires `AssignmentApprovalWorkflow` |
| GET    | `/assignments`                                              | List assignments (filters: `person_id`, `opportunity_id`, `status`) |
| GET    | `/assignments/{assignment_id}`                             | Assignment + person + opportunity |
| POST   | `/approvals/assignments/{assignment_id}/approve`           | Signal `approve(approver_id, notes)` |
| POST   | `/approvals/assignments/{assignment_id}/reject`            | Signal `reject(approver_id, reason)` |
| GET    | `/approvals/assignments/{assignment_id}/status`           | `get_decision` query + DB status |
| POST   | `/approvals/teams/{team_id}/candidates/{assignment_id}/approve` | Signal `approve_candidate(assignment_id, approver_id)` |
| POST   | `/approvals/teams/{team_id}/candidates/{assignment_id}/reject`  | Signal `reject_candidate(assignment_id, reason)` |
| GET    | `/approvals/teams/{team_id}/status`                        | `get_status` query |
| GET    | `/notifications/{person_id}`                               | Inbox (filter `unread_only`; `limit`/`offset`) |
| PATCH  | `/notifications/{notification_id}/read`                    | Mark read |
| GET    | `/notifications/{person_id}/unread-count`                 | Unread count |
| POST   | `/admin/sync-abox`                                          | Manually trigger Postgres → Jena ABox projection |

---

## HITL signal flow

Creating an assignment never calls Temporal directly. The DB trigger is the
glue: an `INSERT` into `assignment` (status `short_listed`) fires `pg_notify`,
which the `pg-listener` process consumes and uses to start the durable
`AssignmentApprovalWorkflow`. The workflow then waits on a signal. The API
relays the human decision as that signal.

```
   UI                       API                    Temporal                Postgres
    |                        |                         |                       |
    |  POST /assignments     |                         |                       |
    |----------------------->|  INSERT assignment      |                       |
    |                        |------------------------------------------------>|
    |                        |                         |   trigger → pg_notify |
    |   {assignment_id,      |                         |<----------------------|
    |    workflow_id:        |                         |  pg-listener starts   |
    |    assignment-         |                         |  AssignmentApproval-  |
    |    approval-<id>}      |                         |  Workflow (waits)     |
    |<-----------------------|                         |                       |
    |                        |                         |                       |
    |  (human reviews notification, then approves)     |                       |
    |                        |                         |                       |
    |  POST /approvals/assignments/<id>/approve        |                       |
    |----------------------->| get_workflow_handle(    |                       |
    |                        |   assignment-approval-<id>)                     |
    |                        |  handle.signal("approve",|                       |
    |                        |    args=[approver_id, notes])                   |
    |                        |------------------------>|  workflow resumes →   |
    |                        |                         |  staffed, opportunity |
    |   {signaled: true}     |                         |  filled, ABox write,  |
    |<-----------------------|                         |  confirm notification |
```

If the workflow is not found / already completed, the signal endpoints raise
`RPCError` → HTTP 404 with a clear message.

The same pattern applies to `TeamStaffingWorkflow` (`team-staffing-{team_id}`)
via `approve_candidate` / `reject_candidate`, and to
`ProjectOnboardingWorkflow` (`project-onboarding-{project_id}`) which is started
when a project row is inserted.

---

## ABox sync loop

On startup the API launches a background task `_abox_sync_loop` that runs
`sync_abox` every `ABOX_SYNC_INTERVAL_SECONDS` (default 300; set to `0` to
disable). Each run reads `person_availability`, `skills`, `assignment`,
`opportunity` from Postgres, builds Turtle, then atomically replaces the named
graph `http://enterprise.org/graphs/abox` in Jena via
`DROP SILENT GRAPH` + `INSERT DATA`. Trigger a sync on demand with
`POST /admin/sync-abox`.

---

## Running locally

With Docker Compose (recommended — brings up Postgres, Fuseki, Temporal,
worker, pg-listener, and the API):

```bash
docker compose up --build api worker pg-listener
# API:           http://localhost:8000
# Swagger docs:  http://localhost:8000/docs
# Temporal UI:   http://localhost:8080
```

Standalone (against already-running dependencies):

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://staffing:staffing-changeme@localhost:5432/staffingdb"
export TEMPORAL_HOST="localhost:7233"
export FUSEKI_ENDPOINT="http://localhost:3030/staffing"
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Example end-to-end flow (curl)

```bash
BASE=http://localhost:8000

# 1) Create a project (auto-starts ProjectOnboardingWorkflow)
curl -s -X POST $BASE/projects -H 'content-type: application/json' -d '{
  "unique_code": "PRJ-2026-001",
  "client": "NovaPay",
  "project_name": "Core Banking Platform",
  "start_date": "2026-07-01",
  "industry": "Financial Services",
  "sector": "Banking",
  "function": "Technology",
  "status": "active"
}'
# → {"project_id": "...", "workflow_id": "project-onboarding-..."}

# 2) Create a team (auto-starts TeamStaffingWorkflow)
curl -s -X POST $BASE/teams -H 'content-type: application/json' -d '{
  "project_id": "<PROJECT_ID>",
  "name": "Core Banking Data Team"
}'
# → {"team_id": "...", "workflow_id": "team-staffing-..."}

# 3) Create an opportunity with required skills
curl -s -X POST $BASE/opportunities -H 'content-type: application/json' -d '{
  "team_id": "<TEAM_ID>",
  "role_title": "Senior Data Engineer",
  "band_required": "Senior Consultant",
  "start_date": "2026-07-01",
  "required_skills": [
    {"skill_id": "Spark", "skill_name": "Apache Spark", "skill_type": "technical"},
    {"skill_id": "SQL",   "skill_name": "SQL",          "skill_type": "technical"}
  ],
  "required_qualifications": []
}'
# → {"opportunity_id": "..."}

# 4) Get ranked candidates (Jena ontology search, Postgres fallback)
curl -s $BASE/opportunities/<OPPORTUNITY_ID>/candidates
# → {"opportunity_id": "...", "source": "jena|postgres_fallback", "count": N, "candidates": [...]}

# 5) Shortlist a candidate (auto-starts AssignmentApprovalWorkflow)
curl -s -X POST $BASE/assignments -H 'content-type: application/json' -d '{
  "opportunity_id": "<OPPORTUNITY_ID>",
  "person_id": "<PERSON_ID>",
  "start_date": "2026-07-01",
  "allocation_pct": 100
}'
# → {"assignment_id": "...", "workflow_id": "assignment-approval-...", "status": "short_listed"}

# 6) Approve (relays the "approve" signal to the workflow)
curl -s -X POST $BASE/approvals/assignments/<ASSIGNMENT_ID>/approve \
  -H 'content-type: application/json' \
  -d '{"approver_id": "<APPROVER_PERSON_ID>", "notes": "Strong fit"}'
# → {"signaled": true, "workflow_id": "assignment-approval-..."}

# 7) Check combined status (workflow decision + DB status)
curl -s $BASE/approvals/assignments/<ASSIGNMENT_ID>/status
```
