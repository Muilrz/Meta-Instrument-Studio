# P2-0D Gateway A4 暂停与恢复

- 日期：2026-11-15（Asia/Singapore）。固定 DeerFlow v2.2.0 / `58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a`。
- 范围：原 Neon P2 / `mis_runtime` / `runtime`，官方 HTTP Run admission、PostgreSQL Checkpoint 和配置扩展；不改核心、Schema、权限或依赖，不调用模型与工具。
- 相关：[P2 Spike](P2_deerflow_integration.md)、[先前底层恢复](P2_checkpoint_recovery.md)、[Adapter 契约](P2_adapter_contracts.md)。

## 实现边界

`src/mis/adapters/a4_resume.py` 增加 `PauseBinding`、`resume_request` 和 `reconcile_a4_status`。
预检要求由可信存储加载的已回答 UserQuestion，以及对应的 user_decision Evidence：项目、原 MIS run、question ID、answer_evidence_id、用户 actor、答案文字、locator=question.id、page_or_anchor=answer 必须一致；当前 checkpoint 必须匹配已绑定暂停点，且只允许一个明确 pending node。错误答案、旧 checkpoint、其他节点/角色/Evidence 和非法 resume key 在 POST 前拒绝。

恢复是新的执行命令：`resume_run_id` 与暂停 MIS run 不同；metadata 的 `mis_run_id` 使用新命令 ID、`mis_parent_run_id` 使用原暂停 run。Question 与 Evidence 仍属于原 run，不能将新 upstream Run 覆盖旧映射。

此函数没有写入数据库、自动提交或授权能力。调用方须将恢复意图/幂等键持久化，串行化同一问题的竞争回答，并对网络超时做查询对账。当前接口与 C 的映射表尚未端到端接合。Gateway 的 full checkpoint selector 只验证该 checkpoint 存在，不是对最新 head 的 compare-and-swap，因此本次单线程测试不证明并发恢复 exactly-once。

## 确定性 Gateway 流程

`probes/a4_workflow.py` 通过官方 `extensions.middlewares` 装配；使用 `before_agent` / `abefore_agent` + `langgraph.interrupt`，恢复后以官方 `hook_config(can_jump_to=["end"])` 完成并返回固定结构化结果。使用真实 Lead 装配、原生 Gateway 路由/RunManager/Checkpoint，不替换 graph factory 或测试 registry。

这只是专用 Spike workflow，只接受 `mis-a4-probe-` Question；不冒充模型生成的 ask_clarification，也不能直接安装为正式业务 Lead。独立 `ZeroModelGuard` 在任何模型入口立即拒绝，配置没有真实模型凭据，后台 Memory 写入/注入、标题、建议、摘要、scheduler 全部禁用，所有工具、技能与 Sandbox 仍由 RBAC 拒绝。

控制器使用 MIS 环境；Gateway worker 使用原固定上游独立环境。原始配置不变，仅在仓库外拷贝配置中追加两项 middleware。原生 lifespan 检查已有 migration head `0048_extension_execution_leases`，未运行自定义 migrate/setup、未新增迁移或业务对象；原生 lifespan 的 bootstrap/setup 检查仍会执行，不将它描述为零 DDL 语句。

恢复前通过官方 register 建普通测试用户，用正常 CSRF session 签发一天的最小 PAT（threads:read/write、runs:create/read）；凭据只在进程内存中保存，最终撤销 PAT 并 logout。首次尝试内部 token 发 POST /threads 得到 403 CSRF，随后改用此正常认证路径，没有伪造 Bearer、关闭 CSRF 或更改角色。

## 实测发现与兼容绑定

原生动态 interrupt 后，Gateway Run 显示 **success**，但图的 `/state.next` 仍为 `A4Workflow.before_agent`。因此 `success` 只是该运行命令已结束；业务仍是 **waiting_user**。`reconcile_a4_status` 在已核验 Question 的 pending 状态存在时优先返回 waiting_user；缺少 checkpoint 证据时返回 unknown，不能把 Run success、SSE end 或 HTTP 200 当业务完成。

首次使用 SSE 给出的 interrupt ID 映射恢复失败：SSE 报告 ID `9e813fd3270354d8704013b1e2ce34e7`；运行结束后的 metadata-only duration checkpoint 创建新 head，恢复时同一节点产生了新 ID `d0d8137cd57691f91816fa81b6680a40`。旧 ID 映射未命中新 interrupt，图再次暂停，Run 仍 success，未进入任何模型。只读 PostgreSQL `PostgresSaver.get_tuple` 对照执行 checkpoint、duration checkpoint 的 pending writes，确认该现象；该调试读取不是产品恢复所需接口。

