# MetaInstrumentStudio 开源 baseline 调研

调研日期：2026-11-01，用户本地时区 UTC−08:00。GitHub 元数据保留 UTC 时间，因此部分记录显示 2026-11-02。依据为当前 MIS 两份本地架构文档、上游官方仓库、README、许可证及部分源文件。

**结论：值得优先做一个 DeerFlow 改装验证；若更看重长期自主架构，则用 LangGraph + Deep Agents 搭建 MIS 的运行层。Research、Lab Knowledge、Procurement 可以分别复用现有组件，但项目数据契约与仪器验证闭环需要自己实现。**

本轮筛查 20 个仓库，核对元数据，对主要候选抽查实现入口。未安装运行、未执行测试、未接模型或搜索付费服务，未验证真实厂商库存与报价。下述适配性、改装成本与优先级属于面向 MIS 的工程判断，不是基准测试结论。最新 main 的源码核查不等于某个已发布软件包具备相同接口。

**1. 与 MIS 需求的对应关系**

MIS 需要的核心是：Project Copilot → Task Orchestrator → Lab / Research / Procurement 三个 Specialist → InstrumentPlan，并以 InstrumentProject 串联工程实现和测试反馈。

选型应关注五件事：

- 能否定义三个具有独立上下文、工具范围和输出要求的 Specialist。
- 能否并发执行、收集结果、处理失败，并在暂停或进程重启后恢复。
- 是否支持带来源的结构化成果，而不只是最终聊天文本。
- 是否便于增加需求基线、方案版本、BOM、测试结果等项目对象。
- 是否有明确的代码复用许可，以及可承接的依赖、维护和部署成本。

Stage 2 的 Rapid Optics Studio、UpperPC 首先按工程工具或独立应用集成，不必为了统一命名再各造一个 Agent。SDK Analysis Agent 可以通过适配器接入已有实现。

**2. 平台底座：优先验证三个方向**

| 方案 | 已核实的基础能力 | 在 MIS 中的复用方式 | 主要新增工作 | 判断 |
|---|---|---|---|---|
| DeerFlow，MIT | Web 工作空间、lead agent、子 Agent、工具与技能、持久化；源码存在 RAGFlow 适配和子任务结果契约 | Fork 应用，在现有运行层上加入三个领域 Specialist 和项目页面 | MIS 数据对象、领域证据、方案版本、测试回流 | **最值得先做可见原型的 baseline** [S1] |
| LangGraph + Deep Agents，MIT | 图执行和状态持久化；Deep Agents 提供规划、文件上下文、子 Agent 等运行能力 | 作为依赖使用，自建 Project Service 和界面 | 产品界面、业务存储与流程；组织已有组件的适配层 | **适合长期可控的自有平台** [S2][S3] |
| AgentScope，Apache-2.0 | 当前源码有 TeamPipeline、团队成员分派和并行执行；另有应用层模块 | 在共享运行时内定义 Supervisor 和三个 Specialist | 任务产物协议、项目生命周期、现有工程工具接入 | **有力备选，值得参与同任务验证** [S4] |

这些方案是可替代的运行底座。DeerFlow 已使用 LangGraph，选择它后不需要再额外套一层独立 Deep Agents 总调度器；也不建议 V1 同时引入 AgentScope、CrewAI 和 LangGraph 管理同一任务生命周期。

DeerFlow 的优势是现成应用功能较多。代价是应用代码和运行基础设施的耦合：本轮抽查的 lead agent 与 executor 分别约 1,458 和 2,517 行，不能把几个文件复制出来就认为完成了平台接入。更合理的做法是固定版本后小范围改装，或通过其接口集成。行数仅用于提示阅读范围，不代表质量评分。[E3]

LangGraph + Deep Agents 的优势是 MIS 可以明确拥有自己的状态机和业务模型。应把“运行状态 checkpoint”和“仪器项目业务记录”分开设计；二者目的不同。自有 Project Service 保存需求、方案及证据，运行层保存执行进度。

AgentScope 当前的 TeamPipeline 已接近本项目的 Supervisor–Specialist 结构。它适合验证三个专业角色是否能在同一运行环境下协作，但团队会话结束仍需由 MIS 的验收逻辑判定产物是否满足任务要求。

**3. 单个 Agent / 工具可以复用什么**

