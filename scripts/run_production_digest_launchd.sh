#!/bin/zsh
set -euo pipefail

# 这个脚本是给 macOS launchd 用的稳定入口。
# 目标是把 launchd 的精简运行环境固定下来，避免因为 PATH、工作目录或日志目录不同导致定时任务不稳定。

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${SKILL_DIR}/logs/launchd"
WORK_DIR="/private/tmp/bio-digest-prod"
ARCHIVE_DIR="${SKILL_DIR}/archives/daily-digests"

# launchd 在后台执行时环境变量非常少，这里显式设置基础 PATH 和编码环境。
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"

# 提前创建日志和归档目录，避免 launchd 因路径不存在而失败。
mkdir -p "${LOG_DIR}"
mkdir -p "${ARCHIVE_DIR}"

cd "${SKILL_DIR}"

# 生产运行命令：
# - 使用本地 .venv 里的 Python
# - 使用稳定的 production entrypoint
# - 使用本地邮件、样式、翻译配置
# - 采用 Asia/Shanghai 的日报窗口和 08:00 交付时刻
# - 允许 review 项排在附件和邮件末尾
exec "${SKILL_DIR}/.venv/bin/python3" "${SKILL_DIR}/scripts/run_production_digest.py" \
  --env-file "${SKILL_DIR}/.env.local" \
  --work-dir "${WORK_DIR}" \
  --archive-dir "${ARCHIVE_DIR}" \
  --email-config "${SKILL_DIR}/references/email_config.local.yaml" \
  --smtp-profile "qq_mail" \
  --style-config "${SKILL_DIR}/references/email_style.local.yaml" \
  --window-mode "schedule" \
  --timezone "Asia/Shanghai" \
  --delivery-time "08:00" \
  --review-provider "placeholder" \
  --summary-provider "google-basic-v2" \
  --summary-config "${SKILL_DIR}/references/translation_google_basic_v2.local.yaml" \
  --allow-review-pending
