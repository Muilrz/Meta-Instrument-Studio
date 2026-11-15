# P2 Adapter 后续集成契约

- 日期：2026-11-15（Asia/Singapore）；P2-0C，基于 `0d4ca22`。
- 范围：薄接口与离线验证；不新增业务 Schema、BFF/UI 或 Trace 存储。
- 依据：[Agent 架构](../design/agent_architecture.md)、[ADR-0002](../adr/0002-agent-runtime-and-integration.md)。

## 本轮实现

`src/mis/adapters/task_bridge.py` 提供以下最小关联：

1. `ThreadBinding.task_id` 使用业务 `AgentTaskBrief.id`；运行仍使用 MIS run_id 和独立 DeerFlow run_id。
2. `start_task_run` 检查本地项目/任务范围并 GET 上游 Thread 验证 metadata，再发送本 Brief，去除 mutable usage/status/history；经 `start_run(context.agent_name=project-copilot, subagent_enabled=true)` 进入原生 Lead。
3. `TaskRunLink` 关联完整 RunBinding、Brief 内容 SHA-256、需求基线版本和 Specialist；接收结果时重新核验快照。Hash 不是授权或签名；调用方必须事先确认需求基线并授权 Brief/证据。
4. `receive_artifact` 使用 P1 `AgentArtifact` schema，要求调用方提供稳定 artifact/claim ID（拒绝自动生成），检查项目、Brief、MIS run_id、角色、分配需求范围、draft 状态。它仅返回未采纳候选，不写库、不执行硬约束判定，也不把 Runtime 候选摘要视作完整 Artifact。
5. `event_envelope` 输出 version=1 的项目/任务/run/type/source_event_id 关联，不把原始模型/工具消息或上游凭据送到产品。`stream.closed` 不代表成功；未知上游事件仍是 `runtime.event`，终态需 GET Run 对账。

`start_run` 新增命名 Agent profile 参数，限路径安全名称，仅传官方 `context.agent_name` 和显式布尔 `subagent_enabled`（启用时必须指定 profile）；不接受 Brief 中的工具权限、Sandbox 或任意 Runtime 配置。它不提供模型预算硬限制；真实调用必须安装服务端共享准入限制器。SDK 零重试不等于上游中间件零重试。

## 持久化准备与未完成项

本轮仅声明 `TaskRunLinkStore` Protocol，**没有持久 ID 映射实现**，也没有假设内存对象可以跨进程恢复。下阶段的 PostgreSQL 实现应满足：

| 契约 | 必要行为 |
|---|---|
| 唯一身份 | MIS `(project_id, run_id)` 与 upstream run identity 唯一，Thread 不跨项目/Brief复用 |
| 不可变插入 | 相同映射重放返回既有记录；同 ID 不同内容原子拒绝 |
| 命令意图 | HTTP 前持久保存幂等键、Brief Hash、配置版本和预算；超时只记 uncertain，查询对账后再决定，不能自动再扣费 |
| 崩溃窗口 | HTTP 成功但映射未落库需凭命令幂等键/metadata 对账；当前 helper 未解决该窗口 |
| 暂停恢复 | 持久保存 question_id、checkpoint/interrupt ID、answer Evidence、resume command key；先核验再恢复；独立于本轮 `TaskRunLink` |
| 安全 | 映射和事件不含 PAT、API Key、数据库连接地址；授权主体来自 MIS 服务身份，不信任模型提供 |

本轮不新增表。正式存储放在哪个 MIS 服务管理的运行关联表、迁移与清理策略，需要后续 P2 契约确认；不可把业务记录塞入上游 Checkpoint 当作唯一权威记录。

## Artifact 接收和事件验收范围

纯接收函数通过后，调用方仍须用 ProjectService 验证 Evidence 存在、项目范围、需求基线、候选指定参数完整性，再执行确定性单位/硬约束规则。若需保存，复用现有 `ProjectService.add` 的事务与同 ID 同内容重放语义；事务由调用方提交，方案采纳另走人工确认。当前未新增回调 HTTP 接口、自动写入或 exactly-once 保证。相同业务结果须使用稳定 artifact_id，不能在重放时重新生成 ID。

上游 source_event_id 可能不存在，不能直接作为永久 MIS 事件幂等键。正式事件契约还需确定 durable event_id、sequence/cursor、occurred_at、断线重放边界和 retention。不得因 SSE end、连接断开或中间 values 推断业务状态，Artifact 必须经过显式接收接口。

## 可重复验证

```powershell
uv run pytest tests/test_task_bridge.py tests/test_deerflow_adapter.py -q
```

本轮结果：42 passed。覆盖命名 Lead 路由、Brief 序列化/Hash、跨项目与任务错误在发送前拒绝、快照变化、角色/运行/需求范围错配、非 draft 产物拒绝，以及事件不泄露 raw payload、不把关闭事件当成功。均为 httpx MockTransport/纯函数测试，不代表 Gateway 上四 Agent 或 Artifact 写入已经验收。
