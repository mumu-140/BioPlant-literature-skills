# HTTPS API 生产部署与使用手册

## 1. 适用范围

本文档用于将 Bio Literature Digest 部署为可远程访问的 HTTPS API，并覆盖：

- Linux 服务器安装和初始化
- Caddy HTTPS 终止
- systemd 长期运行
- Bootstrap 管理员和个人访问令牌
- 用户、角色和权限管理
- 日报任务创建、查询和产物下载
- 期刊、分类规则和邮件收件人在线配置
- 数据备份、升级、回滚和故障排查

这是独立便携服务的部署和接口手册，不是现有线上 Web API 的接口参考。两者可以使用同一业务数据，但路由、权限模型和部署方式不同。

API 服务不接受任意命令、任意服务器路径或文件上传。底层 `command` provider 只能在服务器本地配置和调用。

## 2. 系统架构

```text
Remote client
    |
    | HTTPS :443
    v
Caddy
    |
    | HTTP 127.0.0.1:8787
    v
FastAPI / Uvicorn
    |
    v
Producer CLI -> RSS/API -> digest artifacts -> email/archive/review backlog
```

安全边界：

- Caddy 是唯一公网入口。
- Uvicorn 只监听 `127.0.0.1`。
- 所有 `/api/v1/*` 接口均要求个人访问令牌。
- `/healthz` 和 `/docs` 不要求令牌。
- API 服务使用单 worker，Producer 同一时间只运行一个任务。

## 3. 环境要求

推荐环境：

- Ubuntu 22.04/24.04、Debian 12 或兼容 Linux
- Python 3.10 或更高版本
- 可用域名，例如 `digest-api.example.com`
- 域名 A/AAAA 记录指向服务器公网地址
- TCP 80、443 对公网开放
- TCP 8787 不对公网开放
- 服务器可以访问期刊 RSS、SMTP 和配置的 AI Provider

安装基础依赖的示例：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl ca-certificates
```

`install_server.sh` 会通过 PyPI 联网安装依赖；发行包不是离线依赖镜像。受限网络环境应预先配置可信 PyPI 镜像或内部 wheel 仓库。

Caddy 应按其官方仓库或操作系统包管理方式安装。安装后确认：

```bash
caddy version
systemctl status caddy
```

## 4. 安装项目

本文使用以下部署路径：

```text
/opt/bio-literature-digest
```

应用源码可部署到其他目录，但 systemd 模板固定假定 `/opt/bio-literature-digest`。改变目录时必须同步修改 `WorkingDirectory`、`EnvironmentFile`、`ExecStart` 和 `ReadWritePaths`。

创建系统用户：

```bash
sudo useradd --system --home /opt/bio-literature-digest --shell /usr/sbin/nologin bio-digest
```

先校验发行包。以下示例中的文件名按实际发布日期替换：

```bash
PACKAGE=bio-literature-digest-https-portable-YYYYMMDD.tar.gz
shasum -a 256 -c "${PACKAGE}.sha256"
```

Linux 没有 `shasum` 时可使用：

```bash
sha256sum -c "${PACKAGE}.sha256"
```

解压发行包并调整目录名：

```bash
sudo mkdir -p /opt/bio-literature-digest
sudo tar -xzf "${PACKAGE}" \
  --strip-components=1 \
  -C /opt/bio-literature-digest
