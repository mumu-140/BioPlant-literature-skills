# Engineering Harness

## 目标

这个 harness 约束项目在长期迭代中保持三件事：

1. 重要信息只放在固定位置，不回流到脚本。
2. 新增、修改、删除文件时，目录职责不漂移。
3. 忽略本地配置和运行产物后，源码可以直接开源。

## 固定放置规则

### 0. 项目根位置

只允许在 `skills/` 目录下维护项目仓库。禁止把活动项目目录放在 `workspace/` 根层（例如 `workspace/bio-literature-digest`）。

### 1. 密钥与账号

只允许放在以下位置：

- `.env.local`
- `config/**/*.local.yaml`

禁止写入：

- `scripts/`
- `assets/`
- `docs/`
- `ops/`
- `tests/fixtures/`

### 2. 内容规则

只允许放在：

- `config/content/`

包括：

- 期刊/RSS 订阅源
- 分类规则
- 术语表
- 术语来源

### 3. 外部服务配置

只允许放在：

- `config/integrations/`

包括：

- 邮件 SMTP
- 邮件样式
- 翻译 provider
- 外部 LLM 复核

### 4. 运行时机器配置

只允许放在：

- `config/runtime/`

包括：

- 工作目录
- 归档目录
- backlog 目录
- review workspace 目录
- 时区
- 发送时间
- 默认 provider
- sidecar 开关
- scheduler 参数
- database 开关和 sqlite 路径

### 5. 脚本

只允许放在：

- `scripts/`

脚本内禁止写入：

- 真实邮箱
- 真实账号
- 真实域名
- 个人路径
- 机器专属 label

脚本应从：

- `project_layout.py`
- `config/runtime/*.yaml`

读取路径和默认参数。

### 6. 文档

只允许放在：

- `docs/`
- `README.md`
- `SKILL.md`

文档只写：

- `/path/to/...`
- `example.com`
- `org.example.*`

不要写真实用户路径、真实邮箱、真实域名。

### 7. 调度与运维

只允许放在：

- `ops/`

`launchd` 规则：

- 模板文件允许提交：`*.plist.template`
- 生成产物不允许提交：`*.plist`
- 真实 `plist` 必须由 `scripts/generate_launchd_plist.py` 从运行配置生成

### 8. 运行产物

不允许提交：

- `archives/`
- `reviews/`
- `logs/`
- `ops/launchd/*.plist`

## 修改工作流

当你要新增、修改、删除脚本或配置时，按这个顺序：

1. 先判断信息类型。
2. 把信息放进正确目录，不要先写进脚本再“后面再抽”。
3. 路径、默认 provider、调度参数统一从 `config/runtime/production.local.yaml` 或 `project_layout.py` 进入。
4. 新脚本如果需要固定文件位置，优先复用 `project_layout.py` 的 canonical paths。
5. 改完后优先运行：

```bash
.venv/bin/python3 scripts/check_project.py
```

如果只想单独排查某一层，也可以运行：

```bash
.venv/bin/python3 scripts/check_harness.py
.venv/bin/python3 scripts/check_alignment.py
```

6. 如果改动触及真实主链，再补对应测试。

## 文件放置清单

### 新增文件时

- 新增期刊、规则、术语：放 `config/content/`
- 新增 SMTP、翻译、外部接口：放 `config/integrations/`
- 新增路径、时区、调度参数：放 `config/runtime/`
- 新增生产/维护脚本：放 `scripts/`
- 新增运维模板：放 `ops/`
- 新增说明：放 `docs/`

### 删除文件时

- 先确认是否仍被 `project_layout.py`、脚本入口、文档引用
- 删除后必须重新跑 harness 和 alignment 检查

### 重命名文件时

- 同步更新：
  - `project_layout.py`
  - 入口脚本
  - 文档
  - 测试

## 自动检查项

`scripts/check_harness.py` 默认检查：

1. 目录职责是否被破坏
2. 是否残留 legacy `references` 旧结构
3. 非本地配置文件里是否出现真实邮箱
4. 非本地配置文件里是否出现个人路径
5. 是否出现个人化域名或 label
6. 是否把生成型 `plist` 放回源码目录
7. 是否把 provider/profile 名写死在脚本或文档里
8. 是否在脚本里直接写入应属于配置文件的信息

## 开源前清单

开源前必须确认：

1. `.env.local` 未提交
2. `config/**/*.local.yaml` 未提交
3. `archives/`、`reviews/`、`logs/` 未提交
4. `ops/launchd/*.plist` 未提交
5. 非本地配置与脚本中不存在真实邮箱
6. 非本地配置与脚本中不存在个人路径
7. 文档中不存在真实域名和真实机器信息
8. `scripts/check_harness.py` 返回成功
9. `scripts/check_alignment.py` 返回成功
10. `scripts/check_project.py` 返回成功

## 约束原则

- 重要信息放在固定位置，不放在脚本里。
- 脚本只表达流程，不保存身份。
- 本地配置可以存在，但必须可忽略。
- 忽略本地配置后，仓库应仍可公开、可读、可二次配置。
