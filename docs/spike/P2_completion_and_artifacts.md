# P2 执行完整性与候选 Artifact 接收

- 范围：P2-0E，基于 `a07dea9`；不变更 P1 Schema、迁移或上游核心。
- 固定 DeerFlow：`58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a`。
- 持久映射、Checkpoint 和 A4 沿用已通过结果，本轮没有重做其 Smoke。

## 完整性与原生执行边界

上轮实际问题是 Lead 在 Lab 返回后提前汇总，Research、Procurement 没有派发；不是本轮可证明的 provider 故障。Prompt 中“并行执行三个角色”不能构成验收条件。

`completion.py` 校验受信 MIS 生成的三个独立 TaskBrief：角色各一份、ID 不同、同项目和需求基线、每角色只分配一次模型调用，Evidence 属于相同项目。固定任务的 `completion_policy.py` 只处理 JSON，Runtime 无需安装 MIS 的业务数据库或单位依赖。

`native_completion.py::RequiredSpecialistsMiddleware` 使用固定版官方 AgentMiddleware 的 after_model / jump_to 扩展点：

1. 把 Lead 的合法原生 task 参数规范化为该角色的授权 Brief/Evidence，拒绝角色外工具、重复派发、历史快照上下文和模型覆盖。
2. 普通分批派发不干预。Lead 无 task 调用并提前结束、仍有从未派发的必需角色时，最多补入**一批**确定性的原生 task 调用，再交回原生 ToolNode / task / SubagentExecutor。
3. 已派发、失败或取消的角色不重新执行。安全拒绝、输出截断及 DeerFlow 错误 fallback 不触发补派。
4. 补派记录 `mis_required_brief` 来源、稳定 call ID、原始响应 SHA256；模型原始输出另由 Guard 保存。不会把 MIS 补派伪称为模型主动调用。
5. Specialist 子图没有父级 manifest，中间件对它们不生效。没有新增线程池、Agent 调度器、模型执行器或通用重试引擎。

| 业务执行状态 | 确定性条件 |
|---|---|
| completed | 三角色均有可信原生 task 调用和 completed 结果，并且 Lead 的最终 JSON 含三个角色的非空汇总 |
| missing | 无成功结果，至少角色尚未派发/结果未到；native_statuses 继续保留 pending/unknown |
| failed | 无成功结果且存在原生失败/取消/超时 |
| partial | 已有至少一个成功结果，但角色缺失/失败或 Lead 没有完整汇总 |

Runtime Run 的 success、Lead 自述 completed、SSE end 都不等于这个业务 completed。候选接收还需独立校验，三个执行成功也不自动通过业务验收。

## 有界调用与离线证据

三个子任务各一次。Lead 一批派发需 `1+3+1=5` 次；逐个分派最多 `3+3+1=7` 次。提前汇总后的单批补派也在同一 **7 次**共享上限内，例如 Lab → 提前汇总 → 补 Research/Procurement → 最终汇总共 6 次。达到上限仍拒绝，不为汇总增加第八次。

`p2e_budget_limits.py` 固定每次序列化输入至多 90000 字节、另预留 8192 输入 Token，每次输出至多 1024；SDK retries=0，DeerFlow attempts=1。每次任务最坏费用预留为 **0.0723184 USD**，以旧保守占用 **0.0535860** 入场，总上界 **0.1259044 / 10 USD**。旧缺失 usage 不核销，不按零计费。

`verify_multi_agent.py` 通过官方 Responses SDK + MockTransport 走完整原生图，无外部请求：

- 正常 fixture 故意只派 Lab 并提前汇总：一批补调度、6 次请求、三个原生结果和完整 Lead 汇总，PASS。
- Research / Procurement 的 Barrier 和 handler 时间区间证明至少两者实际执行重叠；各自只收到自己的 CANARY、Brief 和 Evidence。
- `P2E_OFFLINE_FAILURE=research` 注入 HTTP 503：6 次准入，Research failed，其余 completed，整体 partial；没有重试或伪造成功。
- Lead 只有 task，Specialist tools=[]；Sandbox 获取函数设为必失败陷阱，执行策略探针仍通过。Memory、标题、建议、摘要、scheduler 等后台模型功能关闭。

