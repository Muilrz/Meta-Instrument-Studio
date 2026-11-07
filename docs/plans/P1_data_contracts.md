# P1 任务说明：核心数据契约与 Project Service

- 状态：T1–T8 实现及自动验收通过，待负责人评审；Q1–Q4 已确认，见 ADR-0003
- 日期：2026-11-05
- 修订：
  - 2026-11-08，完成 T1–T8；本地及 PostgreSQL CI 118 passed，五项自动验收通过，详见 P1_report.md
  - 2026-11-08，同步实际分支 feat/p1-core-data-contracts；明确 Q1–Q4 默认建议与确认状态，保留草案待评审状态
  - 2026-11-08，依据已确认的 C1 更新 RunRef 与 Trace 的连接边界；Trace 基础设施在 P3 实现，C2 对象不加入 P1 范围
  - 2026-11-05，数据库改为 PostgreSQL（见 ADR-0001），并相应地从 P1 起引入 Alembic
  - 2026-11-06，依据 [Agent 架构需求清单](../design/agent_architecture_requirements.md)：新增出处字段 `RunRef`（3.8）、Brief 参数分类（3.9）、用户问答 `UserQuestion`（3.10）、用户纠正 `UserCorrection`（3.11）
  - 2026-11-06，`InstrumentProject` 增加 `kind`（normal / benchmark），导入器把基准任务包导入为 benchmark 项目
  - 2026-11-06，开发数据库改为 Neon：T5 改为普通 SQL 初始化脚本 `db/init.sql` + Neon `test` 分支，`compose.yaml` 变为可选；本文件移到 `docs/plans/`
