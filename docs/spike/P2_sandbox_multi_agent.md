# P2 容器 Sandbox 与真实 Multi-Agent 协作

- 日期：2026-11-22；沿用 `feat/p2-deerflow-integration`，基线 `6e86c54`。
- 负责人已授权拉取官方所需镜像、部署容器 Sandbox，并给 P2 测试账号授予 sandbox:execute。
- DeerFlow 仍固定 `58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a`；未升级或修改上游核心。

## 部署

Docker Desktop / WSL2 的 Linux Engine 29.9.3 已启动。旧会话 PATH 未包含 Docker，脚本仅为当前进程及其子进程补入安装目录，没有改系统 PATH 或安全软件。

采用固定源码 `config.example.yaml` 推荐的官方 AIO `1.11.0`，镜像已固定为：

`enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox@sha256:6328d7fd2f0ff0b4c147c3d05b3df1ce331f4a482eb6e550ecd64ed1fcf906e7`

GHCR 网络代理镜像拉取没有进展，改为从同一固定提交原样构建官方 `docker/sandbox-network-proxy/Dockerfile`，未改其脚本。基础镜像为官方 `python:3.12-alpine`，构建输出固定为：

`mis-p2-network-proxy@sha256:593523982440d0d97055febf8f478f77d02b1f670ab45bd455f7df7477e99d34`

`p2_sandbox.py` 使用官方 AioSandboxProvider：network.mode=isolated、approval=deny、宿主机 Bash 禁用、prewarm=false、无额外挂载和凭据注入。沿用原生资源限制（2 GB、2 CPU、512 PID）、cap-drop=ALL 加官方启动兼容能力、no-new-privileges；不使用 privileged、host network 或 Docker socket 挂载。沿用官方 AIO 的 seccomp 配置，不声称完成独立的内核安全验收。

管理端口仅绑定 127.0.0.1，原生代理使用短期认证头；Sandbox 本身仅加入内部网络。`prepare_sandbox.py` 在模型调用前通过原生容器 backend 创建/健康检查/检查资源和网络后回收容器，模型调用为0。运行时另保留实际任务容器的检查快照。

普通 user 角色继续拒绝 Sandbox。新建专用 p2-sandbox 角色，仅增加 sandbox:execute，其他工具/技能/路由限制继承原配置；使用现有 mis_runtime 凭据，对刚注册测试账号的匹配 ID、email、原 user 角色作绑定 UPDATE，再以 `/auth/me` 确认。无 owner 提权、DDL 或其他账号授权。Lead 仍只有 task，三个 Specialist 仍无工具/技能。

生命周期沿用原生按 Thread 创建和回收：受控验证结束后撤销 PAT、退出验证 Gateway、回收本轮容器；Docker Desktop、镜像和生成的 Gateway 配置保留。没有重新部署 Neon、MIS 或整个项目。

## 运行与有界预算

工作目录为 MIS 仓库；代理镜像构建的工作目录为固定 DeerFlow 仓库：

```powershell
# 固定 DeerFlow 仓库
docker build -f docker/sandbox-network-proxy/Dockerfile -t mis-p2-network-proxy:58fc5bd .
# MIS 仓库
$env:MIS_P2_PROXY_IMAGE='mis-p2-network-proxy:58fc5bd'
..\deer-flow-p2-0a-filtered\backend\.venv\Scripts\python.exe docs/spike/prepare_sandbox.py
.venv\Scripts\python.exe docs/spike/gateway_multi_agent.py --sandbox
```

真实任务证据文件以 exclusive-create 防止误重跑；不自动覆写旧证据或重试模型。API Key/连接 URL 继续由本机 `.env` 提供，不进入镜像或提交。

首轮三个 Specialist 均完成、Lead 也返回三角色汇总，三个 draft 均校验写入，但继承的旧 Smoke 原生 Token Budget 为8000输入/192输出/8192总量。它在累计输入25538时给汇总追加终止文本，严格接收状态正确为 partial，未绕过校验。

修复仅调整官方 token_budget 配置，保持 enabled=true：输入上限687344、输出7168、总量694512，分别对应既有7次handler × 每次98192输入Token保守边界/1024输出。共享 Guard 仍限制实际输入JSON≤90000字节、7次模型处理、官方API、单次输出1024；SDK retries=0、原生attempts=1。每个任务最坏预留仍0.0723184 USD，没有取消费用限制或放宽模型工具。

首轮6次调用全部有usage：26521输入、722输出，按既定单价核算0.0030131 USD。此前保守占用0.0535860加该用量为0.0565991；修正后复验入场最大占用0.1289175/10 USD。缓存输入按原价计入保守核算，不替代账户账单；旧未知usage继续占用预算。

最终实际 Run、角色调用/并行证据、费用及 CI 结果统一登记在 [P2 主报告第24节](P2_deerflow_integration.md#24-p2-0f容器-sandbox-与真实协作)。仓库外证据位于 `mis-p2-gateway-evidence/`：首轮 `*-initial-token-limit.*` 保留，复验使用 `agents-live-0f.json`、`multi-agent-0f.json`、`gateway-0f.log`，部署检查为 `sandbox-0f-preflight.json`。

本轮只验证固定合成任务的真实协作，未自动采纳 InstrumentPlan 或写正式经验。Checkpoint/A4/基础数据库 Smoke 不重做，完整P2安全验收与火绒告警复核的历史状态不由此次功能验证代替。
