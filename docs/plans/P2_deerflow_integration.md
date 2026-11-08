# P2 任务草案：DeerFlow 集成验证

- 状态：当前 P2 阶段任务草案；开发分支已创建，集成验证尚未开工
- 日期：2026-11-08
- 更新：2026-11-08，增加 DeerFlow 原生 Context 验证、DeerMem 无正式库写入的候选抽取/去重 Spike 与回退决策
- 依据：[ADR-0002](../adr/0002-agent-runtime-and-integration.md)、[开发计划](development_plan.md)
- 本文用于 P2 启动与阶段交接，不包含 P2 实现或已通过验证的声明。

## 启动前准备

P1 的 T1–T8 已完成实现和自动验收，代码已合并 `main`；负责人最终人工评审记录仍需核对。进入 P2 Spike 前应确认此前置条件，再登记以下启动条件；本草案不自行决定它们：

- Spike 时间盒与可运行 Docker 的 CI / 远程环境。
- 上游 release 对应完整 commit、依赖锁、镜像 digest、适配器和配置版本、许可证。
- 模型供应商、模型版本与调用预算。
- 独立 runtime 数据库权限与验证数据；不能改写 MIS 业务主数据。

## 任务顺序

1. 固定 DeerFlow Backend 版本，验证不依赖上游前端即可独立调用。
2. 建立 MIS Adapter 的 ID 映射、状态和事件契约，配置 Copilot 与三个 Specialist。
3. 固定输入验证 DeerFlow 原生子 Agent 隔离、Summarization 和文件卸载，MIS Context Builder 仅组装业务 Brief；检验跨项目/角色隔离与压缩后硬约束/Evidence ID 保真。
4. 禁用/隔离默认 MemoryMiddleware 正式知识自动写入、读回与隐藏注入；使用临时候选区和固定样例验证 DeerMem 抽取、去重、可选整合能否独立复用，记录来源、错误合并、跨项目串记忆和回退成本。
5. 候选 Artifact 经 P1 模型、Evidence 和规则校验后幂等写入 Project Service；验证重放、部分失败与预算。
6. 验证 PostgreSQL runtime Checkpoint、A4 用户提问、回答 Evidence、重启恢复与重复恢复防护。
7. 验证 Docker Sandbox 文件、网络、资源隔离及取消清理。
8. 最小 MIS REST / SSE 与 React 验证页；验证断流、重连及业务状态一致性。
9. 验证 C1 的适配路径、run_id / trace_id 关联和过程导出，补齐架构设计及 ADR-0002 验证记录。

## 验收与交付

- 门槛与复现项以开发计划 P2 和 ADR-0002 为准，不将选型当作验收。DeerMem 可选能力不满足低侵入复用条件时输出回退方案，不直接等同于 Runtime 选型失败。
- 交付 `docs/spike/P2_deerflow_integration.md`：版本、环境、接口映射、测试、结果、缺口。
- PostgreSQL 持久化、暂停恢复、结构化产物或 Sandbox 隔离失败时记录证据，按 ADR-0002 重新评估；不静默更换 Runtime。
- 正式 Trace 存储与 Viewer 留 P3，真实数据源与 C2 评分设施留 P4，正式 UI 与经验审核留 P5。
- P1 的业务对象、版本、证据、备份与规则始终独立于 Runtime。
