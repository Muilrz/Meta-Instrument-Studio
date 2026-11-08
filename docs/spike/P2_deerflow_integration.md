# P2 DeerFlow 集成预检与验证记录

- 日期：2026-11-08（Asia/Singapore）
- 本次范围：**P2-0A 基线冻结与环境预检**；P2-0B 尚未执行。
- MIS 分支：`feat/p2-deerflow-integration`，检查基点 `18b107c`。
- 状态：上游源码基线已确认；运行配置、镜像 digest、受限凭据及负责人前置确认尚未闭合。**没有 MIS 集成测试通过结论。**
- 决策依据：AGENTS.md、P2 任务说明、开发计划 P2、ADR-0001/0002、Agent 架构设计与需求清单、总体架构。本文不修改既定架构或 P1 契约。

## 1. 证据口径与阶段交接

| 分类 | 含义 |
|---|---|
| 预检已验证 | 本次实际执行的 Git、文件校验、工具检查或数据库只读查询 |
| 源码确认 | 固定 commit 的实现和文档支持；尚未在 MIS 环境启动或验收 |
| 待验证 | 必须通过后续可复现运行才能确认 |
| 阻塞/待负责人确认 | 缺少必要环境、授权范围、配置或正式记录，不能默认为批准 |

本次从工作区父目录定位到 `Meta-Instrument-Studio` 后，执行 `git status --short`、`git branch --show-current`、`git fetch origin`。原工作区干净，分支正确，随后用 `git merge --ff-only origin/feat/p2-deerflow-integration` 从 `66eafa4` 同步至 `18b107c`，未覆盖未提交工作。README、P1 报告、P2 任务说明、AGENTS、文档导航和开发计划的交接状态已随该提交同步，不重复修改。