| MIS 能力 | 候选与许可证 | 可复用部分 | 适配边界 |
|---|---|---|---|
| Research Specialist | GPT Researcher；Apache-2.0 | 搜索、资料整理、研究报告；已核实 `GPTResearcher`、`conduct_research()`、`write_report()` 接口 | 封装为受预算约束的研究子任务；将来源、结论和未决问题转成 AgentArtifact [S5][E3] |
| 论文证据分析 | PaperQA；Apache-2.0 | 围绕论文/文档的检索、证据整理和带引用问答 | 适合作为 Research 或 Lab Agent 的文献工具；不替代器件选型和工程方案裁决 [S6] |
| Lab Knowledge Specialist | RAGFlow；Apache-2.0 | 文档解析、知识库、检索和引用；DeerFlow 已有对应工具接口 | 以知识服务接入；项目身份和知识范围需由服务端传入并校验 [S7][E3] |
| Lab / SDK 资料预处理 | Docling；MIT，模型另核许可 | PDF 等资料的版面、表格、OCR 与结构化转换 | 作为摄取管线的一环；仍需索引、检索、来源映射和 Agent [S8] |
| Procurement 的电子器件部分 | BOMi；MIT | LCSC/JLCPCB 相关器件搜索、参数过滤、价格阶梯、库存字段、BOM 分析 | 包装 CLI 或 Python 模块；扩大到光学器件、相机、位移台需新增供应商适配 [S9][E3] |
| Procurement 工作流参考 | ProcurePilot；MIT | 当前代码用 Deep Agents 组织采购任务；README 描述 ERP 库存、采购订单与补货场景 | 借鉴技能组织、业务对象和适配器模式；不要把 ERP 流程直接当作科研器件选型 [S10][E3] |
| 网页资料获取 | Crawl4AI；Apache-2.0 正文并附额外署名要求 | 可作为抓取/提取工具候选 | 接入前核对完整许可；页面提取不等于参数真实性或库存时效性验证 [S11][E4] |

Research 的建议是先封装 GPT Researcher 的库级入口，返回证据与报告，不接管它的整套独立前端。其内部可能展开多步研究，因此 MIS 应统一控制超时、调用预算、查询范围和可用来源，避免外层与内层调度各自无限扩张。

Lab Knowledge 有两种可选路线：资料较多、需要管理知识库时验证 RAGFlow；资料较少、先跑通试点时，可以用 Docling + 自有索引/检索适配器，并按需使用 PaperQA。后者是建议的组合架构，三者并非开箱即用的一体化产品。第一版不必同时部署所有候选。

采购模块目前最有价值的复用点是“供应商连接器 + 参数规范化 + 确定性过滤”。BOMi 的覆盖范围主要是电子器件，不应直接外推到整台科研仪器的采购能力。对光学器件应增加中心波长/范围、数值孔径、镀膜、口径、机械接口等领域字段，再由规则检查约束、Agent 解释取舍。

**4. 已定位的具体代码入口**

以下路径来自 GitHub tree 与固定提交的源码读取；完整 URL、SHA-256、函数名摘要见 `code-evidence-2026-11-01.json`。以项目为单位复用优先于复制内部文件，因为内部代码可能依赖其配置、消息协议和持久化模型。

| 项目 | 核查提交（短 SHA） | 代码路径 | MIS 中的用途 |
|---|---|---|---|
| DeerFlow | `3f86f071f3d2` | `backend/packages/harness/deerflow/agents/lead_agent/agent.py` | 研究 Project Copilot 的装配入口 |
| DeerFlow | 同上 | `backend/packages/harness/deerflow/subagents/config.py` | 配置不同 Specialist 的提示、工具、模型和执行限制 |
| DeerFlow | 同上 | `backend/packages/harness/deerflow/subagents/executor.py` | 子任务状态、执行、结果与工具证据收集 |
| DeerFlow | 同上 | `backend/packages/harness/deerflow/subagents/report_contract.py` | 对接 AgentArtifact 与验收条件；仍需 MIS 自己定义 schema |
| DeerFlow | 同上 | `backend/packages/harness/deerflow/community/ragflow/tools.py` | 连接实验室知识检索服务 |
| Deep Agents | `2b33a4c0cf60` | `libs/deepagents/deepagents/graph.py` | `create_deep_agent()` 与共享运行能力 |
| AgentScope | `300398e3108a` | `src/agentscope/pipeline/_team_pipeline.py` | Supervisor 分派、团队执行机制 |
| GPT Researcher | `3582a6841fe7` | `gpt_researcher/agent.py` | 研究库适配入口 |
| BOMi | `f95b66e4b373` | `src/bomi/models.py`、`filters.py`、`api.py` | Part / PriceTier、属性过滤、JLCPCBClient |
| ProcurePilot | `012b51ed6c1e` | `src/agent/graphs/main_agent.py` | Deep Agents 采购任务装配实例 |

