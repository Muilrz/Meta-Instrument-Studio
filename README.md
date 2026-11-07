# MetaInstrumentStudio

面向科研仪器研发全流程的 AI 原生工程平台。

- 目标架构：[docs/architecture.md](docs/architecture.md)
- 开发计划：[docs/plans/development_plan.md](docs/plans/development_plan.md)
- 全部文档：[docs/README.md](docs/README.md)
- 当前阶段：**P1 核心数据契约与 Project Service**（T1–T8 已实现，本地回归通过；最终 CI 验证中）

进度与验收边界见 [P1 阶段报告](docs/reviews/P1_report.md)。

## 快速上手

需要先安装 [uv](https://docs.astral.sh/uv/)。uv 会自动准备 Python 3.12 和全部依赖。

```bash
uv run pytest
```

其他常用命令：

```bash
uv run ruff check .
```

```bash
uv run ruff format .
```

## 数据库

开发用 Neon 云数据库，不需要在本机安装 PostgreSQL，原因和细节见 [ADR-0001](docs/adr/0001-repo-structure-and-stack.md#部署)。

1. 把 `.env.example` 复制为 `.env`。
2. 在 Neon 控制台（组织 Muil，项目 `meta-instrument-studio`）点 **Connect**，复制直连地址（不要选 Pooled）。
3. 填入 `.env` 的 `MIS_DATABASE_URL`，把开头的 `postgresql://` 改成 `postgresql+psycopg://`。

`.env` 不会被提交。连接地址带密码，不要发到聊天或邮件里。能安装 Docker 的开发者也可以改用本地容器，见 `.env.example` 中的说明。

测试必须使用独立 Neon `test` 分支，将该分支直连地址填入 `.env` 的
`MIS_TEST_DATABASE_URL`。测试会检查开发与测试端点不同；缺少测试库配置会报错，不会跳过。

使用具备建角色和 schema 权限的数据库所有者初始化（先在测试分支验证）：

```bash
uv run python -m mis.project_service.setup --test
uv run alembic -x test=true upgrade head
uv run pytest
```

初始化器执行 `db/init.sql`，再用 Alembic 建立 `mis` 业务表。SQL 可在 Neon 和标准
PostgreSQL + pgvector 上执行；不建立 Runtime、Trace 或知识库业务表。
`mis_admin` 负责迁移，`mis_app` 负责业务写入，`mis_runtime` 对 `mis` 只有只读权限。
SQL 不设置默认密码；部署时分别配置角色凭据，并让业务服务使用 `mis_app` 连接。
测试使用数据库所有者，通过 `SET LOCAL ROLE` 验证权限；每个测试事务最终回滚。

能安装 Docker 时，在 `.env` 设置 `MIS_POSTGRES_PASSWORD`，然后执行：

```bash
docker compose up -d
docker compose exec postgres createdb -U postgres mis_test
```

分别将开发和测试连接指向本地的 `mis`、`mis_test` 数据库，再运行上述初始化命令。
开发库初始化使用 `uv run python -m mis.project_service.setup`；应由开发者明确执行。

Python 服务入口是 `ProjectService(session)`；所有写入在调用方的 SQLAlchemy 事务中执行，
服务不自行 commit。Evidence 和已保存版本没有删除接口；只能删除空项目。

## 业务备份与恢复

`mis.project_service.dump.dump_data(service)` 返回带格式版本的 `ProjectBackup`，使用
`model_dump_json()` 导出。`restore_data(service, json_text)` 在空业务库恢复九类业务对象，
保留 ID、需求与方案版本、状态历史、问答、纠正和证据；引用损坏或目标非空时拒绝导入。
调用方必须用 SQLAlchemy 事务包住操作，并在完成后结束事务以释放导出锁。

备份是业务模型的逻辑 JSON，索引由服务重建；不读取或写入 Agent Runtime、Trace 或知识库。
Schema 位于 `docs/schemas/ProjectBackup.json`。恢复不需要先删除 Evidence；应使用新的空业务库。

## 目录

| 目录 | 内容 |
|---|---|
| `src/mis/` | 平台代码 |
| `tests/` | 自动化测试 |
| `fixtures/raman_baseline/` | Raman 基准任务包（合成资料），各阶段统一的验收输入 |
| `docs/` | 全部文档：架构、计划、设计、ADR、阶段报告、调研存档 |

AI 会话（Claude Code、Codex 等）从 [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md) 开始。
