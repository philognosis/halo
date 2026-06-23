# Ontology Layer — Documentation

This directory contains the **three-layer ontology stack** for the Ontology-Driven Agentic Staffing System. It is consumed by Apache Jena Fuseki at runtime and provides the semantic backbone for agentic reasoning, SHACL validation, and SPARQL-based staffing decisions.

---

## 1. Three-Layer Ontology Stack

```
┌────────────────────────────────────────────────────────┐
│  Layer 3 — RDF Data (ABox)                              │
│  abox-sample.ttl                                        │
│  Instances projected from PostgreSQL. PROV-DM triples   │
│  for audit. Reasoned over at query time.                │
├────────────────────────────────────────────────────────┤
│  Layer 2 — OWL 2 Schema (TBox)                          │
│  staffing-ontology.ttl + skos-taxonomy.ttl              │
│  Class hierarchy, properties, cardinality axioms.        │
│  SKOS concept scheme for skill vocabulary.               │
├────────────────────────────────────────────────────────┤
│  Layer 1 — Foundational Ontology (UFO/gUFO)             │
│  Imported via gUFO prefix (purl.org/nemo/gufo)          │
│  Provides meta-level distinctions:                       │
│    Kind (rigid) · Role (anti-rigid) · Phase              │
│    Quality · Relator · Event · Collection                │
└────────────────────────────────────────────────────────┘
```

### Layer 1 — gUFO (Gentle Unified Foundational Ontology)

Provides principled meta-level distinctions used to classify every concept:

| gUFO type | Meaning | Example |
|---|---|---|
| `gufo:Kind` | Rigid sortal — persists regardless of context | `stf:Person` |
| `gufo:Role` | Anti-rigid — played in a context, can be lost | `stf:Employee` |
| `gufo:Phase` | Anti-rigid, intrinsically determined | `stf:Available` |
| `gufo:Quality` | Inherent attribute of an individual | `stf:SkillProfile` |
| `gufo:Relator` | Mediates a relationship between two individuals | `stf:ProjectAllocation` |
| `gufo:Event` | Bounded occurrence in time | `stf:ClientEngagement` |
| `gufo:Collection` | Aggregate of individuals | `stf:ProjectTeam` |

### Layer 2 — OWL 2 TBox

Defines the schema used to classify instances in the ABox. Key design decisions:

- **`stf:Person` is a `gufo:Kind`** — a consultant's identity persists even if they are not currently an employee.
- **`stf:Employee` is a `gufo:Role`** — employment is a context-dependent role, not a property of the person.
- **Availability phases are disjoint** — `owl:AllDisjointClasses` prevents a person being simultaneously `Available` and `FullyAllocated`.
- **`stf:ProjectAllocation` is a `gufo:Relator`** — it depends existentially on both the `Employee` and the `Opportunity`.

### Layer 3 — RDF ABox

Instance data projected from PostgreSQL. Updated continuously by a projection job. The ABox is not the source of truth — PostgreSQL is. The ABox enables SPARQL reasoning and SHACL validation.

---

## 2. Files

| File | Content |
|---|---|
| `staffing-ontology.ttl` | Master OWL 2 TBox: classes, object properties, datatype properties, OWL axioms, PROV-DM links |
| `skos-taxonomy.ttl` | SKOS `ConceptScheme` for skills: 4 top-level categories, ~40 concepts with `prefLabel`, `altLabel`, `definition`, `notation`, `broader`/`narrower` |
| `shacl-shapes.ttl` | 8 SHACL shapes enforcing business rules (see table below) |
| `abox-sample.ttl` | Sample RDF instance data for 3 persons, 2 projects, 2 allocations, PROV-DM provenance triples |

---

## 3. Dual-Store Pattern

```
  PostgreSQL (source of truth)          Apache Jena Fuseki
  ┌─────────────────────────┐           ┌──────────────────────────────┐
  │ person, skills,          │  project  │ Named Graph: tbox            │
  │ certifications,          │  ──────►  │   staffing-ontology.ttl       │
  │ project, assignment, ... │           │   (OWL classes + properties)  │
  │                          │           ├──────────────────────────────┤
  │ prov_log (audit trail)   │           │ Named Graph: skos             │
  └─────────────────────────┘           │   skos-taxonomy.ttl           │
                                         │   (skill concept scheme)      │
  Projection job (Phase 2):              ├──────────────────────────────┤
  reads PostgreSQL → converts            │ Named Graph: shacl            │
  rows to RDF triples → PUTs            │   shacl-shapes.ttl            │
  into Fuseki ABox graph                 │   (validation rules)          │
                                         ├──────────────────────────────┤
                                         │ Named Graph: abox             │
                                         │   person/project/allocation   │
                                         │   instances + PROV triples    │
                                         └──────────────────────────────┘
```

**PostgreSQL** handles all writes (CRUD, ACID transactions, FK integrity).  
**Jena Fuseki** handles reads for semantic reasoning: SPARQL queries, SHACL validation, OWL inference.

---

## 4. Named Graphs

| Named Graph URI | Contents | Purpose |
|---|---|---|
| `http://enterprise.org/graphs/tbox` | `staffing-ontology.ttl` | OWL 2 class and property definitions |
| `http://enterprise.org/graphs/skos` | `skos-taxonomy.ttl` | SKOS skill concept scheme |
| `http://enterprise.org/graphs/shacl` | `shacl-shapes.ttl` | SHACL business rule shapes |
| `http://enterprise.org/graphs/abox` | `abox-sample.ttl` / projected data | RDF instance data for reasoning |

