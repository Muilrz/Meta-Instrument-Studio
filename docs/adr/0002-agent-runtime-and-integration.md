# ADR-0002 Agent Runtime 与 MIS 集成边界

- 状态：已接受（技术路线已确认；P2 集成验证尚未执行，不代表能力验收通过）
- 日期：2026-11-08
- 决策人：项目负责人
- 修订：2026-11-08，正式采用 DeerFlow Backend + MIS 自研 Web UI + MIS 自有业务后端，替代原 P2 多框架完整对比策略
- 修订：2026-11-08，明确原生 Context 复用及 DeerMem 候选抽取/去重/整合的受控复用路线；保留 MIS 权威数据、A2 人工晋升和 C2 经验治理
- 相关：[总体架构](../architecture.md)、[Agent 内部架构设计](../design/agent_architecture.md)、[需求清单](../design/agent_architecture_requirements.md)、[开发计划](../plans/development_plan.md)、[ADR-0001](0001-repo-structure-and-stack.md)

## 背景

MIS 需要 Supervisor–Specialist 执行能力，同时必须独立管理需求版本、证据、产物、方案、经验记忆和 Trace。用户确认的路线是独立部署 DeerFlow Backend，MIS 自研 React 前端和业务后端；框架不能成为业务事实或跨项目记忆的唯一存储。

A1–A8、C1、C2 和 G1–G6 继续生效。运行底座的默认行为必须适配 MIS 要求，不能反向改变业务数据契约、人工确认点或记忆治理规则。

## 候选与取舍

| 方案 | 取舍 |
|---|---|
| DeerFlow Backend + MIS UI / Backend | 采用；复用执行能力，通过 Adapter 隔离上游接口，业务资产和产品交互由 MIS 控制 |
| DeerFlow 全栈或 Fork 前端 | 不采用；仪器项目、证据链、版本、经验审核和评分页面由 MIS 统一设计，避免维护两套产品语义与前端升级分支 |
| LangGraph + Deep Agents 自建上层 | 保留为失败后的替代评估方向，本次不要求实现同等规模原型 |
| AgentScope | 保留为替代评估候选，本次不要求完整对比 |

以上是架构取舍，不是已完成的性能或兼容性评测。[历史调研](../research/MIS_Open_Source_Baseline_Research_2026-11-01.md) 保留原样；其中 Fork 应用、多方案比较等建议，由本 ADR 的当前决策覆盖。

## 决定

| 项目 | 决策 |
|---|---|
| Agent Runtime | DeerFlow |
| 集成方式 | 独立部署 DeerFlow Backend，由 MIS Backend 调用 |
| DeerFlow UI | 不使用，不 Fork DeerFlow Next.js 前端 |
| MIS Frontend | 完全自研 React + TypeScript |
| MIS Backend | 自建 BFF / Business API，负责权限和业务边界 |
| Agent 调度 | DeerFlow Lead Agent + SubAgents；分别承载 Project Copilot 与三个 Specialist |
| Context | DeerFlow 原生 SubAgent 隔离、Summarization、文件卸载和 Middleware；MIS Context Builder 仅轻量组装业务 Brief、权限、Evidence 和预算 |
| Memory | DeerFlow Checkpoint 负责工作记忆；DeerMem 抽取、去重、整合、检索作为**优先复用候选**，P2 验证能否独立、无正式库写入地使用；MIS 负责 Project Memory、跨项目知识、人工晋升及 C2 治理 |
| 自进化 | MIS Evolution Service，离线回归和人工批准后发布 |
| Tools | DeerFlow Tools / MCP + MIS Tool Gateway |
| Sandbox | DeerFlow Docker Sandbox，P2 验证文件、网络、资源隔离 |
| 业务存储 | MIS 独立管理 PostgreSQL + pgvector，沿用既有 schema 边界 |
| Runtime Checkpoint | 优先 PostgreSQL 独立 `runtime` schema，P2 验证兼容性；不能降级为生产 SQLite 或仅内存存储 |

### 复用与自研职责

