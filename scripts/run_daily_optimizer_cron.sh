#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${SKILL_DIR}/var/logs/cron"
LOCK_DIR="${SKILL_DIR}/var/locks"
RUNTIME_CONFIG="${SKILL_DIR}/local/runtime/production.yaml"

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"
exec >> "${LOG_DIR}/daily-optimizer.log" 2>&1

echo "[cron] $(date -Is) starting daily optimizer"
cd "${SKILL_DIR}"

if [[ ! -f "${RUNTIME_CONFIG}" ]]; then
  echo "[cron] runtime config not found: ${RUNTIME_CONFIG}"
  exit 1
fi

exec 9> "${LOCK_DIR}/daily-optimizer.lock"
if ! flock -n 9; then
  echo "[cron] another daily optimizer run is active; skipping"
  exit 0
fi

exec "${SKILL_DIR}/.venv/bin/python3" "${SKILL_DIR}/scripts/with_env.py" -- \
  "${SKILL_DIR}/.venv/bin/python3" "${SKILL_DIR}/scripts/optimize_daily_results.py" \
  --apply \
  --mark-finalize
