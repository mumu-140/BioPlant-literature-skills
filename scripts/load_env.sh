#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${SKILL_DIR}/.env.local}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Env file not found: ${ENV_FILE}" >&2
  echo "Copy ${SKILL_DIR}/.env.local.example to ${SKILL_DIR}/.env.local and fill the values." >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

echo "Loaded environment variables from ${ENV_FILE}"
