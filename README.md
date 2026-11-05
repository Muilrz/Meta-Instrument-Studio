# MetaInstrumentStudio

面向科研仪器研发全流程的 AI 原生工程平台。

- 目标架构：[MetaInstrumentStudio_ARCHITECTURE.md](MetaInstrumentStudio_ARCHITECTURE.md)
- 开发计划：[plans/MIS_Development_Plan_v0.1.md](plans/MIS_Development_Plan_v0.1.md)
- 当前阶段：**P0 工程基础与基准任务包**

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

## 目录

| 目录 | 内容 |
|---|---|
| `src/mis/` | 平台代码 |
| `tests/` | 自动化测试 |
| `fixtures/raman_baseline/` | Raman 基准任务包（合成资料），各阶段统一的验收输入 |
| `plans/` | 开发计划、阶段任务说明 |
| `reviews/` | 阶段报告、审查记录 |
| `docs/adr/` | 架构决策记录 |
| `research/` | 开源 baseline 选型调研（存档） |

目录约定和技术栈选择见 [ADR-0001](docs/adr/0001-repo-structure-and-stack.md)。

## 密钥

把 `.env.example` 复制为 `.env` 后填写。`.env` 不会被提交。P0 阶段不需要任何密钥。
