# 文档地图

所有文档都在 `docs/` 下。根目录只有项目入口 `README.md` 和 AI 会话入口 `CLAUDE.md` / `AGENTS.md`。

## 按用途查找

| 想知道 | 看哪份 | 状态 |
|---|---|---|
| 平台最终要做成什么样 | [architecture.md](architecture.md) | 目标架构，V4.0；已同步 DeerFlow / MIS 职责与独立部署 |
| 分几个阶段做、每阶段做什么、怎样算完成 | [plans/development_plan.md](plans/development_plan.md) | v0.2.9，待评审；新增 Context 原生复用与 DeerMem 无正式写入 Spike |
| 当前阶段（P2）具体怎么做 | [plans/P2_deerflow_integration.md](plans/P2_deerflow_integration.md) | 分支已创建，DeerFlow 集成尚未验证；依 ADR-0002 开始启动准备 |
| Agent 架构要满足哪些要求、已经做了哪些决定 | [design/agent_architecture_requirements.md](design/agent_architecture_requirements.md) | 持续更新；A1–A11、C1、C2 已确认；B1、B2 的实现绑定在 P2 验证定稿 |
| 技术栈、目录、数据库布局、部署 | [adr/0001-repo-structure-and-stack.md](adr/0001-repo-structure-and-stack.md) | 提议中，整体仍待评审；数据库与开发部署（Neon）、C1 Trace 存储与保留策略、C2 经验评分与生命周期存储规划已确认 |
| Runtime 选什么、哪些复用和自研、何时重新评估 | [adr/0002-agent-runtime-and-integration.md](adr/0002-agent-runtime-and-integration.md) | 已接受 DeerFlow + MIS 分层集成；DeerMem 复用接口与效果待 P2 验证 |
| Agent 内部模块、接口、数据流和执行机制 | [design/agent_architecture.md](design/agent_architecture.md) | 八章 V1 基线：Context Builder 轻量化，DeerMem 候选复用与审核隔离，P4/P5 继续治理细化 |
| 以前的阶段完成得怎样 | [reviews/](reviews/) | P0 已完成；P1 T1–T8 实现及自动验收完成、代码已合并 `main`，最终人工评审记录尚待核对 |
| 为什么选这些开源组件 | [research/MIS_Open_Source_Baseline_Research_2026-11-01.md](research/MIS_Open_Source_Baseline_Research_2026-11-01.md) | 2026-11-01 调研存档，只读；最终 Runtime 与集成决策以 ADR-0002 为准 |

## 目录约定

| 目录 | 放什么 | 命名 |
|---|---|---|
| `plans/` | 开发计划、各阶段任务说明 | `development_plan.md`、`Px_<主题>.md` |
| `design/` | 设计文档、需求清单 | 按主题命名 |
| `spike/` | 集成验证报告，阶段执行后生成 | P2 计划产出 `P2_deerflow_integration.md`（尚未生成） |
| `adr/` | 架构决策记录 | `NNNN-<主题>.md`，模板见 `0000-template.md` |
| `reviews/` | 阶段报告、审查记录 | `Px_report.md` |
| `research/` | 调研资料和证据，只读存档 | 带日期 |

## 维护规则

- 文件名不带版本号，版本和修订记录写在文件开头。
- 新增或移动文档时，同步更新本页和文档之间的链接。
- 已确认的决定写进需求清单或 ADR，不只留在聊天记录里。

- [ADR-0003 P1 单位与业务存储](adr/0003-p1-units-and-storage.md)：已接受。

- [业务 JSON Schema](schemas/)：由 Pydantic 导出，CI 检查与代码一致。

- [P1 阶段报告](reviews/P1_report.md)：区分实现、测试和整体验收；T1–T8 已实现，本地和 CI 均 126 passed（含静态审查加固），已合并 `main`；最终人工评审记录尚待核对。

- [P2 集成验证任务草案](plans/P2_deerflow_integration.md)：当前阶段任务说明，含原生 Context、DeerMem 候选能力验证；分支已创建，Spike 尚未执行。