- **DeerFlow**：Agent Runtime、Supervisor/SubAgent、通用 Context 能力、Skills、Tools、MCP、Sandbox、Checkpoint。通过配置、官方扩展接口和适配层使用这些能力。
- **MIS Backend**：Business API / BFF、Project Service、DeerFlow Adapter、Context Builder、Memory Service、Evolution Service、确定性规则与权限管理；负责业务写入、版本和证据引用校验。
- **MIS Frontend**：项目与会话工作空间、运行状态、人工提问、证据与产物查看、经验治理；只依赖 MIS API 与事件契约。
- **MIS Data Layer**：`mis` 保存业务记录，`knowledge` 保存知识与经验治理，`trace` 保存 C1 Skeleton / Payload，`runtime` 保存执行状态，`cache` 保存外部缓存。原始文件仍按 ADR-0001 由 MIS 管理文件和哈希引用。

Project Copilot 拥有需求拆解和方案汇总的业务责任，DeerFlow Lead Agent 提供执行载体。Task Orchestrator 是逻辑职责：MIS 提交依赖、预算、约束和接收条件，DeerFlow 执行并行、重试、暂停和恢复；不再建设一套并行的通用 Agent 调度引擎。

Specialist 不直接通信，返回结构化结果给 Copilot。运行层不能直接改写 `mis` / `knowledge` 业务主数据；调用 MIS 授权服务写入，数据库权限遵循 ADR-0001。

### Context 和 DeerMem 复用决策（2026-11-08）

- **Context 不重造通用引擎**：DeerFlow 负责子 Agent 隔离、运行历史摘要/压缩、文件卸载和 Checkpoint；MIS Context Builder 收敛为 Business Context Assembler，按 `project_id`、Agent 角色、已确认基线、Evidence、Brief 与预算选择业务片段。P2 验证摘要不丢硬约束和 Evidence ID。
- **三层 Memory 边界不变**：Working Memory 属于 Runtime；Project Memory 以 Project Service/`mis` 为事实权威；Lab Knowledge 和 Experience Memory 共同落在 MIS `knowledge`，经作用域和审核状态过滤。DeerMem 的默认文件/SQLite 索引不成为正式项目事实或经验的第二份权威数据。
- **复用算法、控制写入**：优先研究 DeerMem 已有事实提取、摘要、候选近重复检测、可选整合及相关检索能力，通过公开接口或薄 Adapter 输出 **ExperienceCandidate**；P2 必须核实具体版本中是否可脱离其自动持久化独立调用，不能假定组件直接提供稳定公共 API。无法低侵入复用时使用轻量候选提取/关系判定实现，不为追求复用侵入核心 Runtime。
- **阻断未经审核的自动长期记忆**：DeerFlow 原生 MemoryMiddleware 对正式长期知识的自动写入、默认读回和隐藏上下文注入必须禁用/隔离；这不等于弃用其提取/去重算法。MIS 只允许 A2 业务事件产生候选，候选进入 Promotion Pool；去重/整合均保留来源、证据、项目作用域和候选版本，冲突不自动覆盖；人工审核通过后才能成为正式 ExperienceMemory。
- **不替换 C2**：DeerMem 内置的 staleness、自动合并、事实删除不能覆盖 MIS 已确认的评分、有效性、生命周期和人工管理；正式经验变更仍需版本化和必要的重新审核。
- **验证与分阶段实施**：P2 在临时存储中用固定样本做抽取/去重/可选整合 Spike（含误合并、跨项目泄漏、来源丢失与回退成本）；P3 用 A2 前四类事件触发候选提取，P4 落地关系判断和持久化，P5 人工审核并开放经验检索。DeerMem 的可选功能复用不成功需记载回退，并不自动意味着 DeerFlow Agent Runtime 验收失败。

### 集成与版本策略

