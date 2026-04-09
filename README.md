# bio-literature-digest

面向生物学文献日报的两层流水线：

1. Producer
   抓取、过滤、分类、翻译、导出、发邮件、归档
2. Review + Codex optimizer
   人工在 backlog 审核，Codex 读取 backlog 做保守规则优化
3. web sidecar
   独立项目，可选接入，不应阻塞 Producer 主链

## 目录

- `config/content/`
  内容规则。期刊源、分类规则、术语表
- `config/integrations/`
  邮件、样式、翻译、外部 LLM 配置的公开示例
- `config/runtime/`
  可移植 runtime baseline
- `scripts/`
  稳定 CLI 入口脚本
- `src/bio_literature_digest/`
  可复用实现模块
- `docs/`
  使用说明和产物契约
- `ops/`
  调度和部署说明
- `local/`
  本机私有配置，默认不提交
- `var/`
  工作目录、归档、review、日志、SQLite 等运行产物，默认不提交

## 主入口

生产运行：

```bash
.venv/bin/python3 scripts/run_production_digest.py
```

数据库同步（SQLite）：

- 配置位置：`local/runtime/production.yaml`
- 同步脚本：`scripts/sync_digest_db.py`
- 默认入库文件：`digest.csv`、`review_queue.csv`、`daily_review.csv`
- 默认库路径：`var/db/bio_digest.sqlite3`

人工审核：

- `var/reviews/backlog/review_backlog.xlsx`

第二层优化顺序：

```bash
.venv/bin/python3 scripts/refresh_review_backlog.py
.venv/bin/python3 scripts/mark_review_backlog_optimized.py --selection-json var/reviews/backlog/optimization_selection.json
.venv/bin/python3 scripts/finalize_review_backlog.py
```

统一检查入口：

```bash
.venv/bin/python3 scripts/check_project.py
```

分层检查入口：

- `.venv/bin/python3 scripts/check_harness.py`
- `.venv/bin/python3 scripts/check_alignment.py`

## 关键原则

- 密钥只放 `local/.env.local`
- runtime YAML 以 `config/runtime/production.example.yaml` 为公开 baseline
- 机器本地 override 优先放 `local/runtime/production.yaml`
- 内容规则只放 `config/content/`
- 外部服务配置只放 `config/integrations/` 的示例和 `local/integrations/` 的本机覆盖
- `review_backlog.xlsx` 是人工审核唯一权威文件
- web sync 是 sidecar，不应阻塞 Producer 主链

## 可公开配置模板

以下文件可以直接提交到 GitHub，且应该只保留占位值与中文说明：

- `config/env.local.example`
- `config/runtime/production.example.yaml`
- `config/integrations/*.example.yaml`
- `agents/openai.yaml`

以下文件不要提交真实内容：

- `local/.env.local`
- `local/runtime/production.yaml`
- `local/integrations/*.yaml`

建议初始化方式：

```bash
cp config/env.local.example local/.env.local
cp config/runtime/production.example.yaml local/runtime/production.yaml
cp config/integrations/email_config.example.yaml local/integrations/email_config.yaml
cp config/integrations/users.example.yaml local/integrations/users.yaml
```

## Stage 1 迁移

从旧布局切到严格 `local/` + `var/`：

```bash
.venv/bin/python3 scripts/migrate_runtime_layout.py --dry-run
.venv/bin/python3 scripts/migrate_runtime_layout.py
```

迁移会移动 `archives/`、`reviews/`、`logs/`、`.env.local`、`config/**/*.local.yaml` 和旧 SQLite 到 Stage 1 目录，并写出回滚清单到 `var/migrations/manifests/`。

更多说明见：

- `docs/user_quickstart.md`
- `docs/open_source_config_policy.md`
- `docs/daily_artifact_contract.md`
- `docs/engineering_harness.md`
- `SKILL.md`

## Acknowledgments
Special thanks to the **[Linux.do](https://linux.do/)** community for your support and feedback.
