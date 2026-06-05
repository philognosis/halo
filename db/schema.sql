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
    band                        TEXT        NOT NULL CHECK (band IN (
                                    'Analyst', 'Consultant', 'Senior Consultant',
                                    'Manager', 'Senior Manager', 'Director', 'Partner'
                                )),
    location                    TEXT        NOT NULL,
    office                      TEXT        NOT NULL,
    region                      TEXT        NOT NULL CHECK (region IN ('EMEA', 'Americas', 'APAC')),
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

-- ---------------------------------------------------------------------------
-- Table: skills
-- Skill possessed by a person (projected as gUFO:Quality on the Employee role)
-- ---------------------------------------------------------------------------
CREATE TABLE skills (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id   UUID    NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    skill_id    TEXT    NOT NULL,   -- SKOS concept notation (e.g. "Python", "TOGAF")
    skill_name  TEXT    NOT NULL,
    skill_type  TEXT    NOT NULL CHECK (skill_type IN ('technical', 'functional', 'leadership', 'domain')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE skills IS
  'Skills possessed by a person, classified by type. Skill_id references a SKOS concept in the Jena taxonomy graph.';
COMMENT ON COLUMN skills.skill_id IS
  'SKOS skos:notation value linking to the concept in the stf:SkillScheme concept scheme.';
COMMENT ON COLUMN skills.skill_type IS
  'Broad category: technical | functional | leadership | domain.';

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
    status       TEXT    NOT NULL CHECK (status IN ('active', 'completed', 'on_hold', 'cancelled', 'pipeline')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT project_dates_check CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE project IS
  'Client engagement. Maps to stf:ClientEngagement (gUFO:Event). unique_code is a human-readable project reference.';

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
    band_required   TEXT    NOT NULL CHECK (band_required IN (
                        'Analyst', 'Consultant', 'Senior Consultant',
                        'Manager', 'Senior Manager', 'Director', 'Partner'
                    )),
    start_date      DATE    NOT NULL,
    end_date        DATE,
    status          TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'filled', 'cancelled')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT opportunity_dates_check CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE opportunity IS
  'An open staffing slot within a team. Maps to stf:Opportunity (gUFO:RoleMixin). Demand-side of the staffing relator.';

-- ---------------------------------------------------------------------------
-- Table: opportunity_skill
-- Skills required for an opportunity
-- ---------------------------------------------------------------------------
CREATE TABLE opportunity_skill (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID    NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    skill_name      TEXT    NOT NULL,
    skill_type      TEXT    NOT NULL CHECK (skill_type IN ('technical', 'functional', 'leadership', 'domain')),
    is_mandatory    BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE opportunity_skill IS
  'Skills required for an opportunity. is_mandatory=true means the assigned person MUST have the skill (enforced by SHACL).';

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
-- Table: assignment
-- The linking relator between a person and an opportunity (gUFO:Relator)
-- ---------------------------------------------------------------------------
CREATE TABLE assignment (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID        NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    person_id       UUID        NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    start_date      DATE        NOT NULL,
    end_date        DATE,
    status          TEXT        NOT NULL CHECK (status IN ('short_listed', 'staffed', 'cancelled')),
    notes           TEXT,
    assigned_by     UUID        REFERENCES person(id) ON DELETE SET NULL,
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT assignment_dates_check CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE assignment IS
  'Maps a person to an opportunity. Lifecycle: short_listed → staffed | cancelled. Maps to stf:ProjectAllocation (gUFO:Relator).';
COMMENT ON COLUMN assignment.status IS
  'Workflow state: short_listed (candidate identified), staffed (confirmed), cancelled (withdrawn).';

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
