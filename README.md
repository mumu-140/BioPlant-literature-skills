# BioPlant Literature Skills

一个用于生成生物 / 植物方向文献日报的技能项目。

它会做这些事：

- 抓取配置好的期刊和预印本源
- 过滤非目标方向文献
- 分类
- 翻译标题并生成中文总结
- 导出 `HTML / CSV / XLSX`
- 按邮件发送日报

## 目录放什么

- `.env.local`
  放真实密钥，只放本机，不要提交
- `references/email_config.local.yaml`
  放邮箱配置、收件人、SMTP 信息
- `references/email_style.local.yaml`
  放邮件样式覆盖配置
- `references/translation_google_basic_v2.local.yaml`
  或 `references/translation_tencent_tmt.local.yaml`
  放翻译服务本地配置
- `references/journal_watchlist.yaml`
  放期刊源配置
- `references/category_rules.yaml`
  放过滤和分类规则
- `references/bio_translation_glossary.yaml`
  放术语表

## 先配置什么

### 1. 环境变量

复制模板：

```bash
cp .env.local.example .env.local
```

填写真实值：

```env
GOOGLE_TRANSLATE_API_KEY=
TENCENT_TMT_SECRET_ID=
TENCENT_TMT_SECRET_KEY=
QQ_MAIL_APP_PASSWORD=
```

### 2. 邮件配置

复制模板：

```bash
cp references/email_config.example.yaml references/email_config.local.yaml
```

需要改：

- 发件邮箱
- 收件邮箱
- SMTP 主机和端口
- `password_env`

### 3. 翻译配置

如果用 Google：

```bash
cp references/translation_google_basic_v2.example.yaml references/translation_google_basic_v2.local.yaml
```

如果用腾讯：

```bash
cp references/translation_tencent_tmt.example.yaml references/translation_tencent_tmt.local.yaml
```

### 4. 样式配置

如果需要自定义邮件样式：

```bash
cp references/email_style.example.yaml references/email_style.local.yaml
```

## 怎么安装

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 怎么用

### 本地测试，不发邮件

```bash
.venv/bin/python3 scripts/run_production_digest.py \
  --input-file tests/fixtures/sample_raw.jsonl \
  --skip-email \
  --summary-provider placeholder \
  --window-start 2026-03-13T00:00:00Z \
  --window-end 2026-03-15T00:00:00Z
```

### 正式运行

```bash
.venv/bin/python3 scripts/run_production_digest.py
```

这个入口会自动：

- 读取 `.env.local`
- 使用本地邮件和翻译配置
- 计算日报时间窗口
- 导出附件
- 发送邮件

## 安全检查

运行：

```bash
.venv/bin/python3 scripts/audit_secrets.py
```

如果输出下面这句，说明仓库里没有泄漏真实密钥：

```text
Secret audit passed. Sensitive values exist only in .env.local.
```

更详细的使用说明见：

- `references/user_quickstart.md`
---

## Acknowledgments
---
Special thanks to the **[Linux.do](https://linux.do/)** community for your support and feedback.
