# MetaInstrumentStudio 开发计划（v0.2.8）

- 状态：草案，待评审
- 日期：2026-11-05
- 修订记录：
  - v0.1（2026-11-05）：初稿
  - v0.2（2026-11-05）：数据库统一为 PostgreSQL，新增存储总览（0.4 节）；P2 增加 Agent 架构设计（context / memory / skills / 自进化）；P3 增加只读查看页面和最小 HTTP 接口；P5 改为正式产品界面
  - v0.2.1（2026-11-06）：P2 改为以《Agent 架构需求清单》为输入，选型考察项增加“暂停等待用户”和 trace；D2 注明无数据安全限制
  - v0.2.2（2026-11-06）：经验晋升池分阶段落地——P3 记录触发事件并在查看页面展示，P4 去重与冲突检测，P5 审核页面；自进化增加“失败案例转为考题”（A8）
  - v0.2.3（2026-11-06）：P3 只记录 4 类触发事件并新增命令行纠正入口；为 P3/P4/P5 的经验相关工作补充验收标准；存储总览加入 trace 和晋升池
  - v0.2.4（2026-11-06）：“同类问题反复出现”改为按不同项目计数，P3 的触发与不误触发验收相应调整
  - v0.2.5（2026-11-06）：开发数据库改为 Neon 云数据库；文档统一移到 `docs/`，本文件由 `plans/MIS_Development_Plan_v0.1.md` 改名为 `docs/plans/development_plan.md`；新增 D10
  - v0.2.6（2026-11-08）：落实已确认的 C1 Trace 与 C2 经验评分、生命周期管理，更新存储边界和 P2/P3/P4/P5/P7 范围与验收；P1 不提前承担相关基础设施
  - v0.2.7（2026-11-08）：依据 ADR-0002 采用 DeerFlow Backend + MIS 自研 React UI / Backend；P2 改为 DeerFlow 优先集成验证，失败才评估替代方案；同步 P3/P5 与运行接口边界
  - v0.2.8（2026-11-08）：补充 P4/P5 经验治理持久化对象、审核审计关系及 MemoryUsageEvent 幂等验收；不扩大 P1 范围
- 依据：
  - [`docs/architecture.md`](../architecture.md)：目标架构
  - [`docs/research/MIS_Open_Source_Baseline_Research_2026-11-01.md`](../research/MIS_Open_Source_Baseline_Research_2026-11-01.md)：开源 baseline 选型调研

技术路线以 [ADR-0002](../adr/0002-agent-runtime-and-integration.md) 为准，模块接口以 [Agent 内部架构设计](../design/agent_architecture.md) 为基线；历史调研保留原样，不作为尚未完成选型的依据。

本文只规定**阶段划分、每阶段做什么 / 不做什么、怎样算完成**。具体工期、人员、技术细节在各阶段启动时，另写阶段任务说明（`docs/plans/Px_*.md`）。

---

## 0. 总体策略

### 0.1 开发顺序

先做 Stage 1（设计智能），再接 Stage 2（工程开发），最后闭合测试与 Re-plan 回路。

Stage 1 内部的顺序是：

```text
数据契约 → Agent 架构设计 + DeerFlow 集成验证 → 用模拟数据跑通闭环（附只读查看页面）→ 接真实数据源 → 正式产品界面
```

理由：

- `InstrumentProject` 等数据对象是平台的核心资产，不随 Agent 框架变化，应当最先确定，并且独立于框架。
- 已确定 DeerFlow Backend 为 V1 技术路线（ADR-0002）。先用固定任务做 Integration Spike，验证关键门槛；失败时记录证据，再启动替代方案评估，不再要求两个框架完整实现后才选型。
- 先用固定材料和模拟厂商数据跑通闭环，这样测试可以重复执行；真实数据源最后再接。

### 0.2 全程不变的原则

| 编号 | 原则 |
|---|---|
| G1 | **业务记录与运行状态分离**。需求、方案、证据存在 Project Service；Agent 执行进度存在运行层的 checkpoint。删掉运行层数据，不能丢失任何业务记录。 |
| G2 | **未知就标未知**。没找到的参数记为 `unknown` / `待确认`，不允许 Agent 自动填成“满足要求”。 |
| G3 | **结论必须有证据**。每个关键参数和设计结论都要能追溯到来源，包括文档片段 / 网页、页码或位置、获取时间。 |
| G4 | **硬约束由规则判定**。单位、范围、指标是否达标由确定性代码检查；模型只负责解释取舍。 |
| G5 | **以项目为单位复用开源代码**。通过依赖、适配器或接口集成，不把上游内部文件零散复制进来。引入任何组件前先核对许可证。 |
| G6 | **每个阶段都有可重复执行的验收**。验收以自动化测试或固定脚本为主，人工评审只作补充。 |

### 0.3 基准验收任务（贯穿各阶段）

P0 建立一个固定的 **Raman 仪器方案任务包**，作为后续所有阶段的统一验收输入：

