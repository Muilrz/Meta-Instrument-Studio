# P1 阶段报告：核心数据契约与 Project Service

- 日期：2026-11-08
- 状态：T1–T8 实现及自动验收完成（本地 + CI）；待负责人评审
- 分支：`feat/p1-core-data-contracts`
- 决策：[ADR-0003](../adr/0003-p1-units-and-storage.md)，项目负责人已确认 Q1–Q4

## 已实现

| 任务 | 交付 | 独立提交 |
|---|---|---|
| T1 | pint 封装、Raman 换算、P0 接入正式模块 | `4fd8f20` |
| T2 | Known / Unknown / Quantity / QuantityRange | `a4b94d0` |
| T3 | 9 类业务记录、RunRef、Claim 引用、JSON Schema 和一致性检查 | `beafc06` |
| T4 | 五种比较方式、三值汇总、Raman 上下文、带 FX 引用的预算 | `9d28fcf` |
| T5 | SQL 初始化、Alembic、SQLAlchemy 仓储、版本、引用校验、数据库不可变保护 | `81bca52` |
| T6 | 需求差异、ImpactReport、精确 stale 传播、历史和报告复核 | `efd5943` |
| T7 | Raman 导入、8 器件手工数据、Plan 原文追溯、问答和纠正 | `11b9229` |
| T8 | 逻辑业务备份、空目标原子恢复、格式 Schema、阶段报告 | `9aa79e5` |

业务记录保存在 PostgreSQL `mis` schema，每类对象一表，完整 JSONB 加索引列。
服务不依赖 DeerFlow，不调用 LLM，没有加入 HTTP API、Agent、RAG、向量检索或 Trace 基础设施。
初始化只为 runtime / trace / knowledge / cache 建立 schema 和权限，不提前实现后续阶段业务表。

### 接口与契约

- `mis.units.convert` 封装通用单位；Raman 换算独立，外币需要带出处的汇率。
- Pydantic 模型禁止额外字段，显式区分 Known / Unknown；业务集合使用 tuple，导出 JSON 为数组。
- Claim 证据统一存于 `value.evidence_ids`。Evidence 增加 project_id 和结构化 FX 数据。
- BOM 和方案结论使用 ClaimRef；`ProjectService.trace_plan()` 返回 Claim 和 Evidence 原文记录，属于业务出处链。
- `compare` / `evaluate` 确定性执行；缺参数保持 unknown，must fail 优先于 unknown，should 单列。
- `ProjectService(session)` 不自行 commit，调用方拥有事务。写入重新验证模型、引用、项目范围、版本及指定参数。
- RequirementBaseline / InstrumentPlan 按项目顺序追加版本；Evidence 禁止修改、删除、截断；内容不可变记录由数据库触发器保护。
- Brief / Artifact / Plan 状态更新追加原因、时间和触发记录；stale 内容不能直接重新激活。
- 影响分析先返回报告，执行前重新核对。直接 Artifact 引用、Brief 依赖和跨版本复用均参与传播。
- 回答和纠正生成 user_decision Evidence；纠正保留原 Claim，标记相关 Artifact 和 Plan stale。
- `dump_data(service)` / `restore_data(service, json)` 仅处理九类业务对象，不访问运行状态。
- 备份格式为 `ProjectBackup` v1；恢复要求空目标，引用或版本不一致时整体回滚，不做部分合并。
- 导出持有业务写入屏障和表锁至调用方事务结束；恢复重新建立索引列，逐个业务对象比较相等。

## 已测试

Windows / Python 3.12.16，独立 Neon test 分支。开发数据库没有执行初始化、迁移或清库操作。
本机 uv 未加入 PATH，使用等价的 `py -m uv`。

| 阶段 | 完整回归结果 |
|---|---|
| 启动时 P0 | 57 passed |
| T1 / T2 / T3 / T4 | 69 / 76 / 89 / 104 passed |
| T5 / T6 / T7 | 111 / 113 / 115 passed |
| T8 首轮 | 118 passed |
| 静态审查加固后 | 126 passed |

`ruff check .`、`ruff format --check .`、`python -m mis.schemas.export --check` 均通过。
测试先覆盖核心接口，再实现、修复失败并运行相关和完整回归；没有静默跳过数据库测试。