固定源码 `runtime/runs/worker.py::_persist_run_history_indexes` 复制 checkpoint、更新 marker/step 并 aput 新 head；pending writes 属于原执行 checkpoint，不能假设 SSE ID 在 duration 更新后仍是当前 cursor。`GET /state` 仅提供 task id/name，不提供 interrupt value/id，因此公开状态 API 也不能重新取得权威稳定 ID。

兼容方案使用官方 **标量 `Command(resume=response)`**，不使用 native interrupt ID → response 映射；response 携带 question/checkpoint/Evidence/resume key。SSE observed interrupt ID 只作审计，不能被描述为跨 duration 刷新的稳定权威标识。只支持一个已知 Question/一个 pending node，任意多 interrupt 图不在此接口范围。首次失败原始材料保留为仓库外 `gateway-a4-0d-first-mapped.json/.log`。

## 验证结果与剩余项

最终标量恢复实测 **PASS（Gateway 确定性流程）**，控制器 exit 0：

| 阶段 | 观察 |
|---|---|
| 初次暂停 | Thread `mis-a4-probe-ad42c1a2fa1b`，Run `6635b48b-d843-4514-8432-d1bdf2ec49f9` 的 native status=success，但 state.next=`A4Workflow.before_agent`，业务 waiting_user |
| 第一次重启 | checkpoint `1f1e0f99-6135-6515-bffe-e34275ce0964` 与 pending node 精确保留；3种错误回答/Checkpoint/审计ID在POST前拒绝，暂停head不变 |
| 恢复 | POST 原生标量 command.resume，产生新 Run `50c11c18-4d8e-4de6-b94e-ae2bbf0683e6`；status=success、next=[]、answer Evidence ID正确、completions=1 |
| 第二次重启/重放 | 同resume key、相同body POST返回相同Run ID；完成checkpoint仍为 `1f1e0f9d-62ef-6bc7-bffe-b21eb1886aaa`，completion内容不变 |
| 冲突 | 同resume key更改answer，HTTP **409**；没有新恢复执行 |
| 认证/关闭 | PAT最终撤销HTTP **200**，logout；三个worker均记录Application shutdown complete与Finished server process，控制器的三个退出码断言均为0 |

Windows venv launcher PID为23792/14580/32000，实际Uvicorn worker PID为12784/11732/34384，不能混同。pause/resume的llm_call_count、subagent_tokens、middleware_tokens均为0；未进入模型handler。Gateway日志仍有一次finalization CancelledError及两条pending cleanup task警告；这不改变已核实的暂停/恢复/重放状态，但不将此次重启当作完整后台清理或Sandbox取消验收。

仓库外 `mis-p2-gateway-evidence` 证据：

| 文件 | SHA-256 |
|---|---|
| gateway-a4-0d.json | `62440ff62750d326b78dda5747ec2853c4cdc821c3d50ff0ac23247f2fa6e587` |
| gateway-a4-0d.log | `a854d5dd7a881d937711209e25fd4c6705284ebec7d40b325640cfb74e208643` |
| gateway-a4-0d-first-mapped.json | `851d46e4202b420326b8c4f628bd2b592978b7e14f46db6e2dcf97c6291a9e87` |
| gateway-a4-0d-first-mapped-diagnostics.json | `b227df7e1f135733b776428e3c3dfb09febd39e696292bce1b47a0f38fa13f53` |

最终JSON保留pause/restored/final/replayed状态、原生HTTP响应、Question/Evidence内存fixture、命令metadata及PAT撤销结果；新增worker退出信息来自控制器成功断言和日志，不改变原HTTP响应。首次id映射失败证据另存，没有用后续成功覆盖。纯接口测试 `uv run pytest tests/test_a4_resume.py -q`：**26 passed**，包括错误答案、错配 Checkpoint/节点/Evidence、独立恢复命令身份、native success 与业务 waiting_user 分离，以及无 checkpoint 证据不得完成。

P2 分支专用 owner 凭据当前不可用，不能把 `mis_runtime` 提升为业务写入者。因此本次 Question/Evidence 是符合 P1 schema 和 answer_question 契约的授权内存 fixture，**没有写入 MIS 正式业务表**。实际 ProjectService.answer_question 持久 Evidence 与恢复命令 ledger 接合仍未验收；不将此项报告为完整业务 A4 验收通过。没有新增或修改任何 MIS Schema、没有正式经验库写入。

复现命令（没有真实模型费用；控制器读取现有 P2 runtime 连接，禁止把连接地址放入命令行）：

```powershell
.\.venv\Scripts\python.exe docs/spike/probes/gateway_a4.py
```

运行时会创建新的专用 Thread/普通测试用户、保留 runtime 审计，结束撤销 PAT。不会删除既有 Thread 或执行宿主机 Agent 工具。Docker/Sandbox 和火绒复核仍是独立未验收事项。
