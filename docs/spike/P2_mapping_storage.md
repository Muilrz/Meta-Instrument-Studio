# P2 持久 ID 映射：Schema 提案与验证边界

- 日期：2026-11-15；P2-0D，基于 `fd169db`。
- 当前 Schema 状态：**负责人审批后，仅在原 Neon P2 测试目标安装两表及 `mis_app` 最小授权，真实 PostgreSQL 验收通过**。未修改 P1 迁移或既有 Schema/权限；`mis_runtime` 无新增权限。
- 具体可审查 SQL：[task_run_mapping.sql](sql/task_run_mapping.sql)。

## 最小 Schema 与权限影响

本轮经批准新建 MIS 服务拥有的 `mis_integration` schema，仅两张集成基础表：

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

存储实现不含安装逻辑；Schema 安装与数据库验收由独立、已批准的 P2 操作执行，不会在普通测试或服务导入时触发。没有在 Neon 主分支执行本提案。

## 实现与事务接口

`src/mis/adapters/task_store.py::PostgresTaskRunLinkStore(connection)` 不创建表、不提交事务、不发 HTTP、不自动重试。`begin_intent` 返回 `IntentReceipt(created, command)`；`created=false` 是同内容重放，不能再次发送模型请求。线程和命令冲突用 savepoint 回滚，避免调用方捕获冲突后意外提交半条线程记录。

`mark_uncertain` 只将 intent 转为 uncertain，不回退已有绑定/终态；`put` 仅能把已有 intent 绑定到一个 upstream Run，同内容返回，变更 Hash/范围/上游身份拒绝；上游唯一约束冲突以 savepoint 回滚并返回安全错误。`get_command` 重载尚未绑定的命令，`get` 只返回已验证的 TaskRunLink。`reconcile` 重新核验上游 metadata/ID/状态，然后绑定并保存终态；终态不允许回退或变更。Hash 和预算快照是审计约束，不替代服务端实时预算硬限制。

CallBudget 对模型任务要求调用数、输入/输出上限、Decimal 费用预留全部为正。固定确定性 A4 流程可以记录严格全零 `(0,0,0,Decimal('0'))`，表示完全不授权模型；负数、非有限费用或混合零/正数拒绝。该变化仅影响值校验，无额外 DDL。

## 验证、安装及权限证据

```powershell
uv run pytest tests/test_task_store.py tests/test_task_store_postgres.py -q
```

默认运行结果 **26 passed、1 skipped**。26 项为无数据库的 PostgreSQL SQL 编译/脚本化驱动与 codec 验证：不可变意图、同内容幂等、冲突及 savepoint、uncertain、不回退终态、权威响应错配拒绝、预算/严格零预算校验，以及另一个进程从模拟数据库 JSON row 重建完全相同 link。codec 测试不被当作 PostgreSQL 持久性证明；真实数据库测试另行显式运行。

真实数据库测试 `tests/test_task_store_postgres.py` 默认跳过；须两表已安装，并通过进程环境设置 `MIS_INTEGRATION_TEST_APPROVED=1` 与 `MIS_INTEGRATION_TEST_DATABASE_URL`。该 URL 必须与既有 `DEER_FLOW_TEST_DATABASE_URL` 的 endpoint 一致，且与 MIS 开发和原 P1 测试 endpoint 不同。可由已有授权 owner 连接执行 `SET LOCAL ROLE mis_app`（设置 `MIS_INTEGRATION_TEST_SET_ROLE=mis_app`），但不自动授予角色成员关系。测试本身无 DDL、无模型调用，保留带随机 `p2-ledger-` 前缀的少量审计记录，不因清理要求扩大 DELETE 权限。

负责人批准具体两表方案后，起初两份其他分支的现有 owner 密码无法认证 P2 endpoint，均在连接建立前失败，未执行 DDL。负责人随后把正确 `MIS_INTEGRATION_OWNER_DATABASE_URL` 安全写入 `.env`；安装器先核验该 URL 与既有 `DEER_FLOW_TEST_DATABASE_URL` endpoint 相同、与 MIS 主开发和原 P1 测试 endpoint 不同，再以 `neondb_owner` 验证 CREATE 权限、`mis_app` 已存在和新 schema 尚不存在。

外置安装器只执行已审批两表 SQL，以及 `mis_app` 的 schema USAGE 和两表 SELECT/INSERT/UPDATE。事务提交前比较 `mis`、`runtime`、`knowledge`、`trace`、`public` 的 schema、对象、列、索引、default ACL，以及 MIS 业务数据 Hash，**前后完全相等**。明确断言 `mis_app` 两表 DELETE/TRUNCATE=false、`mis_runtime` 新 schema USAGE 及两表全部受检权限=false，随后才 commit。没有 CREATE ROLE、RESET 密码或扩大原有角色成员关系。

安装完成后，以同一正确 owner URL 连接，事务内 `SET LOCAL ROLE mis_app` 并断言 `current_user=mis_app`。显式启用 opt-in PostgreSQL 测试实际取得 **1 passed in 18.92s**，证明：

- commit 后三个独立子进程从 PostgreSQL 分别读回 intent/uncertain/completed，未使用父进程缓存。
- 模拟在已提交 intent、未绑定 HTTP ack 之间丢失进程，新进程重载后保持 pending/uncertain；相同 intent 重放返回 created=false，不暗示可再次发送。
- 权威响应 fixture 的 ID/metadata 匹配后，uncertain 可绑定并落为 completed；此 fixture 不是真实 Gateway Run，HTTP 查询/断流集成由 Adapter 与 A4 工作线另测。
- Hash/幂等键/task 变更、跨项目复用 upstream Thread 拒绝；upstream Run 的 PostgreSQL 全局唯一约束冲突被转为安全错误，savepoint 回滚后第二条命令仍为 intent。
- 重复相同绑定返回既有 link；新表保留少量随机 `p2-ledger-` 前缀审计行，没有通过增加 DELETE 权限清理。

本轮未验证两个数据库事务同时竞争同一映射、数据库故障切换、任意外部副作用 exactly-once，不能从上述验收推导这些保证。

仓库外证据位于 `C:/Users/Muil/Desktop/MIS_workspace/mis-p2-gateway-evidence`，不含凭据：

| 文件或摘要 | SHA-256 |
|---|---|
| mapping-ddl-0d.json（审批范围、身份、前后对照及权限矩阵） | `ae3d6bd089fcf78083c2ef27dda75e201fff1de63b759cd5b98da207963e2e5f` |
| 既有结构/ACL/MIS 数据摘要（前后相同） | `478d3fcac7d6ecbda72bf07ef6061cdd01df9af3a757018f805259ee5173ecd0` |
| 本轮执行的 task_run_mapping.sql | `403d1c02c47ac767a7f3bf616a549d6b5e49cedcf65b62c665b40ad3ef87062f` |
| mapping-postgres-0d.log（真实 PG 验收输出） | `c16669254593c0363bd6d8b95aece809f928cfcf2181e5d9a086cb45cf3ac01d` |

本专项模型调用和费用均为 0；没有更改上游核心、P1 迁移或正式经验库。
