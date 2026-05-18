# Bio Literature Digest 使用说明

## 1. 项目结构

这个项目按信息类型分层：

- `config/content/`
  文献范围、分类规则、术语表、术语来源
- `config/integrations/`
  邮件、样式、翻译、外部 LLM 配置的公开示例
- `config/runtime/`
  公开 runtime baseline
- `scripts/`
  生产入口、主流水线、审核 backlog 维护脚本
- `src/bio_literature_digest/`
  可复用 Python 模块
- `docs/`
  使用说明、产物契约
- `ops/`
  `launchd` 等运维部署文件
- `local/`
  本机私有配置，不提交
- `var/`
  工作目录、归档、review、日志、SQLite 等运行产物，不提交

## 2. 先配置什么

### 公开模板与本机副本

仓库里提交的是“可公开模板”，真实值只应该存在于 `local/`：

- 公开模板：
  - `config/env.local.example`
  - `config/runtime/production.example.yaml`
  - `config/integrations/*.example.yaml`
- 本机私有副本：
  - `local/.env.local`
  - `local/runtime/production.yaml`
  - `local/integrations/*.yaml`

如果你准备把仓库推到 GitHub，先确认自己编辑的是 `local/` 下的副本，而不是 `.example.yaml` 模板。

### 环境变量

优先使用：

```bash
mkdir -p local
cp config/env.local.example local/.env.local
```

只把真实密钥放进 `local/.env.local`，不要写进 Python、YAML、模板或自动化：

```env
GOOGLE_TRANSLATE_API_KEY=
TENCENT_TMT_SECRET_ID=
TENCENT_TMT_SECRET_KEY=
TENCENT_TMT_SESSION_TOKEN=
SMTP_APP_PASSWORD=
SMTP_BACKUP_APP_PASSWORD=
LLM_REVIEW_API_KEY=
```

### 运行时配置

主运行配置分两层：

- 公开 baseline：`config/runtime/production.example.yaml`
- 本机 override：`local/runtime/production.yaml`

这里统一定义：

- `environment.env_file`
- `paths.work_dir`
- `paths.archive_dir`
- `paths.review_workspace_dir`
- `paths.backlog_dir`
- `paths.watchlist`
- `paths.rules`
- `paths.email_config`
- `paths.users_config`
- `paths.style_config`
- `paths.template`
- `paths.summary_config`
- `delivery.smtp_profile`
- `delivery.timezone`
- `delivery.delivery_time`
- `delivery.window_policy`
- `providers.review_provider`
- `providers.summary_provider`
- `web.sync_enabled`
- `web.project_root`
- `database.enabled`
- `database.sqlite_path`

生产脚本默认从这里取路径和默认参数，不再要求把这些值写死在脚本里。

推荐把 `delivery.window_policy` 保持为：

- `previous_day`

这表示日报默认只覆盖 `delivery.timezone` 下“前一自然日 00:00-24:00”。
如果你确实要保留旧行为“前一日 00:00 到发送时刻”，才改成 `previous_day_to_delivery`。

### 内容配置

常改这几个：

- `config/content/journal_watchlist.yaml`
- `config/content/category_rules.yaml`
- `config/content/bio_translation_glossary.yaml`

### 集成配置

常改这几个：

- `local/integrations/email_config.yaml`
- `local/integrations/users.yaml`
- `local/integrations/email_style.yaml`
- `local/integrations/translation_google_basic_v2.yaml`
- `local/integrations/translation_tencent_tmt.yaml`

首次初始化可从示例复制：

```bash
mkdir -p local/integrations
cp config/integrations/email_config.example.yaml local/integrations/email_config.yaml
cp config/integrations/users.example.yaml local/integrations/users.yaml
cp config/integrations/email_style.example.yaml local/integrations/email_style.yaml
cp config/integrations/translation_google_basic_v2.example.yaml local/integrations/translation_google_basic_v2.yaml
cp config/integrations/translation_tencent_tmt.example.yaml local/integrations/translation_tencent_tmt.yaml
```

注意：这些文件只放“配置形状”和“环境变量名”，不要放真实密钥。

## 3. 安装

