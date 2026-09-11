# Producer Agent Guide — 生产端专用守则与入口

> **适用范围**：本文件专门适用于文献生产端 `bio-literature-digest`。
> 单独在本工程工作时，请首先阅读本手册；全局架构、数据所有权及运维规范请参见父级总控文档：
> - 🌐 **总控全局地图**：[`../AGENTS.md`](../AGENTS.md)
> - 📐 **系统架构与数据所有权**：[`../ARCHITECTURE.md`](../ARCHITECTURE.md)
> - 🛡️ **安全操作守则**：[`../docs/operations/SAFETY.md`](../docs/operations/SAFETY.md)
> - 🚀 **vps219 验证手册**：[`../docs/operations/DEPLOYMENT.md`](../docs/operations/DEPLOYMENT.md)

---

## 一、 核心定位与职责

本工程是整个 Literature Intelligence 体系的 **Source of Record（事实记录唯一源头）**。
核心职责涵盖：
1. **多源数据采集**：自动化监控 CNS、eLife、bioRxiv 等主流学术期刊 RSS 订阅流；
2. **元数据归一化**：提取并清洗 DOI、PMID、arXiv ID、Canonical URL 等关键唯一标识；
3. **AI 推理与处理**：调用 LLM 进行研究方向多标签分类、专业翻译、结构化要点提取与相关性打分；
4. **日度 Digest 归档与分发**：生成日度 Markdown、HTML 报告、CSV 清单，向订阅用户推送邮件，维护生产归档。

---

## 二、 日常维护不变量 (Invariants)

任何日常缺陷修复或功能扩展，必须严格捍卫以下不变量：

1. **【全局第一红线】本地绝对不跑构建与安装**：
   - 本机（Mac）绝不运行 `pip install`、依赖编译或离线抓取全量任务；所有依赖环境与流水线检查在远端 `vps219` 执行。
2. **数据独占性与单向边界**：
   - Producer-owned 数据（原始文献、LLM结果、日度归档）**只允许由 Producer 本身写入**；
   - **绝对禁止为下游 Web 消费端开辟任何数据库回写链路**。
3. **抓取与去重幂等性**：
   - 抓取去重、失败重试或重新跑批，**绝不允许生成重复 Article、重复流水线记录或重复发送邮件轰炸用户**。
4. **AI 产物真实性与可追溯性**：
   - 修改 AI 提示词或提取逻辑时，保留完整的执行日志与版本 Provenance；严禁用硬编码人工假值替换机器输出。
5. **Contract 契约兼容性**：
   - 导出字段、Article 身份识别或日度归档格式发生变动时，必须审查下游 `bio-literature-digest-web` 的消费端逻辑，保持向下兼容过渡；
   - 跨仓库文献匹配严格遵循 6 级身份阶梯（DOI → PMID → arXiv → Canonical URL → Stable ID → Fallback）。
6. **数据库 Schema 演进**：
   - 字段变动必须使用 Migration 脚本，遵循“向下兼容 → 双写/迁移 → 验证 → 删除”四部曲，禁止直接修改生产列名。
7. **日常维护严禁越级重构**：
   - 不得因为外部通用建议或重构计划提及某框架，就在日常小修中擅自推翻当前成熟稳定的 Python 管道。

---

## 三、 修改前检查清单 (Pre-flight Checklist)

在对代码进行任何修改前，必须完成以下确认：

- [ ] 准确定位本次修改的入库点、调用链路、数据库写操作以及 Cron / 定时调度任务；
- [ ] 涉及文献同步逻辑时，确认 Article 身份判定阶梯与失败重试的幂等机制；
- [ ] 涉及邮件推送时，确认候选文章过滤查询、发送去重标志与错误状态记录；
- [ ] 涉及数据库物理变更时，遵循 [`SAFETY.md`](../docs/operations/SAFETY.md) 确认备份与回滚预案。

---

## 四、 提交流程与远端 vps219 验证

本地只负责编辑代码与审查 Git Diff。完成代码修改后按以下规程闭环：

### 1. 本地代码提交与推送
```bash
git status --short
git add <目标修改文件>
git commit -m "feat(producer): <改动说明>"
git push origin main
```

### 2. 远端 vps219 验证与运行确认
登录生产主机 `vps219`，按 [`DEPLOYMENT.md`](../docs/operations/DEPLOYMENT.md) 执行快进拉取并运行测试：
```bash
ssh vps219
cd /root/software/bio-literature-digest
git status --short --branch
git pull --ff-only origin main

# 执行既有测试套件验证
python3 -m unittest discover -s tests
```

> **铁律**：Producer 的 Worker/Scheduler 及测试命令必须从该工程既有文档与脚本中明确读取，严禁凭臆测发明命令。
