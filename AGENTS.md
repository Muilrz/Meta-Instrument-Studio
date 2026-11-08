# AI 会话工作说明

本文件给在本仓库工作的 AI 编码助手（Claude Code、Codex 等）。`CLAUDE.md` 引用的就是本文件，规则只维护这一份。

修订记录：2026-11-08，同步 A1–A11、C1/C2、ADR-0002 和 Agent 内部架构设计的阅读顺序及执行边界。

## 开工前

1. 先同步最新代码：`git pull`。计划会随讨论更新，不要依赖之前会话里记住的内容。
2. 按顺序读：
   1. [docs/README.md](docs/README.md)：文档地图，了解每份文档的用途和状态
   2. [docs/plans/development_plan.md](docs/plans/development_plan.md)：阶段划分和第 0.2 节的全程原则 G1–G6
   3. 当前阶段的任务说明，目前是 [docs/plans/P2_deerflow_integration.md](docs/plans/P2_deerflow_integration.md)；P1 交接以 [P1 阶段报告](docs/reviews/P1_report.md) 为准
   4. [docs/design/agent_architecture_requirements.md](docs/design/agent_architecture_requirements.md)：已确认的决定 A1–A11、C1、C2 必须遵守
   5. [docs/adr/0001-repo-structure-and-stack.md](docs/adr/0001-repo-structure-and-stack.md)：技术栈、数据库、部署和权限；区分整体待评审与已确认部分
   6. [docs/adr/0002-agent-runtime-and-integration.md](docs/adr/0002-agent-runtime-and-integration.md)：已接受的 DeerFlow 技术路线、复用与自研边界、P2 验证门槛
   7. [docs/design/agent_architecture.md](docs/design/agent_architecture.md)：模块接口、Context / Memory / Evolution、REST / SSE、存储与执行设计；具体上游绑定待 P2 验证
   8. [docs/adr/](docs/adr/) 中其他相关决策
3. 文档之间或文档与代码之间有矛盾时，先停下来问人，不要自行取舍。

## 必须遵守

- **不改动已确认的决定。** 需求清单中标为“已确认”的条目、ADR 中“已接受”或“已确认”的部分，要修改必须先得到负责人同意，并在文件开头记下修订。
- **架构边界**：DeerFlow Backend 独立部署；MIS 自研 React + TypeScript UI 与业务后端。前端只调用 MIS BFF，运行层通过 MIS 服务写入业务记录，不直接修改业务主数据；Context、Memory、Evolution 的所有权遵循 A9–A11 和 ADR-0002。
- **Trace 与经验治理**：遵循 C1/C2，不用上游默认记忆替代 MIS Memory Service，不绕过经验晋升审核、评分成熟度或有效性保护。
- **决策状态与阶段边界**：默认建议不等于已批准。P1 的 Q1–Q4 已于 2026-11-08 由负责人确认，见 ADR-0003；T1–T8 实现与自动验收已完成并合并 `main`，最终人工评审记录尚待核对；其他草案不能当作已接受决策。Runtime 路线已确认不等于 P2 验收通过。经验治理对象和使用事件幂等细化留在 P3～P5，不加入 P1 核心模型。
- **未知就标未知**（原则 G2），**结论必须有证据**（G3），**硬约束由规则判定**（G4）。
- **基准任务包** `fixtures/raman_baseline/`：已用于验收的版本不得原地修改，改动要升级 `manifest.yaml` 中的版本号。
- **密钥**：数据库连接地址、API key 只放在 `.env`，不提交、不打印、不写进文档或聊天。
- **数据库**：开发用 Neon（见 ADR-0001“部署”），CI 用 Docker，以 CI 结果为准；只使用 PostgreSQL 和 pgvector 的标准功能。
- **文档**：一律放在 `docs/` 下；文件名不带版本号；新增或移动文档时同步更新 `docs/README.md`。

## 提交

- 多个会话可能共用同一个文件夹：**提交时只添加自己改过的文件，不要用 `git add -A` 或 `git add .`**。
- 提交前运行，并确认全部通过：
  ```bash
  uv run pytest
  ```
  ```bash
  uv run ruff check .
  ```
- 推送前先 `git fetch`，确认没有别人的新提交；有的话先合并再推送。
- 阶段开发在自己的分支上进行，验收通过后由负责人合并到 `main`。
