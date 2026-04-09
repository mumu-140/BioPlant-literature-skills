# Ops Tools

这个目录放不属于主生产链路、但仍需要保留的运维工具。

- `download_imap_attachments.py`
  手工下载邮箱附件的辅助脚本。它不是主日报流水线的一部分，使用时必须显式传入 IMAP 主机、密码环境变量名、关键词和输出目录。
  推荐使用 `ops/tools/download_imap_attachments.py` 作为规范入口；`scripts/download_imap_attachments.py` 仅保留为兼容包装脚本。

这些工具可以保留薄包装入口，但不应在 README 的主入口里当作核心业务脚本介绍。
