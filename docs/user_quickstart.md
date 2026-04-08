# Bio Literature Digest 使用说明

## 1. 项目结构

这个项目按信息类型分层：

- `config/content/`
  文献范围、分类规则、术语表、术语来源
- `config/integrations/`
  邮件、样式、翻译、外部 LLM 复核配置
- `config/runtime/`
  运行时路径、时区、发送时间、默认 provider、sidecar 开关
- `assets/`
  邮件模板等静态资源
- `scripts/`
  生产入口、主流水线、审核 backlog 维护脚本
- `docs/`
  使用说明、产物契约
- `ops/`
  `launchd` 等运维部署文件
- `archives/`
  每日归档产物
- `reviews/`
  每日审核快照和 active backlog

## 2. 先配置什么

### 环境变量

复制并填写：

```bash
cp .env.local.example .env.local
```

只把真实密钥放进 `.env.local`，不要写进 Python、YAML、模板或自动化：

```env
GOOGLE_TRANSLATE_API_KEY=
TENCENT_TMT_SECRET_ID=
TENCENT_TMT_SECRET_KEY=
QQ_MAIL_APP_PASSWORD=
```

### 运行时配置

主运行配置是：

- `config/runtime/production.local.yaml`

这里统一定义：

- `env_file`
- `work_dir`
- `archive_dir`
- `review_workspace_dir`
- `backlog_dir`
- `watchlist`
- `rules`
- `email_config`
- `style_config`
- `template`
- `summary_config`
- `smtp_profile`
- `timezone`
- `delivery_time`
- `review_provider`
- `summary_provider`
- `web.sync_enabled`

生产脚本默认从这里取路径和默认参数，不再要求把这些值写死在脚本里。

### 内容配置

常改这几个：

- `config/content/journal_watchlist.yaml`
- `config/content/category_rules.yaml`
- `config/content/bio_translation_glossary.yaml`

### 集成配置

常改这几个：

- `config/integrations/email_config.local.yaml`
- `config/integrations/email_style.local.yaml`
- `config/integrations/translation_google_basic_v2.local.yaml`
- `config/integrations/translation_tencent_tmt.local.yaml`

注意：这些文件只放“配置形状”和“环境变量名”，不要放真实密钥。

## 3. 安装

```bash
cd /path/to/bio-literature-digest
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

检查密钥是否只存在于 `.env.local`：

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

- 读取 `config/runtime/production.local.yaml`
- 加载 `.env.local`
- 调起 `scripts/run_digest.py`
- 生成日报附件
- 发邮件
- 归档到 `archives/daily-digests/YYYY-MM-DD/`
- 同步每日审核快照到 `reviews/daily-reviews/YYYY-MM-DD/`
- 刷新 active backlog 到 `reviews/backlog/`

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
  --style-config config/integrations/email_style.local.yaml \
  --email-config config/integrations/email_config.local.yaml \
  --smtp-profile primary_smtp
```

## 5. 审核与优化

### 人工审核入口

唯一权威人工审核文件：

- `reviews/backlog/review_backlog.xlsx`

单日快照只作回溯和审计：

- `reviews/daily-reviews/YYYY-MM-DD/daily_review.xlsx`

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
   - `reviews/backlog/optimization_selection.json`
6. 再运行：

```bash
.venv/bin/python3 scripts/mark_review_backlog_optimized.py \
  --selection-json reviews/backlog/optimization_selection.json
.venv/bin/python3 scripts/finalize_review_backlog.py
```

`finalize_review_backlog.py` 会把已消费样本归档出 active backlog，并归档本次 selection 文件。

## 6. 产物在哪里

### 临时工作目录

默认是 `config/runtime/production.local.yaml` 里的 `paths.work_dir`。当前默认值通常是：

- `/private/tmp/bio-literature-digest`

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

- `archives/daily-digests/YYYY-MM-DD/`
- `reviews/daily-reviews/YYYY-MM-DD/`
- `reviews/backlog/`

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

`plist` 现在由模板和运行配置生成，不建议手改生成后的 `ops/launchd/bio-digest-daily.plist`。

## 8. 最短使用步骤

1. 建 `.venv`
2. 填 `.env.local`
3. 改 `config/runtime/production.local.yaml`
4. 改 `config/integrations/email_config.local.yaml`
5. 改 `config/content/journal_watchlist.yaml`
6. 运行 `scripts/audit_secrets.py`
7. 运行 `scripts/run_production_digest.py`

如果只记一条命令，记这个：

```bash
.venv/bin/python3 scripts/run_production_digest.py
```
