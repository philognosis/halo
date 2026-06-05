# Database Layer — Documentation

PostgreSQL is the **operational source of truth** for the staffing system. All writes go through Postgres (CRUD, ACID), and data is projected into Apache Jena Fuseki for semantic reasoning. This document covers the schema design, table relationships, indexing strategy, and seed data instructions.

---

## 1. Overview

| Attribute | Value |
|---|---|
| Engine | PostgreSQL 16 |
| Schema file | `db/schema.sql` |
| Seed file | `db/seed.sql` |
| Extension | `pgcrypto` (for `gen_random_uuid()`) |
| Default database | `staffingdb` |

---

## 2. Table Descriptions

### Supply side

| Table | gUFO Mapping | Description |
|---|---|---|
| `person` | `gufo:Kind` | Core entity for every human individual. Holds identity, band, location, region. Persists independent of employment state. |
| `skills` | `gufo:Quality` (on Employee) | Competency entries per person. `skill_id` references a SKOS concept notation in Fuseki. |
| `certifications` | `gufo:Quality` | Professional certifications with issue/expiry dates. `is_valid` is a generated computed column. |
| `qualifications` | `gufo:Quality` | Academic degrees and professional qualifications (bachelor/master/phd/professional). |

### Engagement / demand side

| Table | gUFO Mapping | Description |
|---|---|---|
| `project` | `gufo:Event` | Client engagement bounded in time. Has `unique_code`, industry, sector, function, status. |
| `leadership` | — | Named leadership roles on a project (engagement_partner, delivery_lead, project_sponsor). Unique per project+role pair. |
| `team` | `gufo:Collection` | A named delivery sub-team within a project. Must have >= 2 staffed seats (SHACL rule). |
| `opportunity` | `gufo:RoleMixin` | An open staffing slot within a team. Carries band requirement, dates, and status. |
| `opportunity_skill` | — | Skills required for an opportunity. `is_mandatory=true` means hard requirement. |
| `opportunity_qualification` | — | Qualification requirements for an opportunity. |

### Staffing relators

| Table | gUFO Mapping | Description |
|---|---|---|
| `assignment` | `gufo:Relator` (active) | Links a person to an opportunity. Lifecycle: `short_listed → staffed | cancelled`. |
| `staffing_history` | `gufo:Relator` (historical) | Completed or ongoing allocation records. Supports matching and analytics. |

### Governance

| Table | Description |
|---|---|
| `prov_log` | Immutable provenance/audit log. Every mutation to core entities writes a row. Payload is JSONB full-row snapshot. |

---

## 3. Key Relationships (ERD Summary)

```
person  ──< skills
person  ──< certifications
person  ──< qualifications
person  ──< staffing_history >── project
person  ──< assignment >── opportunity >── team >── project
person  ──< leadership >── project
team    ──< opportunity
project ──< leadership
project ──< team
```

- A `person` can have many `skills`, `certifications`, `qualifications`.
- A `project` has one or more `team`s; each team has one or more `opportunity` slots.
- An `assignment` connects a `person` to an `opportunity` (many-to-many bridge with status lifecycle).
- `staffing_history` records all past/present allocations with percentage.
- `leadership` enforces unique role per project (e.g., only one `engagement_partner`).

---

## 4. Constraints and Business Rules

### CHECK constraints

| Table | Constraint | Rule |
|---|---|---|
| `person` | `band` | Must be in: Analyst, Consultant, Senior Consultant, Manager, Senior Manager, Director, Partner |
| `person` | `region` | Must be in: EMEA, Americas, APAC |
| `person` | `total_experience_months` | >= 0 |
| `certifications` | `expiry_date` | If set, must be >= `issued_date` |
| `qualifications` | `graduation_year` | Between 1950 and 2100 |
| `qualifications` | `level` | Must be in: bachelor, master, phd, professional |
| `project` | `status` | active, completed, on_hold, cancelled, pipeline |
| `project` | dates | `end_date >= start_date` if set |
| `leadership` | `role` | engagement_partner, delivery_lead, project_sponsor |
| `opportunity` | `band_required` | Same enum as `person.band` |
| `opportunity` | `status` | open, filled, cancelled |
| `assignment` | `status` | short_listed, staffed, cancelled |
| `staffing_history` | `allocation_pct` | 0 < value <= 100 |
| `prov_log` | `action` | INSERT, UPDATE, DELETE |

### Unique constraints

- `person.email` — globally unique
- `project.unique_code` — human-readable project reference
- `leadership (project_id, role)` — one leader per role per project

---

## 5. Prov Log Table

The `prov_log` table implements the **PROV-DM Activity/Entity** pattern for immutable audit logging.

```sql
CREATE TABLE prov_log (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT        NOT NULL,    -- e.g. 'assignment', 'person'
    entity_id   UUID        NOT NULL,    -- PK of the affected row
    action      TEXT        NOT NULL,    -- INSERT | UPDATE | DELETE
    actor_id    UUID        REFERENCES person(id),
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload     JSONB,                   -- full row snapshot
    reason      TEXT                     -- business justification
);
```

**Usage pattern:** Every service layer mutation should insert a `prov_log` row:
- `INSERT`: `payload` = full new row as JSON
- `UPDATE`: `payload` = full new row as JSON, `reason` = what changed and why
- `DELETE`: `payload` = full deleted row as JSON

