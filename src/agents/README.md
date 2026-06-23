# Phase 3 — Agent Layer

The agent layer adds deterministic candidate scoring, a LangGraph
recommendation pipeline, a conversational chat agent, team-shaping proposals,
and Temporal activity wrappers — integrated with the existing Temporal
workflows, FastAPI service, Postgres, and Jena.

> **The LLM is used ONLY for natural-language parsing and human-readable
> explanations — NEVER for scoring or inventing candidates.** All scores come
> from the pure-Python deterministic scorer (`scoring.py`) over Postgres facts +
> SPARQL skill traversal. This preserves auditability.

---

## Scoring model (`scoring.py`)

Pure functions over already-fetched data dicts. No I/O, no LLM.

### Band hierarchy (index = rank)

`Analyst < Consultant < Senior Consultant < Manager < Senior Manager < Director < Partner`

### Hard gates (mandatory)

If any mandatory requirement fails, `gate_passed=False` and the failure is added
to `gate_failures`. A score is still computed for transparency, but flagged.

| Gate | Rule |
|------|------|
| band | candidate band rank ≥ required band rank |
| availability | status not in (on_leave, inactive) AND phase ≠ FullyAllocated AND available_pct ≥ requested (default 100 → require >0 if unknown) |
| mandatory_skills | every mandatory `skill_id` in `matched_skill_ids` (incl. SKOS-broader matches) |
| mandatory_certs | each required cert matched by a candidate cert with `is_valid=True` |
| mandatory_quals | candidate qualification level rank ≥ required (bachelor/professional < master < phd); field matches if specified |
| mandatory_languages | candidate language proficiency rank ≥ required (basic < professional < fluent < native) |
| mandatory_citizenships | candidate holds at least one required country_code |

### Factor sub-scores (each 0..1)

`skills`, `industry_fit`, `function_fit`, `role_category_fit`, `location`,
`experience`, `qualifications`, `certifications`, `language`,
`availability_headroom`.

### Weights (sum = 1.0)

| factor | weight |
|--------|-------:|
| skills | 0.30 |
| industry_fit | 0.12 |
| role_category_fit | 0.08 |
| function_fit | 0.08 |
| location | 0.10 |
| experience | 0.10 |
| qualifications | 0.07 |
| certifications | 0.06 |
| language | 0.05 |
| availability_headroom | 0.04 |

`overall_score = round(100 * Σ weight[f]·subscore[f], 1)`

`rank_candidates` sorts by `(gate_passed desc, overall_score desc)`.

---

## Two modes

### Autonomous (Temporal activities — no NL)

Workflows call agent tools wrapped as activities (`activities.py`):

- `agent_recommend_candidates(opportunity_id, top_n)`
- `agent_propose_team_shape(project_id)`
- `agent_shortlist_candidate(...)`
- `agent_compare_profiles(person_ids, opportunity_id)`

All returns are JSON-serialisable (sets → lists, dates → ISO strings, Decimal →
float). A module-level `SparqlClient` is created lazily by `init_agent_sparql()`
at worker startup. The pool comes from `db_activities.get_pool()`.

Workflow integration:

- **`OpportunityFillWorkflow`** (new — reconciliation fix #1): on
  `opportunity_INSERT`, recommends candidates and nudges leadership.
- **`ProjectOnboardingWorkflow`** now calls `agent_propose_team_shape` and folds
  the suggested roles into the team-creation nudge.
- **`TeamStaffingWorkflow`** now uses `agent_recommend_candidates` (Postgres
  fallback only if empty). On approval it calls `agent_shortlist_candidate`
  (INSERT assignment) — the DB trigger + pg_listener start
  `AssignmentApprovalWorkflow` exactly once (fix #2 — the old child-workflow
  start was removed to stop the double-start).

### Conversational (`/chat` — NL only here)

`chat_graph.py` runs the LangGraph chat agent. NL is used only at this entry
point. When `ANTHROPIC_API_KEY` is unset the agent degrades gracefully to
regex/keyword classification + extraction (`_fallback_classify`,
`_fallback_extract`) and deterministic synthesis.

---

## Recommendation graph (`recommendation_graph.py`)

LangGraph `StateGraph` nodes:

1. `load_requirement` — `fetch_requirement(pool, opportunity_id)` if not supplied
2. `gather_pool` — `fetch_candidate_pool` + `enrich_candidates`
3. `resolve_skills` — `fetch_skos_skill_matches` (SKOS-transitive) merged with
   direct Postgres `skill_id` matching → `candidate.matched_skill_ids`
4. `score` — `rank_candidates(...)`
5. `explain` (conditional) — LLM 1–2 sentence rationale per top-N using ONLY the
   factor scores/matched data; deterministic template when no API key.

`run_recommendation(pool, sparql_client, opportunity_id=None, requirement=None,
top_n=5, explain=True)` → `{requirement, ranked, top}`.

---

## Chat graph (`chat_graph.py`)

Nodes: `classify_intent` → `extract_entities` → `resolve` → `route` →
`synthesize`.

Intents: `SEARCH`, `COMPARE`, `SHORTLIST`, `TEAM_SHAPE`, `STATUS`, `GREETING`,
`UNKNOWN`.

- `resolve` maps skill/role labels to SKOS notations via the SparqlClient
  (`build_skos_resolve`) and builds a requirement dict.
- `route` dispatches by intent to the action tools.
- `synthesize` writes a reply grounded ONLY in the result data.

`run_chat(pool, sparql_client, message, context)` →
`{intent, response, result, entities}`.

---

## Shortlist flows through triggers

`shortlist_candidate` / `agent_shortlist_candidate` INSERT an `assignment` with
`status='short_listed'`. The existing DB trigger (`trg_assignment_event`) emits a
domain event; `pg_listener` routes `assignment_INSERT` →
`AssignmentApprovalWorkflow`. **Never start that workflow directly.**

---

## Team-shaping templates (`team_shaping.py`)

Deterministic role templates keyed by project function/industry (≥ 4 roles each):

- **Technology / Engineering** → Solution Architect (Manager), 2× Engineer
  (Consultant), Business Analyst (Consultant), Data Analyst (Analyst)
- **Analytics / Data** → Data Lead (Manager), 2× Data Engineer (Consultant),
  Data Analyst (Analyst)
- **Strategy / Advisory** → Engagement Manager (Manager), 2× Consultant, BA
- **Generic fallback** → Engagement Manager, Senior Consultant, Consultant,
  Analyst

Roles and bands are always deterministic; the LLM may only refine titles and
rationale text (and is forced to keep `role_category`/`band_required` fixed).

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | NL conversational agent |
| POST | `/agents/recommend/{opportunity_id}` | Recommend candidates (query: `top_n`, `explain`) |
| POST | `/agents/compare` | Compare profiles (body: `person_ids`, `opportunity_id?`) |
| POST | `/agents/team-shape/{project_id}` | Propose a team structure |

### Example calls

```bash
# Conversational search
curl -X POST localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "find me a senior data engineer in London with Spark"}'

# Recommend for an opportunity
curl -X POST 'localhost:8000/agents/recommend/<opportunity_id>?top_n=5&explain=true'

# Compare profiles against an opportunity
curl -X POST localhost:8000/agents/compare \
  -H 'Content-Type: application/json' \
  -d '{"person_ids": ["<id1>", "<id2>"], "opportunity_id": "<opp_id>"}'

# Team shape for a project
curl -X POST localhost:8000/agents/team-shape/<project_id>
```