- 一份需求表：指标、单位、容差、预算、验收方法
- 少量实验室内部文档（可以脱敏或虚构）
- 若干篇论文或技术资料
- 已知器件的页面快照
- 模拟的厂商响应：价格阶梯、库存、交期，并刻意包含缺失字段和单位不一致的情况
- 若干个“标准答案”检查点：哪些参数必须找到、哪些必须标为未知、哪些器件必须被规则排除

### 0.4 存储（统一使用 PostgreSQL）

从 P1 起，开发、测试、CI 和正式环境都使用 **PostgreSQL 17 + pgvector**，不使用 SQLite。开发环境使用 **Neon 云数据库**（新加坡；公司电脑不能安装 Docker），CI 使用 Docker 服务容器，以 CI 结果为准。平台所有需要存储的地方，原则上都放进同一个 PostgreSQL 实例：

| 存什么 | 引入阶段 | 存在哪里 |
|---|---|---|
| 业务记录（项目、需求、任务、产物、证据、方案、测试结果） | P1 | PostgreSQL，`mis` schema |
| Agent 运行状态（进度、断点、消息） | P2/P3 | PostgreSQL，独立 schema |
| Trace 与预算记录（Skeleton / Payload 分表，Hash 去重） | P3 | PostgreSQL `trace` schema；OpenTelemetry Trace + GenAI Semantic Conventions；关键业务 Span 100% 采集，保留策略遵循 C1 |
| 经验晋升池、评分、使用事件、评分历史、生命周期和人工审核记录 | P3 契约与候选事件；P4 基础设施；P5 审核与管理；P7 测试反馈 | PostgreSQL `knowledge` schema，遵循 A2/C2 |
| 知识库及向量索引（实验室知识 + 经验记忆共同检索） | P4 | PostgreSQL `knowledge` schema + pgvector；D5 仅决定连接器方案，不改变统一知识库存储边界 |
| 外部调用缓存 | P4 | PostgreSQL 表 |
| 原始文件（PDF、网页快照） | P4 | 本地文件夹，数据库存路径和哈希 |
| 用户与登录 | P5 | PostgreSQL |

