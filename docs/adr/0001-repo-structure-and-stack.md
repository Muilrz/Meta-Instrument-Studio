# ADR-0001 仓库结构与技术栈

- 状态：提议中（待评审）；数据库部分及 C1 Trace 存储与保留策略、C2 经验评分与生命周期存储规划已由负责人确认
- 日期：2026-11-05
- 修订：
  - 2026-11-08，落实已确认的 C1/C2：Trace 标准、采集与保留策略，以及 knowledge schema 的经验评分、使用事件、评分历史和生命周期存储；不改变本 ADR 整体待评审状态
  - 2026-11-05，数据库由“SQLite 起步、正式换 PostgreSQL”改为“从 P1 起统一使用 PostgreSQL”，并新增存储总览一节
  - 2026-11-06，存储总览第 5 项改为 trace 存储方案，新增第 9 项经验晋升池
  - 2026-11-06，开发数据库改为 Neon 云数据库（公司电脑不能安装 Docker）；新增“数据库布局”和“部署”两节；文档统一移到 `docs/` 下
- 决策人：待定
- 相关：开发计划 P0；待决策事项 D1、D3、D7、D8

## 背景

P0 需要确定代码放在哪里、用什么语言和工具，后续阶段才有统一的基础。
开发计划第 4 节的 D1、D3、D7、D8 需要在 P0 定下来。本 ADR 给出默认选择；评审时可以推翻其中任何一项。

约束：

- 调研报告推荐的候选组件（DeerFlow、LangGraph / Deep Agents、AgentScope、GPT Researcher、PaperQA、BOMi、Docling）都是 Python 生态。
- 现有子项目 SDK_Anlysis_Agent 是 Python / FastAPI；Rapid Optics Studio 是 TypeScript 浏览器应用。
- 开发机是 Windows，CI 用 Linux，二者都要能跑。

## 决定

### D1 技术栈

| 层 | 选择 | 引入阶段 |
|---|---|---|
| 后端 / Agent 层 | Python 3.12 | P0 |
| 依赖与环境管理 | uv（`pyproject.toml` + `uv.lock`） | P0 |
| lint / 格式化 | ruff | P0 |
| 测试 | pytest | P0 |
| CI | GitHub Actions | P0（推送到 GitHub 后生效） |
| 数据库 | PostgreSQL 17（带 pgvector 扩展），开发、测试、CI、正式环境都用它，不使用 SQLite | P1 |
| 开发数据库 | **Neon 云数据库**（新加坡），见下文“部署” | P1 |
| CI 数据库 | GitHub Actions 服务容器，`pgvector/pgvector:pg17` 镜像 | P1 |
| 前端 | TypeScript | P3（只读查看页面）、P5（正式界面） |

### 存储总览

平台所有需要存储的地方，原则上都放进**同一个 PostgreSQL 实例**，只在确有必要时才引入其他存储组件。

| # | 存什么 | 引入阶段 | 存在哪里 | 状态 |
|---|---|---|---|---|
| 1 | 业务记录：项目、需求、任务、产物、证据、方案、测试结果 | P1 | PostgreSQL，`mis` schema | **已确定** |
| 2 | Agent 运行状态：执行进度、断点续跑、对话消息 | P2/P3 | PostgreSQL，与业务记录分开的独立 schema；P2 选型时要求底座支持 PostgreSQL | 方向确定，具体实现随 P2 选型 |
| 3 | 统一知识库：实验室知识、经验记忆及共同检索的向量索引 | P4 | PostgreSQL `knowledge` schema + pgvector；包含经验晋升池、评分数据、MemoryUsageEvent、MemoryScoreHistory、生命周期和人工审核记录（见第 9 项）。连接器选型仍待 D5，不改变统一知识库存储边界 | 存储边界已确认（C2），连接器待 D5 决定 |
| 4 | 原始文件：PDF、网页快照、证据原文 | P4 | 本地文件夹，数据库中只存路径和哈希；需要多机共享时再换成 MinIO | 方向确定 |
| 5 | Trace（全链路调用记录）与预算记录 | P3 | PostgreSQL `trace` schema；OpenTelemetry Trace + GenAI Semantic Conventions；100% 采集关键业务 Span，不采样。Skeleton 与 Payload 分表，Hash 去重，以 content_ref 关联；骨架永久保留；完整内容：基准任务永久、人工确认的错误案例永久、普通运行 90 天。普通运行过期删除完整内容，保留骨架、Hash 和业务引用；后续可接 Langfuse | 存储与保留策略已确认（C1） |
| 6 | 外部调用缓存：报价、搜索结果 | P4 | PostgreSQL 表 | 方向确定 |
| 7 | 任务队列 | P3 | 优先用运行底座自带的机制；需要自建时用 PostgreSQL 实现 | 随 P2 选型 |
| 8 | 用户与登录 | P5 | PostgreSQL，与业务记录同库 | 方向确定 |
| 9 | 经验晋升池与评分管理：触发事件、候选经验、合并与冲突、人工审核、评分、使用事件、评分历史和生命周期记录 | P3 起逐步引入（P4 评分基础设施，P5 审核与管理界面，P7 测试反馈） | PostgreSQL `knowledge` schema，与第 3 项共享知识库存储；ExperienceMemory、MemoryUsageEvent、MemoryScoreHistory 及管理审计记录在此保存；Trace 详细执行数据在 `trace` schema，通过 trace_id / span_id 关联 | 晋升审核原则已确认（A2），评分与生命周期已确认（C2） |