一个重要实现细节：DeerFlow 的 `SubagentConfig` 已区分提示、工具、模型、技能和执行预算。MIS 可以从固定三类配置开始，但配置存在并不能代替运行隔离、访问范围校验和业务验收。[S1][E3]

**5. 其他候选与暂不优先的理由**

| 候选 | 本轮核查情况 | 判断 |
|---|---|---|
| Microsoft Agent Framework | 官方 README 提供 Python/.NET、多种编排和 checkpoint；MIT | 如果后续明显转向 .NET 上位机生态，可进入下一轮比较；目前 MIS 的 Python/TS 组件使前述方案更顺手 [S12] |
| CrewAI | 元数据初筛：MIT、未归档、近期有推送 | 保留候选；本轮未深入代码，不给可靠性或适配性排名 [S13] |
| Browser Use | 元数据初筛：MIT、未归档、近期有推送 | 留作浏览器工具候选，未验证厂商网站成功率 [S14] |
| Dify | 核对 LICENSE：修改版 Apache-2.0，涉及多租户及前端标识的附加条件 | 不作为 MIS 自有品牌平台 Fork 的首选，不能当作无附加条件的 Apache-2.0 项目处理 [S15] |
| Open Deep Research | GitHub API `archived=true` | 可研究其设计或固定版本代码，不选作持续升级底座 [S16][E1] |
| langgraph-supervisor-py | GitHub API `archived=true` | 可参考，不作为新增核心依赖 [S17][E1] |
| AutoGen | README 顶部声明已停止维护，并引导到 Microsoft Agent Framework；API 却仍返回 `archived=false` | 保留这个证据差异；按维护声明，不推荐新项目以它起步。文档 CC-BY-4.0 与代码 MIT 也需区分 [S18][E4] |
| PCBS-BOM-AI-Agent | MIT；元数据最近推送为 2025-06-25 UTC | 作为 BOM 原型参考，未验证供应商接口和当前依赖；优先研究更贴近当前需要的 BOMi [S19][E2] |
| procurement-tools-plugin | 有 BOM/spec/conformance 等 schema；API license 为空，本轮树中未发现 LICENSE | 仅记录设计方向，暂不建议直接复制其代码或模板 [S20][E2] |

“近期推送”只表示仓库有活动，不证明稳定性、响应速度或发布质量。许可证字段也不是完整审计：Crawl4AI 的附加署名、Dify 的自定义条款、AutoGen 的文档/代码许可差异，均说明需要看具体文件。

**6. 推荐的 MIS 组合与自建边界**

建议先用 DeerFlow 验证以下组合；若项目模型接入困难，再用同一组任务比较 LangGraph + Deep Agents 和 AgentScope，而不是先重写全部能力。

```text
MIS Conversation / Instrument Project Workspace
                     |
               Project Copilot
                     |
        统一任务记录、预算与结果汇总
          /          |           \
 Lab Specialist  Research Specialist  Procurement Specialist
       |                 |                    |
 RAGFlow 或检索适配器   GPT Researcher         BOMi / 厂商连接器
 Docling / PaperQA     论文证据工具          参数与单位规则校验
          \             |                  /
                AgentArtifacts + Evidence
                         |
                    InstrumentPlan
                         |
          SDK Analysis / Coding / Rapid Optics / UpperPC
                         |
                 TestResult → Re-plan
```

需要由 MIS 自己拥有的部分：

- `InstrumentProject`：项目身份、成员、资料范围、工程产物关联。
- `RequirementBaseline`：指标、单位、容差、预算和验收方法，以及版本。
- `AgentTaskBrief`：输入版本、目标、限制、验收条件、时间与调用预算。
- `AgentArtifact`：结论、产物类型、证据 ID、假设、未解决问题和状态。
- `Evidence`：来源 URL/文档 ID、页码或片段、抓取时间、文档版本；报价还需币种、数量阶梯、区域和有效时间。
- `InstrumentPlan`：方案版本、候选器件、取舍依据、风险、下一阶段任务。
- `TestResult` / Re-plan：测试与需求项的映射、失败证据、受影响方案范围。