sudo chown -R bio-digest:bio-digest /opt/bio-literature-digest
```

初始化：

```bash
cd /opt/bio-literature-digest
sudo -u bio-digest ./install_server.sh
```

发行包不包含任何 `local/` 私有配置、`var/` 运行数据或虚拟环境。初始化脚本会从公开模板创建这些目录和文件，再安装依赖、执行密钥检查和完整测试。不要把其他服务器的 `.venv` 复制过来。

从源码构建同样的发行包：

```bash
python3 scripts/build_portable_package.py --output-dir /path/to/dist
```

构建来源是已提交的 Git `HEAD`，因此应先完成测试和提交，再生成发行包。

## 5. 目录和数据

| 路径 | 内容 | 备份要求 |
|---|---|---|
| `local/.env.local` | API Key、SMTP 和 AI 密钥 | 必须备份并加密 |
| `local/runtime/production.yaml` | 本机运行参数 | 必须备份 |
| `local/integrations/` | 邮件、用户和 Provider 配置 | 必须备份 |
| `config/content/journal_watchlist.yaml` | 期刊配置 | 必须备份 |
| `config/content/category_rules.yaml` | 分类和过滤规则 | 必须备份 |
| `var/api/auth.sqlite3` | API 用户、令牌摘要、审计日志 | 必须备份 |
| `var/api/runs/` | API 任务状态和任务产物 | 按保留策略备份 |
| `var/api/config-backups/` | 配置 API 自动备份 | 建议保留 |
| `var/archives/` | 日报长期归档 | 按业务要求备份 |
| `var/reviews/` | 人工审核和 backlog | 必须备份 |
| `var/db/` | 可选日报 SQLite | 启用时必须备份 |

设置私有配置权限：

```bash
sudo chown -R bio-digest:bio-digest \
  /opt/bio-literature-digest/local \
  /opt/bio-literature-digest/var \
  /opt/bio-literature-digest/config/content
sudo chmod 700 \
  /opt/bio-literature-digest/local \
  /opt/bio-literature-digest/local/runtime \
  /opt/bio-literature-digest/local/integrations \
  /opt/bio-literature-digest/var/api
sudo find /opt/bio-literature-digest/local -type f -exec chmod 600 {} +
sudo chmod 600 /opt/bio-literature-digest/var/api/auth.sqlite3 2>/dev/null || true
```

## 6. Bootstrap 管理员

生成初始高强度令牌：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

写入 `local/.env.local`：

```env
BIO_DIGEST_API_KEY=替换为生成的随机密钥
BIO_DIGEST_API_HOST=127.0.0.1
BIO_DIGEST_API_PORT=8787
```

可选环境变量：

```env
BIO_DIGEST_API_LOG_LEVEL=info
BIO_DIGEST_API_RUN_ROOT=/opt/bio-literature-digest/var/api/runs
BIO_DIGEST_RUNTIME_CONFIG=/opt/bio-literature-digest/local/runtime/production.yaml
```

首次启动且 `var/api/auth.sqlite3` 中没有用户时，系统创建：

```text
username: bootstrap-admin
role: admin
token: BIO_DIGEST_API_KEY 的值
```

重要行为：

- SQLite 只保存令牌的 SHA-256 摘要和前缀，不保存明文。
- 创建用户或轮换令牌时，明文只在响应中返回一次。
- 身份库中已有用户后，修改 `BIO_DIGEST_API_KEY` 不会自动轮换现有管理员令牌。
- 后续令牌变更必须调用令牌轮换接口。
- 不要在日志、工单、Git 或聊天记录中传递真实令牌。

## 7. 本机 HTTP 验证

启动服务：

```bash
cd /opt/bio-literature-digest
sudo -u bio-digest .venv/bin/python3 scripts/serve_api.py
```

另开终端检查：

```bash
curl -sS http://127.0.0.1:8787/healthz
```

预期响应：

```json
{"status":"ok"}
```

验证鉴权：

```bash
curl -sS http://127.0.0.1:8787/api/v1/me \
  -H "Authorization: Bearer YOUR_API_KEY"
```

Swagger：

```text
http://127.0.0.1:8787/docs
```

完成验证后停止前台进程，再配置 systemd。

## 8. systemd 服务

安装模板：

```bash
sudo cp ops/systemd/bio-literature-digest-api.service.example \
  /etc/systemd/system/bio-literature-digest-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now bio-literature-digest-api
