# P2-0C Checkpoint 重启与恢复验证

- 日期：2026-11-15（Asia/Singapore）
- 上游固定：DeerFlow v2.2.0，`58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a`
- 范围：原 Neon P2 测试目标、`mis_runtime` / `runtime`；不修改 MIS 业务 Schema，不调用模型、Sandbox 或宿主机工具。
- 关联：[P2 Spike](P2_deerflow_integration.md)、[恢复探针](probes/checkpoint_recovery.py)。

## 1. 两个验收项

| 验收项 | 结果 | 证明范围 |
|---|---|---|
| 已完成 Thread 在新 Gateway 进程读回 | PASS | P2-0B 成功 Thread 的全部消息与 metadata 精确相等；新进程通过 HTTP GET 获取持久状态 |
| 持久 interrupt 经独立进程 Command.resume 恢复 | PASS（底层确定性验证） | 固定 LangGraph 图 + PostgreSQL AsyncPostgresSaver，暂停、恢复、重复恢复分别在三个独立进程执行 |
| 错误问题/答案拒绝后暂停点不变 | PASS（离线 preflight） | 两种错误输入在调用图前被薄校验拒绝；InMemorySaver 上断言 checkpoint config、pending interrupt 和完成计数不变 |
| Gateway 原生 command.resume + MIS UserQuestion/回答 Evidence 闭环 | 未验收 | 本轮没有将模型 ask_clarification、Gateway Run admission 与 MIS 回答证据串联；不以底层验证替代此项 |

## 2. 已完成 Thread 的 Gateway 重启读回

P2-0B Gateway 已在上一轮关闭。本轮重新启动同一官方 Gateway app、配置和独立 `DEER_FLOW_HOME`，单 worker、仅监听 `127.0.0.1:18001`。本轮成功进程的 Windows venv launcher PID 为 8928，日志中的实际 Uvicorn worker PID 为 22304。没有重新提交旧 Run，也没有发送新的模型任务。

既有 Thread 为 `19822a2d-536e-5921-9a43-d8f2bd26f9e6`，原 Run 为 `e5efe3fa-2d15-442f-be48-c25438b2540d`。原临时 PAT 已撤销、密码未保存，因此本轮采用上游正式内部服务认证：随机 `DEER_FLOW_INTERNAL_AUTH_TOKEN` 仅在父子进程内存中传递；HTTP 使用 `X-DeerFlow-Internal-Token` 和绑定原 owner 的 `X-DeerFlow-Owner-User-Id`。没有关闭认证、更改角色、重置密码或将令牌写入日志/证据。

`GET /api/threads/{thread_id}` 返回 HTTP 200；断言返回的完整 `values.messages` 与 P2-0B 的 `thread_final.values.messages` 精确相等，metadata 同样相等，AI 内容包含原 `OK`。线程状态为 idle。这证明新 Gateway 通过 PostgreSQL 持久状态重建了已完成会话，而非上一进程内存；接口内部沿用 `get_checkpointer` 和 checkpoint state accessor。读回旧消息中的 usage 是历史用量，不是新增调用。

首轮检查脚本错误地把 Responses API 的 content blocks 当作纯字符串，造成 HTTP 200 后断言失败；已修正为完整消息结构相等，再启动一个新 Gateway 进程复核通过。没有为此调用模型。finally 均设置既有 stop 标记优雅退出，成功进程 exit code 0，日志确认 application shutdown complete。

## 3. PostgreSQL 持久 interrupt / resume

探针只构造一个 approval 节点：输入固定 question_id，调用 LangGraph `interrupt`；恢复输入经固定问题/选项校验后写入 answer，完成计数加一。没有模型、工具或外部动作。使用固定上游安装的 LangGraph 和 AsyncPostgresSaver，通过上游 `_build_postgres_pool` 辅助函数设定 `runtime` search_path；这是 Spike 内部绑定，不承诺该私有函数为 MIS 产品接口。探针不调用 saver.setup、不新建业务表。

测试 Thread：`mis-p2-0c-interrupt-5b1f43241c70`。

