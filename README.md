# bio-literature-digest

面向生物学文献日报的两层流水线：

1. Producer
   抓取、过滤、分类、翻译、导出、发邮件、归档
2. Review + Codex optimizer
   人工在 backlog 审核，Codex 读取 backlog 做保守规则优化
3. [web界面](https://github.com/mumu-140/bio-literature-digest-web/edit/main),需要的话可以部署
## 目录

- `config/content/`
  内容规则。期刊源、分类规则、术语表
- `config/integrations/`
  邮件、样式、翻译、外部 LLM 配置
- `config/runtime/`
  运行时路径、时区、发送时间、默认 provider
- `assets/`
  邮件模板
- `scripts/`
  主脚本和维护脚本
- `docs/`
  使用说明和产物契约
- `ops/`
  调度和部署说明
- `archives/`
  已归档日报
- `reviews/`
  单日审核快照和 active backlog

## 主入口

生产运行：

```bash
.venv/bin/python3 scripts/run_production_digest.py
```

人工审核：

- `reviews/backlog/review_backlog.xlsx`

第二层优化顺序：

```bash
.venv/bin/python3 scripts/refresh_review_backlog.py
.venv/bin/python3 scripts/mark_review_backlog_optimized.py --selection-json reviews/backlog/optimization_selection.json
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

- 密钥只放 `.env.local`
- 路径和默认 provider 放 `config/runtime/production.local.yaml`
- 内容规则只放 `config/content/`
- 外部服务配置只放 `config/integrations/`
- `review_backlog.xlsx` 是人工审核唯一权威文件
- web sync 是 sidecar，不应阻塞 Producer 主链

更多说明见：

- `docs/user_quickstart.md`
- `docs/daily_artifact_contract.md`
- `docs/engineering_harness.md`
- `SKILL.md`
---

## Acknowledgments
Special thanks to the **[Linux.do](https://linux.do/)** community for your support and feedback.