---

## 5. SHACL Shapes

| Shape | Target Class | Rule Enforced | Severity |
|---|---|---|---|
| `stf:PersonShape` | `stf:Person` | Must have `hasName` (1), `hasEmail` (regex), `hasBand` (enum) | Violation |
| `stf:ProjectTeamStructuralShape` | `stf:ProjectTeam` | Must have `>= 2` `stf:hasStaffedSeat` links | Violation |
| `stf:EmployeeDoubleAllocationShape` | `stf:Employee` | SPARQL: no date-overlapping `hasActiveAllocation` entries | Violation |
| `stf:AllocationDateShape` | `stf:ProjectAllocation` | SPARQL: `allocationEnd >= allocationStart` | Violation |
| `stf:OpportunityBandShape` | `stf:ProjectAllocation` | SPARQL: assigned employee band matches `requiredBand` | Violation |
| `stf:CertificationValidityShape` | `stf:ProjectAllocation` | SPARQL: mandatory certification held and not expired | Violation |
| `stf:ProjectDateShape` | `stf:ClientEngagement` | SPARQL: `projectEndDate >= projectStartDate` | Violation |
| `stf:AssignmentStatusShape` | `stf:ProjectAllocation` | `assignmentStatus` in {short_listed, staffed, cancelled} | Violation |

---

## 6. SKOS Skill Taxonomy (Top-Level View)

```
stf:SkillScheme
├── TechnicalSkills
│   ├── DataEngineering
│   │   ├── Python, Spark, SQL, Kafka, dbt
│   ├── SoftwareDevelopment
│   │   ├── Java, React, TypeScript, Microservices
│   ├── CloudPlatforms
│   │   ├── AWS, GCP, Azure
│   ├── DataScience
│   │   ├── MachineLearning (PyTorch, TensorFlow)
│   │   ├── DeepLearning, NLP, ArtificialIntelligence
│   └── Analytics
├── FunctionalSkills
│   ├── StrategyConsulting, ChangeManagement, PMO
│   ├── BusinessAnalysis, ProcessImprovement
│   └── ProjectManager (role alias concept)
├── LeadershipSkills
│   ├── TeamLeadership, StakeholderManagement
│   └── ExecutivePresence, ClientRelationships
└── DomainSkills
    ├── FinancialServices
    │   ├── Banking, AssetManagement, Insurance, Payments
    ├── Healthcare, Energy, Retail
    └── Technology, Manufacturing
```

---

## 7. Loading via Docker Compose

### Start all services (auto-loads ontology on first run)

```bash
# Start Fuseki + PostgreSQL (ontology auto-loaded by fuseki-init service)
docker compose up -d

# Check Fuseki health
curl -u admin:admin-changeme http://localhost:3030/$/ping

# Access SPARQL UI
open http://localhost:3030/staffing
```

### Start with optional PgAdmin

```bash
docker compose --profile tools up -d
# PgAdmin available at http://localhost:5050
```

### Manually reload ontology

```bash
# If you need to reload after editing TTL files:
FUSEKI_URL=http://localhost:3030 \
FUSEKI_ADMIN_PASSWORD=admin-changeme \
./scripts/load_ontology.sh
```

### Initialise PostgreSQL only

```bash
PGHOST=localhost PGDATABASE=staffingdb PGUSER=staffing \
PGPASSWORD=staffing-changeme ./scripts/init_db.sh
```

---

## 8. Example SPARQL Query — Available Consultants with a Skill

Find all `Available` consultants who have the `Python` skill:

```sparql
PREFIX stf:  <http://enterprise.org/staffing/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

SELECT ?person ?name ?band ?region
WHERE {
  GRAPH <http://enterprise.org/graphs/abox> {
    ?person a stf:Available ;
            stf:hasName    ?name ;
            stf:hasBand    ?band ;
            stf:hasRegion  ?region ;
            stf:hasSkill   ?skillConcept .
  }
  GRAPH <http://enterprise.org/graphs/skos> {
    ?skillConcept skos:notation "Python" .
  }
}
ORDER BY ?band ?name
```

Find consultants available for a specific opportunity band, sorted by experience:

```sparql
PREFIX stf:  <http://enterprise.org/staffing/>

SELECT ?person ?name ?band ?totalExp
WHERE {
  GRAPH <http://enterprise.org/graphs/abox> {
    ?person a stf:Available ;
            stf:hasName               ?name ;
            stf:hasBand               ?band ;
            stf:totalExperienceMonths ?totalExp .
    FILTER (?band IN ("Senior Consultant", "Manager"))
  }
}
ORDER BY DESC(?totalExp)
LIMIT 10
```

---

## 9. Key Design References

- **gUFO**: Guizzardi, G. et al. — [purl.org/nemo/gufo](http://purl.org/nemo/gufo)
- **OWL 2**: W3C OWL 2 Web Ontology Language — [www.w3.org/TR/owl2-overview](https://www.w3.org/TR/owl2-overview/)
- **SHACL**: W3C Shapes Constraint Language — [www.w3.org/TR/shacl](https://www.w3.org/TR/shacl/)
- **SKOS**: W3C Simple Knowledge Organisation System — [www.w3.org/TR/skos-reference](https://www.w3.org/TR/skos-reference/)
- **PROV-DM**: W3C Provenance Data Model — [www.w3.org/TR/prov-dm](https://www.w3.org/TR/prov-dm/)
- **ESCO**: European Skills/Competences taxonomy — [esco.ec.europa.eu](https://esco.ec.europa.eu)
