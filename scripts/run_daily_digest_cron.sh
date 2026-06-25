#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${SKILL_DIR}/var/logs/cron"
RUNTIME_CONFIG="${SKILL_DIR}/local/runtime/production.yaml"

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"

mkdir -p "${LOG_DIR}"
exec >> "${LOG_DIR}/daily-digest.log" 2>&1

echo "[cron] $(date -Is) starting daily digest"
cd "${SKILL_DIR}"

if [[ ! -f "${RUNTIME_CONFIG}" ]]; then
  echo "[cron] runtime config not found: ${RUNTIME_CONFIG}"
  exit 1
fi

exec "${SKILL_DIR}/.venv/bin/python3" "${SKILL_DIR}/scripts/run_production_digest.py" \
  --runtime-config "${RUNTIME_CONFIG}"
