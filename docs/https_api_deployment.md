# HTTPS API 生产部署与使用手册

## 1. 适用范围

本文档用于将 Bio Literature Digest 部署为可远程访问的 HTTPS API，并覆盖：

- Linux 服务器安装和初始化
- HTTPS 入口：Caddy 直接监听 443，或上游边缘隧道终止 TLS 后转发到本机 Caddy
- systemd 长期运行
- Bootstrap 管理员和个人访问令牌
- 用户、角色和权限管理
- 日报任务创建、查询和产物下载
- 期刊、分类规则和邮件收件人在线配置
- 数据备份、升级、回滚和故障排查

这是独立便携服务的部署和接口手册，不是现有线上 Web API 的接口参考。两者可以使用同一业务数据，但路由、权限模型和部署方式不同。

API 服务不接受任意命令、任意服务器路径或文件上传。底层 `command` provider 只能在服务器本地配置和调用。

## 2. 系统架构

拓扑 A：Caddy 直接持有证书并监听公网 443。本文第 9 节的配置流程针对这种部署。

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

拓扑 B：TLS 在上游边缘（CDN 或出站隧道）终止，本机 Caddy 只在内网端口做反向代理。服务器不监听
80/443，也不签发证书。已有多站点共用 Caddy 的主机适合这种方式，见第 9.2 节。

```text
Remote client
    |
    | HTTPS :443
    v
Edge (TLS 终止) --outbound tunnel--> Caddy (本机内网端口)
                                       |
                                       | HTTP 127.0.0.1:8787
                                       v
                                     FastAPI / Uvicorn
```

安全边界：

- 反向代理是唯一入口，API 进程本身不接受外部连接。
- Uvicorn 只监听 `127.0.0.1`。
- 所有 `/api/v1/*` 接口均要求个人访问令牌。
- `/healthz` 和 `/docs` 不要求令牌。
- API 服务使用单 worker，Producer 同一时间只运行一个任务。

## 3. 环境要求

推荐环境：

- Ubuntu 22.04/24.04、Debian 12 或兼容 Linux
- Python 3.10 或更高版本
- 可用域名，例如 `digest-api.example.com`
- 拓扑 A：域名 A/AAAA 记录指向服务器公网地址，TCP 80、443 对公网开放
- 拓扑 B：边缘侧已能到达本机（出站隧道或同等通道），本机无需开放 80/443
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

部署路径或运行身份与模板不同时，不要就地改 `/etc/systemd/system/` 里的文件后不留痕迹。做法是在
`ops/systemd/` 下另存一份主机专用单元并纳入版本控制，安装时从该文件复制，使已上线配置始终可以和
仓库比对：

```bash
sudo diff /etc/systemd/system/bio-literature-digest-api.service \
  ops/systemd/你的主机单元文件
```

`ops/systemd/bio-literature-digest-api.vps219.service` 是这种主机专用单元的实例，可作为改写参考。
和通用模板相比它有两处必须同步修改的偏离，并在文件注释里写明了原因：

- 安装目录在 `/root/software` 下时 `ProtectHome=true` 会遮蔽整个 `/root`，服务起不来，必须改为
  `ProtectHome=false`，并把 `ReadWritePaths` 一并指向真实路径。
- 本机已有以 root 运行的 Producer 定时任务时，`User`/`Group` 必须与其一致，否则两边读写不到同一套
  `local/` 和 `var/`。

## 9. 反向代理与 HTTPS

按第 2 节选定的拓扑执行 9.1 或 9.2，两者都要满足 9.3。

### 9.1 拓扑 A：Caddy 直接终止 TLS

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

### 9.2 拓扑 B：边缘终止 TLS，本机 Caddy 共用

这种主机上的 Caddy 通常已经在服务其他站点，配置文件不属于本项目。不要用模板覆盖它，只追加一段
主机名匹配，并且必须放在兜底站点之前，否则请求会被前面的规则吃掉：

```caddyfile
@digestApi host 你的真实域名
handle @digestApi {
    reverse_proxy 127.0.0.1:8787
}
```

改共用配置前先备份，再校验并重载。容器化 Caddy 用容器内路径校验，宿主原生安装用 `systemctl`：

