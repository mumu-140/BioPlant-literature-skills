# 开源配置副本说明

本项目把“源码配置”和“本机私有配置”明确分开：

- 可公开提交：
  - `agents/openai.yaml`
  - `config/content/*.yaml`
  - `config/runtime/production.example.yaml`
  - `config/integrations/*.example.yaml`
  - `config/env.local.example`
- 不可公开提交：
  - `local/.env.local`
  - `local/runtime/production.yaml`
  - `local/integrations/*.yaml`
  - `var/**`

## 设计原则

1. 公开模板只保留：
   - 字段结构
   - 示例占位值
   - 中文说明
2. 真实密钥只放在：
   - `local/.env.local`
3. 真实收件人、发件账号、内网地址、本机路径只放在：
   - `local/runtime/production.yaml`
   - `local/integrations/*.yaml`
4. `config/content/*.yaml` 是项目源码的一部分，不属于私密配置，因此直接作为公开源文件维护。

## 推荐初始化流程

```bash
mkdir -p local/runtime local/integrations
cp config/env.local.example local/.env.local
cp config/runtime/production.example.yaml local/runtime/production.yaml
cp config/integrations/email_config.example.yaml local/integrations/email_config.yaml
cp config/integrations/users.example.yaml local/integrations/users.yaml
cp config/integrations/email_style.example.yaml local/integrations/email_style.yaml
cp config/integrations/translation_google_basic_v2.example.yaml local/integrations/translation_google_basic_v2.yaml
```

## 推送到 GitHub 前检查

建议至少执行：

```bash
.venv/bin/python3 scripts/audit_secrets.py
.venv/bin/python3 scripts/check_project.py
```

如果这两个检查都通过，说明公开面上的模板、结构和关键校验基本一致。
