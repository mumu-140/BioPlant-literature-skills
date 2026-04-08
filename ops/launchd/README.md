# macOS launchd 部署说明

## 1. 涉及文件

- `scripts/run_production_digest_launchd.sh`
- `scripts/generate_launchd_plist.py`
- `ops/launchd/bio-digest-daily.plist.template`
- `ops/launchd/bio-digest-daily.plist`
- `config/runtime/production.local.yaml`

其中：

- `plist.template` 是模板
- `generate_launchd_plist.py` 负责把运行配置渲染成真实 `plist`
- `plist` 是生成产物，供复制到 `~/Library/LaunchAgents/`
- 包装脚本只负责调用 `run_production_digest.py`
- 邮件、翻译、归档、审核目录等运行参数都来自 `config/runtime/production.local.yaml`

## 2. 当前生产链路

`launchd`
-> `scripts/run_production_digest_launchd.sh`
-> `scripts/run_production_digest.py`
-> `scripts/run_digest.py`

网页同步是可选 sidecar，不应默认阻塞 producer。

## 3. 安装前检查

```bash
cd /path/to/bio-literature-digest
test -f .env.local
test -f config/runtime/production.local.yaml
test -x .venv/bin/python3
chmod +x scripts/run_production_digest_launchd.sh
mkdir -p logs/launchd
mkdir -p ~/Library/LaunchAgents
```

## 4. 先生成 plist

```bash
.venv/bin/python3 scripts/generate_launchd_plist.py
```

如果你改了 `config/runtime/production.local.yaml` 里的 `delivery_time`、label、日志路径或 wrapper 路径，也要重新生成一次。

## 5. 复制并加载 plist

```bash
cp ops/launchd/bio-digest-daily.plist \
  ~/Library/LaunchAgents/org.example.bio-digest-daily.plist
chmod 644 ~/Library/LaunchAgents/org.example.bio-digest-daily.plist

plutil -lint ~/Library/LaunchAgents/org.example.bio-digest-daily.plist
zsh -n scripts/run_production_digest_launchd.sh

launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/org.example.bio-digest-daily.plist 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/org.example.bio-digest-daily.plist
launchctl enable "gui/$(id -u)/org.example.bio-digest-daily"
```

## 6. 手动触发验证

```bash
launchctl kickstart -k "gui/$(id -u)/org.example.bio-digest-daily"
launchctl print "gui/$(id -u)/org.example.bio-digest-daily"
tail -n 200 logs/launchd/bio-digest-daily.stdout.log
tail -n 200 logs/launchd/bio-digest-daily.stderr.log
```

校验本次产物：

```bash
cd /path/to/bio-literature-digest
.venv/bin/python3 scripts/validate_daily_artifacts.py --run-dir /path/to/work-dir
```

## 6. 第二层优化

第二层不通过 `launchd` 执行纯 Python 自动维护器。推荐由 Codex 执行：

1. `python3 scripts/refresh_review_backlog.py`
2. 读取 `reviews/backlog/review_backlog.xlsx`
3. 只消费 `reviewed_pending_optimization`
4. 写 `reviews/backlog/optimization_selection.json`
5. `python3 scripts/mark_review_backlog_optimized.py --selection-json reviews/backlog/optimization_selection.json`
6. `python3 scripts/finalize_review_backlog.py`

## 7. 维护命令

重新加载：

```bash
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/org.example.bio-digest-daily.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/org.example.bio-digest-daily.plist
launchctl enable "gui/$(id -u)/org.example.bio-digest-daily"
```

暂停：

```bash
launchctl disable "gui/$(id -u)/org.example.bio-digest-daily"
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/org.example.bio-digest-daily.plist
```

删除：

```bash
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/org.example.bio-digest-daily.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/org.example.bio-digest-daily.plist
```

## 8. 注意事项

- `launchd` 本身仍要求绝对路径，这是调度器限制，不是业务配置泄漏。
- 这些绝对路径现在由模板和 `config/runtime/production.local.yaml` 生成，不再需要手工编辑 `plist`。
- 如果你迁移项目目录，重新运行一次 `scripts/generate_launchd_plist.py` 即可。
- 如果以后迁移到 Windows，只需要替换调度层，Producer 和 backlog 契约可以保持不变。
