# P2 Memory 隔离验证

- 日期：2026-11-15（Asia/Singapore）。范围：P2-0C，关闭原生 Memory 后的内容隔离。
- 上游：DeerFlow v2.2.0，固定 commit `58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a`，未修改核心。
- 结论：禁用写入/注入并配合原生 Agent `memory_enabled=false`，已通过确定性内容隔离测试。单独两个全局开关不足以清理历史 Checkpoint 中已注入的 Memory；禁止以此声称任意旧 Thread 已隔离。
- 主报告：[P2 集成 Spike](P2_deerflow_integration.md)。可复现脚本：[p2_memory_probe.py](tools/p2_memory_probe.py)。

## 空 FTS 初始化的原因与范围

固定版 `backend/app/gateway/app.py` lifespan 的 retrieval rebuild 分支（约 685–703 行）检查 `startup_config.memory.enabled`，关闭时不会后台重建索引。但紧接着 tokenizer warm 分支（约 705–731 行）仍无条件调用 `get_memory_manager()` 再调用 `manager.warm()`。

`agents/memory/manager.py::get_memory_manager()` 的工厂不以 enabled 开关拒绝实例化。默认 `DeerMem.model_post_init()` 调用 `create_storage()`，后者按默认 `retrieval_adapter=fts5` 调用 `create_fts5_retrieval()`，在 storage root 下创建 `.retrieval/memory-fts5.sqlite3`。因此文件创建来自 manager 的构造副作用，不需要 MemoryMiddleware 写入、检索或模型请求。`DeerMem.warm()` 预热词法/token 计数资源，不执行记忆抽取模型。

源码证据均位于上述固定 checkout：

| 路径（相对 backend/packages/harness/deerflow） | 行为 |
|---|---|
| `agents/memory/manager.py` | 工厂解析后端、storage_path 和 host hooks，缓存 manager |
| `agents/memory/backends/deermem/deer_mem.py` | 构造 storage/queue/updater；`warm()` 只预热 tokenizer |
| `agents/memory/backends/deermem/deermem/core/storage.py` | 默认检索适配器创建 |
| `agents/memory/backends/deermem/deermem/core/retrieval.py` | 创建持久的派生 FTS5 文件 |

离线 probe 在全新临时目录实际构造 DeerMem，确认 SQLite 文件存在、`memory_fts` 为 **0 行**，并在 char token counting 下调用 `warm()`，模型调用 spy 为 0。这里的 char 配置只用于消除离线测试的 tokenizer 下载需求；P2-0B Gateway 的实际 tokenizer warm 以主报告第 19 节为准。本次没有重新启动 Gateway 或重复基础 Smoke。

该行为登记为 **MEM-INIT-01：Memory disabled 时 manager/tokenizer warm 仍初始化空派生索引**。它不是 PostgreSQL Checkpoint 的 SQLite 回退；也不能把“空索引”当作“从不创建记忆文件”的证明。后续可向上游提交最小 enabled gate 建议，或单独验证官方 noop manager 配置；本轮不修改上游、不删除已有运行目录，也不以此阻塞 Agent 主线。

## 离线测试与 canary

脚本使用固定上游环境，外部 socket 连接拒绝；Windows asyncio 自管 socketpair 的 loopback 连接保留。模型为抛错 spy，只有假的模型请求 handler；不读取 Neon、MIS `.env` 或调用 Gateway，不写正式 `mis` / `knowledge`。所有 canary 写入均为临时 native Memory fixture 的显式 import，测试退出关闭连接并删除临时目录。