这些对象不是把聊天历史存入数据库就能替代的。三个 Agent 完成调用后，还应由可检查的规则判定字段是否齐全、证据是否存在、单位是否一致。未找到参数时，应保留“未知/待确认”，而不是自动填成满足要求。

**7. 建议的验证任务与选型门槛**

用一项 Raman 仪器方案任务验证：输入一份需求表、少量实验室文档、论文材料和已知器件页面；要求输出带证据的方案与候选 BOM。先使用固定材料和模拟厂商响应，再验证实时数据源。

| 验证项 | 应观察到的结果 |
|---|---|
| 三类 Agent 分工 | 任务、上下文和产物归属明确；能在必要时并行 |
| 证据链 | 每个关键参数和设计结论能定位到文档片段或网页及时间 |
| 采购约束 | 单位、范围和硬性指标由规则校验，不能只看模型推荐 |
| 部分失败 | 某个 Agent 超时，其他结果仍保留，并标明方案缺口 |
| 恢复执行 | 中断后能续跑；恢复不重复写入业务产物 |
| 修改需求 | 需求版本变更后能识别受影响成果，并保留旧版本 |
| 预算 | 能记录并限制各子任务的时间、搜索和模型调用 |
| Stage 2 衔接 | InstrumentPlan 能被至少一个已有工程工具读取 |

建议选择标准：谁能以更少的内部改动支持这些业务约束，谁更适合作为 MIS baseline。本轮不报开发工期或费用数字；它们需要通过上述小规模运行测量获得。开源代码可复用不代表模型、搜索、OCR、托管浏览器或厂商 API 服务免费。

**8. 来源与核查记录**

本地记录：

- [E1] `repository-metadata-2026-11-01.json`：16 个通用候选的默认分支、许可识别、归档标记和推送时间。
- [E2] `procurement-candidates-2026-11-01.json`：4 个采购候选及其提交和代码路径。
- [E3] `code-evidence-2026-11-01.json`：13 个固定提交文件的 URL、摘要哈希和接口摘录；其中含部署说明抽查。
- [E4] `license-and-lifecycle-evidence-2026-11-01.json`：关键许可证和维护声明摘录。
- `*-tree.json`：入围项目的代码树快照，用于定位源码；不是本地部署或运行记录。

官方来源（URL 保留为代码文本，便于复制或在后续核验时使用）：

- [S1] DeerFlow：`https://github.com/bytedance/deer-flow`；`https://raw.githubusercontent.com/bytedance/deer-flow/main/LICENSE`
- [S2] LangGraph：`https://github.com/langchain-ai/langgraph`
- [S3] Deep Agents：`https://github.com/langchain-ai/deepagents`
- [S4] AgentScope：`https://github.com/agentscope-ai/agentscope`
- [S5] GPT Researcher：`https://github.com/assafelovic/gpt-researcher`
- [S6] PaperQA：`https://github.com/Future-House/paper-qa`
- [S7] RAGFlow：`https://github.com/infiniflow/ragflow`
- [S8] Docling：`https://github.com/docling-project/docling`
- [S9] BOMi：`https://github.com/somebox/bomi`
- [S10] ProcurePilot：`https://github.com/KagaribiDev/procurepilot`
- [S11] Crawl4AI：`https://github.com/unclecode/crawl4ai`；`https://raw.githubusercontent.com/unclecode/crawl4ai/main/LICENSE`
- [S12] Microsoft Agent Framework：`https://github.com/microsoft/agent-framework`
- [S13] CrewAI：`https://github.com/crewAIInc/crewAI`
- [S14] Browser Use：`https://github.com/browser-use/browser-use`
- [S15] Dify：`https://raw.githubusercontent.com/langgenius/dify/main/LICENSE`
- [S16] Open Deep Research：`https://github.com/langchain-ai/open_deep_research`
- [S17] LangGraph Supervisor：`https://github.com/langchain-ai/langgraph-supervisor-py`
- [S18] AutoGen：`https://raw.githubusercontent.com/microsoft/autogen/main/README.md`
- [S19] PCBS BOM Agent：`https://github.com/pandysp/PCBS-BOM-AI-Agent`
- [S20] Procurement tools plugin：`https://github.com/danielrosehill/procurement-tools-plugin`

相关 MIS 原始依据：`D:\MIS\MetaInstrumentStudio_ARCHITECTURE.md`、`D:\MIS\MetaInstrumentStudioV4.0_README.md`。本轮未修改这些文件。