```

检查状态和日志：

```bash
sudo systemctl status bio-literature-digest-api
sudo journalctl -u bio-literature-digest-api -n 100 --no-pager
sudo journalctl -u bio-literature-digest-api -f
```

修改配置后重启：

```bash
sudo systemctl restart bio-literature-digest-api
```

服务启用了 `ProtectSystem=strict`，但明确允许写入：

- `/opt/bio-literature-digest/local`
- `/opt/bio-literature-digest/var`
- `/opt/bio-literature-digest/config/content`

缺少第三项会导致期刊和分类规则在线修改失败。

## 9. Caddy HTTPS

复制模板：

```bash
sudo cp ops/caddy/Caddyfile.example /etc/caddy/Caddyfile
sudo sed -i 's/digest-api.example.com/你的真实域名/' /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

检查证书和 HTTPS：

```bash
curl -I https://你的真实域名/healthz
sudo journalctl -u caddy -n 100 --no-pager
```

正式环境要求：

- 防火墙只开放必要的 SSH、80 和 443。
- 不开放 8787。
- Uvicorn 保持 `127.0.0.1`。
- `local/.env.local` 权限为 `600`。
- Caddy 和 API 服务分别使用非 root 运行账户。

## 10. 鉴权方式

推荐使用 Bearer：

```http
Authorization: Bearer YOUR_API_KEY
```

兼容方式：

```http
X-API-Key: YOUR_API_KEY
```

以下示例统一使用：

```bash
export BIO_API_URL="https://digest-api.example.com"
export BIO_API_TOKEN="YOUR_API_KEY"
```

## 11. 角色权限

| 能力 | admin | operator | viewer |
|---|---:|---:|---:|
| 查询本人身份 | 是 | 是 | 是 |
| 创建日报任务 | 是 | 是 | 否 |
| 查询任务和下载产物 | 是 | 是 | 是 |
| 读取期刊和分类规则 | 是 | 是 | 是 |
| 修改期刊和分类规则 | 是 | 否 | 否 |
| 读取、修改邮件收件人 | 是 | 否 | 否 |
| 创建、修改、删除 API 用户 | 是 | 否 | 否 |
| 轮换用户令牌 | 是 | 否 | 否 |
| 查看审计日志 | 是 | 否 | 否 |

保护规则：

- 管理员不能删除自己。
- 管理员不能停用或降级自己。
- 最后一个有效管理员不能被删除、停用或降级。
- 停用用户后，其令牌立即失效。

## 12. 用户管理 API

### 12.1 查询本人

```bash
curl -sS "$BIO_API_URL/api/v1/me" \
  -H "Authorization: Bearer $BIO_API_TOKEN"
```

### 12.2 创建用户

```bash
curl -sS -X POST "$BIO_API_URL/api/v1/users" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username":"digest-operator",
    "display_name":"Digest Operator",
    "role":"operator"
  }'
```

响应中的 `token` 只显示一次：

```json
{
  "id":"USER_ID",
  "username":"digest-operator",
  "display_name":"Digest Operator",
  "role":"operator",
  "token_prefix":"bdg_example",
  "is_active":true,
  "created_at_utc":"2026-07-13T00:00:00Z",
  "updated_at_utc":"2026-07-13T00:00:00Z",
  "token":"bdg_FULL_TOKEN_RETURNED_ONCE"
}
```

### 12.3 列出用户

```bash
curl -sS "$BIO_API_URL/api/v1/users" \
  -H "Authorization: Bearer $BIO_API_TOKEN"
```

### 12.4 修改角色或状态

```bash
curl -sS -X PATCH "$BIO_API_URL/api/v1/users/USER_ID" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role":"viewer","is_active":true}'
```

停用：

```bash
curl -sS -X PATCH "$BIO_API_URL/api/v1/users/USER_ID" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_active":false}'
```

### 12.5 轮换令牌

```bash
curl -sS -X POST "$BIO_API_URL/api/v1/users/USER_ID/rotate-token" \
  -H "Authorization: Bearer $BIO_API_TOKEN"
```