详细说明见 [ADR-0001 存储总览](../adr/0001-repo-structure-and-stack.md#存储总览)。

---

## 1. 阶段总览

```text
P0 工程基础与基准任务包
 └→ P1 核心数据契约与 Project Service
      └→ P2 Agent 架构设计与 DeerFlow 集成验证（Spike）
           └→ P3 Stage 1 最小闭环（模拟数据）+ 只读查看页面
                └→ P4 真实数据源接入
                     ├→ P5 正式产品界面：Project / Conversation Workspace
                     └→ P6 Stage 2 衔接：InstrumentPlan → 工程工具
                          └→ P7 测试验证与 Re-plan 闭环
                               └→ P8+ 扩展（UpperPC、更多工程工具、多用户与部署）
```

P1 与 P2 可以部分并行：P2 的 Spike 可以先用 P1 的草稿 schema。P5 与 P6 在 P4 之后可以并行。

| 阶段 | 回答的问题 | 主要产出 |
|---|---|---|
| P0 | 怎么协作、怎么验收？ | 仓库骨架、CI、基准任务包 |
| P1 | 平台记录什么？ | 7 类核心对象的 schema、规则校验、Project Service |
| P2 | 已选 DeerFlow 能否满足 MIS 集成要求？ | Agent 架构设计定稿 + DeerFlow 集成验证报告 + ADR-0002 验证记录 |
| P3 | Stage 1 能不能端到端跑通？ | 从需求到 InstrumentPlan 的闭环（模拟数据），只读查看页面 |
| P4 | 能不能用真实资料工作？ | 知识库、研究、采购三类真实连接器 |
| P5 | 用户怎么用？ | 正式的 Web 工作空间 |
| P6 | 方案怎么交给工程？ | Plan 导出 + 至少一个 Stage 2 工具读取它 |
| P7 | 测试失败了怎么办？ | TestResult → 影响分析 → Re-plan |

---

## 2. 各阶段详述

### P0 工程基础与基准任务包

**目标**：建立统一的仓库结构、开发规范和验收输入，让后续每个阶段都能被客观检验。

**范围内**

- 仓库目录结构，例如 `services/`、`schemas/`、`adapters/`、`fixtures/`、`docs/plans/`、`docs/reviews/`、`docs/adr/`
- 主语言与工具链：Python 后端，TypeScript 前端，待 ADR 确认
- 依赖管理、lint、格式化、单元测试框架、CI
- ADR 模板，以及第一份 ADR：仓库结构与技术栈
- 0.3 节所述的 Raman 基准任务包，放在 `fixtures/raman_baseline/`，带版本号
- 敏感信息管理约定：API key 不进仓库，`.env.example` 只写变量名

**范围外**

- 任何 Agent、LLM 调用和业务逻辑
- 前端界面

**验收标准**

- [ ] 新成员按 README 一条命令即可装好依赖，并跑通空测试套件
- [ ] CI 在每次提交时运行 lint 和测试，当前主干为绿
- [ ] 基准任务包包含 0.3 列出的全部 6 类材料，并有一份 `README` 说明每个检查点的预期结果
- [ ] 基准任务包中至少包含：1 个必须标为未知的参数、1 个单位不一致的器件、1 个超预算或不达标、必须被排除的器件
- [ ] ADR-0001 已评审通过

---

### P1 核心数据契约与 Project Service

> 任务说明：[P1_data_contracts.md](P1_data_contracts.md)

**目标**：把架构文档第 8 节的数据对象变成可校验、带版本的 schema 和服务。这一阶段完全不涉及 LLM。

执行记录（2026-11-08）：T1–T8 已实现，首轮 118 passed；静态审查加固后本地及 PostgreSQL CI 126 passed；五项自动验收通过，待负责人评审。见 [P1 阶段报告](../reviews/P1_report.md)。

**范围内**

- 以下对象的 schema 定义，用 Pydantic 或 JSON Schema，并导出供前端或其他语言使用：

  | 对象 | 关键字段（初稿） |
  |---|---|
  | `InstrumentProject` | 项目 ID、名称、成员、资料范围、当前需求版本、当前方案版本、关联工程产物 |
  | `RequirementBaseline` | 版本号、需求项列表（指标、单位、目标值 / 范围、容差、优先级、验收方法）、预算 |
  | `AgentTaskBrief` | 任务 ID、目标 Specialist、依赖的需求版本、目标、约束、验收条件、时间与调用预算 |
  | `AgentArtifact` | 产物类型、结论、证据 ID 列表、假设、未决问题、状态（draft / accepted / rejected / stale） |
  | `Evidence` | 来源类型、URL 或文档 ID、页码 / 片段、获取时间、文档版本；报价类另有币种、数量阶梯、区域、有效期 |
  | `InstrumentPlan` | 版本号、依据的需求版本、模块方案、候选 BOM、取舍依据、风险、Stage 2 任务清单 |
  | `TestResult` | 对应的需求项、测量值与单位、通过 / 失败、证据、关联的方案版本 |

- 确定性规则校验：必填字段、证据引用存在、单位换算与量纲一致、数值是否落在需求范围内、`unknown` 不得被当成满足要求
- 版本与影响分析：需求版本变化时，找出依赖旧版本的 Brief、Artifact 和 Plan，并标记为 `stale`
- Project Service：持久化到 PostgreSQL（`mis` schema），以及 Python 服务层的增删查接口（HTTP 接口在 P3 加）
- 数据库初始化脚本（普通 SQL，对 Neon 和 Docker 都能执行）；开发用 Neon，CI 中用 `pgvector/pgvector:pg17` 镜像运行数据库测试

**范围外**

- Agent、编排、检索
- Trace Collector、Span 采集、Payload 存储和 Trace Viewer（P3）；C2 的 ExperienceMemory、MemoryUsageEvent、MemoryScoreHistory（P3～P5）。P1 仅定义和存储 RunRef
- 用户认证与多租户。P1 只保留成员字段，不做权限

**验收标准**

- [x] 7 类对象都有 schema 和正反例单元测试；缺少证据的 Artifact、量纲错误的需求项都会被拒绝
- [x] 单位换算覆盖基准任务包中出现的全部单位，例如 nm / µm、cm⁻¹、mW / W、ms / s，并有测试
- [x] 把基准任务包的需求表导入为 `RequirementBaseline` v1；修改一项指标得到 v2 后，影响分析能准确列出受影响的对象，旧版本可以完整读取
- [x] 用手写的样例 Artifact 和 Evidence 生成一份 `InstrumentPlan`，从任一结论都能追溯到 Evidence 记录
- [x] Project Service 的数据库可以独立备份和恢复，不依赖任何 Agent 运行状态（原则 G1）

---

### P2 Agent 架构设计与 DeerFlow 集成验证（Spike）

**目标**：按照已接受的 [ADR-0002](../adr/0002-agent-runtime-and-integration.md)，验证 DeerFlow Backend + MIS 自研 UI / Backend 路线。路线已确定，集成能力尚待验证；**Spike 代码允许丢弃，不视为正式业务实现**。

**设计输入**：[Agent 架构需求清单](../design/agent_architecture_requirements.md) A1–A11、C1、C2，以及 [Agent 内部架构设计](../design/agent_architecture.md)。设计必须明确 Context、Memory、Trace、Skills、协作和人工交互；在 Spike 中验证扩展接口、事件结构和配置，不重新决定 C1/C2 的公式和阈值。

```text
DeerFlow 为 V1 已确认技术路线
              ↓
DeerFlow Integration Spike（固定 Raman / 模拟工具）
              ↓
       ┌──────┴──────┐
       ▼             ▼
   验证通过        关键门槛失败
       │             ↓
       │       记录证据 / 替代评估与同门槛验证
       │             ↓
       │       负责人确认修订决策
       └──────┬──────┘
              ↓
     更新 ADR-0002 验证记录
              ↓
         P3 最小闭环
```

**范围内**

- 独立部署 DeerFlow Backend，锁定上游 release / 完整 commit、依赖、镜像 digest 和配置版本；通过官方扩展和 MIS Adapter 集成，不 Fork 前端，不直接修改核心执行引擎。
- 配置 Project Copilot / Lead Agent 和 Lab、Research、Procurement 三个 SubAgent。Specialist 不直接通信，返回结构化产物；MIS 定义 Brief、依赖、预算和接收条件，DeerFlow 提供执行调度。
- 最小 MIS Context Builder：按 Brief、指定/不定参数、资料范围和 Token Budget 构建隔离上下文，验证 Middleware 注入不混入其他角色消息或文件。
- 关闭或替换 DeerFlow 原生 Memory 的读取、自动提取写入和隐藏注入，接入 MIS Memory Service 的模拟/固定样例接口；不提前实现 P4 的经验评分与生命周期引擎。
- AgentArtifact 输出经 schema、Evidence、单位、量纲和硬约束检查，通过 Project Service 幂等写入；注入部分失败、重复回调、预算超限和恢复场景。
- 最小 MIS Backend / BFF + React 验证页：独立调用、REST / SSE 转换、MIS Thread / Run / Task 与上游 ID 映射、等待用户、回答与恢复；前端不使用上游接口或事件格式作为产品契约。
- 以 A4 验证持久暂停、回答产生 user_decision Evidence、重启恢复及重复回答幂等；用 PostgreSQL 独立 `runtime` schema 验证 Checkpoint，不以 SQLite / 内存通过正式门槛。
- Docker Sandbox 验证文件、角色、网络和资源隔离及取消清理；使用可运行 Docker 的 CI / 远程环境，环境准备需列入时间盒，不要求受限开发机安装 Docker。
- C1 可观测性适配：LLM、Tool、Retrieval、Rule、Human 等关键 Span 的采集与完整层级/执行内容导出，关联 MIS run_id 和 OpenTelemetry trace_id；验证通过 Adapter / Middleware 补齐、PostgreSQL 持久化与内容分离的可行性。正式 Collector、Payload 保留与 Viewer 在 P3 实现。

**范围外**

- 两个以上框架的完整实现与常规横向评分；只有 DeerFlow 关键门槛失败才评估 LangGraph + Deep Agents、AgentScope 等替代方案。
- 真实数据源、正式产品 UI、完整权限系统、C2 评分引擎和生产级 Trace 基础设施。
- 侵入式修改 DeerFlow 核心引擎、Fork DeerFlow Next.js 前端。

**验收标准**

- [ ] DeerFlow Backend 不依赖上游 UI，可由 MIS 独立调用；版本、配置、镜像及许可证核查已登记。
- [ ] Project Copilot 和三个 Specialist 完成固定最小场景，可并行任务确实并行；上下文、技能、工具和文件范围独立，Specialist 不直接通信。
- [ ] Context Builder 与 Middleware 验证通过；必要约束不会被 Token Budget 裁剪掉；原生 Memory 的读写和隐藏注入已关闭或替换，MIS Memory Service 接入可复现。
- [ ] AgentArtifact 结构化输出与 Project Service 写入通过，未知不当作满足；部分失败保留结果，重复事件或进程恢复不重复写入。
- [ ] MIS SSE 事件转换和 React 最小接入通过；ID 映射、状态查询、断线恢复/快照及错误归一化有记录，浏览器不直连 DeerFlow。
- [ ] A4 提问、持久暂停、回答 Evidence、重启恢复和重复回答幂等通过。
- [ ] PostgreSQL Checkpoint 在独立 schema 中写入和恢复，业务记录不依赖 runtime 数据；不允许静默回退 SQLite 或仅内存。
- [ ] Docker Sandbox 文件/网络/资源隔离与清理通过，含同一规划内不同 Specialist 的隔离验证。
- [ ] C1 关键 Span、run_id / trace_id、层级和内容导出及适配路径有可复现证据，明确哪些只做 Spike、哪些在 P3 正式实现。
- [ ] 输出 `docs/spike/P2_deerflow_integration.md`：记录环境、锁定 commit、配置、接口映射、复现命令、各门槛结果与缺口；该文档在 P2 执行后生成，不在本次文档更新中虚构结果。
- [ ] 八章 Agent 架构设计按验证结果定稿；ADR-0002 补充采用依据与验证记录，仍使用编号 0002。
- [ ] 开始前约定 Spike 时间盒。PostgreSQL 持久化、暂停恢复、结构化产物或 Sandbox 隔离等关键门槛失败时，记录原因并启动替代方案评估，经负责人确认修订 ADR-0002 后再推进；不得将未通过的配置带入 P3。

---

### P3 Stage 1 最小闭环（模拟数据）+ 只读查看页面

**目标**：在 P2 验证通过的 DeerFlow Backend 与 MIS Adapter 上实现“需求 → InstrumentPlan”的完整 Stage 1 流程。所有外部数据都来自基准任务包，结果可以重复。同时提供一个只读页面，让人能直观检查结果。

**范围内**

- **Project Copilot**：需求澄清（基于需求表和对话）、建立 RequirementBaseline、任务拆解、生成 Brief、跨领域汇总、生成 InstrumentPlan
- **Task Orchestrator**：MIS 定义业务依赖、预算与接收条件；DeerFlow Lead / SubAgents 执行调度、并行、重试、超时和恢复，MIS Adapter 收集结果与归一化事件，不另建通用执行引擎
- **Trace 基础设施（C1）**：实现 OpenTelemetry Trace + GenAI Semantic Conventions，100% 采集关键业务 Span，不采样；PostgreSQL `trace` schema 中 Skeleton 与 Payload 分离存储，Hash 去重，content_ref 关联；通过 run_id / trace_id 串起完整执行链。骨架永久保留；完整内容：基准运行永久、人工确认的错误案例永久、普通运行 90 天；到期删除完整内容，保留骨架、Hash 和业务引用，保护仍有效的共享 Payload；写入前凭据脱敏
- **DeerFlow Runtime**：Project Copilot / Lead Agent 与三个 Profile（Lab、Research、Procurement），通过 MIS Context Builder、Middleware、Memory Service 接口集成；保持原生长期 Memory 关闭或替换
- **Tool Gateway**：统一的工具接口层。本阶段全部挂模拟实现，P4 替换为真实实现时不改上层
- **Artifact 验收**：Specialist 返回后先过 P1 的规则校验，不通过就重试或标为缺口
- 最小交互入口：CLI
- **MIS Backend / BFF 最小 REST / SSE**：读取项目、需求版本、Brief、Artifact、证据和 Plan；启动、查询、取消运行及提交 A4 回答以恢复执行。Adapter 隔离上游 ID / 事件，前端不直连 DeerFlow；需求编辑、方案采纳等产品写接口留到 P5
- **只读查看页面**：项目概览、需求版本、任务与 Agent 进度、Artifact 列表、证据链（从 Plan 结论点到原文片段）、Plan 内容和规则检查结果、Trace 树与 Span 详情（可定位到 Artifact、Evidence、InstrumentPlan）、**经验事件流和候选经验**。使用 MIS 自研 React + TypeScript，不使用或扩展 DeerFlow Next.js UI；只读展示业务资料，A4 提问回答通过 BFF 最小交互完成，正式编辑留到 P5
- **经验触发事件的记录**：按需求清单 A2 记录其中 4 类触发事件（用户纠正、用户回答提问、同类问题反复出现、项目复盘）并生成候选经验；“测试失败”到 P7 才有。本阶段不做去重和晋升；建立 C2 相关数据契约，区分候选经验触发事件与供评分使用的 MemoryUsageEvent，后者的持久化与评分在 P4 实现
- **用户纠正的入口**：命令行提供纠正某条结论的命令，写入 P1 定义的 `UserCorrection`

**范围外**

- 真实检索、搜索和厂商 API
- 可编辑的正式产品界面和完整经验评分管理界面（P5）
- Stage 2

**验收标准**（对应调研报告第 7 节的 8 项验证）

- [ ] **三类分工**：每个 Artifact 都能看出由哪个 Brief、哪个 Specialist 产出，可以并行的任务确实并行执行
- [ ] **证据链**：Plan 中的每个关键参数和结论都能定位到基准任务包内的具体片段
- [ ] **采购约束**：基准任务包中预设的不合规器件全部被规则排除，必须标为未知的参数没有被填值
- [ ] **部分失败**：注入一个 Specialist 超时后，流程仍能产出 Plan，并明确列出缺口
- [ ] **恢复执行**：在流程中途杀掉进程再续跑，业务记录不重复、不丢失
- [ ] **修改需求**：需求升级到 v2 后重新规划，受影响的产物被标为 stale 并重新生成，v1 的 Plan 保留
- [ ] **预算**：每个子任务的耗时、搜索次数和模型调用次数都有记录，超出预算会被截停
- [ ] **可重复性**：在模型和模拟数据固定的条件下连续运行 N 次（N 由团队定），基准检查点的通过率达到约定阈值，结果写进阶段报告
- [ ] **查看页面**：自研 React 页面只调用 MIS BFF，能看到一次完整规划的结果，从 Plan 中任一结论最多点 2 次即可看到原始证据片段；REST / SSE 断线恢复及 A4 回答恢复可验证，不暴露上游凭据
- [ ] **Trace**：验证关键事件 100% 采集、层级和执行内容可还原（保留期内）、静态 Prompt / Skill 不可变引用、Hash 去重和凭据脱敏；只读页面可查看树与 Span 详情，并定位业务产物与证据
- [ ] **Trace 保留**：以可控时间验证普通运行满 90 天清理 Payload，Skeleton / Hash / 业务引用保留；基准运行和人工确认的错误案例内容永久保留，普通失败不自动永久保留；共享内容不被误删
- [ ] **经验触发事件**：在基准任务上分别制造 4 类事件——用命令行纠正 SPEC-C 的一条结论、回答 Copilot 的一个提问、把基准任务包导入为 3 个不同的普通项目（`kind = normal`）并各运行一次，使 SPEC-C 的同一参数在 3 个项目中都为未知、执行一次项目复盘。每类事件都生成带来源证据的候选经验，并能在查看页面的事件流中看到
- [ ] **不误触发**：可重复性验收中对同一个基准任务项目连续运行 N 次，以及对同一个普通项目重跑 3 次，都不产生“同类问题反复出现”的候选经验；没有上述事件的正常运行不产生任何候选经验

---

### P4 真实数据源接入

**目标**：把 Tool Gateway 的模拟实现逐个替换成真实连接器，同时保持 P3 的验收依然成立。

**范围内**（按调研报告第 3 节的建议，每类先接一个）

- **Lab Knowledge**：RAGFlow，或 Docling + 自建索引，二选一，需另写 ADR；统一知识库与向量索引在 PostgreSQL `knowledge` schema + pgvector，连接器需适配该存储边界。实现资料导入、按项目划分的知识范围、带片段定位的检索
- **Research**：用 GPT Researcher 的库级入口封装研究子任务，PaperQA 作为文献工具按需接入。由外层统一控制研究的预算和来源范围
- **Procurement**：BOMi 覆盖电子器件；至少 1 个光学器件厂商连接器，补充中心波长、NA、镀膜、口径、机械接口等领域字段，并做参数规范化
- 所有真实结果都转成 P1 的 Evidence，记录获取时间
- 外部调用的缓存、限流和失败重试
- 经验晋升池：去重与冲突检测；经验与实验室知识共享 `knowledge` schema 和检索基础设施（A2）。P4 建好存储和评分基础设施，P5 人工审核通过后经验才正式对 Agent 可见
- **经验评分与生命周期（C2）**：实现 ExperienceMemory、MemoryUsageEvent、MemoryScoreHistory；结构化使用事件与 Trace 通过 trace_id / span_id 关联，详细执行数据仍在 `trace` schema。实现 E/T/U/H 分项及综合评分、版本化配置、评分历史、成熟度门槛、事件驱动评分和月度滞回转换、有效性保护、不同经验类型有效期及即时复核；严格遵循 C2，不使用 LLM-as-Judge 自动评分，不统一按时间衰减

- **经验治理契约细化**：P4 明确候选触发、候选版本、晋升池条目、关系/冲突、审核和人工管理的持久化对象及审计关联；明确 MemoryUsageEvent 的逻辑使用关联、经验版本、稳定事件 ID、幂等键、计分消费与结果修订机制。具体方案以 [内部架构设计 4.3/4.4](../design/agent_architecture.md#43-晋升持久化对象与审计关系p4p5-待细化) 为待细化清单，不加入 P1

**范围外**

- 覆盖全部厂商
- 自动下单或询价（属于对外动作，需要另行设计审批流程）

**验收标准**

- [ ] P3 的全部验收项改用“真实连接器 + 基准任务包对应的真实资料”重跑，并通过
- [ ] 每类连接器都有契约测试：用录制的响应回放，CI 不依赖外网
- [ ] 报价类 Evidence 的币种、数量阶梯、区域、获取时间字段完整率为 100%，缺失时必须显式标注
- [ ] 外部服务不可用时，对应 Specialist 返回结构化缺口，不中断整体流程
- [ ] 新引入组件的许可证已登记，Crawl4AI 等带附加条款的组件逐条核对
- [ ] **晋升池去重**：准备一组固定的候选经验测试集，包含意思相同但措辞不同、更具体、互相矛盾、无关四种情况；去重与冲突检测对每一对给出的关系与标准答案一致，结果可以复现（测试集与判定阈值写进阶段报告）
- [ ] **冲突不覆盖**：与实验室文档矛盾的候选经验被标记为冲突，不会改动文档，也不会进入知识库
- [ ] **未审核不可见**：未经审核的经验条目不会出现在 Agent 的检索结果中；P4 的评分验证使用固定事件，不绕过 P5 晋升审核
- [ ] **评分与事件**：固定事件集复现 C2 的 E/T/U/H 与总分；验证 180 天窗口、同经验/项目/任务类型 30 天去重、未选中或未注入不计 T、未 Applied 或 unknown 不计 U、无反馈不算成功；评分变化可追溯来源事件与版本
- [ ] **生命周期与有效性**：验证新晋升 Active / insufficient_data，成熟度须满足 3 个触发项目和 2 个可评价结果项目；成熟后按 C2 连续月度阈值转换，单次低分不降级，Archived 不自动恢复；contested 暂停默认检索，invalid 禁止使用，Pin 不绕过有效性保护；事实到期复核、方法无统一过期时间、偏好以最新确认为准

- [ ] **事件幂等与治理审计**：重试、乱序、重复投递、重启重放、部分阶段缺失、评价晚到与纠正不造成重复 T/U 或重复晋升；能追溯候选、合并/冲突、待审版本、审核与经验版本。四个使用阶段保留事实关联，不分别累加计分；Trace Payload 到期后审计依据仍可读

---

### P5 正式产品界面：Project Workspace 与 Conversation Workspace

**目标**：在 P3 自研 React + TypeScript 只读页面与 MIS BFF 契约的基础上，做成真实用户可以使用的 Stage 1 产品界面；不 Fork 或使用 DeerFlow Next.js 前端。

**范围内**

- **Instrument Project Workspace**：创建项目、编辑需求并查看版本、查看任务与 Agent 进度、查看 Artifact 和证据（可点击溯源）、查看并对比不同版本的 Plan
- **Conversation Workspace**：轻量问答，提供 Auto / Lab / Research / Procurement 四种路由偏好；结果可以一键沉淀到某个项目
- 基础的用户登录（单组织），权限由 MIS Backend 执行；项目、运行、证据、Trace 与记忆均按范围授权，前端不直连 DeerFlow
- 完善自研 REST / SSE 交互：需求编辑与版本、方案采纳、人工提问回答、取消/恢复、运行状态与错误显示；保持 MIS Thread / Run / Artifact 产品契约独立
- **经验审核页面**：晋升池中候选经验的通过 / 驳回 / 修改，冲突裁决；经验库展示综合总分、E/T/U/H 四分项、score_maturity、lifecycle_state、validity_status、触发次数、使用成功/失败次数、评分历史和状态变化历史
- **经验人工管理（C2）**：人工评分、Pin 置顶、强制降级、强制归档、审核后恢复 Archived、标记失效、修改并生成新版本；记录操作人、时间、原因、变更前后分数和状态。人工评分历史永久保留，评分与管理操作分开

**范围外**

- 多组织、多租户和细粒度权限
- 移动端

**验收标准**

- [ ] 非开发人员不看文档，仅凭界面就能完成基准任务：创建项目 → 得到 Plan → 修改一项需求 → 得到新版 Plan
- [ ] 从 Plan 中任一结论最多点 2 次即可看到原始证据片段
- [ ] 在 Conversation 中指定 Agent 时，系统按偏好路由，但复杂请求可以提示升级为项目流程（验证“路由偏好而非强制”）
- [ ] **经验审核**：在页面上对候选经验执行通过、驳回、修改后通过、裁决冲突四种操作，每种操作都有记录（谁、何时、理由）；通过后处于 valid / Active 的经验在下一次运行中可以被 Agent 检索到，并标注为“线索”而非事实
- [ ] **评分管理**：未审核经验不可被 Agent 检索；评分和状态变化均有审计记录，页面可查看四分项、成熟度及来源；Pin 经验不因低分自动降级，但不豁免有效性保护；contested / invalid 经验不能正常参与检索，invalid 禁止 Agent 使用；Archived 的人工恢复必须经过审核
- [ ] **经验可追溯**：经验库中任一条目最多点 2 次即可看到产生它的触发事件和原始证据
- [ ] **审核关系与使用审计**：页面可追溯候选版本、晋升池状态、合并/冲突与人工裁决到最终经验版本，并可从评分历史查看关联使用阶段及评价来源；待审内容修改后，旧审核不得直接授权新版本
- [ ] 主要页面有端到端测试；前端不依赖 DeerFlow 路由或原生 SSE / ID，MIS BFF 权限过滤、等待用户和重连状态一致性可验证

---

### P6 Stage 2 衔接：InstrumentPlan → 工程工具

**目标**：让 InstrumentPlan 成为 Stage 2 工具能读取的正式契约。

**范围内**

- InstrumentPlan 的导出格式：JSON + 人可读的 Markdown，带 schema 版本号
- 与 Stage 2 工具的适配器，先做以下两个：
  - **SDK_Anlysis_Agent**：把 Plan 中选定器件对应的 SDK 资料交给它分析，结果回写为项目的 Artifact
  - **Rapid Optics Studio**：把 Plan 中的光学参数导出为它能读取的配置
- 从 Plan 生成 Stage 2 任务清单

**范围外**

- 改造 Stage 2 工具本身的内部实现。只做接口层，必要时向对应仓库提需求
- Coding Agent、UpperPC 的深度集成（留到 P8+）

**验收标准**

- [ ] 基准任务的 Plan 导出后，至少 1 个 Stage 2 工具能直接读取，无需手工修改；Rapid Optics Studio 能载入并运行一次仿真
- [ ] 工具的输出（SDK 分析报告或仿真结果）作为 Artifact 回写到同一个 InstrumentProject，并带证据
- [ ] Plan 的 schema 升级时，旧版本导出文件仍可以读取，或有明确的迁移脚本

---

### P7 测试验证与 Re-plan 闭环

**目标**：实现架构文档第 10 节的回路：测试结果 → 对照需求 → 影响分析 → 重新规划。

**范围内**

- TestResult 的录入：手工录入、导入文件（CSV / 仪器输出），或来自 Rapid Optics Studio 的仿真结果
- 把 TestResult 自动对照到 RequirementBaseline 的需求项，判定通过或失败
- 失败后的处理：Copilot 根据失败证据确定受影响的方案范围，生成新的 Brief，只重跑受影响的部分，产出新版 Plan
- 项目历史时间线：需求版本、方案版本、测试结果、每次 Re-plan 的原因
- **经验效果反馈（C2）**：将 TestResult 与 MemoryUsageEvent 关联；仅对实际 Applied 的经验，将可追溯测试成功/失败作为 U 的正/负样本，unknown 不计入。用户纠正和测试失败触发经验复核，可查询评分变化的来源
- **离线校准**：基于实际数据评估评分权重和生命周期阈值，版本化保存，经人工批准后发布；运行中的 Agent 不得自行修改

**范围外**

- 与真实仪器的实时数据联动（依赖 UpperPC，留到 P8+）

**验收标准**

- [ ] 基准任务包中加入一组“测试失败”数据，例如分辨率不达标；系统能指出是哪个需求项失败、影响了 Plan 中哪些模块
- [ ] Re-plan 只重新执行受影响的 Brief，未受影响的 Artifact 原样保留，并有日志证明
- [ ] 新版 Plan 附有变更说明：改了什么、为什么改、依据哪次测试
- [ ] 全部测试都通过时，项目可以标记为“满足需求”，并生成最终的方案与证据汇总
- [ ] **经验反馈与复核**：测试成功、失败和 unknown 对 U 的影响符合 C2；用户纠正与测试失败触发复核，能从评分历史追溯到 MemoryUsageEvent、TestResult / UserCorrection 和 Evidence
- [ ] **离线校准**：权重与阈值调整有评估依据、人工批准和新 score_version，历史版本可追溯，Agent 运行时不能自行修改

---

### P8+ 后续扩展（暂不细化）

- UpperPC 集成：真实仪器的控制和测量数据回流
- Coding Agent 与大型代码仓库的理解能力
- 更多工程工具：机械、电路、数据分析
- 多组织、多租户、权限与审计
- 部署形态：私有化部署、模型与数据不出内网等

这些在 P7 完成后按实际需要排序，届时再补充计划。

---

## 3. 每个阶段统一的“完成”定义

阶段结束时必须同时满足以下条件：

1. 本阶段的验收清单全部勾选，或未完成项已由负责人书面确认为豁免并写明原因
2. 验收以自动化测试或脚本为主，并在 CI 中可以复现
3. 有一份阶段报告 `docs/reviews/Px_report.md`，内容包括：完成了什么、验收结果、偏离计划之处、遗留问题
4. 涉及架构选择的决定已写成 ADR
5. 下一阶段的任务说明 `docs/plans/Px+1_*.md` 已起草

---

## 4. 待决策事项

以下问题会影响计划细节，需要在对应阶段开始前确定：

| 编号 | 问题 | 最晚决策时间 | 当前状态 |
|---|---|---|---|
| D1 | 主技术栈和数据库 | P0 | 数据库**已确定**为 PostgreSQL 17 + pgvector；Python + uv 见 ADR-0001，待评审 |
| D2 | LLM 供应商与模型、是否需要私有化部署、调用预算上限 | P2 | 无数据安全限制，可以使用外部模型 API、不需要私有化部署；供应商和预算未定 |
| D3 | 基准任务包的真实资料来源：用哪些实验室文档、论文，哪些需要脱敏 | P0 | P0 用合成资料（ADR-0001），真实资料推迟到 P4 |
| D4 | DeerFlow Integration Spike 时间盒与验证环境 | P2 | 集成优先策略已确认（ADR-0002），不再要求两个框架完整对比；时间盒、Docker 环境与锁定 commit 待启动前登记 |
| D5 | Lab Knowledge 连接器选 RAGFlow 还是 Docling + 自建 | P4 | 连接器未定；统一知识库与向量索引采用 PostgreSQL knowledge schema + pgvector，遵循已确认的 C2 存储边界 |
| D6 | 第一个接入的光学器件厂商 | P4 | 未定 |
| D7 | 平台是否需要与现有 GitHub 子项目（SDK_Anlysis_Agent、Rapid_Optics_Studio）放在同一个仓库 | P0 | 建议分仓库（ADR-0001），待评审 |
| D8 | 开发协作方式：人与 Agent、多个 Agent 之间如何分工，计划和审查记录放在哪里 | P0 | 建议见 ADR-0001，待评审 |
| D9 | 前端框架与集成边界 | P2 最小接入，P3 只读页，P5 正式产品 | 已确认 React + TypeScript、自研 UI、仅调用 MIS Backend / BFF（ADR-0002）；monorepo 工具未定 |
| D10 | 多人使用时数据库部署在哪里：实验室或公司服务器、云服务器，还是托管 PostgreSQL | P5 | 未定；开发阶段已确定使用 Neon（ADR-0001“部署”） |
