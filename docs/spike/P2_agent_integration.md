# P2-0C Project Copilot / Specialist 原生集成

日期：2026-11-15。固定 DeerFlow v2.2.0 commit
`58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a`，不修改上游源码。

## 配置和绑定

`src/mis/agents/profiles.py` 提供配置数据生成器，不实现调度器、不自动安装到 Gateway。
`deerflow_profiles()` 返回三个可独立审查的部分：

| 部分 | 官方绑定 | 最小权限 |
|---|---|---|
| lead_config | AgentConfig / operator-selected Agent store，name=project-copilot | allowed_subagents=[lab,research,procurement]，skills=[]，mcp_plugins=[]，tool_groups=[]，memory_enabled=false |
| lead_soul | 同一 Agent store 的 SOUL.md | 拆分 Brief、isolated 下发、结果摘要汇总、未知和人工接收边界 |
| deployment | AppConfig.subagents.custom_agents | Lab / Research / Procurement 各 tools=[]、skills=[]、disallowed_tools 含 task，max_turns=1，timeout_seconds=30 |

启动调用还须显式 `context.agent_name=project-copilot`、`context.subagent_enabled=true`；
默认关闭 delegation。lead 的空 tool_groups 并不能单独禁用原生内置工具，因此 Probe 同时配置
RBAC 只允许 task，Sandbox/Skills 全拒绝，装配后断言实际工具仅 task。三 Specialist 的空工具
白名单由原生 Executor 进一步收窄；不是只写在 Prompt 里。

部署人员将 deployment 合入同一固定配置，将 lead_config/lead_soul 经官方 Agent store 安装，
保留原 PostgreSQL、认证、授权与预算配置，再由 MIS Adapter 调用。此次只在临时文件 Agent
store 和内存运行状态的独立 Harness 进程装配；**未将四角色持久安装到现有 Gateway**，不代表
Neon 中已保存这份配置。内存后端仅用于离线/受控模型编排 Probe，不是生产 Checkpoint 回退。

原生源码绑定：`config/agents_config.py` 的 AgentConfig/allowed_subagents；
`config/subagents_config.py` 的 custom_agents；`subagents/registry.py` 的角色查找；
`tools/builtins/task_tool.py` 的路由/isolated/snapshot/权限传播；
`subagents/executor.py` 的独立初始状态、tools 过滤、模型循环、结果与容量管理。
Lead 生成多个 task calls 后，由原生 LangGraph ToolNode 和 DeerFlow capacity 执行并行。
MIS 不增加第二套线程池、通用执行引擎或 Specialist 互通通道。

## 可重复离线验证

在固定上游的 backend 目录，使用已装好的环境执行（不自动升级依赖）：

```powershell
.\.venv\Scripts\python.exe C:/Users/Muil/Desktop/MIS_workspace/Meta-Instrument-Studio/docs/spike/verify_native_agents.py
.\.venv\Scripts\python.exe C:/Users/Muil/Desktop/MIS_workspace/Meta-Instrument-Studio/docs/spike/verify_agent_guard.py
.\.venv\Scripts\python.exe C:/Users/Muil/Desktop/MIS_workspace/Meta-Instrument-Studio/docs/spike/verify_native_agents.py --http-mock
```

结果 PASS：真实 assemble_lead_agent → native task_tool → 三个原生 SubagentExecutor →
完整 runtime middleware → Lead 汇总，仅模型创建边界替换为确定性 MockModel。
三 Specialist 到同一 barrier 后才允许返回，时间区间重叠，证明三者实际并发，不是按返回顺序
推断。各模型输入只出现自身 CANARY-role，无其他角色 canary；Lead 接收全部三个候选摘要。
额外原生 task_tool 检查：allowed_subagents=[] 时 lab 拒绝，bash 在宿主执行策略下拒绝，
不存在的角色拒绝。模型返回纯文本 block（含 Responses phase）也通过。

`--http-mock` 第二层离线验证也 PASS：使用官方 ChatOpenAI / AsyncOpenAI / Responses
请求和响应解析，由公开 http_async_client 参数注入 httpx.MockTransport，HTTP 在建连前被
拦截；5 个真实 SDK 请求、0 个外网请求，三个子任务 barrier 并行、canary 隔离、Lead 汇总
均通过。该测试关闭 SDK streaming，仅验证完整非流式 Responses 路径，不证明线上网络及
缓存连接行为。Mock provider `p2_http_model.py` 仅用于此模式；禁止同时指定 --live。