| 阶段 | Python PID | 持久状态 | checkpoint 行数 |
|---|---:|---|---:|
| pause | 28340 | question-0c，completions=0，next=approval，interrupt payload 已存储 | 2 |
| resume | 5744 | 新进程先读取相同暂停 checkpoint，再 Command.resume；answer=fixture-a，completions=1，next 为空 | 3 |
| repeat | 35368 | 第三个进程重复同一 Command.resume；completions 仍为 1，next 仍为空 | 3 |

三个进程均断言 `current_user=mis_runtime`、`current_schema=runtime`。pause 输出 checkpoint ID 为 `1f1e0f25-7f04-6184-8000-917234ada8c7`，与 resume 输入 checkpoint ID 相等。完成 checkpoint 为 `1f1e0f25-bc71-6272-8001-86b224aa5a62`；repeat 前后仍为此 ID，checkpoint 行数保持 3。因此重复恢复并非仅返回相同文本，图确实没有再次执行完成节点或产生新 checkpoint。

此处证明的是已完成确定性图对同一恢复命令的重复提交行为；不承诺任意外部副作用 exactly-once，也未验证并发恢复、崩溃于业务提交与 checkpoint 之间或 Gateway Idempotency-Key 的持久去重。MIS 后续仍须将 question_id、checkpoint、用户决定 Evidence、授权主体和幂等键关联，在调用 Runtime 前拒绝错配。

新增的 `offline` 模式进一步使用 InMemorySaver：错误 question_id 和不允许的 choice 共两项由 `validate_answer` 拒绝，仍保留原 approval interrupt、原 checkpoint config 和 completions=0；正确恢复与再次恢复后 checkpoint config 相同、completions=1。它验证的是薄适配 preflight，非 PostgreSQL 错误答案或 Gateway HTTP 准入测试。本次持久化实测先于此追加断言版本；新增 `reject` 模式可在下一次独立持久化复验中插在 pause 与 resume 之间。

## 4. 复现和证据

在固定上游 `backend` 目录使用既有 `.venv/Scripts/python.exe`，不安装或升级上游依赖。离线检查可直接运行：

```powershell
.venv/Scripts/python.exe ../../Meta-Instrument-Studio/docs/spike/probes/checkpoint_recovery.py offline
```

持久化检查须由调用方从既有 `.env` 在进程内设置 `P2_CHECKPOINT_DSN` 和全新的 `P2_CHECKPOINT_THREAD=mis-p2-0c-interrupt-<unique>`；不要将 DSN 放入命令行、报告或 shell 历史。四条命令必须使用相同 Thread，各命令创建独立进程；本轮实测 pause/resume/repeat，reject 为新增可复验模式：

```powershell
.venv/Scripts/python.exe ../../Meta-Instrument-Studio/docs/spike/probes/checkpoint_recovery.py pause
.venv/Scripts/python.exe ../../Meta-Instrument-Studio/docs/spike/probes/checkpoint_recovery.py reject
.venv/Scripts/python.exe ../../Meta-Instrument-Studio/docs/spike/probes/checkpoint_recovery.py resume
.venv/Scripts/python.exe ../../Meta-Instrument-Studio/docs/spike/probes/checkpoint_recovery.py repeat
```

仓库外原始材料位于 `C:/Users/Muil/Desktop/MIS_workspace/mis-p2-gateway-evidence`：

| 文件 | 内容 / SHA-256 |
|---|---|
| checkpoint-0c.json | 三独立进程输出、Gateway 读取结果及退出状态；`2e3ef60a79b23288a031c26638b7665bb3d6816f750b22a831ef9f34c80c6868` |
| checkpoint-gateway-state-0c.json | 新 Gateway 的完整已完成 Thread 响应；`4f47b2f2cae73906688eb5bb2e8938a70407eac7e0fb2fddf8fb6fef271f85dc` |
| gateway-restart-0c.log | 成功新 worker 的启动、HTTP 200 和优雅关闭日志；已脱敏 |
| checkpoint_0c.py | 外置编排器；从现有秘密配置读取连接，内部令牌仅内存；不作为产品代码 |

新增模型调用 **0**，新增 Token **0**，费用 **0 USD**；已知累计仍为 **0.0003295 USD / 10 USD**（仅此 Checkpoint 专项，不含同轮其他 Agent 验证）。未执行 Sandbox 或宿主机工具，未写入正式经验库。固定上游工作树未修改。