新令牌生效后，旧令牌立即失效。

### 12.6 删除用户

```bash
curl -i -X DELETE "$BIO_API_URL/api/v1/users/USER_ID" \
  -H "Authorization: Bearer $BIO_API_TOKEN"
```

成功返回 `204 No Content`。

## 13. 日报任务 API

### 13.1 创建计划窗口任务

```bash
curl -sS -X POST "$BIO_API_URL/api/v1/runs" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"skip_email":true}'
```

### 13.2 指定 UTC 窗口

```bash
curl -sS -X POST "$BIO_API_URL/api/v1/runs" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "window_start":"2026-03-13T00:00:00Z",
    "window_end":"2026-03-15T00:00:00Z",
    "skip_email":true,
    "summary_provider":"placeholder",
    "review_provider":"placeholder"
  }'
```

`window_start` 和 `window_end` 必须同时出现，且起始时间早于结束时间。

### 13.3 查询任务

```bash
curl -sS "$BIO_API_URL/api/v1/runs/RUN_ID" \
  -H "Authorization: Bearer $BIO_API_TOKEN"
```

任务状态：

- `queued`
- `running`
- `success`
- `failed`
- `interrupted`

### 13.4 下载产物

```bash
curl -sS "$BIO_API_URL/api/v1/runs/RUN_ID/artifacts" \
  -H "Authorization: Bearer $BIO_API_TOKEN"

curl -o digest.csv \
  "$BIO_API_URL/api/v1/runs/RUN_ID/artifacts/digest.csv" \
  -H "Authorization: Bearer $BIO_API_TOKEN"
```

## 14. 期刊配置 API

### 14.1 读取期刊

```bash
curl -sS "$BIO_API_URL/api/v1/config/journals" \
  -H "Authorization: Bearer $BIO_API_TOKEN"
```

### 14.2 新增期刊

```bash
curl -sS -X POST "$BIO_API_URL/api/v1/config/journals" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id":"example-journal",
    "enabled":true,
    "publisher_family":"example-publisher",
    "journal_name":"Example Journal",
    "group":"biology-core",
    "source_strategy":"official_feed",
    "source_locator":"https://example.com/feed.xml",
    "article_scope":"all",
    "topic_bias":{"include":["biology"],"exclude":[]}
  }'
```

### 14.3 修改期刊

`id` 必须与 URL 中的 `journal_id` 一致：

```bash
curl -sS -X PUT "$BIO_API_URL/api/v1/config/journals/example-journal" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d @journal.json
```

### 14.4 删除期刊

```bash
curl -i -X DELETE "$BIO_API_URL/api/v1/config/journals/example-journal" \
  -H "Authorization: Bearer $BIO_API_TOKEN"
```

每次写入前，原文件会备份到 `var/api/config-backups/journals/`。

`source_locator` 仅允许公开的 `http/https` 地址，不允许 URL 凭据、本机名、私有 IP、链路本地地址或本地协议。抓取时还会校验 DNS 解析结果和重定向目标。

## 15. 分类规则 API

当前接口采用完整文档替换，不提供局部 PATCH。修改前必须先读取并保存本地副本：

为保证单次日报使用一致配置，只要有 API 日报任务处于 `queued` 或 `running`，期刊、分类规则和收件人写接口都会返回 `409`。任务结束后再修改配置。

```bash
curl -sS "$BIO_API_URL/api/v1/config/category-rules" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -o category-rules.json
```

编辑后提交：

```bash
curl -sS -X PUT "$BIO_API_URL/api/v1/config/category-rules" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @category-rules.json
```

校验要求：

- `categories` 必须是列表。
- 分类 ID 必须唯一。
- 必须保留 `other` 分类。

备份目录：`var/api/config-backups/category-rules/`。

## 16. 邮件收件人配置 API

该配置包含邮箱，仅 `admin` 可访问。它与 API 登录账户完全分离。

读取：