- 上级计划：[开发计划 · P1](development_plan.md#p1-核心数据契约与-project-service)
- 前置条件：P0 完成（[P0 报告](../reviews/P0_report.md)）
- 分支：`feat/p1-core-data-contracts`，按下文任务拆成多个提交或 PR

---

## 1. 这一阶段要做成什么

P1 结束时，平台应当能做到以下几件事。全程**不调用任何 LLM**，都是确定性代码：

1. 把 Raman 基准任务包的需求表导入成 `RequirementBaseline` v1。
2. 手工录入器件参数和证据后，规则引擎能对每个需求项给出 **通过 / 不通过 / 未知** 三种结论，并且与基准任务包的标准答案一致。
3. 修改一项需求得到 v2 后，系统能列出受影响的 Brief、Artifact 和 Plan，并把它们标记为 `stale`；v1 仍然可以完整读取。
4. 从 InstrumentPlan 中的任何一个结论，都能沿着引用追溯到 Evidence 记录和原文片段。
5. 所有业务记录都存在 Project Service 里，可以导出和导入，与任何 Agent 运行状态无关。

---

## 2. 范围

**范围内**

- 7 类核心对象，加上 `UserQuestion`、`UserCorrection` 和 `RunRef` 的 Pydantic 模型，以及导出的 JSON Schema
- 带单位的数值类型，以及“未知”的显式表示
- 单位换算，以及拉曼领域换算（波长 ↔ 拉曼位移、nm 分辨率 → cm⁻¹）
- 需求比较规则引擎（min / max / range / covers / enum）
- 版本管理和影响分析
- 持久化层（PostgreSQL，`mis` schema）、数据库迁移（Alembic）和服务层 API
- 数据库初始化脚本 `db/init.sql`（普通 SQL：建 schema、建账号、启用 pgvector），对 Neon 和 Docker 都能执行
- 开发数据库用 Neon（ADR-0001“部署”）；CI 用 `pgvector/pgvector:pg17` 服务容器；另提供 `compose.yaml` 给能安装 Docker 的开发者
- 基准任务包的需求导入器
- 数据导出 / 导入（备份与恢复）

**范围外**

- 任何 LLM、Agent、检索功能
- HTTP API（在 P3 确定交互入口时再加；P1 只提供 Python 服务层接口）
- 用户认证和权限（只保留 `members` 字段）
- 正式环境的数据库部署和备份策略（P1 只做本地和 CI）
- pgvector 的实际使用（P1 只确保镜像带有该扩展，向量检索在 P4 才用）

---

## 3. 关键设计决定

以下关键设计已随 2026-11-08 P1 正式启动确认；单位库与存储方式见 ADR-0003。

### 3.1 “未知”必须显式表示（原则 G2）

参数值不用 `None` 表示缺失，而是用带类型标签的联合类型：

```python
class Known(BaseModel):
    kind: Literal["known"] = "known"
    value: Quantity | QuantityRange | str      # 数值、范围或枚举值
    evidence_ids: list[EvidenceId]             # 至少 1 个，否则校验失败

class Unknown(BaseModel):
    kind: Literal["unknown"] = "unknown"
    reason: str                                # 例如 "厂商页面未给出"
    evidence_ids: list[EvidenceId] = []        # 可以指向“查过但没找到”的来源

SpecValue = Annotated[Known | Unknown, Field(discriminator="kind")]
```

规则引擎遇到 `Unknown` 时一律返回 `unknown`，**永远不返回 `pass`**。

### 3.2 规则结果采用三值逻辑

`CheckResult = pass | fail | unknown`。汇总多个需求项时：

- 只要有一项 must 级需求的结果是 `fail`，整体为 `fail`
- 否则只要有一项 must 级需求的结果是 `unknown`，整体为 `unknown`
- 只有全部 must 级需求都是 `pass`，整体才是 `pass`
- should 级需求单独列出，不影响整体结论

### 3.3 单位库用 pint，领域换算单独实现

- 通用单位换算（W ↔ mW、s ↔ ms、µm ↔ nm、°C）用 [pint](https://github.com/hgrecco/pint)（BSD 许可证），封装在 `mis.units` 中，上层代码不直接调用 pint。
- 波长与拉曼位移的换算依赖激发波长，不是普通的单位换算，放在 `mis.units.raman`：
  - `shift_cm1(excitation_nm, wavelength_nm)`
  - `wavelength_at_shift_nm(excitation_nm, shift_cm1)`
  - `resolution_nm_to_cm1(resolution_nm, at_wavelength_nm)`
- P0 测试里临时写的换算函数，在 P1 改为调用 `mis.units`。

### 3.4 记录不可修改，变更就生成新版本

- `RequirementBaseline`、`InstrumentPlan` 每次修改都生成新版本（`version` 加 1），旧版本原样保留。
- `AgentArtifact` 内容不可修改，只有 `status` 可以变化，每次变化都记一条状态历史（时间、原因、触发它的对象）。
- `Evidence` 一旦写入就不能修改，也不能删除。

### 3.5 依赖关系精确到需求项

影响分析按**需求项**计算，而不是按整个需求版本，否则改一项就会导致全部失效：

- `AgentTaskBrief.requirement_refs`：这个任务依赖哪些需求项，例如 `["R03", "R04"]`
- `AgentArtifact.requirement_refs`：这个产物涉及哪些需求项
- `InstrumentPlan.artifact_ids`：方案用到了哪些产物

需求从 v1 变到 v2 时：

```text
计算发生变化的需求项（新增 / 删除 / 修改）
  → 引用了这些项的 Brief          → 标记 stale
  → 这些 Brief 产出的 Artifact，
    以及直接引用这些项的 Artifact  → 标记 stale
  → 包含 stale Artifact 的 Plan   → 标记 stale
```

影响分析先生成一份 `ImpactReport`（列出将被标记的对象和原因），然后由调用方决定是否执行标记。

### 3.6 存储采用“文档 + 索引列”的方式

- 用 SQLAlchemy 2.x 加 PostgreSQL（驱动 psycopg 3），所有表放在 `mis` schema 中。每类对象一张表，包含少量索引列（`id`、`project_id`、`version`、`status`、`created_at`），完整内容以 `JSONB` 存在 `body` 列中。
- 从第一张表起就用 Alembic 管理表结构变更。因为 PostgreSQL 从开发第一天就是正式数据库，里面的数据会一直保留，每次改表都应当有迁移脚本。对象内部字段的变化仍由 Pydantic 处理，不需要改表。
- 测试连接独立的测试数据库，每个测试在事务中运行并回滚，互不影响。本地没有运行数据库时，数据库相关的测试应明确报错并提示启动方法，而不是静默跳过。
- ID 格式为带类型前缀的 ULID，例如 `req_01J…`、`art_01J…`、`evd_01J…`，便于从日志中看出对象类型。

### 3.7 汇率是一条证据

预算计算中的外币换算，必须引用一条 `source_type = fx_rate` 的 Evidence，内容包括汇率、日期、来源。基准任务包使用 `manifest.yaml` 中的固定汇率，导入时生成这条 Evidence。

### 3.8 出处字段：业务记录与 trace 的连接

[Agent 架构需求清单](../design/agent_architecture_requirements.md) C1 已确定 Trace 标准、数据粒度、存储方式和保留策略：采用 OpenTelemetry Trace + GenAI Semantic Conventions，关键业务 Span 100% 采集，PostgreSQL `trace` schema 分离骨架与 Payload，骨架永久保留，内容按运行类型保留。

业务记录与 Trace 统一通过 `RunRef` 关联。P1 只定义和存储 RunRef，不负责生成 Trace，不实现 Trace Collector、Span 采集、Payload 存储和 Trace Viewer；实际 Trace 基础设施在 P3 实现。C2 的 ExperienceMemory、MemoryUsageEvent、MemoryScoreHistory 不加入 P1 核心数据模型范围，数据契约与实际实现安排在 P3～P5（P2 先做架构设计）。

RunRef 字段：

| 字段 | 含义 |
|---|---|
| `run_id` | 一次规划运行的 ID |
| `trace_id` | OpenTelemetry Trace ID，P1 阶段允许为空 |
| `actor` | 产生者：copilot / lab / research / procurement / rule_engine / user |
| `model` | 使用的模型名称和版本，非模型产生时为空 |
| `skill_versions` | 使用的技能及其版本，例如 `{"raman_resolution": "1.2.0"}` |
| `prompt_version` | 提示词版本 |

挂载位置：

- `AgentArtifact.produced_by: RunRef`
- `Evidence.retrieved_by: RunRef`，外加 `tool_call_id`（由哪次工具调用取得）
- `AgentTaskBrief.usage`：实际消耗，包括耗时、输入和输出 token 数、搜索次数、费用
- `InstrumentPlan.produced_by: RunRef`

### 3.9 Brief 中区分指定参数与不定参数

依据需求清单 A3：Copilot 下发任务前，必须把参数分为两类，Specialist 之间不直接沟通。

- `specified_params`：需求明确要求的参数，每项都要关联需求项编号（如 R04），带目标值和单位。
- `open_params`：需求没有要求的参数，Specialist 可以自由选择，但必须报告实际值；只列参数名称和期望的单位。

校验规则：

- `specified_params` 中引用的需求项必须存在于对应版本的需求基线里。
- 同一个参数不能同时出现在两个列表中。

相应地，Procurement 类的 Artifact 允许包含**多个候选**，每个候选都列出所有指定参数的已知值或未知值，由 Copilot 取舍。

### 3.10 用户提问与回答

依据需求清单 A4：Copilot 可以在规划中途向用户提问。问答属于项目记忆，存在业务数据库，新增对象 `UserQuestion`：

- 用户的回答写成一条 `source_type = user_decision` 的 Evidence，后续结论可以引用它。
- 运行的暂停和恢复由运行层负责（P2/P3），P1 只负责存储问题和回答。

### 3.11 用户纠正结论

依据需求清单 A2：“用户纠正了某个结论”是经验的触发事件之一，也是 A8 中“确认过的错误”的主要来源，因此纠正必须作为业务记录保存，新增对象 `UserCorrection`：

- 纠正针对某个 Artifact 中的某条 Claim，所以 `Claim` 需要有稳定的 `claim_id`。
- 纠正后的值仍然是 `SpecValue`，可以是新的已知值，也可以改为未知。
- 纠正时生成一条 `source_type = user_decision` 的 Evidence，记录纠正内容和理由。
- 原 Artifact 内容不变（3.4），但状态变为 `stale`，状态历史记录原因为“用户纠正”；包含它的 Plan 同样标记为 `stale`，复用 3.5 的影响传播。
- P1 只负责存储纠正和标记 stale；纠正的入口（命令行、页面）和触发候选经验在 P3 及之后实现。

---

## 4. 对象字段（初稿）

开工后以代码为准。字段有调整时，同步更新这一节。

| 对象 | 字段 |
|---|---|
| `InstrumentProject` | `id`、`name`、`kind`（normal / benchmark，基准任务项目默认不参与“同类问题反复出现”的计数）、`members`、`knowledge_scope`（可用的资料范围）、`current_baseline_version`、`current_plan_version`、`created_at` |
| `RequirementBaseline` | `id`、`project_id`、`version`、`items[]`、`budget`、`created_at`、`change_note` |
| `RequirementItem` | `key`（如 R04）、`name`、`metric`（指标键）、`comparator`、`lower`、`upper`、`allowed`（枚举）、`unit`、`priority`、`verification` |
| `AgentTaskBrief` | `id`、`project_id`、`baseline_version`、`requirement_refs`、`specialist`（lab / research / procurement）、`goal`、`specified_params`、`open_params`、`constraints`、`acceptance`、`budget`（时间、搜索次数、模型调用次数）、`usage`（实际消耗）、`status` |
| `AgentArtifact` | `id`、`project_id`、`brief_id`、`artifact_type`、`requirement_refs`、`candidates[]`（可选，多候选时使用）、`claims[]`、`assumptions`、`open_questions`、`produced_by: RunRef`、`status`、`status_history` |
| `Claim` | `claim_id`、`statement`、`subject`（如器件 ID）、`metric`、`value: SpecValue`、`evidence_ids`（属于 Artifact 的一部分） |
| `Evidence` | `id`、`source_type`（document / web / vendor_api / fx_rate / measurement / user_decision）、`locator`（URL 或文档 ID）、`excerpt`（原文片段）、`page_or_anchor`、`retrieved_at`、`source_version`、`retrieved_by: RunRef`、`tool_call_id`；报价类另加 `quote`：`currency`、`price_tiers`、`region`、`valid_until` |
| `InstrumentPlan` | `id`、`project_id`、`version`、`baseline_version`、`artifact_ids`、`modules[]`、`bom[]`、`rationale`、`risks`、`stage2_tasks`、`check_summary`、`produced_by: RunRef`、`status` |
| `UserQuestion` | `id`、`project_id`、`run_id`、`brief_id`（可选）、`question`、`options`（可选）、`context`（为什么要问）、`answer`、`answered_at`、`answer_evidence_id`、`status`（open / answered / cancelled） |
| `UserCorrection` | `id`、`project_id`、`artifact_id`、`claim_id`、`original_value: SpecValue`、`corrected_value: SpecValue`、`reason`、`evidence_id`（user_decision）、`corrected_by`、`created_at` |
| `TestResult` | `id`、`project_id`、`requirement_key`、`plan_version`、`measured: SpecValue`、`verdict`、`evidence_ids`（P1 只定义，P7 才使用） |

---

## 5. 模块布局

```text
src/mis/
├─ ids.py                  带前缀的 ULID
├─ units/
│  ├─ __init__.py          Quantity、convert()，封装 pint
│  └─ raman.py             波长 / 位移 / 分辨率换算
├─ schemas/
│  ├─ values.py            Known / Unknown / SpecValue / QuantityRange
│  ├─ project.py           InstrumentProject
│  ├─ requirements.py      RequirementBaseline / RequirementItem
│  ├─ tasks.py             AgentTaskBrief
│  ├─ artifacts.py         AgentArtifact / Claim
│  ├─ evidence.py          Evidence
│  ├─ plan.py              InstrumentPlan
│  ├─ questions.py         UserQuestion / UserCorrection
│  ├─ provenance.py        RunRef
│  ├─ testing.py           TestResult
│  └─ export.py            导出 JSON Schema 到 docs/schemas/
├─ rules/
│  ├─ compare.py           单个需求项比较，返回 CheckResult
│  └─ evaluate.py          对器件组合或方案汇总三值结论
├─ project_service/
│  ├─ db.py                SQLAlchemy 表定义和会话
│  ├─ repository.py        增删查、版本、状态历史
│  ├─ impact.py            需求差异 → ImpactReport → 标记 stale
│  └─ dump.py              导出 / 导入
└─ importers/
   └─ raman_baseline.py    requirements.csv + manifest → 项目、需求 v1、汇率证据

migrations/                Alembic 迁移脚本（仓库根目录）
db/init.sql                数据库初始化脚本（schema、账号、pgvector）
compose.yaml               可选：本地 Docker 运行 PostgreSQL（pgvector/pgvector:pg17）
```

---

## 6. 任务拆分

按顺序执行。每个任务都应当能单独提交、单独通过 CI。

| 编号 | 任务 | 完成标志 |
|---|---|---|
| T1 | `mis.units` 和 `mis.units.raman`，P0 测试改为调用它们 | 基准任务包涉及的单位（nm、µm、cm⁻¹、mW、W、ms、s、°C、CNY）都有换算测试；CP05、CP06 的数值由新模块复算通过 |
| T2 | `schemas/values.py`：Known / Unknown / Quantity / QuantityRange | `Known` 缺证据会被拒绝；量纲不符（例如给功率字段填 nm）会被拒绝 |
| T3 | 其余 7 类对象、`UserQuestion`、`UserCorrection`、`RunRef` 的 schema，以及 JSON Schema 导出 | 每类对象都有正例和反例测试；CI 检查导出的 JSON Schema 与代码一致 |
| T4 | `rules/`：5 种比较方式加三值汇总 | 见第 7 节的“规则复现标准答案” |
| T5 | `db/init.sql`、Neon `test` 分支、Alembic 初始迁移、CI 数据库服务、可选的 `compose.yaml`；`project_service`：表定义、仓储、版本、状态历史 | `db/init.sql` 能在 Neon 和 CI 容器上执行成功，并建出 ADR-0001“数据库布局”中的 schema 和三个账号；用 `mis_runtime` 修改 `mis` 中的数据会被拒绝；`alembic upgrade head` 能从空库建出全部表；增删查测试；修改需求生成新版本、旧版本可读；Artifact 内容无法被修改；CI 中数据库测试通过 |
| T6 | `impact.py`：需求差异和影响分析 | 见第 7 节的“影响分析” |
| T7 | 导入器，以及手写的 Raman 示例数据（`tests/data/`） | 需求 v1 导入后共 11 项，单位和比较方式都正确；默认导入为 `kind = benchmark` 的项目，也可以指定导入为 normal 项目（供 P3 的触发测试使用）；示例 Artifact 和 Plan 能写入并读出 |
| T8 | 导出 / 导入，以及 P1 阶段报告 | 见第 7 节的“备份恢复”；完成 `docs/reviews/P1_report.md` |

T7 中的示例数据，是**假设一个完美的 Specialist 会产出什么**：按器件页面和报价手工录入 8 个器件的结构化参数，录成 Claim 和 Evidence。它放在 `tests/data/`，不放进基准任务包，避免修改 v0.1.0 的标准答案。

---

## 7. 验收标准

以下内容都要用自动化测试实现，并在 CI 中运行。

### 规则复现标准答案

用 T7 的示例数据跑规则引擎，结果必须与 `checkpoints.yaml` 一致：

- [x] CP02：LAS-A 线宽 → `pass`
- [x] CP03：LAS-B 功率 0.35 W 对比 ≥ 450 mW → `fail`
- [x] CP04：LAS-C 线宽 2 nm → `fail`
- [x] CP05：SPEC-B 分辨率 0.6 nm 换算到 R02 全范围 → `fail`
- [x] CP06：SPEC-A 波长范围覆盖 200–2000 cm⁻¹ → `pass`
- [x] CP07、CP08：SPEC-C 的制冷温度、信噪比为 `Unknown` → `unknown`，**不是 `pass`**
- [x] CP10：SPEC-D 单件预算 → `fail`
- [x] CP11：LAS-A + SPEC-A + PRB-A 的组合，预算为 `pass`，且 must 级需求汇总结果为 `pass`
- [x] 包含 SPEC-C 的组合，must 级需求汇总结果为 `unknown`

### 拒绝非法数据

- [x] `Known` 值没有证据时，创建失败
- [x] 量纲错误时（例如功率字段的单位是 nm），创建失败
- [x] Claim 引用了不存在的 Evidence ID 时，写入失败
- [x] Brief 的 `specified_params` 引用了基线中不存在的需求项，或同一参数同时出现在指定和不定两个列表中时，创建失败

### 出处与问答

- [x] 示例 Artifact、Evidence、Plan 都带 `RunRef`，能按 `run_id` 查出同一次运行产生的全部业务记录
- [x] 写入一个 `UserQuestion` 并回答后，生成 `user_decision` 类型的 Evidence，后续 Claim 可以引用它
- [x] 对示例 Artifact 中 SPEC-C 的一条 Claim 写入 `UserCorrection` 后：生成 `user_decision` Evidence；原 Artifact 内容不变、状态变为 `stale`，包含它的 Plan 也变为 `stale`；纠正前后的值都能读出

### 版本与影响分析

- [x] 把 R04 从 ≥ 450 mW 改为 ≥ 300 mW 生成需求 v2 后，`ImpactReport` 只列出引用 R04 的 Brief、Artifact 及包含它们的 Plan，引用其他需求项的对象不受影响
- [x] 执行标记后，这些对象的状态变为 `stale`，状态历史记录了原因（“需求 v1 → v2，R04 变更”）
- [x] v1 的需求和 Plan 仍然可以完整读取，内容不变

### 证据追溯

- [x] 对示例 Plan 中的每个 BOM 条目和每条 Claim，都能沿 `Plan → Artifact → Claim → Evidence` 找到原文片段，并且该片段确实出现在基准任务包对应的文件里
- [x] 预算计算引用了汇率 Evidence

### 备份恢复（原则 G1）

- [x] 导出全部数据 → 清空数据库 → 导入，前后所有对象逐个相等
- [x] 这个过程不需要任何 Agent 运行状态参与

### 工程

- [x] `uv run pytest`、`ruff check`、`ruff format --check` 本地和 CI 都通过
- [x] 新增依赖（pydantic、pint、sqlalchemy、psycopg、alembic、python-ulid）的许可证登记在 P1 报告中
- [x] README 写明开发数据库的连接方法（Neon，`.env`），以及可选的本地 Docker 方法

---

## 8. 风险与注意事项

| 风险 | 应对 |
|---|---|
| schema 设计过细，P3 接入 Agent 时发现不好用 | P1 只做到能表达基准任务包所需的程度；字段命名保持通用，P2 Spike 期间收集反馈，在 P3 开始前允许一次不兼容的调整 |
| pint 对 cm⁻¹、°C 等单位的处理有坑（例如温度是偏移量，不能直接乘除） | T1 先写测试；温度比较只做同单位比较，或者统一换算到 K |
| “stale”传播过宽或过窄 | 用第 7 节的 R04 用例固定预期；再增加一个“只改 R11 预算”的用例 |
| 示例数据与基准任务包不一致 | 测试中校验示例 Evidence 的原文片段确实出现在任务包对应的文件里 |

---

## 9. 启动决策确认记录

2026-11-08，项目负责人在 P1 启动会话中明确确认以下事项，已同步 ADR-0003。

| 编号 | 问题 | 默认建议 | 确认状态 |
|---|---|---|---|
| Q1 | 是否用 pint 做单位换算 | 使用 pint | 已确认，2026-11-08，项目负责人 |
| Q2 | P1 是否做 HTTP API | 不做，留到 P3 | 已确认，2026-11-08，项目负责人 |
| Q3 | 存储采用“文档 + 索引列”，用 PostgreSQL，从 P1 起引入 Alembic | 文档 + 索引列，使用 Alembic | 全部已确认，2026-11-08，项目负责人 |
| Q4 | 示例结构化器件数据是否放在 `tests/data/` | 放在 `tests/data/`，不修改基准任务包 | 已确认，2026-11-08，项目负责人 |

## 10. 实施进度（2026-11-08）

- T1：已实现并通过本地回归：69 passed；ruff 检查及格式化通过。
- T2：已实现并通过本地回归：76 passed；含缺证据、非法单位、量纲转换拒绝、序列化和 JSON Schema。
- T3：已实现；模型正反例、序列化与 Schema 导出一致性测试通过。跨记录引用待 T5 服务校验。
- T4：核心规则已实现并通过本地完整回归：104 passed；完整数据库场景验收待 T5–T7。
- T5：已实现；独立 Neon test 分支初始化和迁移成功；完整回归 111 passed，含角色权限、不可变约束及版本测试。CI 数据库服务已配置，远程结果待运行。
- T6：已实现；R04/R11 精确传播、直接 Artifact 依赖、跨版本复用、报告复核和重放测试通过；完整回归 113 passed。
- T7：已实现；基准包导入、8 器件样例、13 个检查点、Plan 出处链、用户问答和纠正测试通过；完整回归 115 passed。
- T8：逻辑导出/导入、空目标恢复与原子失败已实现；本地及最终 PostgreSQL CI 均为 118 passed，五项自动验收通过；待负责人评审。

### 实现字段补充

- Evidence 增加必填 project_id，以便 Project Service 校验项目范围；fx_rate 包含结构化币种、汇率、日期。
- Claim 的证据 ID 统一存于 value.evidence_ids，Claim.evidence_ids 为只读访问属性，避免双份引用不一致。
- InstrumentPlan 的 modules/rationale 使用带 ClaimRef 的 PlanConclusion；BOM 使用带 ClaimRef 的 BomEntry；每条引用包含 artifact_id、claim_id。
- Brief 和 Plan 增加 status_history；SpecifiedParam.target 使用完整 RequirementItem，服务写入时与基线核对。
- 所有模型禁止额外字段，冻结实例，列表型业务内容用 tuple；JSON 仍序列化为数组。
- Schema 导出命令：`uv run python -m mis.schemas.export`；CI 用 `--check` 检查。

- 最终代码 CI：[42417562572](https://github.com/Muilrz/Meta-Instrument-Studio/actions/runs/42417562572)。
- ProjectBackup v1 为九类业务对象的逻辑备份；ClaimTrace 表达业务出处链，均导出 JSON Schema。

## 11. 静态审查边界加固（2026-11-08）

负责人已确认 Impact Analysis 限定相邻版本；契约同步 [ADR-0003](../adr/0003-p1-units-and-storage.md)。

- 并发同 ID 同内容写入：项目锁后复查，并使用 PostgreSQL ON CONFLICT；不同内容返回 ValueError，事务仍可使用。测试以两个独立连接、真实提交、同步屏障复现窗口，数据隔离在测试专用临时 schema。
- 新 Artifact / Plan 拒绝 stale 上游；历史读取与空目标备份恢复保持可用，恢复入口不作为新业务写入的通用开关。
- analyze() 和 ImpactReport 均拒绝跳级版本，继续检查更早版本复用对象。
- Alembic 0002 为 questions 增加内容、状态和删除保护；0001 保持不变。迁移角色使用 SET LOCAL，避免提交后影响连接池的下一次使用。
- 新增并发、stale、相邻版本和问答 SQL 保护测试；恢复兼容性与完整回归结果见阶段报告。