The `session_id` and `ip_address` columns (in schema) support network-level tracing.

---

## 6. Indexing Strategy

All foreign key columns are indexed to prevent table scans on JOIN operations.
Frequently filtered columns (band, status, skill_name, etc.) have additional indexes.

| Index | Table | Columns | Purpose |
|---|---|---|---|
| `idx_person_band` | `person` | `band` | Filter by seniority band |
| `idx_person_region` | `person` | `region` | Filter by operating region |
| `idx_skills_person_id` | `skills` | `person_id` | Join person → skills |
| `idx_skills_skill_name` | `skills` | `skill_name` | Skill search |
| `idx_skills_skill_id` | `skills` | `skill_id` | SKOS concept lookup |
| `idx_cert_person_id` | `certifications` | `person_id` | Join person → certs |
| `idx_cert_is_valid` | `certifications` | `is_valid` | Filter valid certs |
| `idx_project_status` | `project` | `status` | Active/completed filter |
| `idx_project_industry` | `project` | `industry` | Industry filter |
| `idx_sh_person_id` | `staffing_history` | `person_id` | History by person |
| `idx_sh_dates` | `staffing_history` | `(start_date, end_date)` | Date range queries |
| `idx_opp_status` | `opportunity` | `status` | Open opportunity search |
| `idx_opp_band` | `opportunity` | `band_required` | Band-match queries |
| `idx_assign_person_id` | `assignment` | `person_id` | Assignment by person |
| `idx_assign_status` | `assignment` | `status` | Workflow state filter |
| `idx_prov_entity` | `prov_log` | `(entity_type, entity_id)` | Audit lookup |
| `idx_prov_payload` | `prov_log` | `payload` (GIN) | JSONB full-text search |

---

## 7. Seed Data Summary

The seed data in `db/seed.sql` provides a complete, self-consistent dataset:

| Entity | Count | Details |
|---|---|---|
| Persons | 12 | Analyst × 2, Consultant × 2, Senior Consultant × 3, Manager × 2, Senior Manager × 1, Director × 1, Partner × 1 |
| Regions | 3 | EMEA (London, Frankfurt), Americas (New York), APAC (Singapore, Mumbai, Sydney) |
| Skills | 50 | Mix of technical (Python, Spark, SQL, React, Java, ML, GCP), functional (Strategy, PMO, BA, Change Mgmt), domain (FinServ, Healthcare, Energy, Retail), leadership |
| Certifications | 16 | AWS SA, PMP, CFA, Scrum Master, TOGAF, Google Cloud, Databricks, OCP Java |
| Qualifications | 15 | BSc/BEng/BTech/BCom, MSc/MS, MBA from UCL, LBS, IIT Bombay, Columbia, INSEAD, TU Munich, etc. |
| Projects | 4 | NovaPay (FinTech/active), MedCore NHS (Healthcare/active), GreenVolt (Energy/completed), GlobalMart (Retail/active) |
| Teams | 7 | 2 on NovaPay, 2 on MedCore, 1 on GreenVolt, 2 on GlobalMart |
| Opportunities | 7 | 2 filled, 3 open, 1 cancelled + 1 replacement open |
| Assignments | 7 | 3 staffed, 3 short_listed, 1 cancelled |
| Staffing History | 6 | Past allocations including GreenVolt (completed project) |
| Prov Log | 3 | Sample audit entries for key assignment actions |

---

## 8. Running the Seed Data

### Via Docker Compose (automatic)

The `postgres` service maps `db/schema.sql` and `db/seed.sql` to `/docker-entrypoint-initdb.d/`, so they run automatically on first container startup:

```bash
docker compose up -d postgres
```

### Manually via script

```bash
export PGHOST=localhost
export PGPORT=5432
export PGDATABASE=staffingdb
export PGUSER=staffing
export PGPASSWORD=staffing-changeme

./scripts/init_db.sh
```

### Manually via psql

```bash
psql -h localhost -U staffing -d staffingdb -f db/schema.sql
psql -h localhost -U staffing -d staffingdb -f db/seed.sql
```

### Reset and re-seed

```bash
# Drop and recreate the database, then re-run
psql -h localhost -U staffing -d postgres -c "DROP DATABASE IF EXISTS staffingdb;"
psql -h localhost -U staffing -d postgres -c "CREATE DATABASE staffingdb;"
psql -h localhost -U staffing -d staffingdb -f db/schema.sql
psql -h localhost -U staffing -d staffingdb -f db/seed.sql
```

---

## 9. Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `PGHOST` | `localhost` | PostgreSQL host |
| `PGPORT` | `5432` | PostgreSQL port |
| `PGDATABASE` | `staffingdb` | Database name |
| `PGUSER` | `staffing` | Database user |
| `PGPASSWORD` | `staffing-changeme` | Database password |
| `POSTGRES_DB` | `staffingdb` | Docker env var for DB name |
| `POSTGRES_USER` | `staffing` | Docker env var for DB user |
| `POSTGRES_PASSWORD` | `staffing-changeme` | Docker env var for DB password |

> **Security note:** Change all default passwords before deploying to any non-local environment. Use a `.env` file (excluded from git) to override values for `docker compose`.
