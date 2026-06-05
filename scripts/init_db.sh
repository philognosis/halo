#!/usr/bin/env bash
# =============================================================================
# init_db.sh
# Initialises the PostgreSQL staffing database by running schema.sql then
# seed.sql using psql.
#
# Environment variables (with defaults):
#   PGHOST     — database host       (default: localhost)
#   PGPORT     — database port       (default: 5432)
#   PGDATABASE — database name       (default: staffingdb)
#   PGUSER     — database user       (default: staffing)
#   PGPASSWORD — database password   (default: staffing-changeme)
#   DB_DIR     — directory with SQL files (default: script's parent ../db)
#   MAX_RETRIES — max connection retries (default: 20)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGDATABASE="${PGDATABASE:-staffingdb}"
export PGUSER="${PGUSER:-staffing}"
export PGPASSWORD="${PGPASSWORD:-staffing-changeme}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_DIR="${DB_DIR:-${SCRIPT_DIR}/../db}"
MAX_RETRIES="${MAX_RETRIES:-20}"
RETRY_INTERVAL=3

SCHEMA_FILE="${DB_DIR}/schema.sql"
SEED_FILE="${DB_DIR}/seed.sql"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
green()  { echo -e "\033[32m$*\033[0m"; }
red()    { echo -e "\033[31m$*\033[0m"; }
blue()   { echo -e "\033[34m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
blue "==> Preflight: checking required tools and files..."

if ! command -v psql &> /dev/null; then
    red "ERROR: psql is not installed or not in PATH."
    exit 1
fi

if [ ! -f "$SCHEMA_FILE" ]; then
    red "ERROR: Schema file not found: $SCHEMA_FILE"
    exit 1
fi

if [ ! -f "$SEED_FILE" ]; then
    red "ERROR: Seed file not found: $SEED_FILE"
    exit 1
fi

green "  psql found: $(psql --version)"
green "  Schema file: $SCHEMA_FILE"
green "  Seed file  : $SEED_FILE"

# ---------------------------------------------------------------------------
# Step 1: Wait for PostgreSQL to accept connections
# ---------------------------------------------------------------------------
blue "==> Waiting for PostgreSQL at ${PGHOST}:${PGPORT} (database: ${PGDATABASE}, user: ${PGUSER})..."

attempt=0
until psql -c '\q' > /dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$MAX_RETRIES" ]; then
        red "ERROR: PostgreSQL not available after $((MAX_RETRIES * RETRY_INTERVAL)) seconds. Aborting."
        exit 1
    fi
    yellow "  Not ready yet (attempt ${attempt}/${MAX_RETRIES}). Retrying in ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done

green "  PostgreSQL is ready."

# ---------------------------------------------------------------------------
# Step 2: Run schema.sql
# ---------------------------------------------------------------------------
blue "==> Running schema.sql ..."

if psql \
    --variable ON_ERROR_STOP=1 \
    --echo-errors \
    --file="$SCHEMA_FILE" ; then
    green "  schema.sql executed successfully."
else
    red "ERROR: schema.sql failed. Aborting."
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 3: Run seed.sql
# ---------------------------------------------------------------------------
blue "==> Running seed.sql ..."

if psql \
    --variable ON_ERROR_STOP=1 \
    --echo-errors \
    --file="$SEED_FILE" ; then
    green "  seed.sql executed successfully."
else
    red "ERROR: seed.sql failed. Check FK references and data consistency."
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 4: Verify row counts
# ---------------------------------------------------------------------------
blue "==> Verifying row counts..."

psql --tuples-only --command "
SELECT
    'person'                AS table_name, COUNT(*) AS rows FROM person
UNION ALL SELECT 'skills',                    COUNT(*) FROM skills
UNION ALL SELECT 'certifications',            COUNT(*) FROM certifications
UNION ALL SELECT 'qualifications',            COUNT(*) FROM qualifications
UNION ALL SELECT 'project',                   COUNT(*) FROM project
UNION ALL SELECT 'leadership',                COUNT(*) FROM leadership
UNION ALL SELECT 'team',                      COUNT(*) FROM team
UNION ALL SELECT 'opportunity',               COUNT(*) FROM opportunity
UNION ALL SELECT 'opportunity_skill',         COUNT(*) FROM opportunity_skill
UNION ALL SELECT 'opportunity_qualification', COUNT(*) FROM opportunity_qualification
UNION ALL SELECT 'assignment',                COUNT(*) FROM assignment
UNION ALL SELECT 'staffing_history',          COUNT(*) FROM staffing_history
UNION ALL SELECT 'prov_log',                  COUNT(*) FROM prov_log
ORDER BY table_name;
"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
green ""
green "============================================================"
green " Database initialisation complete!"
green "  Host     : ${PGHOST}:${PGPORT}"
green "  Database : ${PGDATABASE}"
green "  User     : ${PGUSER}"
green "============================================================"
