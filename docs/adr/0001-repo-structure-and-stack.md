# ADR-0001 仓库结构与技术栈

- 状态：提议中（待评审）
- 日期：2026-11-05
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
| 数据库 | 原型用 SQLite，正式用 PostgreSQL | P1 |
| 前端 | TypeScript | P5 |

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

## 后果

- 前端在 P5 才引入，到时需要另写 ADR，确定框架和是否采用 monorepo 工具。
- 合成任务包只能检验流程和规则是否正确，不能检验真实资料下的效果，P4 必须补充真实任务包。
- 仓库目前没有推送到 GitHub，CI 文件在推送前不会运行；本地用 `uv run pytest` 和 `uv run ruff check .` 代替。