```bash
sudo cp /path/to/Caddyfile "/path/to/backup/Caddyfile.before-digest-api-$(date +%Y%m%d-%H%M%S)"
# 容器
sudo docker exec caddy caddy validate --config /etc/caddy/Caddyfile
sudo docker exec caddy caddy reload  --config /etc/caddy/Caddyfile
# 原生
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

在边缘侧把公网主机名指向本机 Caddy 监听的内网端口。域名与路由记录保存在边缘控制台，不落在
主机上，因此排查时要同时看边缘配置和本机 Caddy 日志。

验证时先确认本机链路，再确认公网链路：

```bash
curl -sS http://127.0.0.1:8787/healthz
curl -sS http://127.0.0.1:本机Caddy端口/healthz -H "Host: 你的真实域名"
curl -sS https://你的真实域名/healthz
```

三条都返回 `{"status":"ok"}` 才算通。第二条失败说明 Caddy 匹配没生效，第三条单独失败说明边缘映射
或隧道有问题，与本项目无关。

### 9.3 正式环境要求

- 拓扑 A 的防火墙只开放必要的 SSH、80 和 443；拓扑 B 不需要开放 80/443。
- 不开放 8787，也不开放本机 Caddy 的内网端口。
- Uvicorn 保持 `127.0.0.1`。
- `local/.env.local` 权限为 `600`。
- 反向代理和 API 服务分别使用非 root 运行账户。如果本机已有以 root 身份运行的 Producer 定时任务，
  API 必须复用同一身份才能读写同一套 `local/` 和 `var/`；此时以目录权限和 systemd 沙箱选项作为
  替代边界，并在单元文件里写明这一偏离及原因。

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
- `partial_success`：产物已全部写出，但邮件投递失败。`send_email` 是流水线最后一步，此时产物可直接使用，不需要重跑。
- `failed`
- `interrupted`

除状态外，响应还会带上 `run_metadata.json` 中的实时进度字段。Producer 在每一步结束后都会重写该文件，因此任务运行途中即可读到这些值：

- `email_status`：`skipped` / `sent` / `failed` / `not_attempted`，由 Producer 判定，API 只做透传。
- `failed_step`、`failure_type`：失败发生在哪一步、属于哪一类。
- `completed_steps`：已完成的步骤列表。
- `counts`：各阶段论文计数。
- `artifacts`：已写出的产物及其下载路径。

`failure_message` 中的订阅者邮箱地址已做掩码处理。

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
4. 修正所有权为服务运行账户。
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
- 检查目录所有者是否为服务运行账户。
- 执行 `systemctl daemon-reload` 并重启服务。

### 公网访问失败但本机正常

先用第 9.2 节的三条 `curl` 定位断点，再按断点排查：

- 本机 `127.0.0.1:8787` 失败：问题在 API 服务，看 `journalctl -u bio-literature-digest-api`。
- 本机 Caddy 端口失败：主机名匹配没生效或被兜底站点吃掉，检查匹配段的位置，重新校验并重载。
- 只有公网失败：问题在边缘侧的主机名和路由配置，本机日志不会有记录。

### Caddy 无法签发证书

仅拓扑 A 需要签发证书。拓扑 B 由边缘持有证书，本机不签发，出现这类报错说明拓扑配置串了。

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

- [ ] 公网主机名指向本部署：拓扑 A 解析到服务器地址，拓扑 B 在边缘侧指向本机 Caddy 端口
- [ ] `8787` 和本机 Caddy 内网端口都未暴露公网；拓扑 A 的 80/443 可访问，拓扑 B 无需开放
- [ ] `https://你的真实域名/healthz` 返回 `{"status":"ok"}`
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
- [ ] HTTPS 证书有效：拓扑 A 检查本机 Caddy 签发结果，拓扑 B 检查边缘侧证书
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

## 25. MCP 只读接口

MCP 服务器让 MCP 客户端直接查询任务和产物，不经过 HTTPS。它与 HTTP API 共用
`bio_literature_digest.api.runs_service`，因此两个接口返回的任务视图完全一致。

### 25.1 传输与依赖

- 传输方式：stdio 上的换行分隔 JSON-RPC 2.0，即 MCP 的 stdio transport。
- 依赖：仅标准库。不需要 `mcp` SDK，也不需要 FastAPI、Uvicorn、pydantic。
  生产 venv 未安装这些包时该接口依然可用。
- stdout 是协议通道。诊断信息一律写 stderr，任何写入 stdout 的内容都会破坏流。

### 25.2 启动

```bash
.venv/bin/python3 scripts/serve_mcp.py
```

运行目录默认取 `$BIO_DIGEST_API_RUN_ROOT`，否则为 `var/api/runs`，与 `serve_api.py`
的解析方式相同。也可用 `--run-root` 显式指定。

MCP 客户端注册示例：

```json
{
  "command": "/root/software/bio-literature-digest/.venv/bin/python3",
  "args": ["/root/software/bio-literature-digest/scripts/serve_mcp.py"]
}
```

### 25.3 工具

| 工具 | 作用 |
|---|---|
| `list_runs` | 列出最近任务，最新优先；`limit` 默认 20，上限 100 |
| `get_run` | 按 `run_id` 查询单个任务 |
| `list_artifacts` | 列出该任务已生成的产物、字节数和 HTTP 下载路径 |
| `read_artifact` | 读取文本产物，按 `max_bytes` 截断；默认 64 KiB，上限 1 MiB |

`read_artifact` 只接受文本产物。`digest.xlsx` 等表格是二进制，只能走 HTTP 下载。
返回文本中的订阅者邮箱地址一律经过掩码。

### 25.4 安全边界

- 接口是只读的。没有创建任务的工具：启动任务会改动共享状态、占用单任务锁并可能
  发送订阅邮件，因此只保留在需要令牌的 HTTP API 上。
- 产物读取受白名单约束，客户端无法读取运行目录内的任意路径。`status.json`
  属于存储层簿记，不在白名单内。
- MCP 通过 stdio 运行在服务器本地，没有按调用方区分的身份；进程本身的文件权限
  就是它的权限边界。不要把它暴露到公网。
