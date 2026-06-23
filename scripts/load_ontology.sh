#!/usr/bin/env sh
# =============================================================================
# load_ontology.sh
# Uploads all Turtle ontology files into Apache Jena Fuseki named graphs.
#
# Environment variables (with defaults):
#   FUSEKI_URL              — base URL of Fuseki (default: http://localhost:3030)
#   FUSEKI_ADMIN_PASSWORD   — admin password    (default: admin-changeme)
#   DATASET                 — dataset name      (default: staffing)
# =============================================================================

set -eu

FUSEKI_URL="${FUSEKI_URL:-http://localhost:3030}"
FUSEKI_ADMIN_PASSWORD="${FUSEKI_ADMIN_PASSWORD:-admin-changeme}"
DATASET="${DATASET:-staffing}"
ONTOLOGY_DIR="${ONTOLOGY_DIR:-/ontology}"

FUSEKI_AUTH="admin:${FUSEKI_ADMIN_PASSWORD}"
MAX_RETRIES=30
RETRY_INTERVAL=5

# ANSI colour helpers (safe for non-tty via sh)
green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
blue()  { printf '\033[34m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }

# =============================================================================
# Step 1: Wait for Fuseki to be ready
# =============================================================================
blue "==> Waiting for Fuseki at ${FUSEKI_URL} ..."
attempt=0
until curl -sf -u "${FUSEKI_AUTH}" "${FUSEKI_URL}/\$/ping" > /dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$MAX_RETRIES" ]; then
        red "ERROR: Fuseki did not become ready after $((MAX_RETRIES * RETRY_INTERVAL)) seconds. Aborting."
        exit 1
    fi
    yellow "  Fuseki not ready yet (attempt ${attempt}/${MAX_RETRIES}). Retrying in ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done
green "  Fuseki is ready."

# =============================================================================
# Step 2: Create the 'staffing' dataset (idempotent — ignore 409 Conflict)
# =============================================================================
blue "==> Creating dataset '${DATASET}' ..."
HTTP_CODE=$(curl -s -o /tmp/fuseki_create_resp.txt -w "%{http_code}" \
    -X POST \
    -u "${FUSEKI_AUTH}" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data "dbName=${DATASET}&dbType=tdb2" \
    "${FUSEKI_URL}/\$/datasets")

RESP_BODY=$(cat /tmp/fuseki_create_resp.txt)

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    green "  Dataset '${DATASET}' created successfully (HTTP ${HTTP_CODE})."
elif [ "$HTTP_CODE" = "409" ]; then
    yellow "  Dataset '${DATASET}' already exists (HTTP 409). Continuing."
else
    red "  ERROR: Failed to create dataset '${DATASET}'. HTTP ${HTTP_CODE}"
    red "  Response: ${RESP_BODY}"
    exit 1
fi

# =============================================================================
# Helper function: upload a TTL file to a named graph
# =============================================================================
upload_graph() {
    local filepath="$1"
    local graph_uri="$2"
    local label="$3"

    if [ ! -f "$filepath" ]; then
        red "  ERROR: File not found: $filepath"
        exit 1
    fi

    blue "==> Uploading ${label} ..."
    blue "    File: ${filepath}"
    blue "    Graph: ${graph_uri}"

    HTTP_CODE=$(curl -s -o /tmp/fuseki_upload_resp.txt -w "%{http_code}" \
        -X PUT \
        -u "${FUSEKI_AUTH}" \
        -H "Content-Type: text/turtle; charset=utf-8" \
        --data-binary "@${filepath}" \
        "${FUSEKI_URL}/${DATASET}/data?graph=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$graph_uri" 2>/dev/null || printf '%s' "$graph_uri" | sed 's|:|\%3A|g; s|/|\%2F|g; s|#|\%23|g')")

    RESP_BODY=$(cat /tmp/fuseki_upload_resp.txt)

    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "204" ]; then
        green "  SUCCESS (HTTP ${HTTP_CODE}): ${label} uploaded."
    else
        red "  ERROR: Failed to upload ${label}. HTTP ${HTTP_CODE}"
        red "  Response: ${RESP_BODY}"
        exit 1
    fi
}

# URL-encode helper using curl's --write-out (pure sh fallback)
url_encode() {
    local raw="$1"
    printf '%s' "$raw" | \
        sed 's/%/%25/g; s/ /%20/g; s|:|\%3A|g; s|/|\%2F|g; s|#|\%23|g; s|?|\%3F|g; s|&|\%26|g'
}

# =============================================================================
# Step 3–6: Upload each TTL file to its designated named graph
# =============================================================================

# Build upload URL with graph parameter using raw concatenation for curl
upload_ttl() {
    local filepath="$1"
    local graph_uri="$2"
    local label="$3"

    if [ ! -f "$filepath" ]; then
        red "  ERROR: File not found: $filepath"
        exit 1
    fi

    blue "==> Uploading ${label} ..."
    blue "    File  : ${filepath}"
    blue "    Graph : ${graph_uri}"

    HTTP_CODE=$(curl -s -o /tmp/fuseki_resp.txt -w "%{http_code}" \
        -X PUT \
        -u "${FUSEKI_AUTH}" \
        -H "Content-Type: text/turtle; charset=utf-8" \
        --data-binary "@${filepath}" \
        "${FUSEKI_URL}/${DATASET}/data?graph=${graph_uri}")

    RESP_BODY=$(cat /tmp/fuseki_resp.txt)

    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "204" ]; then
        green "  SUCCESS (HTTP ${HTTP_CODE}): ${label} loaded into <${graph_uri}>."
    else
        red "  ERROR: Failed to upload ${label}. HTTP ${HTTP_CODE}"
        red "  Response body: ${RESP_BODY}"
        exit 1
    fi
}

# Step 3: TBox — master OWL ontology
upload_ttl \
    "${ONTOLOGY_DIR}/staffing-ontology.ttl" \
    "http://enterprise.org/graphs/tbox" \
    "TBox (staffing-ontology.ttl)"

# Step 4: SKOS taxonomy
upload_ttl \
    "${ONTOLOGY_DIR}/skos-taxonomy.ttl" \
    "http://enterprise.org/graphs/skos" \
    "SKOS Skill Taxonomy (skos-taxonomy.ttl)"

# Step 5: SHACL shapes
upload_ttl \
    "${ONTOLOGY_DIR}/shacl-shapes.ttl" \
    "http://enterprise.org/graphs/shacl" \
    "SHACL Shapes (shacl-shapes.ttl)"

# Step 6: ABox sample instance data
upload_ttl \
    "${ONTOLOGY_DIR}/abox-sample.ttl" \
    "http://enterprise.org/graphs/abox" \
    "ABox Sample Instances (abox-sample.ttl)"

# =============================================================================
# Step 7: Confirmation summary
# =============================================================================
green ""
green "============================================================"
green " Ontology load complete!"
green "  Dataset   : ${FUSEKI_URL}/${DATASET}"
green "  Graphs loaded:"
green "    TBox  : http://enterprise.org/graphs/tbox"
green "    SKOS  : http://enterprise.org/graphs/skos"
green "    SHACL : http://enterprise.org/graphs/shacl"
green "    ABox  : http://enterprise.org/graphs/abox"
green ""
green "  SPARQL UI  : ${FUSEKI_URL}/${DATASET}"
green "  Admin UI   : ${FUSEKI_URL}/\$/datasets"
green "============================================================"
