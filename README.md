# MetaInstrumentStudio

面向科研仪器研发全流程的 AI 原生工程平台。

- 目标架构：[docs/architecture.md](docs/architecture.md)
- 开发计划：[docs/plans/development_plan.md](docs/plans/development_plan.md)
- 全部文档：[docs/README.md](docs/README.md)
- 当前阶段：**P1 核心数据契约与 Project Service**（T1–T4 已实现并本地测试；T5 等待独立测试库）

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

## 目录

| 目录 | 内容 |
|---|---|
| `src/mis/` | 平台代码 |
| `tests/` | 自动化测试 |
| `fixtures/raman_baseline/` | Raman 基准任务包（合成资料），各阶段统一的验收输入 |
| `docs/` | 全部文档：架构、计划、设计、ADR、阶段报告、调研存档 |

AI 会话（Claude Code、Codex 等）从 [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md) 开始。
