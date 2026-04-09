#!/bin/zsh
set -euo pipefail

# 这个脚本是给 macOS launchd 用的稳定入口。
# 目标是把 launchd 的精简运行环境固定下来，避免因为 PATH、工作目录或日志目录不同导致定时任务不稳定。

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${SKILL_DIR}/var/logs/launchd"
RUNTIME_CONFIG="${SKILL_DIR}/local/runtime/production.yaml"

# launchd 在后台执行时环境变量非常少，这里显式设置基础 PATH 和编码环境。
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"

# 提前创建日志和归档目录，避免 launchd 因路径不存在而失败。
mkdir -p "${LOG_DIR}"
if [[ ! -f "${RUNTIME_CONFIG}" ]]; then
  echo "Runtime config not found: ${RUNTIME_CONFIG}" >&2
  exit 1
fi

cd "${SKILL_DIR}"

# 生产运行命令：
# - 使用本地 .venv 里的 Python
# - 使用稳定的 production entrypoint
# - 所有工作目录、归档目录、集成配置都从 runtime config 读取
# - 采用 runtime config 里的生产参数
# - 允许 review 项排在附件和邮件末尾
exec "${SKILL_DIR}/.venv/bin/python3" "${SKILL_DIR}/scripts/run_production_digest.py" \
  --runtime-config "${RUNTIME_CONFIG}"