```bash
curl -sS "$BIO_API_URL/api/v1/config/recipients" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -o recipients.json
```

示例结构：

```json
{
  "users":[
    {
      "uid":"UDI-0001",
      "email":"member@example.com",
      "name":"Example Member",
      "role":"member",
      "group":"internal",
      "is_active":true,
      "receives_digest":true,
      "smtp_profile":"primary_smtp",
      "tags":["biology"]
    }
  ]
}
```

完整替换：

```bash
curl -sS -X PUT "$BIO_API_URL/api/v1/config/recipients" \
  -H "Authorization: Bearer $BIO_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @recipients.json
```

邮箱必须包含 `@` 且不能重复。备份目录：`var/api/config-backups/recipients/`。

## 17. 审计日志

```bash
curl -sS "$BIO_API_URL/api/v1/audit-log?limit=100" \
  -H "Authorization: Bearer $BIO_API_TOKEN"
```

审计记录覆盖用户创建、修改、删除、令牌轮换和配置写入。只有 `admin` 可读取。

## 18. 状态码和错误

| 状态码 | 含义 | 常见原因 |
|---:|---|---|
| `200` | 成功 | 查询或更新成功 |
| `201` | 已创建 | 创建用户或期刊成功 |
| `202` | 已接受 | 日报任务进入队列 |
| `204` | 成功且无响应体 | 删除成功 |
| `401` | 未认证 | 令牌缺失、错误、停用或已轮换 |
| `403` | 禁止 | 当前角色无权限 |
| `404` | 不存在 | 用户、任务、期刊或产物不存在 |
| `409` | 状态冲突 | 用户名重复、已有任务运行、运行中禁止改配置、管理员保护 |
| `422` | 校验失败 | 请求字段、时间窗口或配置结构错误 |
| `503` | 服务未配置 | 没有 Bootstrap API Key 或身份用户 |

错误响应示例：

```json
{"detail":"insufficient permissions"}
```

## 19. 备份与恢复

备份前可短暂停止 API，确保 SQLite 和配置一致：

```bash
sudo systemctl stop bio-literature-digest-api
sudo tar -czf /path/to/backup/bio-digest-backup-$(date +%F).tar.gz \
  /opt/bio-literature-digest/local \
  /opt/bio-literature-digest/config/content \
  /opt/bio-literature-digest/var/api \
  /opt/bio-literature-digest/var/archives \
  /opt/bio-literature-digest/var/reviews \
  /opt/bio-literature-digest/var/db
sudo systemctl start bio-literature-digest-api
```

恢复流程：

1. 停止 API 服务。
2. 备份当前损坏或错误状态。
3. 恢复 `local/`、`config/content/` 和需要的 `var/` 数据。
4. 修正所有权为 `bio-digest:bio-digest`。
5. 启动服务并执行验收检查。

不要只恢复 `auth.sqlite3` 而丢失对应的 API Key 管理记录和审计上下文。

## 20. 升级与回滚

升级：

1. 完成上述备份。
2. 在新目录解压新发行包。
3. 迁移旧实例的 `local/` 和需要保留的 `var/`。
4. 合并 `config/content/` 的在线修改。
5. 在新目录重新运行 `install_server.sh`。
6. 执行本机 HTTP 验证。
7. 更新 systemd 路径或切换目录。
8. 重启 Caddy 和 API。

回滚：

1. 停止新版本 API。
2. 切回旧版本目录。
3. 恢复与旧版本兼容的配置和数据库备份。
4. 启动旧版本并执行验收。

不要覆盖仍在使用的目录后再尝试回滚；推荐使用版本化目录和稳定符号链接进行切换。

## 21. 令牌泄露处置

如果普通用户令牌泄露：

1. 管理员立即停用该用户或轮换其令牌。
2. 检查 `/api/v1/audit-log`。
3. 检查 Caddy 和 systemd 日志。
4. 确认是否发生配置修改或异常任务创建。

如果 Bootstrap 管理员令牌泄露：

