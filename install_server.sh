#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "${ROOT_DIR}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "错误：未找到 ${PYTHON_BIN}，请先安装 Python 3。" >&2
  exit 1
fi

"${PYTHON_BIN}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "错误：需要 Python 3.10 或更高版本。" >&2
  exit 1
}

if [ ! -d ".venv" ]; then
  "${PYTHON_BIN}" -m venv ".venv"
fi

".venv/bin/python3" -m pip install --upgrade pip
".venv/bin/python3" -m pip install -r "requirements.txt"

mkdir -p "local/runtime" "local/integrations"
mkdir -p "var/work/current" "var/archives/daily-digests"
mkdir -p "var/reviews/daily-reviews" "var/reviews/backlog"
mkdir -p "var/logs" "var/db" "var/api/runs"

copy_if_missing() {
  local source_path="$1"
  local target_path="$2"
  if [ ! -e "${target_path}" ]; then
    cp "${source_path}" "${target_path}"
    echo "已创建 ${target_path}"
  fi
}

copy_if_missing "config/env.local.example" "local/.env.local"
copy_if_missing "config/runtime/production.example.yaml" "local/runtime/production.yaml"
copy_if_missing "config/integrations/email_config.example.yaml" "local/integrations/email_config.yaml"
copy_if_missing "config/integrations/users.example.yaml" "local/integrations/users.yaml"
copy_if_missing "config/integrations/email_style.example.yaml" "local/integrations/email_style.yaml"
copy_if_missing "config/integrations/ai_chat.example.yaml" "local/integrations/nvidia_ai.yaml"
copy_if_missing "config/integrations/translation_tencent_tmt.example.yaml" "local/integrations/translation_tencent_tmt.yaml"
copy_if_missing "config/integrations/llm_review_config.example.yaml" "local/integrations/llm_review_config.yaml"

chmod 600 "local/.env.local"
chmod 700 "local" "local/runtime" "local/integrations" "var/api" "var/api/runs"
find "local" -type f -exec chmod 600 {} +
".venv/bin/python3" "scripts/audit_secrets.py"
".venv/bin/python3" -m unittest discover -s "tests" -p "test_*.py"

echo
echo "初始化完成。"
echo "1. 编辑 local/.env.local 和 local/integrations/*.yaml。"
echo "2. 干跑：.venv/bin/python3 scripts/run_production_digest.py --input-file tests/fixtures/sample_raw.jsonl --skip-email --summary-provider placeholder --review-provider placeholder --window-start 2026-03-13T00:00:00Z --window-end 2026-03-15T00:00:00Z"
echo "3. 生产运行：.venv/bin/python3 scripts/run_production_digest.py"
echo "4. 远程 API：配置 BIO_DIGEST_API_KEY 后运行 .venv/bin/python3 scripts/serve_api.py"
