# 文档地图

所有文档都在 `docs/` 下。根目录只有项目入口 `README.md` 和 AI 会话入口 `CLAUDE.md` / `AGENTS.md`。

## 按用途查找

| 想知道 | 看哪份 | 状态 |
|---|---|---|
| 平台最终要做成什么样 | [architecture.md](architecture.md) | 目标架构，V4.0 |
| 分几个阶段做、每阶段做什么、怎样算完成 | [plans/development_plan.md](plans/development_plan.md) | v0.2.6，待评审；已同步 C1/C2 的分阶段安排 |
| 当前阶段（P1）具体怎么做 | [plans/P1_data_contracts.md](plans/P1_data_contracts.md) | 草案，Q1–Q4 待确认 |
| Agent 架构要满足哪些要求、已经做了哪些决定 | [design/agent_architecture_requirements.md](design/agent_architecture_requirements.md) | 持续更新；A1–A8、C1、C2 已确认；B1、B2 仍待细化 |
| 技术栈、目录、数据库布局、部署 | [adr/0001-repo-structure-and-stack.md](adr/0001-repo-structure-and-stack.md) | 提议中，整体仍待评审；数据库与开发部署（Neon）、C1 Trace 存储与保留策略、C2 经验评分与生命周期存储规划已确认 |
| 以前的阶段完成得怎样 | [reviews/](reviews/) | P0 已完成 |
| 为什么选这些开源组件 | [research/MIS_Open_Source_Baseline_Research_2026-11-01.md](research/MIS_Open_Source_Baseline_Research_2026-11-01.md) | 2026-11-01 调研存档，只读 |

## 目录约定

| 目录 | 放什么 | 命名 |
|---|---|---|
| `plans/` | 开发计划、各阶段任务说明 | `development_plan.md`、`Px_<主题>.md` |
| `design/` | 设计文档、需求清单 | 按主题命名 |
| `adr/` | 架构决策记录 | `NNNN-<主题>.md`，模板见 `0000-template.md` |
| `reviews/` | 阶段报告、审查记录 | `Px_report.md` |
| `research/` | 调研资料和证据，只读存档 | 带日期 |

## 维护规则

- 文件名不带版本号，版本和修订记录写在文件开头。
- 新增或移动文档时，同步更新本页和文档之间的链接。
- 已确认的决定写进需求清单或 ADR，不只留在聊天记录里。
