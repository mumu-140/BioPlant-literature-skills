# bio-literature-digest

面向生物学文献日报的两层流水线：

1. Producer
   抓取、过滤、分类、翻译、导出、发邮件、归档。
2. Review + Codex optimizer
   人工在 backlog 审核，Codex 读取 backlog 做保守规则优化。
3. web sidecar
   独立项目，可选接入，不应阻塞 Producer 主链。

这个仓库已经按“源码 / 本机私有配置 / 运行产物”分开：

- `config/`：公开模板与共享规则
- `local/`：本机真实配置与密钥，不提交
- `var/`：运行产物、归档、日志、SQLite，不提交

## 安装

### 手动安装

适合你自己在本机直接运行日报流水线。

```bash
git clone <repo-url> bio-literature-digest
cd bio-literature-digest
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

依赖目前很轻，只要求 Python 3 和 `PyYAML`。

### AI 安装

适合把它作为 Codex / Claude Code / 其他支持本地 skill 或仓库上下文的 AI 项目来使用。

推荐方式是把整个仓库放进你的 AI skills 工作区，而不是只拷贝某几个脚本：

```bash
cd /path/to/your/skills
git clone <repo-url> bio-literature-digest
```

然后让 AI 工具直接读取这些文件：

- `SKILL.md`
- `README.md`
- `docs/user_quickstart.md`
- `config/`
- `scripts/`

AI 安装不替代本机配置。即使由 AI 代你执行，真实运行时仍然要配置 `local/` 下的私有文件。

## 配置

### 配置放在哪里

- `config/content/`
  项目共享规则。期刊源、分类规则、术语表、术语来源。
- `config/runtime/production.example.yaml`
  公开 runtime baseline。给出默认目录结构和字段形状。
- `config/integrations/*.example.yaml`
  邮件、样式、翻译、外部 review 配置模板。
- `config/env.local.example`
  公开 env 模板，只保留变量名和中文说明。
- `local/.env.local`
  本机密钥，只放真实 secret。
- `local/runtime/production.yaml`
  本机 runtime override，控制本机路径、时区、SMTP profile、日报时间窗口策略、sidecar、数据库等。
- `local/integrations/*.yaml`
  本机真实集成配置，比如邮件、用户、翻译、样式。
- `var/`
  运行产物。不要手工把真实配置塞到这里。

一句话规则：

- `config/` 里放“可公开模板和共享规则”
- `local/` 里放“你自己机器上的真实配置”
- `var/` 里放“程序跑出来的东西”

### 首次初始化

先创建本机目录，再从 `config/` 复制模板到 `local/`：

```bash
mkdir -p local/runtime local/integrations
cp config/env.local.example local/.env.local
cp config/runtime/production.example.yaml local/runtime/production.yaml
cp config/integrations/email_config.example.yaml local/integrations/email_config.yaml
cp config/integrations/users.example.yaml local/integrations/users.yaml
cp config/integrations/email_style.example.yaml local/integrations/email_style.yaml
cp config/integrations/translation_google_basic_v2.example.yaml local/integrations/translation_google_basic_v2.yaml
cp config/integrations/translation_tencent_tmt.example.yaml local/integrations/translation_tencent_tmt.yaml
cp config/integrations/llm_review_config.example.yaml local/integrations/llm_review_config.yaml
```

如果你暂时只想本地占位跑通，也可以先只复制最小集合：

```bash
mkdir -p local/runtime local/integrations
cp config/env.local.example local/.env.local
cp config/runtime/production.example.yaml local/runtime/production.yaml
cp config/integrations/email_config.example.yaml local/integrations/email_config.yaml
cp config/integrations/users.example.yaml local/integrations/users.yaml
cp config/integrations/email_style.example.yaml local/integrations/email_style.yaml
```

### 关键配置文件怎么改

- `local/.env.local`
  只放真实密钥，例如 SMTP 授权码、翻译 API key、LLM review API key。
- `local/runtime/production.yaml`
  这是运行时主配置入口。默认路径、工作目录、归档目录、review 目录、SQLite 路径、delivery 配置都应该从这里管。
  常用项包括 `delivery.timezone`、`delivery.delivery_time`、`delivery.window_policy`。
- `local/integrations/users.yaml`
  收件人主名单。通常新增用户只改这个文件。
- `local/integrations/email_config.yaml`
  SMTP profile、发件账号、端口、认证方式。只有新增 SMTP 通道或换发件配置时才需要改。
- `config/content/journal_watchlist.yaml`
  期刊源与抓取范围。
- `config/content/category_rules.yaml`
  分类规则与过滤逻辑。
- `config/content/bio_translation_glossary.yaml`
  生物术语表。

如果你只是新增一个收件人，正常只需要改：

- `local/integrations/users.yaml`

只有当这个用户要走一个新的 `smtp_profile` 时，才需要再改：

- `local/integrations/email_config.yaml`

### 配置原则

- 不要把真实密钥写进 `config/`、`scripts/`、测试、自动化文件。
- 不要把真实邮箱、真实本机路径、真实内网地址写进 `.example.yaml`。
- 不要依赖环境变量承载普通运行时路径，普通路径归 `local/runtime/production.yaml`。
- `local/` 和 `var/` 默认不应提交到 GitHub。

## 使用

### 先检查配置是否安全

```bash
.venv/bin/python3 scripts/audit_secrets.py
```

### 先检查项目结构是否对齐

```bash
.venv/bin/python3 scripts/check_project.py
```

如果只想定位结构层问题，也可以单独跑：

- `.venv/bin/python3 scripts/check_harness.py`
- `.venv/bin/python3 scripts/check_alignment.py`

### 推荐生产入口

```bash
.venv/bin/python3 scripts/run_production_digest.py
```

这个入口会：

- 以 `config/runtime/production.example.yaml` 为 baseline
- 叠加 `local/runtime/production.yaml`
- 加载 `local/.env.local`
- 调起 Producer 主流程
- 生成附件和 HTML
- 发邮件
- 归档到 `var/archives/daily-digests/YYYY-MM-DD/`
- 同步每日审核快照到 `var/reviews/daily-reviews/YYYY-MM-DD/`
- 刷新 active backlog 到 `var/reviews/backlog/`
- 按 runtime YAML 决定是否同步 SQLite

默认计划窗口现在是：

- `previous_day`
- 即按 `delivery.timezone` 计算“前一自然日 00:00-24:00”

如果你确实要保留旧行为“前一日 00:00 到发送时刻”，再把 `local/runtime/production.yaml` 里的 `delivery.window_policy` 改成 `previous_day_to_delivery`。

### 本地干跑或样例运行

不想真的发邮件时，建议这样跑：

```bash
.venv/bin/python3 scripts/run_production_digest.py \
  --input-file tests/fixtures/sample_raw.jsonl \
  --skip-email \
  --summary-provider placeholder \
  --review-provider placeholder \
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

### 人工审核与第二层优化

人工审核的唯一权威文件：

- `var/reviews/backlog/review_backlog.xlsx`

第二层优化顺序：

```bash
.venv/bin/python3 scripts/refresh_review_backlog.py
.venv/bin/python3 scripts/mark_review_backlog_optimized.py --selection-json var/reviews/backlog/optimization_selection.json
.venv/bin/python3 scripts/finalize_review_backlog.py
```

## 目录说明

- `config/content/`
  内容规则。期刊源、分类规则、术语表。
- `config/integrations/`
  邮件、样式、翻译、外部 LLM 配置的公开示例。
- `config/runtime/`
  可移植 runtime baseline。
- `scripts/`
  稳定 CLI 入口脚本。
- `src/bio_literature_digest/`
  可复用实现模块。
- `docs/`
  使用说明和产物契约。
- `ops/`
  调度和部署说明。
- `local/`
  本机私有配置，默认不提交。
- `var/`
  工作目录、归档、review、日志、SQLite 等运行产物，默认不提交。

## 常用入口

生产运行：

```bash
.venv/bin/python3 scripts/run_production_digest.py
```

统一检查入口：

```bash
.venv/bin/python3 scripts/check_project.py
```

数据库同步（SQLite）：

- 配置位置：`local/runtime/production.yaml`
- 同步脚本：`scripts/sync_digest_db.py`
- 默认入库文件：`digest.csv`、`review_queue.csv`、`daily_review.csv`
- 默认库路径：`var/db/bio_digest.sqlite3`

## 更多说明

- `docs/user_quickstart.md`
- `docs/open_source_config_policy.md`
- `docs/daily_artifact_contract.md`
- `docs/engineering_harness.md`
- `SKILL.md`

## Acknowledgments

Special thanks to the **[Linux.do](https://linux.do/)** community for your support and feedback.