1. 前端只调用 MIS Backend / BFF，不能直连 DeerFlow Gateway 或使用上游 Thread / Run / SSE 格式作为产品契约。
2. DeerFlow Adapter 封装 Gateway 调用、ID 映射、事件转换、暂停恢复、错误归一化与结构化产物接收；Gateway 到 Harness 是 DeerFlow Backend 内部逻辑，不要求拆成两个独立部署服务。
3. MIS Context Builder 仅选择授权业务片段、Brief、审核后记忆引用和预算约束；DeerFlow Middleware 处理运行期隔离、摘要和文件卸载。不另建通用 Context Engine，不得绕过 MIS 的隔离与来源规则。
4. 不直接修改 DeerFlow 核心执行引擎，优先官方扩展接口。无法满足关键要求时先启动重新评估，不默认通过侵入式补丁或长期 Fork 解决。
5. 必须锁定上游 release 对应的完整 commit；没有 release 时锁定完整 commit。P2 开始前登记 commit、依赖锁、镜像 digest、配置与适配器版本及许可证核查结果；禁止使用浮动 main / latest 作为可复现基线。
6. 本次没有指定已验收版本，不虚构 commit 或兼容性结论。P2 报告必须补齐上述版本信息和复现命令；升级必须重跑集成契约与 Raman 回归并保留回滚版本。

## 理由与证据边界

DeerFlow 官方资料描述了 Lead Agent、Subagent、Middleware、Tools / MCP、Skills、Sandbox 和 Gateway 能力，适合作为复用执行层的起点。MIS 自研 UI 与 Backend 则保持仪器业务契约、记忆治理和运行底座解耦。

参考：[官方仓库与许可证](https://github.com/bytedance/deer-flow)、[官方 Backend 架构说明](https://github.com/bytedance/deer-flow/blob/main/backend/README.md)（查阅日期：2026-11-08；链接为上游可变分支，仅用于能力背景，P2 必须改用被锁定 commit 的证据）。官方能力说明不等于 MIS 的 PostgreSQL、隔离、暂停恢复或结构化产物要求已通过验证。

## P2 集成验证与采用门槛

P2 改为 DeerFlow Integration Spike，不再要求至少两个框架完成全量比较。以固定 Raman 材料与模拟工具验证：

- Backend 无需 DeerFlow 前端即可独立被 MIS 调用；Lead Agent + 三个 Specialist 可配置并执行。
- 轻量 Context Builder 与 Specialist 隔离；默认 MemoryMiddleware 对正式库的自动写入/读回和隐藏注入隔离；另在非正式候选存储上验证 DeerMem 提取、去重、整合能否低侵入复用。
- 结构化 AgentArtifact 经 MIS 校验后幂等写入 Project Service；异常、重复回调和部分失败不会丢失或重复业务记录。
- MIS REST / SSE 契约和 React 最小接入；A4 提问、持久暂停、进程重启后的回答与恢复。
- PostgreSQL Checkpoint 在独立 schema 中恢复运行，不将运行状态变成业务主数据。
- Docker Sandbox 文件、网络、资源隔离和失败清理；隔离需求以实测为准。
- C1 关键 Span、MIS run_id / OpenTelemetry trace_id 关联和导出能力，可通过适配器实现；正式 Trace 存储与 Viewer 在 P3 实现。

产出计划中的 `docs/spike/P2_deerflow_integration.md`，逐项记录版本、配置、测试、结果和缺口，并更新本 ADR 的验证记录。该报告尚未生成，不能视作完成证明。

## 后果与重新评估条件

采用独立运行服务会增加部署、版本协调、事件映射和故障恢复工作；MIS 同时承担自研产品 UI、业务后端、Context、Memory 和 Evolution 的维护成本。

以下任一关键要求不能在约定时间盒内通过配置、官方扩展或 Adapter 满足，即触发 Runtime 重新评估：PostgreSQL 持久化、暂停恢复、结构化产物、Sandbox 隔离。上下文隔离、阻断未经审核的自动长期记忆写入/隐藏注入或必要观测边界无法满足时，同样不得带缺陷进入 P3；DeerMem 候选抽取/去重无法安全复用时采用已记录的轻量回退方案，不单独触发 Runtime 重新选型。

验证失败时记录证据和失败原因，再按相同业务契约评估 LangGraph + Deep Agents、AgentScope 等替代方案。替代 Runtime 的采纳须负责人确认并修订本 ADR，不静默切换。路线已确认与实现验收通过是两件事；进入 P3 必须有验证通过记录。

本 ADR 明确前端采用 React + TypeScript，覆盖 ADR-0001 中“前端框架尚待后续 ADR 决定”的未决部分；不改变 ADR-0001 整体待评审状态，也不提前决定 monorepo 工具。