独立复验曾在并发区间断言出现假失败：本机 Python 3.12 的 monotonic 实际为
GetTickCount64，分辨率 0.015625 秒；MockTransport 三调用都在一个 tick 内结束，起止
值可能相同。区间计时改用 QueryPerformanceCounter（perf_counter，分辨率 1e-7 秒），
修正后连续三次 HTTP-Mock PASS；两次公开安全区间显示三个 child 无 error_types、共同
重叠分别约 0.0090 秒和 0.0079 秒。没有通过增加模型调用或修改生产运行逻辑解决测试。
第一次真实调用的原始 monotonic 时间保留，不重算；0.000 秒只表示粗粒度观测，不能
用于判定是否发出 HTTP 或推断根因。

实际装配断言 Lead 不含 MemoryMiddleware，DynamicContextMiddleware._memory_enabled=false；
三个子链均不含 MemoryMiddleware 和 DynamicContextMiddleware，只装 SubagentDateContextMiddleware。
子图从自己的 Brief 新建状态，不继承父历史；生产路由须继续禁止 snapshot 模式扩大输入范围。
本地 guard 在模型结果离开处理器、工具执行前拒绝非 isolated、其他角色、模型覆盖及非 task 调用。

SandboxMiddleware 原生 lazy_init=true，无工具的 Specialist 不取得 Sandbox；Probe 为 acquire
入口安装会立即失败的审计 trap，运行中未触发。trap 只能拒绝执行，不能提供宿主执行。
这证明不调用工具的原生子 Agent 编排不依赖已验收 Sandbox；文件、搜索、MCP、真实技能及
任何需要 Sandbox 的 Specialist 仍 BLOCKED，不据此宣称隔离专项通过。

## 一次受控真实请求：部分通过，整体失败

离线原生链和 guard 负向验证通过后，执行一次 `--live`；未自动重发。真实模式使用官方
ChatOpenAI / Responses API / gpt-6-luna，默认官方 base_url，SDK max_retries=0，
LLMErrorHandlingMiddleware retry_max_attempts=1；未使用 MockModel 或模拟响应。
输入依然是固定虚构 Brief，不是正式业务资料。

`p2_agent_budget_guard.py` 通过官方 extensions.middlewares 同时装入 Lead 和每个子图，
进程共享锁最多准入 5 个模型 handler，每次输出最多 1024 Token，消息和实际工具 schema
合计不超过 90000 JSON 字节，另保留 8192 输入 Token 协议余量。只允许纯文本/明确白名单
function-call blocks，拒绝媒体、额外工具、全部 request.model_settings 覆盖、非官方端点。
按既有单价，总预留上界 `5 × (98192 × 0.10 + 1024 × 0.50) / 1000000`
= **0.051656 USD**。该上界是此次有限纯文本任务的保守预留，不是通用多模态计费承诺。

| 实际步骤 | 结果 |
|---|---|
| Lead 首次输出 | 只调用 Lab；未按提示一次生成三调用 |
| Lab | 已路由到原生子图并准入模型 handler；约 0.016 秒失败，无 usage；原生返回通用 provider unavailable 文本 |
| Lead 第二次输出 | 同时下发 Research 和 Procurement |
| Research | 已路由并准入 handler，约 0.000 秒失败，无 usage |
| Procurement | 真实模型返回结构化 JSON，包含 EV-procurement、4 cm^-1、available resolution unknown；结果返回 Lead |
| Lead 最终汇总 | 第六次 handler 被共享调用上限拒绝；最终输出预算失败，整体 FAIL |

真实模式证明 Lead → Procurement → Lead 的原生调用和结果返回；没有证明三个 Specialist
均真实成功，也没有证明至少两个真实模型调用并行成功。Research/Procurement 两个子 handler
在准入时间区间开始点重叠，但 Research 立即失败，不当作真实并行成功。**离线三并发 PASS
与真实并发未验收分开登记**。

原证据保存在仓库外 `mis-p2-gateway-evidence/agents-live.json`：5 admissions、3 outcomes。
Lab/Research 的 handler 异常没有在第一次版本 guard 中被捕获，只有原生通用错误；快速失败
不能证明请求没有送出，也不能把缺失 usage 当作 0 费用。之后完善 guard，记录安全异常类型链
和函数名、不记录原始凭据，并修正 Probe 必须检查最终 error fallback/汇总内容。
没有再次真实请求来补取丢失的异常。

本机依赖的 langchain_openai `_client_utils.py` 缓存默认异步 httpx client，完全相同的模型设置
会共用 client；这是跨事件循环故障的候选风险。localhost HTTP/1 keepalive 离线探测未复现
错误，故**实际 Lab/Research 失败原因仍未知**，不能直接归因于这一风险或供应商不可用。
后续可在无模型费用的合规 Responses MockTransport 链补充诊断，再决定是否发起第二个
独立、重新核算预算的任务。Prompt 不是并发或固定调用次数的硬保证。

