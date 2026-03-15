# 每天订阅新的文献，然后发到指定邮箱
# 最简单的办法，扔给Codex、Claude code、antigravity等软件，让软件帮忙安装、配置、提交！！！
# Bio Literature Digest 使用说明

## 1. 这个项目做什么

`bio-literature-digest` 是一个生物文献日报技能。它会：

- 抓取配置期刊和预印本文献
- 过滤非目标方向文献
- 分类
- 翻译标题并生成中文总结
- 导出 `HTML / CSV / XLSX`
- 发送邮件
- 自动保存最近 30 天日报附件

默认日报窗口是北京时间：

- 前一天 `00:00`
- 到当天 `08:00`

## 2. 目录说明

### 根目录

- `SKILL.md`
  - 技能主说明，给 Codex 读取
- `requirements.txt`
  - Python 依赖
- `.env.local`
  - 私密配置文件
  - 只放真实密钥
  - 不要提交，不要分享
- `.env.local.example`
  - 私密配置模板
- `.gitignore`
  - 忽略 `.env.local`

### `agents/`

- `openai.yaml`
  - 技能在 Codex/OpenAI 界面中的元信息

### `assets/`

- `email_template.html`
  - 邮件 HTML 模板
  - 调整视觉展示时主要看这个文件

### `references/`

- `journal_watchlist.yaml`
  - 期刊和 RSS/TOC 配置
- `category_rules.yaml`
  - 过滤、分类、排序、展示规则
- `bio_translation_glossary.yaml`
  - 生物学术语表
- `email_config.example.yaml`
  - 邮件配置模板
- `email_config.local.yaml`
  - 本地邮件配置
  - 放邮箱地址、SMTP 主机、发件人等
  - 不放授权码
- `email_style.example.yaml`
  - 样式配置模板
- `email_style.local.yaml`
  - 邮件样式覆盖配置
- `translation_config.example.yaml`
  - 通用翻译接口模板
- `translation_google_basic_v2.example.yaml`
  - Google 翻译配置模板
- `translation_google_basic_v2.local.yaml`
  - Google 翻译本地配置
- `translation_tencent_tmt.example.yaml`
  - 腾讯翻译配置模板
- `translation_tencent_tmt.local.yaml`
  - 腾讯翻译本地配置
- `llm_review_config.example.yaml`
  - 外部 LLM 复核配置模板
- `terminology_sources.yaml`
  - 可下载的术语库来源说明
- `user_quickstart.md`
  - 当前这份简易使用说明

### `scripts/`

- `run_production_digest.py`
  - 生产入口
  - 手工运行和定时任务都建议用它
- `run_digest.py`
  - 主流水线入口
  - 抓取、过滤、分类、翻译、导出、发信
- `with_env.py`
  - 自动读取 `.env.local` 后再执行命令
- `fetch_feeds.py`
  - 抓取 RSS / TOC
- `normalize_and_dedupe.py`
  - 标准化和去重
- `filter_bio_relevance.py`
  - 过滤非目标文献
- `classify_papers.py`
  - 固定分类
- `llm_review.py`
  - 第二层审核
- `translate_and_summarize.py`
  - 翻译和中文总结
- `export_digest.py`
  - 生成 HTML / CSV / XLSX
- `send_email.py`
  - 发邮件
- `send_style_preview.py`
  - 样式预览邮件
- `apply_manual_decisions.py`
  - 合并人工审核结果
- `rule_feedback_report.py`
  - 输出规则反馈报告
- `classification_suggestions.py`
  - 生成分类规则优化建议
- `build_glossary_candidates.py`
  - 生成术语表增量候选
- `audit_secrets.py`
  - 检查是否有密钥泄漏到项目文件
- `check_alignment.py`
  - 检查自动化、文档、生产配置是否对齐
- `common.py`
  - 通用工具函数
- `load_env.sh`
  - macOS/Linux 加载环境变量
- `load_env.ps1`
  - Windows PowerShell 加载环境变量

### `tests/`

