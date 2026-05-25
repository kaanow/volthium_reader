#!/usr/bin/env bash
# Watch reviewer automation status and logs.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AUTOMATION_SCRIPT="${REPO_DIR}/scripts/reviewer_automation.sh"
LOG_FILE="${REPO_DIR}/.reviewer_automation/automation.log"

if [ ! -x "${AUTOMATION_SCRIPT}" ]; then
  echo "ERROR: ${AUTOMATION_SCRIPT} not found or not executable" >&2
  exit 1
fi

echo "=== Reviewer Automation Status ==="
"${AUTOMATION_SCRIPT}" status
echo ""
echo "=== Live Log (Ctrl-C to stop watching) ==="

if [ ! -f "${LOG_FILE}" ]; then
  mkdir -p "$(dirname "${LOG_FILE}")"
  touch "${LOG_FILE}"
fi

tail -n 40 -f "${LOG_FILE}"
