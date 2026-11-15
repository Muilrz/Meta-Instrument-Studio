# P2-0D Provider 诊断与有界编排

- 日期：2026-11-15；基线 MIS `fd169db`。
- 固定 DeerFlow v2.2.0：`58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a`，不改核心或依赖。
- 原报告：[P2-0C Agent 集成](P2_agent_integration.md)。本报告不把原失败改写成成功。

## 历史 Lab / Research 的证据结论

仓库外 `mis-p2-gateway-evidence/agents-live.json` 保留 5 admissions、3 outcomes：两个 Lead 和 Procurement 有 usage；Lab、Research 只有 handler 准入和原生 provider unavailable 返回，没有 handler 原始异常链、HTTP 状态或传输阶段证据。

| 角色 | 已知 | 仍未知 |
|---|---|---|
| Lab | 已路由、模型 handler 已准入、没有 usage、原生通用失败 | 是否发送 HTTP、具体客户端/供应商/解析异常、实际费用 |
| Research | 同上 | 同上，不能因为计时约为零就推断未发送 |

原时钟是 Windows GetTickCount64（15.625ms 分辨率）；计时不足以归因。新版 guard 的异常类型链只能为**新运行**提供证据，不能恢复旧异常。分别认定两个历史根因均为 **UNKNOWN**。它们的缺失 usage 继续占用原预留，不按零费用处理。

## 新的确定性诊断

在固定上游 backend 目录运行：

```powershell
.\.venv\Scripts\python.exe C:/Users/Muil/Desktop/MIS_workspace/Meta-Instrument-Studio/docs/spike/verify_provider_diagnostics.py
```

该 probe 使用官方 ChatOpenAI / AsyncOpenAI / Responses SDK，不读取真实凭据。socket 仅允许 loopback，HTTP fixture 为本地 HTTP/1.1 keepalive 服务，其他响应由 MockTransport 提供。外网模型调用 0，数据库/工具/Sandbox 操作 0。

| 场景 | 实际结果与可区分范围 |
|---|---|
| 正常非流式、SSE Streaming | PASS；SDK 请求/解析均执行，流文本可恢复 |
| 同一 client、同 loop 三并发 | PASS |
| 401 / 503 | AuthenticationError(401) / InternalServerError(503)，MockTransport 进入一次，无自动重试 |
| 建连异常 | APIConnectionError → ConnectError，不能把 client.send 进入当作服务器收到 |
| 超时 | APITimeoutError → ReadTimeout，超时并不等价于未收费 |
| 发送前 client 已关闭 | APIConnectionError → RuntimeError，MockTransport 进入数 0，确实未到传输 fixture |
| HTTP 200 畸形响应 | AttributeError，属于本固定样本的响应转换失败；会触发预期 Pydantic serializer warning |
| HTTP 200 后流读取异常 | ReadError，区别于初始 HTTP/API 错误 |
| HTTP 200 后坏 SSE JSON | JSONDecodeError，区别于连接错误 |
| 流消费中取消 | CancelledError 向上传播，async stream 的 aclose 被执行 |
| 默认缓存 client 连续 event loops | 本机 fixture PASS，没有复现旧故障 |
| 默认缓存 client 两个同时存活 loops | 本机 fixture PASS，没有复现旧故障 |
| 新 provider 每模型独立 client、连续 loops | PASS，池在所属 loop 关闭 |

本机依赖 `langchain_openai/chat_models/_client_utils.py` 的默认 `_cached_async_httpx_client` 以相同 base_url/timeout/socket_options 缓存 client；两个相同默认模型实例确实引用同一 client。DeerFlow 的 isolated SubagentExecutor 使用独立持久 loop。这个组合形成共享资源风险，但上述真实 keepalive fixture 未复现错误，**不是已证实的历史根因**。

### 原生全图 Streaming 与非流式

```powershell
.\.venv\Scripts\python.exe C:/Users/Muil/Desktop/MIS_workspace/Meta-Instrument-Studio/docs/spike/verify_native_agents.py --http-mock
.\.venv\Scripts\python.exe C:/Users/Muil/Desktop/MIS_workspace/Meta-Instrument-Studio/docs/spike/verify_native_agents.py --streaming-mock
```

两种模式实际 PASS。原生 Lead/task/三个 SubagentExecutor、完整中间件、官方 SDK 与 Responses 序列化均执行；仅公开 HTTP client transport 为固定 fixture。Streaming fixture 支持 function-call 参数增量和文本 delta，三个 child 经同一 barrier，perf_counter 区间重叠，角色 canary 未互相进入输入，Lead 汇总返回。每种固定任务 5 次 SDK handler、0 外网请求。

与 P2-0C 的区别：P2-0C HTTP fixture 强制关闭 Streaming，因此其通过不能代替本轮 Streaming 验证。本轮 offline provider 继承与拟真实调用相同的 `IsolatedResponsesModel`，使用同一 client 归属检查和清理，只覆盖 transport。

首次尝试 native probe 在官方 skillscan/orchestrator 导入时出现 OSError errno 9，发生于任何模型准入之前。负责人随后报告火绒再次删除文件并明确要求恢复；主代理从固定 commit 正常恢复单文件后，native probes 才继续通过。未关闭/绕过安全软件或伪造 scanner 模块，此环境问题不归为 Lab/Research 历史 provider 根因。

## 最小防御性适配

`src/mis/agents/responses_model.py` 提供可由官方 ModelConfig.use 加载的 `IsolatedResponsesModel`，通过 ChatOpenAI 的公开 `http_async_client` 构造参数注入每模型独立的 httpx client，避免默认跨模型缓存。没有修改 LangChain、OpenAI SDK 或 DeerFlow。

