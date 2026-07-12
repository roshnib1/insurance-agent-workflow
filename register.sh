#!/bin/bash

set -e

echo "Registering producer..."

curl -s -X POST http://127.0.0.1:8000/v1/producers/register \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: local-dev-admin-token" \
  -d '{
    "producer_id": "insurance-underwriting",
    "tenant_id": "default-tenant",
    "api_key": "test-insurance-underwriting-key",
    "producer_type": "SDK",
    "allowed_event_types": [
      "WORKFLOW_RUN_STARTED",
      "WORKFLOW_RUN_COMPLETED",
      "WORKFLOW_RUN_FAILED",
      "AGENT_RUN_STARTED",
      "AGENT_RUN_COMPLETED",
      "AGENT_RUN_FAILED",
      "MODEL_INVOCATION_STARTED",
      "MODEL_INVOCATION_COMPLETED",
      "MODEL_INVOCATION_FAILED",
      "TOOL_CALL_STARTED",
      "TOOL_CALL_COMPLETED",
      "TOOL_CALL_FAILED",
      "UNDERWRITING_GATE_EVALUATED",
      "UNDERWRITING_DECISION_FINALIZED",
      "HUMAN_APPROVAL"
    ]
  }'

echo
echo "Producer registration completed."