离线复现（工作目录为 MIS 仓库）：

```powershell
..\deer-flow-p2-0a-filtered\backend\.venv\Scripts\python.exe docs\spike\verify_multi_agent.py
$env:P2E_OFFLINE_FAILURE='research'
..\deer-flow-p2-0a-filtered\backend\.venv\Scripts\python.exe docs\spike\verify_multi_agent.py
Remove-Item Env:P2E_OFFLINE_FAILURE
```

这些原生探针不计入常规 pytest 数量，也不当作真实模型通过。成功路径仅在 configurable 提供 thread_id，没有 Gateway 注入的 runtime.context.thread_id，不能证明 Gateway 的物理技能投影路径可无 Sandbox 运行。追加 `P2E_PROJECTION_DENIED=1` 的离线负向探针：在 Runtime context 提供 thread_id，并以固定占位投影替代文件投影构建，原生 before_agent 正确抛 SandboxAuthorizationError，0 次模型准入。它验证拒绝路径，不宣称重做了真实投影存储。

## Artifact 业务接收

`artifact_receiver.py::receive_bundle` 是 MIS 服务内接收边界。调用方先授权项目、加载持久命令并获取经核验的 Runtime 状态，不能接收任意用户/模型伪造的回调消息。

- 一个协调 Run 对应一条真实 Thread/Run 映射；子 Brief 清单由持久命令的完整 request_sha256 绑定，task call ID 关联各原生结果。没有为三个子任务伪造 Gateway Run，或重复占用同一 upstream Run。
- 重新核验项目、当前需求基线、不可变 Brief/Evidence 快照、原生 task receipt ID/name/success、角色与 task_id，以及仅限本角色的 Evidence 引用。
- 复用现有 AgentArtifact 候选校验与 ProjectService。Schema、指定参数、单位维度、硬约束通过才保存 draft，未通过为明确 gap；每角色 savepoint 防止失败污染其他有效结果。
- 固定结构化 Evidence 的数值还要与被引用的原始事实一致，支持单位换算。非结构化文本目前只核验引用和范围，**不宣称完成语义事实审查**。
- artifact_id 从 MIS run_id + Brief ID 稳定生成，claim ID 由服务生成。同内容重放幂等，同 ID 不同内容拒绝，不覆盖已有记录。
- 执行 completed 且三角色都 stored_draft 才标记本批接收 completed；部分有效结果仍可分别保存，但总批为 partial。adoption 始终 unreviewed。
- 没有自动采纳 InstrumentPlan，没有写入正式经验库，没有新增表、权限或 BFF/UI。

两项数据库测试同时覆盖缺失角色、部分写入、重复事件/写入、后续完整结果、冲突拒绝、错误单位、错任务和角色越权 Evidence、无来源支持的数值、硬约束未知，以及 InstrumentPlan 始终未创建。事务和数据库由既有 P1 独立测试 fixture 管理。

所有样例都是合成的 500 mW 固定事实与 450 mW 硬约束，用于验证契约；不代表真实实验室能力、科研结论或供应商承诺。

## 真实验证与检查

最终实际结果、费用、回归与 CI 数量统一登记在 [P2 主报告第23节](P2_deerflow_integration.md#23-p2-0e执行完整性与候选业务接收)。本文件的离线 PASS 不替代那里的真实验收状态。

真实 runner `gateway_multi_agent.py` 使用官方管理 API 安装配置，Thread/Run 使用独立受限 PAT；进程共享 Guard 和仓库外 exclusive-create 证据文件防止自动重跑。Agent 管理接口为部署方显式启用的官方 `agents_api.enabled`，不赋予 Lead 修改配置的工具。业务数据通过 owner 连接后每事务 SET LOCAL ROLE mis_app；Gateway 始终使用 mis_runtime，无 DDL 或增权。

Sandbox / Docker 仍 BLOCKED，火绒告警复核未完成。接下来仍须验证压缩/卸载保真、正式事件重连边界、DeerMem 候选复用和多进程预算治理；不合并 main，不进入 P3。