```bash
cd /path/to/bio-literature-digest
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

检查密钥是否只存在于本地 env 文件：

```bash
.venv/bin/python3 scripts/audit_secrets.py
```

修改脚本、配置或目录结构后，统一检查：

```bash
.venv/bin/python3 scripts/check_project.py
```

## 4. 主流程怎么跑

### 推荐生产入口

```bash
.venv/bin/python3 scripts/run_production_digest.py
```

这个入口会：

- 以 `config/runtime/production.example.yaml` 为 baseline
- 叠加 `local/runtime/production.yaml`
- 加载 `local/.env.local`
- 调起 `scripts/run_digest.py`
- 生成日报附件
- 发邮件
- 归档到 `var/archives/daily-digests/YYYY-MM-DD/`
- 同步每日审核快照到 `var/reviews/daily-reviews/YYYY-MM-DD/`
- 刷新 active backlog 到 `var/reviews/backlog/`
- 如果 `database.enabled=true`，把 `digest/review_queue/daily_review` 同步入 SQLite

### 本地样例测试

```bash
.venv/bin/python3 scripts/run_production_digest.py \
  --input-file tests/fixtures/sample_raw.jsonl \
  --skip-email \
  --summary-provider placeholder \
  --window-start 2026-03-13T00:00:00Z \
  --window-end 2026-03-15T00:00:00Z
```

### 样式预览邮件

```bash
.venv/bin/python3 scripts/send_style_preview.py \
  --localized-input /path/to/work-dir/localized_records.jsonl \
  --style-config local/integrations/email_style.yaml \
  --email-config local/integrations/email_config.yaml \
  --users-config local/integrations/users.yaml \
  --smtp-profile primary_smtp
```

## 5. 审核与优化

### 人工审核入口

唯一权威人工审核文件：

- `var/reviews/backlog/review_backlog.xlsx`

单日快照只作回溯和审计：

- `var/reviews/daily-reviews/YYYY-MM-DD/daily_review.xlsx`

### Codex 优化顺序

1. 先运行：

```bash
.venv/bin/python3 scripts/refresh_review_backlog.py
```

2. 只看 `review_status=reviewed_pending_optimization` 的 backlog 行
3. 按 `admission_tier` 做分层准入
4. 保守更新：
   - `config/content/category_rules.yaml`
   - `config/content/bio_translation_glossary.yaml`
5. 把真正消费的行写到：
   - `var/reviews/backlog/optimization_selection.json`
6. 再运行：

```bash
.venv/bin/python3 scripts/mark_review_backlog_optimized.py \
  --selection-json var/reviews/backlog/optimization_selection.json
.venv/bin/python3 scripts/finalize_review_backlog.py
```

`finalize_review_backlog.py` 会把已消费样本归档出 active backlog，并归档本次 selection 文件。

## 6. 产物在哪里

### 临时工作目录

默认是 runtime YAML 里的 `paths.work_dir`，公开 baseline 默认值是：

- `var/work/current`

常看这些文件：

- `digest.html`
- `digest.csv`
- `digest.xlsx`
- `review_queue.csv`
- `daily_review.csv`
- `daily_review.xlsx`
- `run_metadata.json`
- `rule_feedback_report.md`
- `classification_suggestions.md`
- `classification_suggestions.json`
- `glossary_candidates.md`

### 长期产物

- `var/archives/daily-digests/YYYY-MM-DD/`
- `var/reviews/daily-reviews/YYYY-MM-DD/`
- `var/reviews/backlog/`
- `var/db/bio_digest.sqlite3`（当启用 database 同步时）

产物契约见：

- `docs/daily_artifact_contract.md`

校验某次产物：

```bash
.venv/bin/python3 scripts/validate_daily_artifacts.py --run-dir /path/to/work-dir
```

## 7. 运维入口

`launchd` 相关文件在：

- `ops/launchd/bio-digest-daily.plist.template`
- `ops/launchd/bio-digest-daily.plist`
- `ops/launchd/README.md`

包装脚本是：

- `scripts/run_production_digest_launchd.sh`

生成脚本是：

- `scripts/generate_launchd_plist.py`

`plist` 现在由模板和 runtime YAML 生成，不建议手改生成后的 `ops/launchd/bio-digest-daily.plist`。

## 8. 最短使用步骤

1. 建 `.venv`
2. 填 `local/.env.local`
3. 复制 `config/runtime/production.example.yaml` 到 `local/runtime/production.yaml` 后按需修改
4. 改 `local/integrations/users.yaml`
5. 改 `local/integrations/email_config.yaml`（只放 SMTP 参数）
6. 改 `config/content/journal_watchlist.yaml`
7. 运行 `scripts/audit_secrets.py`
8. 运行 `scripts/run_production_digest.py`

如果只记一条命令，记这个：

```bash
.venv/bin/python3 scripts/run_production_digest.py
```

## 9. Stage 1 一次性迁移

如果你还有旧布局文件，先执行：

```bash
.venv/bin/python3 scripts/migrate_runtime_layout.py --dry-run
.venv/bin/python3 scripts/migrate_runtime_layout.py
```

迁移后只保留以下布局：

- runtime override: `local/runtime/production.yaml`
- 本机集成配置: `local/integrations/*.yaml`
- 本机密钥: `local/.env.local`
- 运行产物: `var/*`
