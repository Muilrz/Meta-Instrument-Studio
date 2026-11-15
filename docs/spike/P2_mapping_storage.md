# P2 持久 ID 映射：Schema 提案与验证边界

- 日期：2026-11-15；P2-0D，基于 `fd169db`。
- 当前 Schema 状态：**负责人已批准仅在原 Neon P2 测试目标创建两表及 `mis_app` 最小授权；尚未执行 DDL**。现有两份 owner 凭据均不能认证该分支，等待将正确 P2 owner URL 安全写入 `.env`。未修改 P1 迁移、未授权角色。
- 具体可审查 SQL：[task_run_mapping.sql](sql/task_run_mapping.sql)。

## 最小 Schema 与权限影响

建议新建 MIS 服务拥有的 `mis_integration` schema，仅两张集成基础表：

| 表 | 保存内容与硬约束 |
|---|---|
| thread_bindings | MIS project/task/thread 与 upstream thread；MIS project/thread 主键、upstream thread 全局唯一、task 绑定不可变 |
| run_commands | HTTP 前命令意图、幂等键、Brief/配置/请求 Hash、基线版本、角色、预算快照、uncertain/绑定/终态及 upstream run；MIS project/run 主键、project/idempotency key 唯一、upstream run 全局唯一、复合外键约束 thread/task 范围 |

该方案不改 `mis`、`knowledge`、`trace`、DeerFlow `runtime` 中的既有表，也不修改 P1 核心模型或迁移。新表不是业务事实库：只保存运行关联和命令账本，不保存模型原文、凭据、Evidence 正文或正式经验。P1 项目/Brief 与此处引用的对应关系仍由 MIS 服务在授权后校验，不给 Runtime 修改业务主数据的能力。

DDL 必须由批准测试目标的 migration owner 执行。负责人批准的 MIS backend 角色为 `mis_app`，仅授新 schema 的 USAGE 和两表 SELECT/INSERT/UPDATE。**不授予 `mis_runtime` 新权限**，不授 CREATE、DELETE、TRUNCATE，不修改原有业务表权限。SQL 中的 GRANT 为注释模板，实际执行时仅可替换为已批准的 `mis_app`。本轮审批依据为负责人在 P2-0D 对两表具体方案的明确批准，不代表其他 Schema 或环境获准。

现有 DeerFlow 通用 Store 可以保存键值，但不能直接提供跨键唯一约束和本方案的原子冲突检查。把唯一映射寄存在 Checkpoint 又会违反业务与 Runtime 生命周期分离，因此本轮不以此规避 Schema 审批。

## 执行与崩溃窗口

调用方拥有 PostgreSQL 事务：准备 intent 后必须提交，才允许调用 Gateway。请求前没有确定响应的 intent 与请求超时后的 uncertain 均**不得自动重发**。查询对账只能绑定经过 metadata 与身份核验的单一权威 Run；查不到或多条冲突保持 uncertain，不能由模型生成一个新 run_id 再扣费。

HTTP 成功但本地 bind 前进程退出时，新进程重载持久 intent 后按幂等键/metadata 查询上游；确认同一 project/task/thread/run 后再原子绑定。业务 Artifact、用户回答 Evidence 和方案采纳仍走各自服务，不因映射进入 completed 自动采纳。

本轮可实现存储代码、PostgreSQL SQL 编译/离线驱动测试，并准备 opt-in 的真实 PostgreSQL 验收。未批准并实际安装两表前，不声称 PostgreSQL 跨进程重载、约束竞争或崩溃窗口已验收。不得在 Neon 主分支自动执行本提案。

## 实现与事务接口

`src/mis/adapters/task_store.py::PostgresTaskRunLinkStore(connection)` 不创建表、不提交事务、不发 HTTP、不自动重试。`begin_intent` 返回 `IntentReceipt(created, command)`；`created=false` 是同内容重放，不能再次发送模型请求。线程和命令冲突用 savepoint 回滚，避免调用方捕获冲突后意外提交半条线程记录。

`mark_uncertain` 只将 intent 转为 uncertain，不回退已有绑定/终态；`put` 仅能把已有 intent 绑定到一个 upstream Run，同内容返回，变更 Hash/范围/上游身份拒绝；上游唯一约束冲突以 savepoint 回滚并返回安全错误。`get_command` 重载尚未绑定的命令，`get` 只返回已验证的 TaskRunLink。`reconcile` 重新核验上游 metadata/ID/状态，然后绑定并保存终态；终态不允许回退或变更。Hash 和预算快照是审计约束，不替代服务端实时预算硬限制。

## 验证及凭据阻塞

```powershell
uv run pytest tests/test_task_store.py tests/test_task_store_postgres.py -q
```

当前结果 **25 passed、1 skipped**。25 项仅为无数据库的 PostgreSQL SQL 编译/脚本化驱动与 codec 验证：不可变意图、同内容幂等、冲突及 savepoint、uncertain、不回退终态、权威响应错配拒绝、预算校验，以及另一个进程从模拟数据库 JSON row 重建完全相同 link。最后一项只证明 codec 不依赖进程内对象，不是 PostgreSQL 跨进程持久性证明。

真实数据库测试 `tests/test_task_store_postgres.py` 默认跳过；须两表已安装，并通过进程环境设置 `MIS_INTEGRATION_TEST_APPROVED=1` 与 `MIS_INTEGRATION_TEST_DATABASE_URL`。该 URL 必须与既有 `DEER_FLOW_TEST_DATABASE_URL` 的 endpoint 一致，且与 MIS 开发和原 P1 测试 endpoint 不同。可由已有授权 owner 连接执行 `SET LOCAL ROLE mis_app`（设置 `MIS_INTEGRATION_TEST_SET_ROLE=mis_app`），但不自动授予角色成员关系。测试本身无 DDL、无模型调用，保留带随机 `p2-ledger-` 前缀的少量审计记录，不因清理要求扩大 DELETE 权限。

真实验收准备覆盖：commit 后三个独立子进程分别读回 intent/uncertain/completed、HTTP ack 绑定前的进程消失窗口、相同 intent 重放不发送、冲突键拒绝、跨项目 upstream Thread 占用拒绝、upstream Run 全局唯一约束及部分写入回滚。目前 owner URL 认证失败发生在建立连接前，**任何安装或这些 PostgreSQL 验收均未通过**，也没有在 Neon 主分支执行 DDL。等待正确 P2 分支 owner 凭据后，可在审批范围内继续，不需要重复批准已经确定的两表方案。