- 存放单元测试
- `fixtures/`
  - 测试样例数据

### `archives/`

- `daily-digests/`
  - 每天归档的日报附件
  - 按日期目录保存
  - 超过 30 天自动删除

## 3. 先配置什么

### 第一步：创建环境变量文件

复制模板：

```bash
cp .env.local.example .env.local
```

填写这 4 个值：

```env
GOOGLE_TRANSLATE_API_KEY=
TENCENT_TMT_SECRET_ID=
TENCENT_TMT_SECRET_KEY=
QQ_MAIL_APP_PASSWORD=
```

说明：

- 真实密钥只允许写在 `.env.local`
- 不要把密钥写进 Python 脚本、YAML、邮件模板、自动化文件

### 第二步：配置邮箱

编辑：

- `references/email_config.local.yaml`

需要配置：

- 发件邮箱
- 收件邮箱列表
- SMTP 主机和端口
- `password_env`

注意：

- 这里填的是环境变量名
- 不是 SMTP 授权码本身

### 第三步：配置期刊

编辑：

- `references/journal_watchlist.yaml`

可以开启、关闭或新增期刊源。

### 第四步：配置规则和术语

常改这两个文件：

- `references/category_rules.yaml`
- `references/bio_translation_glossary.yaml`

## 4. 如何安装

```bash
cd /Users/mumu/Documents/skills/bio-literature-digest
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 5. 如何检查密钥安全

运行：

```bash
.venv/bin/python3 scripts/audit_secrets.py
```

预期输出：

```text
Secret audit passed. Sensitive values exist only in .env.local.
```

## 6. 如何本地测试

### 只跑样例，不发邮件

```bash
.venv/bin/python3 scripts/run_production_digest.py \
  --input-file tests/fixtures/sample_raw.jsonl \
  --skip-email \
  --summary-provider placeholder \
  --window-start 2026-03-13T00:00:00Z \
  --window-end 2026-03-15T00:00:00Z
```

### 发样式预览邮件

```bash
.venv/bin/python3 scripts/send_style_preview.py \
  --localized-input /tmp/bio-digest-prod/localized_records.jsonl \
  --style-config references/email_style.local.yaml \
  --email-config references/email_config.local.yaml \
  --smtp-profile qq_mail
```

## 7. 如何正式运行

### 推荐命令

```bash
.venv/bin/python3 scripts/run_production_digest.py
```

这个入口会自动：

- 读取 `.env.local`
- 使用本地邮件配置
- 使用本地样式配置
- 采用北京时间日报窗口
- 发邮件
- 归档日报文件
- 自动删除 30 天前归档

## 8. 输出文件在哪

### 运行中间文件

默认工作目录：

- `/tmp/bio-digest-prod`

其中常看这些：

- `digest.html`
- `digest.csv`
- `digest.xlsx`
- `review_queue.csv`
- `rule_feedback_report.md`
- `classification_suggestions.md`
- `glossary_candidates.md`

### 长期归档文件

- `archives/daily-digests/YYYY-MM-DD/`

例如：

- `archives/daily-digests/2026-03-15/digest.csv`

## 9. 常见修改入口

### 想改期刊

- `references/journal_watchlist.yaml`

### 想改过滤和分类

- `references/category_rules.yaml`

### 想改术语翻译

- `references/bio_translation_glossary.yaml`

### 想改邮件样式

- `assets/email_template.html`
- `references/email_style.local.yaml`

### 想改收件人

- `references/email_config.local.yaml`

### 想查有没有泄漏密钥

- `scripts/audit_secrets.py`

## 10. 给其他使用者的最短使用步骤

1. 复制整个目录到新机器
2. 创建 `.venv`
3. 填 `.env.local`
4. 改 `references/email_config.local.yaml`
5. 运行 `scripts/audit_secrets.py`
6. 运行 `scripts/run_production_digest.py`

如果只记一条命令，记这个：

```bash
.venv/bin/python3 scripts/run_production_digest.py
```
