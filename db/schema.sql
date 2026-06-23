-- =============================================================================
-- Ontology-Driven Agentic Staffing System — PostgreSQL Schema
-- Phase 1 Foundation
-- =============================================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- ENUMERATIONS (as CHECK constraints or domain types)
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- Table: person
-- Represents a human being in the system (gUFO:Kind — rigid identity)
-- ---------------------------------------------------------------------------
CREATE TABLE person (
    id                          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                        TEXT        NOT NULL,
    email                       TEXT        NOT NULL UNIQUE,
    role                        TEXT        NOT NULL,
    role_category               TEXT        CHECK (role_category IN (
                                    'engineer', 'manager', 'associate', 'business_analyst',
                                    'expert', 'designer', 'consultant', 'architect',
                                    'lead', 'analyst', 'specialist'
                                )),
    band                        TEXT        NOT NULL CHECK (band IN (
                                    'Analyst', 'Consultant', 'Senior Consultant',
                                    'Manager', 'Senior Manager', 'Director', 'Partner'
                                )),
    location                    TEXT        NOT NULL,
    office                      TEXT        NOT NULL,
    region                      TEXT        NOT NULL CHECK (region IN ('EMEA', 'Americas', 'APAC')),
    hire_date                   DATE,
    status                      TEXT        NOT NULL DEFAULT 'active' CHECK (status IN (
                                    'active', 'bench', 'on_leave', 'inactive'
                                )),
    total_experience_months     INTEGER     NOT NULL CHECK (total_experience_months >= 0),
    experience_in_role_months   INTEGER     NOT NULL CHECK (experience_in_role_months >= 0),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE person IS
  'Core entity representing an individual. Maps to gUFO:Kind — a rigid sortal that persists regardless of employment state.';
COMMENT ON COLUMN person.band IS
  'Grade/seniority band: Analyst → Consultant → Senior Consultant → Manager → Senior Manager → Director → Partner.';
COMMENT ON COLUMN person.region IS
  'Geographic operating region: EMEA, Americas, or APAC.';
COMMENT ON COLUMN person.hire_date IS
  'Date the person joined the firm. Used to compute tenure dynamically (NOW() - hire_date).';
COMMENT ON COLUMN person.status IS
  'Current employment/availability status: active (on project or available), bench (available for staffing), on_leave (temporarily unavailable), inactive (left firm).';

-- ---------------------------------------------------------------------------
-- Table: skills
-- Skill possessed by a person (projected as gUFO:Quality on the Employee role)
-- ---------------------------------------------------------------------------
CREATE TABLE skills (
    id                UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id         UUID    NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    skill_id          TEXT    NOT NULL,   -- SKOS concept notation (e.g. "Python", "TOGAF")
    skill_name        TEXT    NOT NULL,
    skill_type        TEXT    NOT NULL CHECK (skill_type IN ('technical', 'functional', 'leadership', 'domain')),
    proficiency_level TEXT    NOT NULL DEFAULT 'intermediate' CHECK (proficiency_level IN (
                          'beginner', 'intermediate', 'advanced', 'expert'
                      )),
    years_experience  NUMERIC(4,1) CHECK (years_experience >= 0),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE skills IS
  'Skills possessed by a person, classified by type. Skill_id references a SKOS concept in the Jena taxonomy graph.';
COMMENT ON COLUMN skills.skill_id IS
  'SKOS skos:notation value linking to the concept in the stf:SkillScheme concept scheme.';
COMMENT ON COLUMN skills.skill_type IS
  'Broad category: technical | functional | leadership | domain.';
COMMENT ON COLUMN skills.proficiency_level IS
  'Self-assessed or manager-assessed proficiency: beginner | intermediate | advanced | expert.';
COMMENT ON COLUMN skills.years_experience IS
  'Years of hands-on experience with this skill (fractional, e.g. 2.5).';

-- ---------------------------------------------------------------------------
-- Table: certifications
-- Professional certifications held by a person
-- ---------------------------------------------------------------------------
CREATE TABLE certifications (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id   UUID        NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    issuer      TEXT        NOT NULL,
    issued_date DATE        NOT NULL,
    expiry_date DATE,
    is_valid    BOOLEAN     GENERATED ALWAYS AS (
                    expiry_date IS NULL OR expiry_date >= CURRENT_DATE
                ) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE certifications IS
  'Professional certifications. is_valid is a computed column: true when no expiry date set or expiry is in the future.';
COMMENT ON COLUMN certifications.is_valid IS
  'Computed: TRUE if expiry_date IS NULL or expiry_date >= today. Used in SHACL CertificationValidityShape.';

-- ---------------------------------------------------------------------------
-- Table: qualifications
-- Academic / professional qualifications held by a person
-- ---------------------------------------------------------------------------
CREATE TABLE qualifications (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id       UUID    NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    degree          TEXT    NOT NULL,
    institution     TEXT    NOT NULL,
    field_of_study  TEXT    NOT NULL,
    graduation_year INTEGER NOT NULL CHECK (graduation_year BETWEEN 1950 AND 2100),
    level           TEXT    NOT NULL CHECK (level IN ('bachelor', 'master', 'phd', 'professional')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE qualifications IS
  'Academic and professional degrees held by a person (gUFO:Quality on the Employee role).';

-- ---------------------------------------------------------------------------
-- Table: project
-- A client engagement / project (gUFO:Event — bounded in time)
-- ---------------------------------------------------------------------------
CREATE TABLE project (
    id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    unique_code  TEXT    NOT NULL UNIQUE,
    client       TEXT    NOT NULL,
    project_name TEXT    NOT NULL,
    start_date   DATE    NOT NULL,
    end_date     DATE,
    industry     TEXT    NOT NULL,
    sector       TEXT    NOT NULL,
    function     TEXT    NOT NULL,
    region       TEXT    NOT NULL DEFAULT 'EMEA' CHECK (region IN ('EMEA', 'Americas', 'APAC')),
    status       TEXT    NOT NULL CHECK (status IN ('active', 'completed', 'on_hold', 'cancelled', 'pipeline')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT project_dates_check CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE project IS
  'Client engagement. Maps to stf:ClientEngagement (gUFO:Event). unique_code is a human-readable project reference.';
COMMENT ON COLUMN project.region IS
  'Primary delivery region of the engagement (EMEA | Americas | APAC). Drives default candidate-search locality in TeamStaffingWorkflow and the /candidates endpoint.';

-- ---------------------------------------------------------------------------
-- Table: staffing_history
-- Historical allocations of a person to a project (gUFO:Relator — historical)
-- ---------------------------------------------------------------------------
CREATE TABLE staffing_history (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id       UUID        NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    project_id      UUID        NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    role_played     TEXT        NOT NULL,
    start_date      DATE        NOT NULL,
    end_date        DATE,
    allocation_pct  NUMERIC(5,2) NOT NULL CHECK (allocation_pct > 0 AND allocation_pct <= 100),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT staffing_history_dates_check CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE staffing_history IS
  'Historical record of person-to-project allocations. Maps to stf:StaffingHistory (gUFO:Relator, historical).';

-- ---------------------------------------------------------------------------
-- Table: leadership
-- Leadership roles on a project (e.g. engagement partner, delivery lead)
-- ---------------------------------------------------------------------------
CREATE TABLE leadership (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID    NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    role        TEXT    NOT NULL CHECK (role IN ('engagement_partner', 'delivery_lead', 'project_sponsor')),
    person_id   UUID    NOT NULL REFERENCES person(id) ON DELETE RESTRICT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, role)
);

COMMENT ON TABLE leadership IS
  'Named leadership roles on a project. A project should have at most one of each role type.';

-- ---------------------------------------------------------------------------
-- Table: team
-- A staffing team within a project (gUFO:Collection)
-- ---------------------------------------------------------------------------
CREATE TABLE team (
    id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID    NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    team_lead_id UUID    REFERENCES person(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE team IS
  'A named team within a project. Maps to stf:ProjectTeam (gUFO:Collection). Must have >= 2 staffed seats (enforced by SHACL).';

-- ---------------------------------------------------------------------------
-- Table: opportunity
-- An open staffing role on a team (gUFO:RoleMixin — demand side)
-- ---------------------------------------------------------------------------
CREATE TABLE opportunity (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         UUID    NOT NULL REFERENCES team(id) ON DELETE CASCADE,
    role_title      TEXT    NOT NULL,
    role_category   TEXT    CHECK (role_category IN (
                        'engineer', 'manager', 'associate', 'business_analyst',
                        'expert', 'designer', 'consultant', 'architect',
                        'lead', 'analyst', 'specialist'
                    )),
    description     TEXT,
    band_required   TEXT    NOT NULL CHECK (band_required IN (
                        'Analyst', 'Consultant', 'Senior Consultant',
                        'Manager', 'Senior Manager', 'Director', 'Partner'
                    )),
    start_date      DATE    NOT NULL,
    end_date        DATE,
    status          TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'filled', 'cancelled')),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT opportunity_dates_check CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE opportunity IS
  'An open staffing slot within a team. Maps to stf:Opportunity (gUFO:RoleMixin). Demand-side of the staffing relator.';
COMMENT ON COLUMN opportunity.role_category IS
  'Normalised role archetype used by the recommendation agent as a scoring factor: engineer, manager, associate, business_analyst, expert, designer, consultant, architect, lead, analyst, specialist. Maps to the stf:RoleScheme SKOS taxonomy.';

-- ---------------------------------------------------------------------------
-- Table: opportunity_skill
-- Skills required for an opportunity
-- ---------------------------------------------------------------------------
CREATE TABLE opportunity_skill (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID    NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    skill_id        TEXT,           -- SKOS concept notation — links to stf:SkillScheme for ontology-aware matching
    skill_name      TEXT    NOT NULL,
    skill_type      TEXT    NOT NULL CHECK (skill_type IN ('technical', 'functional', 'leadership', 'domain')),
    min_proficiency TEXT    CHECK (min_proficiency IN ('beginner', 'intermediate', 'advanced', 'expert')),
    is_mandatory    BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE opportunity_skill IS
  'Skills required for an opportunity. is_mandatory=true means the assigned person MUST have the skill (enforced by SHACL).';
COMMENT ON COLUMN opportunity_skill.skill_id IS
  'SKOS skos:notation linking to the skill concept. Enables skos:broaderTransitive matching in SPARQL (e.g. ScrumMaster satisfies AgileDelivery).';
COMMENT ON COLUMN opportunity_skill.min_proficiency IS
  'Minimum proficiency level required. NULL means any proficiency is acceptable.';

-- ---------------------------------------------------------------------------
-- Table: opportunity_qualification
-- Academic qualifications required for an opportunity
-- ---------------------------------------------------------------------------
CREATE TABLE opportunity_qualification (
    id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id      UUID    NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    qualification_level TEXT    NOT NULL CHECK (qualification_level IN ('bachelor', 'master', 'phd', 'professional')),
    field_of_study      TEXT,
    is_mandatory        BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE opportunity_qualification IS
  'Academic qualifications required for an opportunity. is_mandatory=true enforces hard requirement.';

-- ---------------------------------------------------------------------------
-- Table: opportunity_certification
-- Certifications required for an opportunity (closes the SHACL stf:requiresCertification reference)
-- ---------------------------------------------------------------------------
CREATE TABLE opportunity_certification (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID    NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    cert_name       TEXT    NOT NULL,
    is_mandatory    BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE opportunity_certification IS
  'Certifications required for an opportunity. is_mandatory=true is enforced by SHACL CertificationValidityShape (stf:requiresCertification / stf:certRequirementMandatory).';

-- ---------------------------------------------------------------------------
-- Table: opportunity_language
-- Language requirements for an opportunity
-- ---------------------------------------------------------------------------
CREATE TABLE opportunity_language (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID    NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    language_code   TEXT    NOT NULL,   -- IETF BCP 47 tag, matches person_language.language_code
    min_proficiency TEXT    NOT NULL DEFAULT 'professional' CHECK (min_proficiency IN (
                        'native', 'fluent', 'professional', 'basic'
                    )),
    is_mandatory    BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE opportunity_language IS
  'Language requirements for an opportunity (used only when a language is specified). Matched against person_language by the recommendation agent.';

-- ---------------------------------------------------------------------------
-- Table: person_citizenship
-- Citizenships / nationalities held by a person (supports dual citizenship)
-- ---------------------------------------------------------------------------
CREATE TABLE person_citizenship (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id       UUID    NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    country_code    TEXT    NOT NULL,   -- ISO 3166-1 alpha-2 (e.g. 'GB', 'US', 'SG', 'IN', 'DE', 'AU')
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (person_id, country_code)
);

COMMENT ON TABLE person_citizenship IS
  'Citizenships held by a person (ISO 3166-1 alpha-2). Supports dual citizenship. Used for citizenship-gated staffing (e.g. government / cleared work).';

-- ---------------------------------------------------------------------------
-- Table: opportunity_citizenship
-- Citizenship requirements for an opportunity (used only when specified)
-- ---------------------------------------------------------------------------
CREATE TABLE opportunity_citizenship (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID    NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    country_code    TEXT    NOT NULL,   -- ISO 3166-1 alpha-2
    is_mandatory    BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE opportunity_citizenship IS
  'Citizenship requirements for an opportunity. When present and mandatory, a candidate must hold at least one matching citizenship. A hard gate in the recommendation scorer.';

-- ---------------------------------------------------------------------------
-- Table: assignment
-- The linking relator between a person and an opportunity (gUFO:Relator)
-- ---------------------------------------------------------------------------
CREATE TABLE assignment (
    id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID          NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    person_id       UUID          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    start_date      DATE          NOT NULL,
    end_date        DATE,
    allocation_pct  NUMERIC(5,2)  NOT NULL DEFAULT 100 CHECK (allocation_pct > 0 AND allocation_pct <= 100),
    status          TEXT          NOT NULL CHECK (status IN ('short_listed', 'staffed', 'cancelled')),
    notes           TEXT,
    assigned_by     UUID          REFERENCES person(id) ON DELETE SET NULL,
    assigned_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT assignment_dates_check CHECK (end_date IS NULL OR end_date >= start_date),
    CONSTRAINT assignment_unique_active UNIQUE NULLS NOT DISTINCT (person_id, opportunity_id, status)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE assignment IS
  'Maps a person to an opportunity. Lifecycle: short_listed → staffed | cancelled. Maps to stf:ProjectAllocation (gUFO:Relator).';
COMMENT ON COLUMN assignment.status IS
  'Workflow state: short_listed (candidate identified), staffed (confirmed), cancelled (withdrawn).';
COMMENT ON COLUMN assignment.allocation_pct IS
  'Percentage of the person capacity committed to this assignment (0 < value <= 100). Required for detecting overcommitment (sum > 100).';

-- ---------------------------------------------------------------------------
-- Table: prov_log
-- Provenance / audit log for all entity changes
-- ---------------------------------------------------------------------------
CREATE TABLE prov_log (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT        NOT NULL,
    entity_id   UUID        NOT NULL,
    action      TEXT        NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    actor_id    UUID        REFERENCES person(id) ON DELETE SET NULL,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload     JSONB,
    reason      TEXT,
    session_id  TEXT,
    ip_address  INET
);

COMMENT ON TABLE prov_log IS
  'Immutable provenance / audit trail. Maps to PROV-DM model. entity_type + entity_id identify the affected row. payload holds the full row snapshot (jsonb).';
COMMENT ON COLUMN prov_log.payload IS
  'Full JSON snapshot of the row at time of change (NEW for INSERT/UPDATE, OLD for DELETE).';
COMMENT ON COLUMN prov_log.reason IS
  'Optional human-readable justification for the change (e.g., "Approved by engagement partner").';

-- ---------------------------------------------------------------------------
-- Table: person_language
-- Languages spoken by a person (gUFO:IntrinsicMode — inherent capability)
-- ---------------------------------------------------------------------------
CREATE TABLE person_language (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id       UUID    NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    language_code   TEXT    NOT NULL,  -- IETF BCP 47 tag e.g. 'en', 'fr', 'de', 'zh-Hans'
    language_name   TEXT    NOT NULL,
    proficiency     TEXT    NOT NULL CHECK (proficiency IN (
                        'native', 'fluent', 'professional', 'basic'
                    )),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (person_id, language_code)
);

COMMENT ON TABLE person_language IS
  'Languages spoken by a person. Maps to gUFO:IntrinsicMode. language_code uses IETF BCP 47 tags.';

-- ---------------------------------------------------------------------------
-- Table: domain_event
-- Immutable record of all domain events (event sourcing / pub-sub source)
-- ---------------------------------------------------------------------------
CREATE TABLE domain_event (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      TEXT        NOT NULL,  -- e.g. PROJECT_CREATED, TEAM_CREATED, ASSIGNMENT_STATUS_CHANGED
    aggregate_type  TEXT        NOT NULL,  -- e.g. project, team, assignment
    aggregate_id    UUID        NOT NULL,
    actor_id        UUID        REFERENCES person(id) ON DELETE SET NULL,
    payload         JSONB       NOT NULL,  -- full event payload
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ,           -- set when agent/worker consumes it
    processing_error TEXT                  -- last error if processing failed
);

COMMENT ON TABLE domain_event IS
  'Immutable event log for all domain mutations. Populated by triggers. Consumed by the agentic layer via pg_notify or polling. '
  'event_type drives the nudge/recommendation workflow (PROJECT_CREATED → nudge leadership; TEAM_CREATED → recommend candidates).';

-- ---------------------------------------------------------------------------
-- Table: notification
-- Actionable nudges sent to users (created from domain_events by the agent)
-- ---------------------------------------------------------------------------
CREATE TABLE notification (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        UUID        REFERENCES domain_event(id) ON DELETE SET NULL,
    recipient_id    UUID        NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    type            TEXT        NOT NULL CHECK (type IN (
                        'nudge_create_team',        -- project created, no team yet
                        'nudge_fill_opportunity',   -- team created, opportunities open
                        'candidate_recommendation', -- agent found a match
                        'approval_request',         -- HITL approval needed
                        'assignment_confirmed',     -- person confirmed on opportunity
                        'assignment_cancelled',     -- assignment cancelled
                        'certification_expiring'    -- cert expires within 30 days
                    )),
    title           TEXT        NOT NULL,
    body            TEXT        NOT NULL,
    metadata        JSONB,                -- structured payload (opportunity_id, candidate_ids, etc.)
    is_read         BOOLEAN     NOT NULL DEFAULT false,
    read_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ
);

COMMENT ON TABLE notification IS
  'Actionable nudges surfaced to users. Created by the agentic layer in response to domain_events. '
  'The approval_request type represents a HITL gate requiring human action before the agent proceeds.';

-- =============================================================================
-- INDEXES
-- =============================================================================

-- person
CREATE INDEX idx_person_band        ON person(band);
CREATE INDEX idx_person_region      ON person(region);
CREATE INDEX idx_person_office      ON person(office);
CREATE INDEX idx_person_email       ON person(email);

-- skills
CREATE INDEX idx_skills_person_id   ON skills(person_id);
CREATE INDEX idx_skills_skill_name  ON skills(skill_name);
CREATE INDEX idx_skills_skill_type  ON skills(skill_type);
CREATE INDEX idx_skills_skill_id    ON skills(skill_id);

-- certifications
CREATE INDEX idx_cert_person_id     ON certifications(person_id);
CREATE INDEX idx_cert_name          ON certifications(name);
CREATE INDEX idx_cert_is_valid      ON certifications(is_valid);

-- qualifications
CREATE INDEX idx_qual_person_id     ON qualifications(person_id);
CREATE INDEX idx_qual_level         ON qualifications(level);

-- project
CREATE INDEX idx_project_status     ON project(status);
CREATE INDEX idx_project_region     ON project(region);
CREATE INDEX idx_project_industry   ON project(industry);
CREATE INDEX idx_project_client     ON project(client);
CREATE INDEX idx_project_dates      ON project(start_date, end_date);

-- staffing_history
CREATE INDEX idx_sh_person_id       ON staffing_history(person_id);
CREATE INDEX idx_sh_project_id      ON staffing_history(project_id);
CREATE INDEX idx_sh_dates           ON staffing_history(start_date, end_date);

-- leadership
CREATE INDEX idx_leadership_project ON leadership(project_id);
CREATE INDEX idx_leadership_person  ON leadership(person_id);

-- team
CREATE INDEX idx_team_project_id    ON team(project_id);
CREATE INDEX idx_team_lead          ON team(team_lead_id);

-- opportunity
CREATE INDEX idx_opp_team_id        ON opportunity(team_id);
CREATE INDEX idx_opp_status         ON opportunity(status);
CREATE INDEX idx_opp_band           ON opportunity(band_required);
CREATE INDEX idx_opp_dates          ON opportunity(start_date, end_date);

-- opportunity_skill
CREATE INDEX idx_oppskill_opp_id    ON opportunity_skill(opportunity_id);
CREATE INDEX idx_oppskill_name      ON opportunity_skill(skill_name);

-- opportunity_qualification
CREATE INDEX idx_oppqual_opp_id     ON opportunity_qualification(opportunity_id);

-- opportunity_certification / language / citizenship
CREATE INDEX idx_oppcert_opp_id     ON opportunity_certification(opportunity_id);
CREATE INDEX idx_opplang_opp_id     ON opportunity_language(opportunity_id);
CREATE INDEX idx_oppcit_opp_id      ON opportunity_citizenship(opportunity_id);

-- person_citizenship
CREATE INDEX idx_pcit_person_id     ON person_citizenship(person_id);
CREATE INDEX idx_pcit_country       ON person_citizenship(country_code);

-- person / opportunity role_category
CREATE INDEX idx_person_role_cat    ON person(role_category);
CREATE INDEX idx_opp_role_cat       ON opportunity(role_category);

-- assignment
CREATE INDEX idx_assign_opp_id      ON assignment(opportunity_id);
CREATE INDEX idx_assign_person_id   ON assignment(person_id);
CREATE INDEX idx_assign_status      ON assignment(status);
CREATE INDEX idx_assign_dates       ON assignment(start_date, end_date);
CREATE INDEX idx_assign_assigned_by ON assignment(assigned_by);

-- prov_log
CREATE INDEX idx_prov_entity        ON prov_log(entity_type, entity_id);
CREATE INDEX idx_prov_timestamp     ON prov_log(timestamp DESC);
CREATE INDEX idx_prov_actor         ON prov_log(actor_id);
CREATE INDEX idx_prov_action        ON prov_log(action);
-- GIN index for JSONB payload querying
CREATE INDEX idx_prov_payload       ON prov_log USING gin(payload);

-- person_language
CREATE INDEX idx_lang_person_id     ON person_language(person_id);
CREATE INDEX idx_lang_code          ON person_language(language_code);

-- person (new columns)
CREATE INDEX idx_person_status      ON person(status);
CREATE INDEX idx_person_hire_date   ON person(hire_date);

-- skills (new columns)
CREATE INDEX idx_skills_proficiency ON skills(proficiency_level);

-- domain_event
CREATE INDEX idx_event_type         ON domain_event(event_type);
CREATE INDEX idx_event_aggregate    ON domain_event(aggregate_type, aggregate_id);
CREATE INDEX idx_event_created      ON domain_event(created_at DESC);
CREATE INDEX idx_event_unprocessed  ON domain_event(created_at) WHERE processed_at IS NULL;
CREATE INDEX idx_event_payload      ON domain_event USING gin(payload);

-- notification
CREATE INDEX idx_notif_recipient    ON notification(recipient_id);
CREATE INDEX idx_notif_unread       ON notification(recipient_id) WHERE is_read = false;
CREATE INDEX idx_notif_type         ON notification(type);
CREATE INDEX idx_notif_created      ON notification(created_at DESC);

-- Covering index for availability computation (the hottest query path)
CREATE INDEX idx_assign_avail ON assignment(person_id, status, start_date, end_date)
    WHERE status IN ('short_listed', 'staffed');

-- =============================================================================
-- VIEWS
-- =============================================================================

-- ---------------------------------------------------------------------------
-- View: person_availability
-- Derives the current gUFO Phase for every active person from live assignments.
-- Phases: Available | PartiallyAllocated | FullyAllocated | OnLeave
-- This view is the Postgres source that the Jena ABox projection is built from.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW person_availability AS
WITH active_alloc AS (
    SELECT
        a.person_id,
        SUM(a.allocation_pct)                                               AS total_pct,
        COUNT(*)                                                            AS assignment_count,
        MAX(a.end_date)                                                     AS latest_end,
        ARRAY_AGG(DISTINCT a.status)                                        AS statuses,
        ARRAY_AGG(JSONB_BUILD_OBJECT(
            'assignment_id',   a.id,
            'opportunity_id',  a.opportunity_id,
            'status',          a.status,
            'allocation_pct',  a.allocation_pct,
            'start_date',      a.start_date,
            'end_date',        a.end_date
        )) AS active_assignments
    FROM assignment a
    WHERE a.status IN ('short_listed', 'staffed')
      AND a.start_date <= CURRENT_DATE
      AND (a.end_date IS NULL OR a.end_date >= CURRENT_DATE)
    GROUP BY a.person_id
)
SELECT
    p.id                                            AS person_id,
    p.name,
    p.band,
    p.region,
    p.office,
    p.status                                        AS person_status,
    COALESCE(aa.total_pct, 0)                       AS allocated_pct,
    COALESCE(100 - aa.total_pct, 100)               AS available_pct,
    COALESCE(aa.assignment_count, 0)                AS active_assignment_count,
    CASE
        WHEN p.status = 'on_leave'                  THEN 'OnLeave'
        WHEN p.status = 'inactive'                  THEN 'Inactive'
        WHEN aa.total_pct IS NULL                   THEN 'Available'
        WHEN aa.total_pct >= 100                    THEN 'FullyAllocated'
        ELSE                                             'PartiallyAllocated'
    END                                             AS availability_phase,
    aa.latest_end                                   AS next_available_date,
    COALESCE(aa.statuses, ARRAY[]::TEXT[])          AS assignment_statuses,
    COALESCE(aa.active_assignments, ARRAY[]::JSONB[]) AS active_assignments
FROM person p
LEFT JOIN active_alloc aa ON aa.person_id = p.id;

COMMENT ON VIEW person_availability IS
  'Derived availability phase for each person, computed from live assignments. '
  'availability_phase maps to gUFO Phases: Available | PartiallyAllocated | FullyAllocated | OnLeave. '
  'This view is used by the SPARQL ABox projection (Postgres → Jena) to maintain the semantic graph. '
  'available_pct = 100 - sum(allocation_pct) for active assignments overlapping today.';

-- =============================================================================
-- TRIGGER FUNCTIONS & TRIGGERS (Event-driven domain events + pg_notify)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Helper: emit a domain event and fire pg_notify on channel 'staffing_events'
-- Called by all entity-level triggers below.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_emit_domain_event()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_event_type    TEXT;
    v_payload       JSONB;
    v_event_id      UUID;
BEGIN
    -- Determine event type from table name + operation
    v_event_type := TG_TABLE_NAME || '_' || TG_OP;  -- e.g. project_INSERT, assignment_UPDATE

    -- Build payload: NEW row for INSERT/UPDATE, OLD row for DELETE
    IF TG_OP = 'DELETE' THEN
        v_payload := TO_JSONB(OLD);
    ELSE
        v_payload := TO_JSONB(NEW);
    END IF;

    -- Insert into domain_event log
    INSERT INTO domain_event (event_type, aggregate_type, aggregate_id, payload)
    VALUES (v_event_type, TG_TABLE_NAME, COALESCE(NEW.id, OLD.id), v_payload)
    RETURNING id INTO v_event_id;

    -- Fire pg_notify so async listeners (Python asyncpg / LangGraph) wake immediately
    PERFORM pg_notify(
        'staffing_events',
        JSONB_BUILD_OBJECT(
            'event_id',      v_event_id,
            'event_type',    v_event_type,
            'aggregate_type', TG_TABLE_NAME,
            'aggregate_id',  COALESCE(NEW.id, OLD.id)
        )::TEXT
    );

    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------
-- Trigger: project — fire on INSERT (project created → nudge leadership)
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_project_event
AFTER INSERT OR UPDATE ON project
FOR EACH ROW EXECUTE FUNCTION fn_emit_domain_event();

-- ---------------------------------------------------------------------------
-- Trigger: team — fire on INSERT (team created → trigger recommendations)
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_team_event
AFTER INSERT ON team
FOR EACH ROW EXECUTE FUNCTION fn_emit_domain_event();

-- ---------------------------------------------------------------------------
-- Trigger: opportunity — fire on INSERT or status change
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_opportunity_event
AFTER INSERT OR UPDATE OF status ON opportunity
FOR EACH ROW EXECUTE FUNCTION fn_emit_domain_event();

-- ---------------------------------------------------------------------------
-- Trigger: assignment — fire on INSERT and status changes (HITL events)
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_assignment_event
AFTER INSERT OR UPDATE OF status ON assignment
FOR EACH ROW EXECUTE FUNCTION fn_emit_domain_event();

-- ---------------------------------------------------------------------------
-- Trigger: prevent staffing when person.status = 'on_leave' or 'inactive'
-- Enforces the OnLeave gUFO phase at the DB layer (SHACL enforces it in Jena).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_block_unavailable_assignment()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_status TEXT;
BEGIN
    SELECT status INTO v_status FROM person WHERE id = NEW.person_id;
    IF v_status IN ('on_leave', 'inactive') THEN
        RAISE EXCEPTION
            'Cannot assign person % — current status is "%". '
            'A person must be active or bench to receive assignments.',
            NEW.person_id, v_status;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_block_unavailable
BEFORE INSERT OR UPDATE ON assignment
FOR EACH ROW EXECUTE FUNCTION fn_block_unavailable_assignment();

-- ---------------------------------------------------------------------------
-- Trigger: prevent total allocation_pct exceeding 100% for a person on overlapping dates
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_check_allocation_cap()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_total NUMERIC;
BEGIN
    SELECT COALESCE(SUM(allocation_pct), 0) INTO v_total
    FROM assignment
    WHERE person_id = NEW.person_id
      AND id        != NEW.id
      AND status    IN ('short_listed', 'staffed')
      AND start_date <= COALESCE(NEW.end_date, '9999-12-31'::DATE)
      AND (end_date IS NULL OR end_date >= NEW.start_date);

    IF v_total + NEW.allocation_pct > 100 THEN
        RAISE EXCEPTION
            'Allocation cap exceeded for person %: existing active allocations total %% during requested period. '
            'Adding %% would exceed 100%%.',
            NEW.person_id, v_total, NEW.allocation_pct;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_allocation_cap
BEFORE INSERT OR UPDATE ON assignment
FOR EACH ROW
WHEN (NEW.status IN ('short_listed', 'staffed'))
EXECUTE FUNCTION fn_check_allocation_cap();
