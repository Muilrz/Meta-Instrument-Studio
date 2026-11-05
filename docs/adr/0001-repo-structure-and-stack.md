# ADR-0001 仓库结构与技术栈

- 状态：提议中（待评审）；数据库部分已由负责人确认
- 日期：2026-11-05
- 修订：2026-11-05，数据库由“SQLite 起步、正式换 PostgreSQL”改为“从 P1 起统一使用 PostgreSQL”，并新增存储总览一节
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
| 本地数据库服务 | Docker Desktop 运行 `pgvector/pgvector:pg17` 镜像 | P1 |
| 前端 | TypeScript | P3（只读查看页面）、P5（正式界面） |

### 存储总览

平台所有需要存储的地方，原则上都放进**同一个 PostgreSQL 实例**，只在确有必要时才引入其他存储组件。

| # | 存什么 | 引入阶段 | 存在哪里 | 状态 |
|---|---|---|---|---|
| 1 | 业务记录：项目、需求、任务、产物、证据、方案、测试结果 | P1 | PostgreSQL，`mis` schema | **已确定** |
| 2 | Agent 运行状态：执行进度、断点续跑、对话消息 | P2/P3 | PostgreSQL，与业务记录分开的独立 schema；P2 选型时要求底座支持 PostgreSQL | 方向确定，具体实现随 P2 选型 |
| 3 | 知识库向量索引 | P4 | 首选 PostgreSQL + pgvector；如果 P4 最终选择 RAGFlow，则使用它自带的存储 | 待 D5 决定 |
| 4 | 原始文件：PDF、网页快照、证据原文 | P4 | 本地文件夹，数据库中只存路径和哈希；需要多机共享时再换成 MinIO | 方向确定 |
| 5 | 调用日志与预算记录 | P3 | PostgreSQL 自建表；以后需要更强的可视化时再评估 Langfuse | 方向确定 |
| 6 | 外部调用缓存：报价、搜索结果 | P4 | PostgreSQL 表 | 方向确定 |
| 7 | 任务队列 | P3 | 优先用运行底座自带的机制；需要自建时用 PostgreSQL 实现 | 随 P2 选型 |
| 8 | 用户与登录 | P5 | PostgreSQL，与业务记录同库 | 方向确定 |

约定：

- 第 1 项（业务记录）和第 2 项（运行状态）即使在同一个实例里，也放在**不同的 schema** 中，互相不做外键关联，满足原则 G1：清空运行状态不影响业务记录。
- 只用 PostgreSQL 自身和 pgvector 的功能，不引入其他扩展，便于以后换到托管数据库。
- 数据库软件本身免费。只有改用云厂商托管的数据库服务时才会产生费用，届时另行决策。

### D7 仓库关系

MetaInstrumentStudio 平台单独成一个仓库。SDK_Anlysis_Agent、Rapid_Optics_Studio 保持各自独立的仓库，P6 通过适配器和导出格式对接，不合并代码。

### D3 基准任务包的资料来源

P0 的 Raman 基准任务包**全部使用合成资料**：器件、厂商、实验室文档和论文都是虚构的，并在文件中明确标注。原因：

- 合成资料没有版权和保密问题，可以放进仓库、进 CI。
- 每个检查点的正确答案由我们自己设计，可以确定无误。

真实资料（实验室文档、论文、真实器件页面）留到 P4 接入真实数据源时，另建一个任务包，不修改这一份。

### D8 协作方式

- 阶段计划和任务说明写在 `plans/`。
- 阶段报告和审查意见写在 `reviews/`。
- 架构决策写在 `docs/adr/`。
- 每个阶段在自己的分支上开发，验收通过后由负责人合并。

### 目录结构

```text
MIS/
├─ README.md                  项目入口和快速上手
├─ pyproject.toml / uv.lock   依赖
├─ src/mis/                   平台代码（P1 起加入 schemas、project_service、adapters 等子包）
├─ tests/                     自动化测试
├─ fixtures/                  基准任务包，每个包独立带版本号
│  └─ raman_baseline/
├─ plans/                     开发计划、阶段任务说明
├─ reviews/                   阶段报告、审查记录
├─ docs/adr/                  架构决策记录
├─ research/                  选型调研资料（只读存档）
└─ .github/workflows/         CI
```

子包按需要创建，不预先建空目录。

## 理由

- Python 和所有候选 Agent 组件、现有后端子项目一致，集成成本最低。
- uv 一条命令就能完成装依赖和跑测试，满足 P0 的“一条命令跑通”验收。
- 平台与子项目分仓库，可以避免 P0–P5 期间被子项目的发布节奏牵制；P6 再决定是否需要更紧密的整合。
- 从一开始就用 PostgreSQL，可以省掉以后从 SQLite 迁移的工作，也避免两种数据库在 JSON 处理和并发上的差异导致“测试通过、上线出错”。PostgreSQL 加上 pgvector，还能同时承担向量检索、运行状态、缓存等需求，整个平台起步时只需维护一个数据库服务。

## 后果

- 每位开发者的电脑上需要安装 Docker Desktop，才能在本地运行 PostgreSQL 和数据库相关的测试；CI 用 GitHub Actions 的服务容器运行同一个镜像。
- 前端在 P3 引入只读查看页面，引入前需要另写 ADR，确定框架和是否采用 monorepo 工具。
- 合成任务包只能检验流程和规则是否正确，不能检验真实资料下的效果，P4 必须补充真实任务包。
- 仓库已推送到 `https://github.com/Muilrz/Meta-Instrument-Studio`，CI 在每次推送时运行。