| 验证 | 结果 | 证据边界 |
|---|---|---|
| MemoryMiddleware 同步/异步 after_agent | PASS | `enabled=false` 时未获取 manager，因而未排入写入/模型抽取队列 |
| Summarization `memory_flush_hook` | PASS | disabled 时未获取 manager，未 enqueue |
| `_get_memory_context` 自动读回 | PASS | 两个开关 false 时返回空字符串，未获取 manager |
| 隔离样本存在性与正向对照 | PASS | 显式 import A 的 canary，同一 user 的 native `get_memory()` 和 enabled `_get_memory_context()` 能读到它，证明不是空存储造成假通过 |
| 同 user、两个其他项目的新 Thread | PASS | sync/async before_agent 后，经真实 DynamicContext wrap_model_call / awrap_model_call 的假 handler 截获请求，均无 A canary 或 `<memory>`；未获取 manager 或调用 get_context |
| 内容自动写回 | PASS（上述路径内） | fixture 的所有 `.md` / `.json` 内容 hash 前后相等；模型 invoke / ainvoke 为 0 |
| 历史冻结 Memory、仅全局开关关闭 | **缺口已复现** | 同日旧 Thread 的 `old__memory` 块仍留在状态，关闭开关不会清理已注入消息 |
| 历史冻结 Memory、Agent `memory_enabled=false` | PASS | sync/async before_agent 均生成移除操作，`add_messages` 合并后 canary 消失 |

正常启用时 native Memory 的作用域是 `user_id` / `agent_name`；其 manager API 没有 MIS `project_id` 参数。不能把 native 的 user 隔离当作 MIS 跨项目隔离。当前通过的是 **禁用原生读取/写入后的内容隔离**，不是启用 Memory 后的项目授权验证。

`DynamicContextMiddleware._disabled_memory_removals()` 按 `HumanMessage`、受框架拥有的 `__memory` ID 和 reminder marker 清理。它不清理普通用户消息、摘要、合法业务上下文或任意已污染历史。因此仍要求项目/角色与 Runtime Thread 绑定一致，禁止跨项目复用 Thread；对曾启用 Memory 的历史运行，必须单独评估摘要和其他载荷，不能只切开关便宣称历史已净化。

## 复现与结果

在固定 checkout 的 `backend` 目录运行（脚本首先校验 Git HEAD）：

```powershell
.\.venv\Scripts\python.exe C:/Users/Muil/Desktop/MIS_workspace/Meta-Instrument-Studio/docs/spike/tools/p2_memory_probe.py
```

2026-11-15 实际退出码 0，约 3.6 秒；输出 8 个行为项（6 个 PASS / CONFIRMED，2 个已复现行为/缺口），`model_calls=0`、`formal_memory_writes=0`。这不是 `pytest` 的测试计数，不叠加到 MIS 完整套件的 passed 数。脚本 SHA-256：`bb51528f9508e758eebe516b4e31ac8e71156e8c9e5673fd44315aa7ea1b8555`。

`uv run ruff check docs/spike/tools/p2_memory_probe.py`、`git diff --check` 均通过。未发起真实模型调用，新增费用 **0 USD**；已知累计维持 **0.0003295 USD / 10 USD**，其他工作线如产生调用由主报告统一汇总。

## 未纳入本次通过声明的项目

配置绑定需区分两种原生类型：Lead `AgentConfig.memory_enabled=false` 传递给 `build_middlewares()` / `DynamicContextMiddleware`，禁用读写并清理受拥有的历史冻结块；Specialist 的 `SubagentConfig` 无此字段，不应增加无效配置。固定版 `build_subagent_runtime_middlewares()` 只装配 `SubagentDateContextMiddleware`，不装配 Lead 的 DynamicContext / MemoryMiddleware，且原生强制 `skip_memory_flush=True`，不把子 Agent 内部历史写到父 Thread 的 Memory。这是源码审查结论；四 Agent 的实际装配/运行证据以主线 native probe 为准，本脚本只测试上述 Memory 入口和两类 canary 边界。

这些确定性测试覆盖当前 disabled Memory 入口和 canary 请求边界，没有运行后台提取计时器或启用记忆写入，也没有对全部插件、管理 API、任意未受控扩展作否定证明。直接调用 native Memory 管理接口本身仍能读写（正向对照正是显式 import）；生产授权仍需由工具白名单、RBAC 与 MIS 服务边界控制。

DeerMem 的候选抽取、去重、冲突关系、来源保留和可选整合仍是独立 P2 待验证项，本次未声称通过。没有任何候选晋升或正式经验库写入；本报告也不替代 Docker/Sandbox 或火绒告警复核。