P1 实现提交 `dd304c0` 位于 `origin/main` 历史中。仓库 `docs/reviews/` 只有 P0/P1 报告；P1 报告明确未登记最终人工评审。本次通过 GitHub 连接器读取 [P1 PR #1](https://github.com/Muilrz/Meta-Instrument-Studio/pull/1) 的评论及正式 Review，返回均为空。**未找到负责人最终人工评审证据，保持待确认**；合并和自动验收不替代该记录，也不代表 P2 集成通过。

## 2. 上游版本与可复现基线

| 项目 | 结果与证据 |
|---|---|
| 官方 Release | [DeerFlow v2.2.0](https://github.com/bytedance/deer-flow/releases/tag/v2.2.0)，本次查到的页面标为 Latest；API tag ref 直接指向下述 commit |
| 完整 commit | `58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a`；本地 `git rev-parse HEAD`、`git rev-parse v2.2.0` 完全一致，`git describe --tags --exact-match` 返回 `v2.2.0` |
| 独立克隆位置 | `C:\Users\Muil\Desktop\MIS_workspace\deer-flow-p2-0a-filtered`，在 MIS Git 仓库之外；partial clone + sparse checkout，detached HEAD，工作区干净 |
| 克隆方式 | `git clone --filter=blob:none --no-checkout --depth 1 --branch v2.2.0 --single-branch https://github.com/bytedance/deer-flow.git <独立目录>`；选择审计路径后 `git checkout --detach <完整 commit>` |
| 网络限制与旁证 | 普通克隆长时间无进度后终止；过滤克隆成功。另从固定 commit 取 326 个审计文件，与 GitHub recursive tree 的 Git blob SHA-1 全部匹配（0 mismatch）。这些文件副本在仓库外，不是 MIS 依赖或运行环境 |
| 上游许可证 | 固定 commit 的 [LICENSE](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/LICENSE) 为 **MIT**；分发需保留版权和许可声明 |
| Python / 工作空间 | `backend/pyproject.toml` 与 `backend/packages/harness/pyproject.toml` 均要求 Python `>=3.12`；app/harness 版本 `2.2.0`；extension API 锁定 `0.2.9` |
| 后端依赖锁 | `backend/uv.lock`：format 1、revision 3；SHA-256 `94bf2c5c0d136d8632775f899b65afa8992d68117771ee70dc61cfaebe9e4eb5` |
| 配置模板 | `config.example.yaml` 的 `config_version: 63`；SHA-256 `3c3860dc295fd6db4d649d8b0f24b8137bced4270a38dbd9edec98df23abc01c`；MIS 实际运行配置尚未创建/批准 |
| 前端锁（仅登记） | `frontend/pnpm-lock.yaml` SHA-256 `9be09570336b0a30b33fcce301341d31564292d2892fd5f3b81f18486914527d`；不安装、不使用上游 UI |
| Adapter 版本 | 无：本次没有开发 Adapter |
| 镜像基线 | **未冻结 digest，阻塞容器可复现验收**。上游 Dockerfile/compose 仍使用标签，不能把源码 commit 当镜像 digest |

锁文件抽查版本：LangGraph `1.2.9`、langgraph-checkpoint `4.3.0`、checkpoint-postgres `3.1.3`、checkpoint-sqlite `3.1.2`、psycopg `3.3.3`、psycopg-pool `3.3.0`、asyncpg `0.31.0`、langchain-openai `1.2.1`。PostgreSQL 是可选 extra，存在于锁文件不等于已安装；后续在上游独立环境执行 `uv sync --locked --all-packages --extra postgres`，不得把其依赖装入 MIS 虚拟环境。

许可证核查范围：上游根许可已确认；**未完成锁定依赖和镜像内系统包的逐项许可证/SBOM 审计**，不能用 MIT 概括整个依赖树。后续对实际安装的 postgres extra 和实际拉取镜像导出版本与许可证清单，保留第三方声明；可选 extra 需单独核查。

镜像待登记清单：后端构建基镜像 `python:3.12-slim-bookworm`、uv 构建来源 `ghcr.io/astral-sh/uv:0.11.1`；如使用整套 compose，另有 `redis:7-alpine`、`nginx:1.31.2-alpine`。Sandbox provider 默认 AIO `:latest`，模板注释建议显式 `:1.11.0`；网络代理亦有 `:latest`。MIS CI 的 `pgvector/pgvector:pg17` 同样尚未按 digest 锁定。本次没有拉取镜像、查询 registry digest 或构建后端镜像。

## 3. Backend 独立运行：源码证据

以下路径均相对于上述固定 commit 的上游根目录；行号为本次 checkout。

| 入口 | 源码结论 |
|---|---|
| [backend/Makefile:18](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/backend/Makefile#L18) | `gateway` 直接运行 `uv run --locked uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001`，不启动 Node/Next.js/nginx |
| [backend/app/gateway/app.py:587](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/backend/app/gateway/app.py#L587) | FastAPI lifespan 进入 embedded runtime；`create_app()` 注册 REST/SSE，`/health`、`/health/ready` 为独立后端健康入口 |
| [backend/app/gateway/deps.py:750](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/backend/app/gateway/deps.py#L750) | `langgraph_runtime` 在 849–851 行初始化数据库 engine 与 async checkpointer，不以 Web UI 进程作为运行前提 |
| [backend/app/gateway/routers/thread_runs.py:985](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/backend/app/gateway/routers/thread_runs.py#L985) | 线程 Run create、stream、wait、query、cancel、join、events 路由和鉴权；流恢复/取消并非靠上游浏览器实现 |
| [backend/docs/API.md](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/backend/docs/API.md) | 官方 API 文档描述 Thread、Run、SSE、Idempotency-Key、`command.resume`；文档多用代理路径 `/api/langgraph/...`，直连 Gateway 使用路由路径 `/api/...`，P2-0B 必须从 OpenAPI 核对 |

结论：**不依赖上游 Web UI 的独立 Gateway + embedded Harness 为源码确认**。根目录 `make dev` 是全栈入口，MIS 应使用 backend 的 `make gateway` 或对应 uvicorn 命令。未启动进程、未调用模型、未验证服务鉴权、SSE 或重启恢复，因此不能写成“MIS 集成测试通过”。

后续 Adapter 优先依赖固定版本的官方 HTTP Thread/Run API、状态/历史、SSE、取消与 `command.resume`，结合 Idempotency-Key；工具/MCP、SandboxProvider、配置 `extensions.middlewares` 与 `deerflow-extension-api==0.2.9` 是扩展候选。HTTP 兼容性和扩展契约须锁版本做测试，不能假设所有内部模块路径长期稳定。不上游内部 `RunManager`/私有 updater 做产品耦合，不开始 Adapter 实现。

## 4. PostgreSQL、Memory、Sandbox 的兼容性

### 4.1 PostgreSQL 与防回退

- 原生支持：`backend/packages/harness/deerflow/runtime/checkpointer/provider.py:61`（同步）及 `async_provider.py:191`（异步）解析配置；使用 `PostgresSaver` / `AsyncPostgresSaver`、`saver.setup()`。缺少 postgres 包或 DSN 会抛错；已检查分支未发现“Postgres 连接失败后改用 SQLite/内存”的路径。此为源码判断，故障注入尚未执行。
- schema：`config/database_config.py:203` 的 `database.postgres_schema` 同时控制 app ORM、Checkpoint/Store；旧 `config/checkpointer_config.py:33` 也有 `postgres_schema`。`persistence/postgres_schema.py` 给 psycopg DSN 注入 search_path，asyncpg 使用 `server_settings.search_path`；schema 只接受小写普通标识符。`runtime` 符合要求，**可配置到 runtime 为源码确认，实际落表范围尚待验证**。
- 回退风险：模板 `database.backend: sqlite`；类默认 `memory`；缺省 checkpointer 最终产生 InMemorySaver；旧 `checkpointer:` 优先于统一 `database:`。P2-0B 必须显式设置 postgres，删除旧段或严格核对一致性，检查生效配置和 saver 类型，做缺 DSN、断库、缺 extra、旧 SQLite 段等负例。不能只看 YAML 中出现 postgres。
- 自动 DDL：`persistence/engine.py` / `bootstrap.py` 会建 schema、自动迁移 app 表；数据库不存在时还有尝试创建数据库的路径。Gateway 的 users、threads_meta、runs、run_events 等也属于上游运行数据，应全部位于测试目标的 runtime；不只是四张 checkpoint 表。不得以 owner DSN 指向 MIS 开发/正式业务库启动。
- 现有测试 schema 由 `mis_admin` 拥有，`mis_runtime` 有 USAGE/CREATE；CREATE SCHEMA IF NOT EXISTS、上游迁移、检查点 setup 和既有 schema owner 的兼容性待 P2-0B 实测。受限账号应无 CREATEDB/CREATEROLE；不能以扩大业务权限解决启动问题。新建 runtime 表的 owner/default privileges 也需核对。
- DSN：MIS 使用 SQLAlchemy `postgresql+psycopg` URL，上游统一配置的 ORM 使用 asyncpg、Checkpoint 使用 psycopg。后续在秘密配置中提供上游支持的普通 PostgreSQL URL，分别验证 SSL/channel binding/连接选项；不要直接复制 MIS URL 后假设双驱动兼容。Neon 休眠后重连和连接池行为也待测。

### 4.2 Memory 隔离

- 默认示例 `memory.enabled: true`、`injection_enabled: true`、`mode: middleware`、`manager_class: deermem`。这不符合 MIS 正式知识治理边界。
- 写入口：`agents/middlewares/memory_middleware.py:161` 检查 enabled 后排队自动更新；`agents/lead_agent/agent.py:654` 组装中间件/工具模式。读回与隐藏注入入口：`agents/lead_agent/prompt.py:878` 检查 enabled 和 injection_enabled。
- P2-0B 基线应显式同时设置 `enabled: false` 与 `injection_enabled: false`，使用全新 `DEER_FLOW_HOME` 和独立 memory 路径；检查无 memory 工具绑定、无旧记忆读回、无 `<memory>` 注入、无结束/退出时延迟写入。**只关闭 injection 或改成 tool 模式不足以证明自动/显式写入已隔离**。管理 API、插件和其他调用点仍须验证权限，不能把这两个开关当成全局存储防火墙。
- 公共候选入口：`agents/memory/manager.py:128` 的 MemoryManager 契约与 backend factory；DeerMem 实现在 `agents/memory/backends/deermem/deer_mem.py`。默认文件存储、FTS5/SQLite 派生索引不能成为 MIS 正式 knowledge 权威库。
- 私有抽取实现：`.../deermem/core/updater.py:2095` 的 `update_memory()` 返回是否已持久化，而非无写入候选；存在 `_apply_updates`。**尚未确认稳定的无写入抽取/去重公共 API**，不能直接拿 updater 当只读算法。候选复用以后在隔离临时存储验证，必要时走薄 Adapter 或已批准路线中的轻量回退；不改核心引擎、不实现 C2。

### 4.3 Docker Sandbox

- 默认 `deerflow.sandbox.local:LocalSandboxProvider` 不是 Docker 隔离证明。容器候选为 `deerflow.community.aio_sandbox:AioSandboxProvider`，实现位于 `community/aio_sandbox/aio_sandbox_provider.py`，本地容器后端为 `local_backend.py`，通过容器运行时 CLI 启停，agent-sandbox 客户端访问 AIO HTTP API。
- 配置需显式指定 provider、AIO 镜像 digest、容器前缀、授权 mounts、port、并发/超时和 network policy。配置模板提醒默认镜像 `:latest` 旧版本可能缺 API，建议版本 `1.11.0` 仍须实际拉取验证和锁 digest。
- 网络模式 open/isolated/allowlist；模板说明受限网络要求 **Docker Engine 28+**，不适用于 Apple Container 或 provisioner 模式。网络代理镜像也要锁定。allowlist 应使用拒绝未经批准域名的策略。
- `local_backend.py:240` 默认 memory `2g`、CPU `2`、PID `512`，通过 `DEER_FLOW_SANDBOX_MEMORY`、`DEER_FLOW_SANDBOX_CPUS`、`DEER_FLOW_SANDBOX_PIDS_LIMIT` 配置并生成 CLI 限额。磁盘配额、超时真正终止、取消/失败后的容器和文件回收尚未实测。
- provider 计算 thread/workspace 挂载并缓存/复用 sandbox；不能由此推断同一 thread 内不同 Specialist 文件隔离已满足 A3。后续需探测跨角色读取、宿主路径、数据库/元数据网络访问、Docker socket 暴露及取消清理。不得给 sandbox 注入 DB 凭据或挂载宿主 Docker socket；宿主 provider 所需 Docker 控制权限与 sandbox 内权限区分。

## 5. 本地与远程环境检查表

数据库检查用现有凭据从内存读取配置，在 `SET TRANSACTION READ ONLY` 事务中查询版本、扩展、schema、角色、成员关系及权限，最后 rollback；异常仅输出类型/SQLSTATE。未执行建库、迁移、建表、DML 或破坏性操作；未输出密码、Key 或连接字符串。

| 项目 | 本次实际结果 | 分类/限制 |
|---|---|---|
| Python | MIS `.venv/Scripts/python.exe` 可执行：CPython `3.12.16` | 预检已验证；裸 `python` 指向 WindowsApps 占位入口，后续指定环境 |
| uv | shell PATH 未发现；已有 `C:\Users\Muil\AppData\Local\Microsoft\WinGet\Links\uv.exe`，版本 `0.13.7` | 预检已验证；无需安装或改系统 PATH |
| MIS 依赖 | `uv pip check` 检查 27 包兼容；psycopg 3.3.8、SQLAlchemy 2.1.8、pytest 9.2.0、ruff 0.17.3 | 仅现有 MIS 环境，不是 DeerFlow 依赖安装结果 |
| MIS 锁/环境一致性 | `uv sync --locked --check` 报 outdated：仅 MIS 本地项目安装来源需刷新，拟卸载/重装该 editable 包 | 待修复环境一致性；本次未实际 sync，不改锁文件 |
| DeerFlow 依赖环境 | 未安装、未启动 | 待验证；须在独立 upstream 环境安装 postgres extra |
| Docker / psql | `Get-Command docker,psql` 未发现 | 本地不可用于容器验收；不安装 Docker/WSL，不断言存在可用 daemon |
| Neon 开发目标 | 连接成功，PostgreSQL `17.11 (9045acd)`；未发现 vector 扩展及 mis/runtime/knowledge/trace/cache schema；未发现 MIS 专用角色 | 实际目标未初始化，不根据历史文档推断当前已就绪；后续角色权限查询因角色缺失报 SQLSTATE 42704，本次不补建 |
| Neon 测试目标 | 连接成功，PostgreSQL 同上，vector `0.8.0`；五个 schema 均存在、owner 为 mis_admin；`mis.alembic_version=0002` | 预检已验证；相较开发目标，去除 pooler 别名后 host/port/database 标识不同；Neon 控制台分支名称与组织/地区未通过控制面复核 |
| 测试 Runtime schema 权限 | mis_runtime：runtime USAGE/CREATE=true；mis USAGE=true、CREATE=false；trace USAGE=true、CREATE=false；knowledge USAGE/CREATE=false；public USAGE=true、CREATE=false | 权限目录预检已验证；本次没有写入探针 |
| 测试业务表权限 | mis schema 共 10 张表（含迁移表），mis_runtime 有 SELECT，无 INSERT/UPDATE/DELETE/TRUNCATE | 当前表边界预检已验证；runtime/trace/knowledge 尚无普通表，不虚构这些表的写入测试 |
| Runtime 角色能力 | mis_runtime 为 LOGIN，非 superuser，无 CREATEDB/CREATEROLE；未发现其继承其他角色 | 目录已验证，不等于已拿到可登录受限凭据 |
| 现有 DB 凭据 | dev/test 均以 neondb_owner 登录；测试 owner 可切换 mis_admin/mis_app/mis_runtime 等角色 | **阻塞：不能将此连接直接交给 Runtime**；需专用受限凭据/测试身份及负责人确认目标 |
| GitHub Actions | MIS 现有 CI 配置 ubuntu-latest + pgvector/pgvector:pg17，P1 报告有既往 CI 证据 | 仅配置和历史；本次未新增/触发 P2 workflow，未验证 Docker Engine 28+ 或 Sandbox |
| 远程 Linux | 未配置可用主机/凭据、资源和网络策略 | 待负责人提供/确认；不能标记可用 |
| 模型配置 | `.env` 与当前进程合并检查：LLM_PROVIDER、LLM_API_KEY 均为空；未发现其他匹配的模型/API Key/base URL/预算配置 | **阻塞真实模型验证**；仅该范围内未发现，不扫描其他账户秘密或尝试调用 |

后续环境路径：优先新建隔离 GitHub Actions P2 job 或一次性远程 Linux 验证机，先执行 `docker version`、`docker info` 核实 Engine 28+，再拉取固定 digest 的 PostgreSQL/AIO/代理镜像；只用合成输入。现有 P1 CI 不自动具备 P2 Sandbox 验收能力，不在本次提交 workflow。

## 6. 前置确认、时间盒与阻塞项

| 编号 | 需要闭合的事项 | 当前结论 |
|---|---|---|
| B1 | P1 负责人最终人工评审：人员、日期、范围及正式记录链接 | 待确认，无证据不写已批准 |
| B2 | P2-0B 测试目标、专用 Runtime 凭据与允许的 DDL/迁移范围 | 测试目标及目录权限可见，但只有 owner 连接；未批准 owner 启动或改开发目标 |
| B3 | Docker CI/远程 Linux、资源配额、Engine 版本和镜像 digest | 尚未验证；本机无 Docker 命令 |
| B4 | 模型供应商、base URL、协议、精确模型/版本、Key、预算 | 全部待确认；未发生模型请求和费用 |
| B5 | Spike 时间盒、负责人和停止/重新评估条件 | 计划只要求开始前约定，尚无批准记录 |
| V1 | 实际配置版本/Hash、postgres extra 安装、双驱动 TLS、独立启动、错误配置防回退 | 待 P2-0B 验证 |
| V2 | Memory 无写入/读回/注入及候选 API、Sandbox 隔离/清理、恢复幂等 | 源码入口已定位，实测未执行 |

建议时间盒（**提议，未批准**）：P2-0B 两个工作日，第一天完成 Docker/镜像、依赖、受限 DB 与 Backend 无 UI 启动；第二天完成 PostgreSQL 重启恢复、防回退负例、Memory 隔离和 Sandbox 冒烟并汇报。完整 P2（角色、Adapter、结构化产物、A4、Context/SSE 等）另行约定时间盒，不能把两天视为完整 P2 承诺。关键门槛在约定时间盒内无法通过配置/官方扩展/薄适配满足时，保留失败证据并按 ADR-0002 交负责人评估，不改核心引擎或静默换 Runtime。

模型确认至少包括：供应商、官方 endpoint、Chat Completions/Responses/Anthropic 等协议、精确 model ID（不要只给展示别名）、工具调用/流式/结构化输出/usage/超时/重试兼容性、上下文与单次输出上限、输入/输出/缓存价格及币种。预算需分别给出本次 Spike 总额、单次 Run 金额/Token/调用次数/时长、并发、重试及摘要等后台调用额度与超限停止规则。模板 token_budget 默认禁用；启用后的硬停语义也需验证，不能用 Prompt 或 token_usage 展示替代确定性预算执行。

## 7. 下一任务 P2-0B 的复现步骤（本次未执行）

以下是在 B1–B5 闭合后执行的 Linux 路径；变量中的秘密由批准的测试秘密注入，不回显，不使用 shell tracing。稀疏 checkout 应在独立验证机恢复完整工作树后安装；上游测试文件是否存在需检查。

```bash
git clone --depth 1 --branch v2.2.0 --single-branch \
  https://github.com/bytedance/deer-flow.git deer-flow-p2-0b
cd deer-flow-p2-0b
test "$(git rev-parse HEAD)" = 58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a
git checkout --detach 58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a
docker version
docker info
uv --version
cd backend
uv sync --locked --all-packages --extra postgres
uv pip check
uv run --locked --extra postgres python --version
uv run --locked --extra postgres pytest -q \
  tests/test_checkpointer.py tests/test_postgres_schema_helper.py \
  tests/test_memory_middleware.py tests/test_aio_sandbox_provider.py
```

这些是上游测试候选，不代替 MIS 集成验收；需记录通过、失败和 skipped。确保每个 `uv run` 继续指定 postgres extra，避免 uv 同步时去掉可选依赖。记录实际 uv/Python、锁 Hash、依赖版本、许可证清单；此处测试尚未运行。

1. **先冻结镜像**：对批准的 AIO/网络代理/数据库镜像执行 `docker pull <批准的标签>`，用 `docker image inspect --format '{{json .RepoDigests}}' <镜像>` 登记 registry digest 和平台，后续 `docker pull <image>@sha256:<已核实值>`。后端如自建也需记录基镜像 digest、构建参数与产物 digest；禁止捏造值或继续使用 latest 作为冻结结果。
2. **只读验证目标与身份**：分别用管理身份和实际 Runtime 身份核对 PG17、vector、测试分支、`current_user`、schema owner/ACL、角色继承、`search_path`、无业务写权限；只把测试 DSN 放入秘密变量 `DEER_FLOW_TEST_DATABASE_URL`。DSN 不进入命令参数日志或报告。获得批准后才在独立测试目标验证 runtime DDL/迁移；失败保留 SQLSTATE，不放宽 mis/knowledge 权限。
3. **生成隔离配置**：从固定模板复制到仓库外测试配置，保留 config_version 63，设置如下覆盖项，再填入已批准模型、容器/网络及鉴权配置。此片段不是完整可启动配置，也没有在本次落地。

```yaml
database:
  backend: postgres
  postgres_url: $DEER_FLOW_TEST_DATABASE_URL
  postgres_schema: runtime
  checkpoint_channel_mode: full
memory:
  enabled: false
  injection_enabled: false
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  image: <已核实的AIO镜像@sha256:digest>
  container_prefix: mis-p2-test
  network:
    mode: isolated
token_budget:
  enabled: true
  max_tokens: <负责人批准的单Run额度>
```

删除旧 `checkpointer:` 段；如必须保留，检查它也为 postgres/runtime，避免优先级覆盖。独立 `DEER_FLOW_HOME` 不含历史 memory；确认所有后台服务、插件、外部工具和调度器配置不会扩大验证范围。`models` 使用 `config/model_config.py`、`models/factory.py` 的官方 provider 配置，不自行假设协议兼容。

4. **无 UI 启动**：在 backend 目录，设置 `DEER_FLOW_PROJECT_ROOT`、`DEER_FLOW_CONFIG_PATH`、新建的测试 `DEER_FLOW_HOME`，注入受限秘密与批准模型，再执行以下官方等价入口；仅绑定 loopback。运行前确认这是允许迁移的测试库。

```bash
PYTHONPATH=. uv run --locked --extra postgres uvicorn \
  app.gateway.app:app --host 127.0.0.1 --port 8001
# 另一个终端；不启动前端、不运行根目录 make dev
curl --fail --silent http://127.0.0.1:8001/health
curl --fail --silent http://127.0.0.1:8001/health/ready
curl --fail --silent http://127.0.0.1:8001/openapi.json > gateway-openapi.json
```

5. **最小 HTTP/SSE 与恢复**：先从 OpenAPI 确认直连 `/api/threads`、`/api/threads/{id}/runs`、`/stream`、`/{run_id}`、`/{run_id}/cancel`、`/state` 实际路径与鉴权。用批准的受限服务身份建测试 thread，提交固定合成输入（`assistant_id: lead_agent`，`input.messages` 为 user 消息），以唯一 Idempotency-Key 调用 create/stream。保存脱敏请求、响应、SSE、thread/run/checkpoint ID；重新提交相同 key 不重复执行，不同 payload 同 key 明确拒绝。暂停/`command.resume`、取消和重复恢复依接口 schema 做后续测试，不能假设有独立 `/resume` URL。
6. **Postgres 正/负例**：核对 saver 实际类型，记录 runtime 中全部上游表位置及 checkpoint；停 Gateway 进程并重启，读取同一 thread 的状态，确认不依赖内存或 SQLite。断库、缺 DSN/extra、旧 SQLite 覆盖等负例必须明确失败或被启动预检拒绝，不得报告为就绪。比较前后 mis/knowledge/trace 的表定义与数据摘要，检查 public 无上游落表；不清空测试库、DROP schema 或修改原始 Raman 包。
7. **Memory/Sandbox 冒烟**：放置隔离 canary，验证跨项目/角色和历史记忆均不注入；运行结束、等待 debounce、正常退出后均无自动写入。固定容器 digest 下探测授权/越界文件、隔离网络、CPU/内存/PID、命令超时、取消/失败回收；Docker socket/DB 秘密不可见。按 run/thread 记录容器身份和资源 inspect，不能用“容器成功启动”代替隔离通过。清理仅限明确标识的本次测试资源，先核对范围。

**P2-0B 验收标准**：版本/锁/实际配置 Hash/镜像 digest 可重现；无上游 UI 时健康与一次授权 API/SSE 可调用；PostgreSQL runtime 落表且重启状态可恢复；错误配置不能被误报持久化就绪；实际受限 Runtime 身份不能写 mis/knowledge；Memory 写入/读回/注入隔离有 canary 证据；Docker 冒烟隔离/限额/清理有日志；模型与预算配置有批准记录及脱敏用量。任何失败/跳过项明确记录，不勾选完整 P2 验收。完整角色协作、MIS Adapter、业务幂等写入、A4 Evidence、Context 保真和 MIS SSE 产品契约继续按后续任务执行。

## 8. 本次验证边界

本次仅修改本报告和文档索引；没有修改配置、代码、ADR、P1 契约、数据库数据或原始 Raman 基准任务包。执行 `uv run --no-sync ruff check .` 通过；未跑会初始化/写入测试库的 pytest，也未把 P1 历史 126 passed 作为本次或 P2 测试结果。没有启动 DeerFlow、调用模型、拉镜像或自动继续 P2-0B。

## 9. P2-0B 执行记录（2026-11-08）

本节为后续执行记录，不覆盖前面 P2-0A 历史。负责人本次确认：使用现有 OpenAI-compatible 服务；**整个 P2 真实模型调用累计预算 10 USD**；Docker/Sandbox 保持 BLOCKED。P1 最终人工评审继续待确认。没有新增 Adapter、Multi-Agent、UI 或 P3–P5 实现。

状态口径：PASS=实际执行且符合标准；FAIL=执行但不符合标准；BLOCKED=缺少前置条件；NOT RUN=未执行；SOURCE CONFIRMED=仅源码确认。

| 检查项 | 状态 | 本次证据 |
|---|---|---|
| 分支及远程同步 | PASS | `git status --short` 仅 P2-0A 两份文档变更；分支正确；`git fetch origin` 后 `git rev-list --left-right --count HEAD...origin/feat/p2-deerflow-integration` 为 `0 0` |
| P2-0A 报告读取 | PASS | 实际读取完整报告及 AGENTS.md，不仅依赖聊天摘要 |
| 上游固定版本 | PASS | `git -C ../deer-flow-p2-0a-filtered rev-parse HEAD` 为 `58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a`；工作区干净 |
| 文档提交与推送 | BLOCKED | P2-0A 尚未提交；AGENTS.md 要求完整 pytest 通过，但 `tests/conftest.py:db_engine` 会执行 `db/init.sql` 和 Alembic upgrade；本次明确要求初始化/迁移先确认。已请求仅本次文档提交豁免完整 pytest，未收到确认前不绕过提交规范 |
| lint | PASS | `uv run --no-sync ruff check .`，通过；uv 使用本机 WinGet 已安装路径 |
| 模型配置可用性 | BLOCKED | MIS `.env` 仅 LLM_PROVIDER/LLM_API_KEY（均空）与两个 DB URL；上游根/backend `.env` 不存在；当前进程无 OPENAI/LLM_/MODEL_ID/Runtime DSN 匹配项。未找到 Base URL、模型 ID、鉴权凭据；已请求服务配置文件路径，不扫描其他账户秘密 |
| 协议/工具调用/流式支持 | NOT RUN | 未获得 endpoint/model，不能假设兼容；未发 `/models`、Chat Completions 或 Responses 请求 |
| 费用可约束性 | BLOCKED | 10 USD 总额度已批准，但无价格表、服务端额度或已存在用量账本，不能计算可承受调用或可靠监控实际费用；不发无费用约束的请求 |
| Neon 测试目标只读连接 | PASS | 当前身份 neondb_owner；PG `17.11 (9045acd)`；事务 read_only=on；迁移版本 `0002` |
| Runtime 角色目录边界 | PASS | mis_runtime 为 LOGIN、非 superuser、无 CREATEDB/CREATEROLE；runtime USAGE/CREATE=true；mis USAGE=true、CREATE=false；knowledge 无 USAGE/CREATE；trace USAGE=true、CREATE=false；现有 mis 普通表 10 张，具有 INSERT/UPDATE/DELETE/TRUNCATE 任一种权限的数量为 0 |
| 实际 Runtime 登录与拒写探针 | BLOCKED | 只有 owner DSN，未发现专用 Runtime DSN；目录检查不是实际受限登录测试，未启动 DeerFlow 使用 owner，也未以 SET ROLE 冒充受限凭据隔离 |
| 实际 Runtime 写入位置 | NOT RUN | 本次只读查询 runtime 表列表为空；没有 DeerFlow 写入，不能标记 PostgreSQL checkpoint 验收通过 |
| Gateway 自动迁移 | SOURCE CONFIRMED | persistence/engine.py:257–297 调用 bootstrap_schema；bootstrap.py 处理 create_all/stamp/upgrade；Gateway deps.py:849–851 初始化 engine/checkpointer。启动本身可能执行 DDL，尚未授权执行 |
| 无 Docker 最小请求可行性 | SOURCE CONFIRMED | lead_agent/agent.py:548 传 lazy_init=True；sandbox/middleware.py:59–60 描述首次工具调用获取；231–248、354–368 的技能 projection 可绕过普通延迟路径；436–445 存在 prewarm 路径。因此仅可确认有延迟机制，尚不能确认安全无 Sandbox 运行 |
| Gateway 健康、Python 客户端、真实返回、Thread/Run、SSE/终态 | BLOCKED | 缺 Runtime 凭据/迁移批准、模型配置/费用约束及已核实的无宿主执行配置；未启动 Gateway，没有 HTTP 请求或响应，没有运行日志和 ID 可登记 |
| Docker/Sandbox 隔离 | BLOCKED | 按本次负责人决定保持阻塞；未用 LocalSandboxProvider 或宿主 bash 替代 |

### 9.1 实际执行与脱敏输出

在 MIS 仓库执行了以下命令；没有 uvicorn、模型 API 或数据库写入命令：

```powershell
git status --short
git branch --show-current
git fetch origin
git rev-list --left-right --count HEAD...origin/feat/p2-deerflow-integration
Get-Content AGENTS.md
Get-Content docs/spike/P2_deerflow_integration.md
Get-Content tests/conftest.py
git -C ../deer-flow-p2-0a-filtered rev-parse HEAD
git -C ../deer-flow-p2-0a-filtered status --short
& $env:LOCALAPPDATA/Microsoft/WinGet/Links/uv.exe run --no-sync ruff check .
```

配置探针由 `.venv/Scripts/python.exe` 从 dotenv/当前进程读取，仅输出键名及有无值；Base URL 如存在只允许输出去掉 userinfo/query 的部分，本次没有可报告的 endpoint。数据库探针通过 `engine_for(test=True)` 连接，执行 `SET TRANSACTION READ ONLY`、`SET LOCAL statement_timeout='10s'` 后查询 pg_roles、pg_namespace、pg_class、pg_tables 和 mis.alembic_version，最后 rollback。关键拒写查询如下（只读，不尝试 INSERT）：

```sql
SELECT count(*), count(*) FILTER (
  WHERE has_table_privilege('mis_runtime', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')
)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='mis' AND c.relkind IN ('r','p');
-- 结果：(10, 0)
SELECT tablename FROM pg_tables WHERE schemaname='runtime' ORDER BY 1;
-- 结果：空列表
```

API 请求/脱敏响应：无（未发送）；运行日志：无（未启动）；模型版本、Token：未知/无调用记录；**本 chat 已执行真实模型请求 0 次，本次费用 0 USD**。已知本 chat P2 累计支出为 0 USD，可分配余额 10 USD；其他会话/服务账户是否有 P2 消耗未知，首次调用前需对账，不将 10 USD 当成已核实的账户余额。

### 9.2 待确认的具体方案与影响范围

1. **文档提交**：允许仅本次文档变更豁免 AGENTS.md 的完整 pytest 门槛，使用 ruff、diff/链接检查后，仅添加报告和 docs/README.md，单独提交、fetch 后推送当前分支。否则暂不提交；不为满足提交门槛执行未批准的数据库初始化。
2. **凭据**：优先提供现有 mis_runtime 的独立测试登录 DSN（只存本地秘密文件），不修改角色、密码或 ACL。管理/初始化身份只用于经批准的测试 runtime 迁移，运行期只能使用 mis_runtime；不得把 owner 凭据交给 Gateway。现有 runtime schema 属 mis_admin，需先确认上游启动迁移在此 owner/权限组合下的兼容性，再决定是否需要单独迁移身份；未验证前不新增角色或授予权限。
3. **迁移授权范围**：仅指定 Neon 独立测试目标的 runtime schema；允许上游 app migrations 与 checkpoint setup 所需 DDL，记录前后表清单、owner 与默认权限，不改 mis/knowledge/trace、不清空库、不启用 CREATE DATABASE。先审查实际迁移；遇 schema ownership/DDL 权限错误停止并提交精确调整方案，不临时使用 owner 启动。**此方案尚待批准，未执行。**
4. **模型/预算**：提供现有服务配置文件路径与价格/服务端额度依据；确认精确模型及协议，再准备一次输出最多 64 Token、max_retries=0 的独立 Python 客户端请求。先计算包含输入、输出和后台 title/summary 等调用的费用上界，限制调用数/时长和循环；费用未知且无服务端硬额度时仍停止。每次调用前对账剩余 P2 额度，达到 10 USD 即停止；只记录脱敏 usage/费用，不猜测成本。
5. **无 Sandbox 路径**：继续静态核对官方 tools/authorization/skills 配置，禁用全部执行/文件/网络/MCP/子代理工具、memory、预热与后台额外模型调用，验证不能提前 acquire sandbox。先做无外部服务的配置/工具绑定检查；做不到即保持 BLOCKED，不启动本机命令执行替代 Sandbox。Docker 阻塞独立保留，不能据无工具 Smoke 宣称通过 Sandbox 验收。

完整 P2 验收仍未通过：Backend 真实调用、模型兼容性/预算、受限身份实际拒写、runtime 持久化/重启恢复、Memory 隔离、角色/Context、业务幂等产物、A4、MIS SSE、Sandbox 均没有本次通过证据。本次在前置条件处停止，不进入下一阶段。

### 9.3 负责人回复与交接闭合

2026-11-08，负责人明确批准：**仅本次两份纯文档提交豁免完整 pytest**，以 ruff、diff 和文档检查通过后提交推送。此批准取代 9 节表中“等待文档提交豁免”的历史阻塞，不授权数据库初始化、迁移、角色或权限变更。

负责人指定模型服务配置位于 MIS 根目录 `.env`，服务商为 openai，测试模型选择 **GPT-6 Luna**。再次从该文件读取的磁盘结果仍为 `LLM_PROVIDER`、`LLM_API_KEY` 空值，未发现模型 ID 或 Base URL 字段；可能尚未保存，但原因未核实。没有回显或改写秘密。模型展示名称不能直接当作 API ID；精确 ID、接口能力、价格表/服务端硬预算以及跨会话累计支出仍待核实，真实请求继续 BLOCKED。本次追加核查未发生模型调用，已知本 chat 累计支出仍为 0 USD。

本次提交范围只包含 `docs/spike/P2_deerflow_integration.md` 和 `docs/README.md`。提交前核对分支正确，fetch 后本地/远程差异为 `0 0`；执行 ruff、diff、文档本地链接/代码围栏检查。提交推送结果由 Git 历史和任务最终汇报记录，不把提交成功当作 Smoke 通过。
