# macOS launchd 部署说明

公开仓库里提供的是一个可改造模板：

- `scripts/run_production_digest_launchd.sh`
- `references/launchd/com.example.bio-digest-daily.plist`

在使用前，你需要把 plist 中的占位绝对路径替换成自己的仓库路径。

## 推荐变量

```bash
REPO_DIR="/absolute/path/to/bio-literature-digest"
PLIST_NAME="com.example.bio-digest-daily.plist"
PLIST_LABEL="com.example.bio-digest-daily"
```

## 当前生产命令

```bash
"${REPO_DIR}/.venv/bin/python3" \
  "${REPO_DIR}/scripts/run_production_digest.py" \
  --env-file "${REPO_DIR}/.env.local" \
  --work-dir /private/tmp/bio-digest-prod \
  --archive-dir "${REPO_DIR}/archives/daily-digests" \
  --email-config "${REPO_DIR}/references/email_config.local.yaml" \
  --smtp-profile qq_mail \
  --style-config "${REPO_DIR}/references/email_style.local.yaml" \
  --window-mode schedule \
  --timezone Asia/Shanghai \
  --delivery-time 08:00 \
  --review-provider placeholder \
  --summary-provider google-basic-v2 \
  --summary-config "${REPO_DIR}/references/translation_google_basic_v2.local.yaml" \
  --allow-review-pending
```

## 安装步骤

### 1. 确认基础环境

```bash
cd "${REPO_DIR}"
test -f .env.local
test -x .venv/bin/python3
```

### 2. 给 launchd 包装脚本执行权限

```bash
chmod +x "${REPO_DIR}/scripts/run_production_digest_launchd.sh"
```

### 3. 准备日志和 LaunchAgents 目录

```bash
mkdir -p ~/Library/LaunchAgents
mkdir -p "${REPO_DIR}/logs/launchd"
```

### 4. 复制并重命名 plist

```bash
cp "${REPO_DIR}/references/launchd/${PLIST_NAME}" ~/Library/LaunchAgents/"${PLIST_NAME}"
chmod 644 ~/Library/LaunchAgents/"${PLIST_NAME}"
```

### 5. 语法检查

```bash
plutil -lint ~/Library/LaunchAgents/"${PLIST_NAME}"
zsh -n "${REPO_DIR}/scripts/run_production_digest_launchd.sh"
```

### 6. 加载任务

```bash
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/"${PLIST_NAME}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/"${PLIST_NAME}"
launchctl enable "gui/$(id -u)/${PLIST_LABEL}"
```

### 7. 手动触发一次验证

```bash
launchctl kickstart -k "gui/$(id -u)/${PLIST_LABEL}"
```

### 8. 查看运行状态

```bash
launchctl print "gui/$(id -u)/${PLIST_LABEL}"
tail -n 200 "${REPO_DIR}/logs/launchd/bio-digest-daily.stdout.log"
tail -n 200 "${REPO_DIR}/logs/launchd/bio-digest-daily.stderr.log"
```

### 9. 检查产物是否符合契约

```bash
cd "${REPO_DIR}"
.venv/bin/python3 scripts/validate_daily_artifacts.py --run-dir /private/tmp/bio-digest-prod
```

## 注意事项

- `launchd` 使用的是 Mac 当前系统时区。如果你的 Mac 不是 `Asia/Shanghai` 时区，08:00 触发时刻会按系统时区解释。
- 时间窗口依然由 `run_production_digest.py` 按 `Asia/Shanghai` 计算，所以“触发时区”和“日报窗口时区”是两个概念。
- 当前 plist 直接执行 `run_production_digest_launchd.sh`，不再通过 `/bin/zsh <script>` 间接调用，目的是减少 launchd 下的脚本路径解析问题。
- 如果仓库放在 `~/Documents`、`~/Desktop`、`~/Downloads` 这类 macOS 受保护目录，后台 LaunchAgent 仍可能因为系统隐私限制无法读取脚本或项目文件。优先把仓库放到 `~/workspace/`、`~/code/` 这类非受保护路径。