T7 提交已在 GitHub Actions 的 pgvector/pgvector:pg17 容器通过：
[CI 42416886952](https://github.com/Muilrz/Meta-Instrument-Studio/actions/runs/42416886952)。
最终 T8 代码提交 `9aa79e5` 在 PostgreSQL 容器中 **118 passed（1.50 s）**，全部检查成功：
[CI 42417562572](https://github.com/Muilrz/Meta-Instrument-Studio/actions/runs/42417562572)。
完整 Raman v1→v2 的补充端到端回归在本地另行通过，并包含在此最终 CI 中。
迁移模板渲染编译通过；本地测试结束后业务表记录总数为 0，回滚隔离生效。

### 验证覆盖

- 全部业务记录正反例、JSON 序列化及 Schema 一致性；量纲、有限值、缺证据拒绝。
- 空业务库 Alembic upgrade head；Neon 与 CI 均执行 SQL 初始化；mis_runtime 读业务表成功、写业务表被拒绝。
- Evidence、Baseline、Artifact、Plan 的直接非法 SQL 写入被拒绝；版本追加及旧版本读取。
- 五种比较、Unknown、范围最差值、接口一致性、must/should 汇总、带汇率引用的预算。
- 基准 v0.1.0 的 CP01–CP13：数值、Unknown、采购缺失、选择依据、库存复用与 SOP 引用。
- 8 器件手工数据在 tests/data/；SPEC-B 的异条件 SNR 不冒充 SOP 指标，SPEC-C 缺失字段保持 Unknown。
- 推荐组合 pass；SPEC-C 组合 unknown；所有示例 BOM / Claim 的来源片段确实存在于基准文件。
- 用户回答可以被后续 Claim 引用；用户纠正保留原值、生成证据并传播 stale。
- R04 与 R11 精确影响、直接引用、跨版本复用、报告复核、重复执行不增加重复历史。
- 九类对象连同需求/方案版本、状态历史、问答、纠正和 TestResult 备份恢复后逐个相等。
- 损坏引用导入整体回滚，非空目标拒绝恢复；过程不需要任何 Runtime 状态。

## 已验收

下列为自动化验收，不能替代负责人对 P1 的人工评审。

| 验收目标 | 自动验证依据 | 状态 |
|---|---|---|
| 1. 导入 Raman 得到基线 v1 | test_raman_import，11 项、单位、比较方式、FX、项目类型 | 本地及最终 CI 通过 |
| 2. 手工器件与证据复现标准答案 | test_p1_acceptance、test_rules、P0 完整性测试 | 本地及最终 CI 通过 |
| 3. v2 精确传播并保留 v1 | test_impact 的 R04/R11、复用与历史；完整 Raman v2 补充场景 | 本地及最终 CI 通过 |
| 4. Plan 追溯 Evidence 原文 | test_p1_acceptance，BOM / Claim / FX 原文与 RunRef | 本地及最终 CI 通过 |
| 5. 业务记录独立导出导入 | test_dump，九类记录、空目标恢复相等、原子回滚 | 本地及最终 CI 通过 |

P0 原有 57 项测试继续通过，fixtures/raman_baseline/ v0.1.0 没有修改。

## 尚存问题与交接

- 当前无实现或自动验收阻塞项。
- 负责人对 P1 的人工评审、合并尚未进行；ADR-0001 整体待评审状态保持不变。
- 可选 compose.yaml 在本机受 Docker 限制未运行；同镜像 PostgreSQL 容器已由 CI 验证。
- 备份是业务对象的逻辑 JSON；正式环境部署、物理备份、用户认证与多租户仍在后续阶段。
- [P2 任务草案](../plans/P2_deerflow_integration.md) 仅作阶段交接；未实现或启动 P2，时间盒、环境和上游版本等待该阶段登记。

## 依赖许可证登记

依据本地 distribution 元数据核对，版本锁定于 uv.lock。

| 依赖 | 锁定版本 | 许可证 |
|---|---|---|
| pint | 0.26.2 | BSD-3-Clause |
| pydantic | 2.14.3 | MIT |
| SQLAlchemy | 2.1.8 | MIT |
| psycopg / psycopg-binary | 3.3.8 | LGPL-3.0-only |
| Alembic | 1.20.1 | MIT |
| python-ulid | 4.1.0 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |

未来重新分发时保留各依赖许可证及二进制包内的第三方声明。

## 静态审查加固记录（2026-11-08）

本轮针对新增边界覆盖，不改变此前 118 项测试通过的事实。新增测试复现了并发重复插入的唯一约束冲突，以及 stale Brief 仍可生成 Artifact 的路径。

已实现：

- add() 项目锁后复查 ID，并用 PostgreSQL ON CONFLICT 处理冲突；相同内容返回已有对象，冲突内容返回 ValueError，调用方事务不被唯一约束错误中断。
- 新 Artifact / Plan 拒绝 stale 上游。恢复使用独立私有历史重建路径；正常 add() 不提供 allow_stale 开关。
- 按负责人确认，入口与 ImpactReport 仅允许相邻版本；保留跨版本复用的依赖传播。
- 新迁移 0002 保护 questions：仅 open → answered / cancelled、禁止改写身份与上下文、终态不可改写、禁止删除与截断，回答关联本项目 user_decision Evidence。
- 迁移角色使用 SET LOCAL，修复初始化提交后可能影响连接池复用的角色残留。

已测试：新增 8 项边界测试及 2 项恢复回归共 10 passed；完整回归 **126 passed**，ruff、格式和 Schema 一致性检查通过；本轮 [CI 42420560664](https://github.com/Muilrz/Meta-Instrument-Studio/actions/runs/42420560664) **126 passed（1.11 s）**，全部检查成功。

并发验证在默认 READ COMMITTED 下使用双连接和屏障，提交数据位于测试专用临时 schema，结束后删除该临时 schema；正式 mis 业务数据不参与。P2 运行流程的重放与幂等仍按后续计划单独验证。

本轮修复提交：`dd304c0`。Neon 测试库从 0001 升级到 0002、CI 从空库迁移到 0002 均通过；测试结束后业务表记录总数与并发测试临时 schema 数量均为 0。
