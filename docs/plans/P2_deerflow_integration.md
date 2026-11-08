# P2 任务草案：DeerFlow 集成验证

- 状态：下一阶段草案，尚未开工
- 日期：2026-11-08
- 依据：[ADR-0002](../adr/0002-agent-runtime-and-integration.md)、[开发计划](development_plan.md)
- 本文仅满足阶段交接文档要求，不包含 P2 实现或已通过验证的声明。

## 启动前准备

P1 由负责人评审后，再登记以下启动条件；本草案不自行决定它们：

- Spike 时间盒与可运行 Docker 的 CI / 远程环境。
- 上游 release 对应完整 commit、依赖锁、镜像 digest、适配器和配置版本、许可证。
- 模型供应商、模型版本与调用预算。
- 独立 runtime 数据库权限与验证数据；不能改写 MIS 业务主数据。

## 任务顺序

1. 固定 DeerFlow Backend 版本，验证不依赖上游前端即可独立调用。
2. 建立 MIS Adapter 的 ID 映射、状态和事件契约，配置 Copilot 与三个 Specialist。
3. 以固定输入和模拟工具验证 Context Builder / Middleware、角色隔离及原生 Memory 禁用。
4. 候选 Artifact 经 P1 模型、Evidence 和规则校验后幂等写入 Project Service；验证重放、部分失败与预算。
5. 验证 PostgreSQL runtime Checkpoint、A4 用户提问、回答 Evidence、重启恢复与重复恢复防护。
6. 验证 Docker Sandbox 文件、网络、资源隔离及取消清理。
7. 最小 MIS REST / SSE 与 React 验证页；验证断流、重连及业务状态一致性。
8. 验证 C1 的适配路径、run_id / trace_id 关联和过程导出，补齐架构设计及 ADR-0002 验证记录。

## 验收与交付

- 门槛与复现项以开发计划 P2 和 ADR-0002 为准，不将选型当作验收。
- 交付 `docs/spike/P2_deerflow_integration.md`：版本、环境、接口映射、测试、结果、缺口。
- PostgreSQL 持久化、暂停恢复、结构化产物或 Sandbox 隔离失败时记录证据，按 ADR-0002 重新评估；不静默更换 Runtime。
- 正式 Trace 存储与 Viewer 留 P3，真实数据源与 C2 评分设施留 P4，正式 UI 与经验审核留 P5。
- P1 的业务对象、版本、证据、备份与规则始终独立于 Runtime。
