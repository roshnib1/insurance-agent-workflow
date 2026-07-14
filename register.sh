#!/bin/bash
# Register the Commercial Property Underwriting producer with the Assurance
# gateway (all ADK framework event types for AssuranceADKPlugin).
# Loads ASSURANCE_* from .env when present. Requires the gateway to be running.
#
# Usage: ./register.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

GATEWAY_URL="${ASSURANCE_GATEWAY_URL:-http://127.0.0.1:8000}"
ADMIN_TOKEN="${GATEWAY_ADMIN_TOKEN:-local-dev-admin-token}"
PRODUCER_ID="${ASSURANCE_PRODUCER_ID:-commercial-property-underwriting}"
TENANT_ID="${ASSURANCE_TENANT_ID:-default-tenant}"
API_KEY="${ASSURANCE_API_KEY:-test-commercial-property-underwriting-key}"

echo "Commercial Property Underwriting — registering producer '${PRODUCER_ID}' (tenant=${TENANT_ID}) at ${GATEWAY_URL} ..."

RESPONSE="$(curl -sS -w "\n%{http_code}" -X POST "${GATEWAY_URL%/}/v1/producers/register" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: ${ADMIN_TOKEN}" \
  -d "{
    \"producer_id\": \"${PRODUCER_ID}\",
    \"tenant_id\": \"${TENANT_ID}\",
    \"api_key\": \"${API_KEY}\",
    \"producer_type\": \"SDK\",
    \"allowed_event_types\": [
      \"WORKFLOW_RUN_STARTED\",
      \"WORKFLOW_RUN_COMPLETED\",
      \"WORKFLOW_RUN_FAILED\",
      \"AGENT_RUN_STARTED\",
      \"AGENT_RUN_COMPLETED\",
      \"AGENT_RUN_FAILED\",
      \"MODEL_INVOCATION_STARTED\",
      \"MODEL_INVOCATION_COMPLETED\",
      \"MODEL_INVOCATION_FAILED\",
      \"TOOL_CALL_STARTED\",
      \"TOOL_CALL_COMPLETED\",
      \"TOOL_CALL_FAILED\"
    ]
  }")"

HTTP_BODY="$(echo "$RESPONSE" | sed '$d')"
HTTP_CODE="$(echo "$RESPONSE" | tail -n1)"

echo "$HTTP_BODY"
echo "HTTP ${HTTP_CODE}"

if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "201" ]]; then
  echo "Producer registration completed."
  exit 0
fi

# Re-registering an existing API key fails with a UNIQUE constraint — treat as already registered.
if echo "$HTTP_BODY" | grep -qiE 'UNIQUE constraint|already|duplicate'; then
  echo "Producer (or API key) already registered — nothing to do."
  echo "To change allowed_event_types, update the gateway DB or use a new ASSURANCE_API_KEY."
  exit 0
fi

echo "Producer registration failed." >&2
exit 1