1. 使用另一个管理员令牌轮换该用户令牌。
2. 如果没有其他管理员，停止服务并隔离公网访问。
3. 备份 `auth.sqlite3` 后执行受控恢复，不要仅修改环境变量并假定旧令牌失效。

## 22. 常见故障

### API 返回 401

- 检查是否使用了完整的新令牌。
- 确认用户没有被停用或删除。
- 令牌轮换后旧令牌立即失效。

### API 返回 403

- 检查 `/api/v1/me` 返回的角色。
- `viewer` 不能创建任务。
- `operator` 不能修改配置或管理用户。

### 配置接口返回只读文件系统

- 检查 systemd 的 `ReadWritePaths` 是否包含 `config/content`。
- 检查目录所有者是否为 `bio-digest`。
- 执行 `systemctl daemon-reload` 并重启服务。

### Caddy 无法签发证书

- 检查域名解析。
- 检查 80/443 防火墙。
- 检查是否有其他程序占用端口。
- 查看 `journalctl -u caddy`。

### 任务长时间处于 running

- 查看对应任务的 `run.log`。
- 查看 systemd 日志。
- 检查期刊、SMTP 和 AI Provider 网络。
- 不要在确认进程状态前手工删除活动锁。

### 服务启动后令牌无效

- 确认首次初始化时使用的 `BIO_DIGEST_API_KEY`。
- 如果身份库已有用户，修改环境变量不会更新原用户令牌。
- 使用现有管理员执行令牌轮换。

## 23. 部署验收清单

- [ ] 域名解析到正确服务器
- [ ] TCP 80/443 可访问，8787 未暴露公网
- [ ] `local/.env.local` 权限为 `600`
- [ ] `local/`、`var/api/` 目录仅服务账户可访问，敏感 YAML 和 SQLite 为 `600`
- [ ] Bootstrap 管理员可调用 `/api/v1/me`
- [ ] 已创建至少一个额外管理员并妥善保存其令牌
- [ ] `operator` 可以创建任务但不能修改配置
- [ ] `viewer` 可以读取任务但不能创建任务
- [ ] 管理员可以新增并删除测试期刊
- [ ] 分类规则和收件人配置修改会生成备份
- [ ] 日报测试任务可以完成并下载 `digest.csv`
- [ ] systemd 重启后服务自动恢复
- [ ] Caddy HTTPS 证书有效
- [ ] 已验证身份库、配置和 review 数据的备份恢复流程

## 24. 接口索引

| 方法 | 路径 | 最低角色 |
|---|---|---|
| `GET` | `/healthz` | 无 |
| `GET` | `/api/v1/me` | viewer |
| `POST` | `/api/v1/runs` | operator |
| `GET` | `/api/v1/runs` | viewer |
| `GET` | `/api/v1/runs/{run_id}` | viewer |
| `GET` | `/api/v1/runs/{run_id}/artifacts` | viewer |
| `GET` | `/api/v1/runs/{run_id}/artifacts/{name}` | viewer |
| `GET` | `/api/v1/users` | admin |
| `POST` | `/api/v1/users` | admin |
| `PATCH` | `/api/v1/users/{user_id}` | admin |
| `DELETE` | `/api/v1/users/{user_id}` | admin |
| `POST` | `/api/v1/users/{user_id}/rotate-token` | admin |
| `GET` | `/api/v1/audit-log` | admin |
| `GET` | `/api/v1/config/journals` | viewer |
| `POST` | `/api/v1/config/journals` | admin |
| `PUT` | `/api/v1/config/journals/{journal_id}` | admin |
| `DELETE` | `/api/v1/config/journals/{journal_id}` | admin |
| `GET` | `/api/v1/config/category-rules` | viewer |
| `PUT` | `/api/v1/config/category-rules` | admin |
| `GET` | `/api/v1/config/recipients` | admin |
| `PUT` | `/api/v1/config/recipients` | admin |