- client 第一次 send 绑定所属 loop；同一 client 跨 loop 使用在网络前拒绝。
- 每次 send 仅记录 client/loop identity、时间、JSON 字节数、stream 布尔、HTTP 状态与异常类型，不记录 URL、headers、API key 或请求内容。
- `close_model_clients()` 在相应 owner loop 关闭池；native runner 在父 loop 退出前统一 await 清理。没有新的 Agent 调度器。
- guard 为每次模型准入记录 loop/thread/client identity、异常类型链、函数名和有限错误类别；取消不再因只捕获 Exception 而漏记。类别仍需结合 HTTP 状态、send telemetry 和调用栈判断，不把泛化 AttributeError 自动当成供应商故障。

这是减少共享池风险、提高可观测性的薄适配，**不是对历史根因的确认**。它覆盖当前原生异步调用路径，不宣称完成同步客户端或整个生产连接池治理。

## 调用数与费用上界

三个 Specialist 各最多一轮；若 Lead 一批分派三个子任务，理想模型次数为 1 次分派 + 3 次子任务 + 1 次汇总 = 5。原 P2-0C Lead 分两批时需要 2 + 3 + 1 = 6，原 cap=5 无法完成最后汇总。若逐个分派，最多 3 + 3 + 1 = 7。

新 cap 固定为 **7**，SDK max_retries=0、DeerFlow retry_max_attempts=1；保持 max_total_subagents=3、每角色 max_turns=1、Lead 仅 task、子任务无工具/技能/Sandbox、Memory/标题/建议/摘要等后台模型路径关闭。Prompt 不保证批次；超过 7 次仍必须拒绝，不连续扩大上限。

输入消息及实际工具 schema JSON <=90000字节，另留8192输入Token余量；每次输出<=1024。按既有单价，单任务最坏预留：

`7 × (98192 × 0.10 + 1024 × 0.50) / 1000000 = 0.0723184 USD`。

以前轮**保守占用** 0.0519855 而非已知 usage 作为新基线，最坏累计 **0.1243039 USD / 10 USD**。仅针对本次纯文本/有限工具 schema 的保守计量，不是任意多模态计费保证。

真实 runner 写入新的仓库外 `agents-live-0d.json`，以 exclusive-create 在调用前占用该文件，存在即拒绝再次启动；保留原 `agents-live.json`。它最多执行一个新任务，不自动重试。主代理负责唯一一次真实复验及结果汇总；本诊断工作线没有调用真实模型。

## 验证和边界

本工作线已经通过新增 SDK 诊断 probe、原生 Streaming / 非流式 probes、guard 7次硬上限负向验证、9项结果完整性单测，以及所属文件 ruff check/format。没有执行 Neon DDL、改动 P1 Schema、操作 Gateway 或新增正式经验。

真实复验结果由 [P2 主报告](P2_deerflow_integration.md) 单独登记。即使复验成功，也不能倒推两个历史异常的准确根因；如果复验失败，必须保留本轮异常证据并停止再次请求。


## 本轮唯一真实复验：Lab 成功，整体未闭合

主代理完成离线验证及重新预算后执行唯一一次 `--live`，未再次请求。原始证据 `mis-p2-gateway-evidence/agents-live-0d.json` 独立保存，原 P2-0C 证据不变。

| 步骤 | 实际结果 |
|---|---|
| Lead 第一次 | 只分派 Lab，调用模型成功 |
| Lab | 独立模型/client 成功，Evidence EV-lab、4 cm^-1、未知项保留，结果返回 Lead |
| Lead 第二次 | 直接生成最终汇总；Research、Procurement summary=null，并明示 No result received |
| Research / Procurement | 没有分派，缺失结果；不是本轮 provider 调用失败 |
| 费用/连接 | 3 admissions、3 outcomes、3次HTTP200，全部有usage，全部client清理完成 |
| 验收 | **FAIL**，没有三Specialist闭环或真实并行证明，7cap没有触发 |

实际 telemetry 的3次HTTP请求均 `stream=false`。DeerFlow graph.astream 不意味着每次底层 Responses 请求必然 Streaming；P2-0C 原证据未记录 stream，旧调用模式仍未知。本轮显式 Streaming fixture验证与真实非流式请求必须分别表述。

本轮两次 Lead 与一次 Lab合计 input=14385、output=324，实际可核算费用 **0.0016005 USD**；与既有已知累计0.0020283相加为 **0.0036288 USD**。本轮3次调用usage完整，可释放未使用的新增预留；继续保留旧缺失usage的保守占用，最终保守累计为 **0.0535860 USD / 10 USD**（旧0.0519855 + 新0.0016005），入场最坏累计预留仍为0.1243039。其他会话及账户账单未知。

这次成功证明新的专用client路径可以完成真实 Lab往返；不能倒推旧Lab失败是共享client导致，也未复验旧Research provider，因为本轮根本没有调用Research。三角色未齐备的本次直接原因已知：Lead提早结束，属于编排完整性失败，不是API、传输或费用上限失败。按任务要求停止真实请求，保留缺失状态。

新增 `src/mis/agents/results.py` 只核对可信Runtime返回的原生 task call/result/status，不信任Lead自述的roles或unreviewed标记；按角色输出missing/pending/completed/失败状态并拒绝不完整。它不调度或重试、不采纳业务Artifact。9项单测覆盖完整结果、缺失角色、失败/取消/未知、pending和重复/冲突回执。对本轮原始证据的只读离线复验得到 `lab=completed, research=missing, procurement=missing`，完整性校验按预期拒绝。后续需设计经授权的固定任务接收条件或原生约束，使Lead不能在必要角色缺失时被产品接受；不能通过再次真实请求碰运气补验收。
