# P1 阶段报告：核心数据契约与 Project Service

- 日期：2026-11-08
- 状态：进行中；T1–T4 实现及本地测试通过，T5 已在独立测试数据库验证，继续 T6–T8
- 本报告为阶段进度记录，**不是 P1 完成或验收通过声明**。
- 分支：`feat/p1-core-data-contracts`

## 已实现

| 任务 | 实现 | 独立提交 |
|---|---|---|
| T1 | pint 单位封装、Raman 换算，P0 改用正式模块 | `4fd8f20` |
| T2 | Known / Unknown / Quantity / QuantityRange，显式未知和证据约束 | `a4b94d0` |
| T3 | 9 类业务记录、RunRef、Claim 引用及 JSON Schema；CI 一致性检查 | `beafc06` |
| T4 | min / max / range / covers / enum；三值汇总；Raman 上下文；预算与 FX 引用 | 随本报告提交 |

Q1–Q4 已由负责人在本次启动会话明确确认，见 [ADR-0003](../adr/0003-p1-units-and-storage.md)。
业务代码不依赖 DeerFlow，不调用 LLM，没有实现 HTTP API、Agent、RAG 或 Trace 基础设施。

### 已实现的接口边界

- `convert(value, source, target)`：兼容量纲转换；外币不能当作普通单位直接互转。
- `compare(requirement, value, context=...)`：包含边界；缺资料返回 unknown，非法量纲抛 ValueError。
- `evaluate(baseline, values, context=...)`：调用方按需求项提供所有适用器件的值；缺项仍为 unknown，should 不改变 must 汇总；光纤接口还需彼此一致。
- `budget_total(prices, fx_evidence)`：单件价格求和，USD 需要结构化汇率 Evidence，结果保留价格及汇率证据 ID。
- RamanContext 显式提供激发波长和评价范围；nm 分辨率取范围两端换算的最差值。
- 模型与规则仅做结构和数值验证；Evidence 存在性、跨项目引用、Brief 与基线核对、不可变数据库记录须由 T5 实现。

## 已测试

Windows / Python 3.12.16，使用 `py -m uv`（本机 uv 未加入 PATH）：

| 检查 | 结果 |
|---|---|
| 启动时 P0 回归 | 57 passed |
| T1 完整回归 | 69 passed |
| T2 完整回归 | 76 passed |
| T3 完整回归 | 89 passed |
| T4 完整回归 | 104 passed |
| `ruff check .` | 通过 |
| `ruff format --check .` | 通过 |
| `python -m mis.schemas.export --check` | 通过 |

新增任务先加入测试并观察缺失模块失败，再实现并运行相关测试与完整回归。
测试覆盖模型正反例、JSON 序列化、Schema 导出、量纲错误、缺证据、五种比较方式、
Raman 分辨率/覆盖、must 失败优先于未知、should 未知不影响 must、预算缺汇率不通过、接口不一致。
规则测试包含 CP02–CP08、CP10–CP11 对应数值场景；11 项需求的手工事实可得推荐组合 pass、
SPEC-C 组合 unknown。当前事实在规则测试内，T7 将建立完整的 8 器件 Claim / Evidence 示例。

未推送或触发远程 CI；本地通过不等于 CI 已通过。

## 已验收

- 本地自动化验证已确认 T1–T4 的上述单元行为；P0 原有 57 项测试保持通过。
- **P1 五项整体验收均未完成**：尚无持久化的基线 v1 导入、完整 8 器件证据链、v2 影响传播、Plan 原文追溯和数据库导出恢复结果。
- 人工验收尚未进行；P0 报告中的 ADR-0001 整体待评审状态保持不变。

## 尚存问题与下一步

1. `.env` 尚未配置独立 Neon test 分支的 `MIS_TEST_DATABASE_URL`。负责人已说明稍后自行配置，并要求必要时停下等待。
2. 当前停在 T5 前：未连接或修改开发库，未执行迁移、角色授权或清库操作。后续数据库测试不能静默跳过。
3. T5：SQL 初始化、schema / 三账号权限、Alembic、表与 Project Service、引用校验、不可变内容和版本历史。
4. T6：需求差异、ImpactReport、R04 与 R11 影响传播及 stale 历史。
5. T7：11 项需求导入 v1、FX Evidence、8 器件手写示例、问答和纠正、Plan 原文追溯与全部标准答案验收。
6. T8：独立业务导出 / 导入、空测试库恢复相等、CI PostgreSQL 验证与本报告最终更新。

T5–T8 **未实现、未测试、未验收**。独立测试库配置后从 T5 接续，不重做已通过部分。

## 依赖许可证登记

核对依据：本地已安装 distribution 元数据；版本锁定在 `uv.lock`。

| 依赖 | 锁定版本 | 许可证 |
|---|---|---|
| pint | 0.26.2 | BSD-3-Clause |
| pydantic | 2.14.3 | MIT |
| SQLAlchemy | 2.1.8 | MIT |
| psycopg | 3.3.8 | LGPL-3.0-only |
| psycopg-binary | 3.3.8 | LGPL-3.0-only |
| Alembic | 1.20.1 | MIT |
| python-ulid | 4.1.0 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |

数据库相关依赖已锁定，为后续 T5 准备；依赖安装成功不代表数据库功能已实现。
psycopg 及其二进制分发的 LGPL 声明需随未来分发保留；部署或重新分发时仍需核对所用平台二进制包内第三方声明。

## T5 接续记录

2026-11-08：负责人已配置独立 Neon test 分支。连接、pgvector、建 schema 和角色权限检查通过；从无业务表状态迁移至 head 成功。T5 完整回归 111 passed，ruff 和 Schema 检查通过。已实现仓储、引用/项目范围校验、版本追加、状态历史及数据库不可变触发器；mis_runtime 写入被数据库拒绝。初始化和测试只使用测试端点，开发库未修改。CI PostgreSQL 服务已配置，远程验证待执行。