## 用量、检查和剩余边界

可见三条 usage：Lead 6733/144、Lead 7169/307、Procurement 446/77（输入/输出）。
合计输入 **14348**、输出 **528**，按既有单价可核算 **0.0016988 USD**；
加 P2-0B 已知 **0.0003295**，可核算累计 **0.0020283 USD**。
两条缺失 usage 费用未知，保守将此次全额预留 **0.051656** 加此前已知额，
作为本轮调用预算占用上界 **0.0519855 USD / 10 USD**；不把已知使用量当完整账单。
未运行后台记忆/标题/摘要模型，功能均禁用，所有五个 handler 由同一 guard 计数。

纯配置单元测试 `tests/test_agent_profiles.py` 两项通过，覆盖工具/角色边界及可变对象隔离。
原生 Probe、guard 负向验证通过；真实主线失败保留，不用离线结果覆盖。
后续仍需稳定真实多角色/汇总、上下文压缩保真、工具/文件隔离、真正 Gateway 配置安装，
并与 Adapter 持久化 ID 映射及正式 Artifact 接收验证接合。保持 P2，不提前实施 P3 闭环。


## P2-0D 补充（2026-11-15）

诊断和薄修复详见 [Provider 诊断专项](P2_provider_diagnostics.md)。原P2-0C的Lab、Research异常链没有保存，分别仍为UNKNOWN；共享client、跨loop或Streaming都不能凭时长猜定。新SDK probes覆盖Streaming、共享client并发、连续/同时存活loops、HTTP/API、连接/超时/解析异常和取消清理。默认缓存风险未能在真实本地HTTP/1.1 fixture复现。

新增公开ModelConfig.use provider `mis.agents.responses_model:IsolatedResponsesModel`，每模型专用http_async_client、loop归属保护和清理，并补安全阶段telemetry。原生Streaming及非流式MockTransport全图均PASS。Budget Guard保留，固定7次handler（3次子任务+最多3批派发+1次汇总），新增最坏预留0.0723184 USD，使用旧保守占用重算入场累计上界0.1243039 USD。

唯一一次新真实任务整体仍**FAIL**：3次HTTP200且有usage，Lead→Lab→Lead成功，但Lead随后直接最终汇总，Research/Procurement没有分派，汇总显式列summary=null/No result received；未触发7次上限。实际3次底层请求均stream=false，不能由graph.astream推断必然Streaming。没有追加请求或真实三角色并发证明。

本轮新增可核算0.0016005 USD，已知累计0.0036288 USD；保留旧未知usage占用后保守累计0.0535860 USD/10 USD。新原始证据为仓库外agents-live-0d.json；旧agents-live.json保持不变。9项结果完整性单测和原始证据离线校验确保missing角色不因Lead的unreviewed汇总而被判完成；这仍不是正式Artifact采纳或P3闭环。

## P2-0E：完整性补派与真实阻塞

新增官方 AgentMiddleware 薄扩展，在 Lead 提前结束时最多补派一批尚未执行的必需角色，仍通过原生 task/ToolNode/SubagentExecutor 执行；拒绝重复和失败重试，三个 TaskBrief 各绑定自己的 Evidence。6次 SDK MockTransport 原生闭环和至少两角色真实执行区间重叠通过；HTTP503 注入为 partial。缺失/失败/未汇总不能标整体 completed。

唯一新真实 Run 在 before_agent 阶段被 SandboxAuthorizationError 拒绝：空 skills 白名单仍触发物理技能投影，现有 role=user 明确拒绝 Sandbox。没有执行 task 或模型请求，三个角色 missing，业务 failed，无 Artifact。没有放开 Sandbox/宿主机，没有再次提交 Run。真实三角色完整返回、汇总和并行仍未验收。

成功的原生执行策略探针没有 Gateway runtime.context.thread_id，不能覆盖实际投影门槛；追加固定投影的原生拒绝探针确认 0 次模型准入。配置安装之前还记录两次零 Run/零模型的认证前检修正（PAT不支持Agent scope；官方 agents_api 默认关闭），原始证据分别保留，不能当作真实模型复验次数。

具体实现、Artifact 校验边界和复现见 [完整性与业务接收专项](P2_completion_and_artifacts.md)，最终检查及费用口径见 [主报告第23节](P2_deerflow_integration.md#23-p2-0e执行完整性与候选业务接收)。历史 Lab/Research provider 根因仍 UNKNOWN，本轮没有请求它们，不能用本轮 Sandbox 错误倒推旧错误。
