# ADR-0003 P1 单位与业务存储

- 状态：已接受
- 日期：2026-11-08
- 修订：2026-11-08，按静态审查补充写入与历史边界；负责人明确确认 Impact Analysis 限定相邻版本
- 决策人：项目负责人（本次 P1 启动会话明确确认）

## 决定

使用 pint，由 `mis.units` 封装，Raman 领域换算单独实现。业务对象使用
Pydantic；SQLAlchemy 2.x + psycopg 3 连接 PostgreSQL 17，每类对象一表，
完整文档存 JSONB，保留索引列。Alembic 管理迁移。P1 不实现 HTTP API。
手写结构化器件示例放 `tests/data/`，不改动已验收的基准包。

以上解决 P1 Q1–Q4，不改变 ADR-0001 中其他尚待评审事项。
业务存储不依赖 DeerFlow 或任何运行状态。

## 后果

所有写入必须验证模型及引用；数据库约束保护不可变记录和版本。
JSONB 字段演进由模型处理，索引和表约束变化使用迁移。
外币不做无来源的单位换算，预算换算必须引用汇率 Evidence。

## P1 静态审查后的边界约定

- `add()` 的幂等单位是对象类型 + ID + 相同序列化内容；不同内容报 ValueError。默认 PostgreSQL READ COMMITTED 下，业务对象取得项目锁后复查 ID，INSERT 使用 ON CONFLICT 处理并发冲突；不通过捕获唯一约束异常让事务进入失败状态。
- 新 Artifact 不得引用 stale Brief，新 Plan 不得引用 stale Artifact。读取既有历史对象保持可用；空库恢复通过私有历史重建路径保留原状态和引用，并逐对象核对相等。P1 不提供把 stale 对象作为新方案历史依据的公共入口。
- Impact Analysis 只支持 `to_version == from_version + 1`；2026-11-08 由负责人确认。每次升级分别分析，保留更早基线复用对象的依赖传播；跳级比较明确拒绝。
- questions 的 UPDATE 仅允许 open → answered / cancelled；题目、上下文和身份字段不可修改，终态不能重写或恢复 open，DELETE / TRUNCATE 被拒绝。回答需要时间和本项目的 user_decision Evidence。
- 上述约定不代表 P2 的工具重试、Checkpoint、回调或 SSE 全流程幂等已验证；P2 仍需提供稳定业务 ID，并验证执行流程的重放。