约定：

- 第 1 项（业务记录）和第 2 项（运行状态）即使在同一个实例里，也放在**不同的 schema** 中，互相不做外键关联，满足原则 G1：清空运行状态不影响业务记录。
- 只用 PostgreSQL 自身和 pgvector 的功能，不引入其他扩展，便于以后换到托管数据库。
- 数据库软件本身免费。只有改用云厂商托管的数据库服务时才会产生费用，届时另行决策。

Trace 失败不会自动获得永久保留资格，须人工确认其为错误案例。Hash 去重清理不得删除仍被永久或未过期运行引用的 Payload；Trace 到期不删除业务 Evidence。完整内容写入前脱敏，详情见 [C1/C2 正式规范](../design/agent_architecture_requirements.md#4-已确认的补充架构决策)。

### 数据库布局（总体提议；C1/C2 相关存储边界已确认）

P1 的 T5 负责初始化 schema 与账号，不提前实现 Trace 或 C2 业务表；Trace 基础设施在 P3 实现，经验评分与生命周期基础设施在 P4 实现。

```text
PostgreSQL（开发环境是 Neon 项目，CI 是 Docker 容器）
├─ 数据库 mis（正式数据）
│   ├─ schema mis
│   │   └─ 业务记录                                      P1
│   ├─ schema runtime
│   │   └─ Agent 运行状态                                 P2/P3
│   ├─ schema trace
│   │   ├─ Trace Skeleton                               P3
│   │   └─ Trace Payload                                P3
│   ├─ schema knowledge
│   │   ├─ Lab Knowledge                                P4
│   │   ├─ Experience Memory（评分、生命周期、有效性）       P4
│   │   ├─ Promotion Pool（含人工审核与管理记录）            P3/P4/P5
│   │   ├─ Memory Usage Events                          P4
│   │   └─ Memory Score History                         P4
│   └─ schema cache
│       └─ 外部调用缓存                                   P4
└─ 测试库（结构相同，测试专用）：Neon 上用 test 分支，CI 中用 mis_test 数据库
```

账号与权限：

| 账号 | 权限 | 使用者 |
|---|---|---|
| `mis_admin` | 建 schema、启用扩展、执行迁移 | 初始化脚本、Alembic |
| `mis_app` | 读写 `mis`、`knowledge`、`cache`；读 `trace` | Project Service、查看页面 |
| `mis_runtime` | 读写 `runtime`、`trace`；`mis` 只读 | Agent 运行层 |

- Agent 运行层不能直接改业务记录，写入必须经过 Project Service（数据库层面保证原则 G1）。
- 初始化脚本是普通 SQL，可以对任何 PostgreSQL 执行（Neon、Docker、以后的服务器）：建 schema、建账号、启用 pgvector。
- Alembic 只管理 `mis`、`trace`、`knowledge`、`cache`，不碰 `runtime`（运行底座自己建表）。
- 备份：`mis`、`knowledge` 必须备份；`trace` 按保留策略；`runtime`、`cache` 不备份。

### 部署

| 环境 | 位置 | 状态 |
|---|---|---|
| 开发 | **Neon**：组织 Muil，项目 `meta-instrument-studio`，地区 AWS Asia Pacific (Singapore) | **已确定**，2026-11-06 起使用 |
| CI | GitHub Actions 服务容器（`pgvector/pgvector:pg17`） | 已确定，P1 的 T5 配置 |
| 多人使用（P5 起） | 实验室或公司服务器 / 云服务器 / 托管 PostgreSQL | 待定（开发计划 D10） |

选择 Neon 的原因：公司电脑不允许安装 WSL2 和 Docker；公司网络可以连接外部 PostgreSQL（5432 端口）；没有数据安全限制；基准任务包是合成资料。2026-11-06 的连接测试结果：

- PostgreSQL 17.11，pgvector 0.8.0 可用
- 能启用扩展、建 schema、建 JSONB 和向量列、做向量检索；当前账号可以建账号和建库
- 单次查询往返约 0.25 秒，开发够用；最终以 CI 的 Docker 环境为准
- 免费版：1 GB 存储、空闲自动休眠、每个项目最多 10 个分支（以 Neon 官网为准）

能安装 Docker 的开发者也可以在本地运行同一个镜像，只需修改 `.env` 中的连接地址，代码不变。连接地址带有密码，只放在 `.env` 中，不提交、不在聊天中传递。

### D7 仓库关系

MetaInstrumentStudio 平台单独成一个仓库。SDK_Anlysis_Agent、Rapid_Optics_Studio 保持各自独立的仓库，P6 通过适配器和导出格式对接，不合并代码。

### D3 基准任务包的资料来源

P0 的 Raman 基准任务包**全部使用合成资料**：器件、厂商、实验室文档和论文都是虚构的，并在文件中明确标注。原因：

- 合成资料没有版权和保密问题，可以放进仓库、进 CI。
- 每个检查点的正确答案由我们自己设计，可以确定无误。

真实资料（实验室文档、论文、真实器件页面）留到 P4 接入真实数据源时，另建一个任务包，不修改这一份。

### D8 协作方式

- 所有文档都放在 `docs/` 下，文档地图见 `docs/README.md`。
- 阶段计划和任务说明写在 `docs/plans/`。
- 阶段报告和审查意见写在 `docs/reviews/`。
- 架构决策写在 `docs/adr/`，设计文档写在 `docs/design/`。
- AI 会话（Claude Code、Codex 等）从根目录的 `CLAUDE.md` / `AGENTS.md` 开始，按其中的顺序读文档。
- 多个会话共用同一个文件夹时，提交只添加自己改过的文件，不用 `git add -A`。
- 每个阶段在自己的分支上开发，验收通过后由负责人合并。

### 目录结构

```text
MIS/
├─ README.md                  项目入口和快速上手
├─ CLAUDE.md / AGENTS.md      AI 会话的入口：先读什么、要守哪些规则
├─ pyproject.toml / uv.lock   依赖
├─ src/mis/                   平台代码（P1 起加入 schemas、project_service、adapters 等子包）
├─ tests/                     自动化测试
├─ fixtures/                  基准任务包，每个包独立带版本号
│  └─ raman_baseline/
├─ docs/
│  ├─ README.md               文档地图
│  ├─ architecture.md         目标架构
│  ├─ plans/                  开发计划、阶段任务说明
│  ├─ design/                 设计文档、需求清单
│  ├─ adr/                    架构决策记录
│  ├─ reviews/                阶段报告、审查记录
│  └─ research/               选型调研资料（只读存档）
└─ .github/workflows/         CI
```

根目录只放入口文件和工程配置，不放其他文档。子包按需要创建，不预先建空目录。

## 理由

- Python 和所有候选 Agent 组件、现有后端子项目一致，集成成本最低。
- uv 一条命令就能完成装依赖和跑测试，满足 P0 的“一条命令跑通”验收。
- 平台与子项目分仓库，可以避免 P0–P5 期间被子项目的发布节奏牵制；P6 再决定是否需要更紧密的整合。
- 从一开始就用 PostgreSQL，可以省掉以后从 SQLite 迁移的工作，也避免两种数据库在 JSON 处理和并发上的差异导致“测试通过、上线出错”。PostgreSQL 加上 pgvector，还能同时承担向量检索、运行状态、缓存等需求，整个平台起步时只需维护一个数据库服务。

## 后果

- 开发依赖网络访问 Neon；断网时无法运行数据库相关的测试。Neon 免费版有容量和分支数量限制，空闲时休眠，首次连接会慢几秒。
- 开发环境（Neon）和 CI（Docker）不是同一种部署，以 CI 结果为准；两边都只用 PostgreSQL 和 pgvector 的标准功能，避免差异。
- 前端在 P3 引入只读查看页面，引入前需要另写 ADR，确定框架和是否采用 monorepo 工具。
- 合成任务包只能检验流程和规则是否正确，不能检验真实资料下的效果，P4 必须补充真实任务包。
- 仓库已推送到 `https://github.com/Muilrz/Meta-Instrument-Studio`，CI 在每次推送时运行。
