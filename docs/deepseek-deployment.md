# 0.10.1 DeepSeek 接入与基础服务部署

2026-11-17 核对 [DeepSeek 官方工具调用说明](https://api-docs.deepseek.com/guides/tool_calls/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)与[模型列表](https://api-docs.deepseek.com/quick_start/pricing/)：当前示例模型 `deepseek-flash`，Chat Completions 基址 `https://api.deepseek.com`。这些名称与能力以后可能变化，实际接入前应重新确认官方说明。

## 配置

```dotenv
REPOLENS_MODEL_URL=https://api.deepseek.com
REPOLENS_MODEL=deepseek-flash
REPOLENS_MODEL_THINKING=disabled
REPOLENS_API_KEY=
```

密钥只在本机 `.env` 或进程环境中填写。Python 原生仍不自动读取 `.env`；Compose 会读取。不要将真实 `.env` 提交到 Git。示例中的空密钥会让应用保持“模型未配置”，健康检查和空队列不会发起模型请求。

新增 `REPOLENS_MODEL_THINKING=provider_default|disabled`，默认 provider_default 不改变其他供应商的请求字段；显式 disabled 时才发送 `thinking: {type: disabled}`。API/worker 的 Compose 环境同时传递该设置，现有完整配置/源码指纹包含它。修改此设置或升级源码后，旧任务恢复仍需符合原来的严格指纹规则。

DeepSeek 默认开启思考模式，工具调用历史需要保留并回传相应 reasoning_content。当前 RepoLens 适配器不实现这种思考历史，因此官方 DeepSeek 接入必须使用 disabled。preflight 对不兼容模式给出诊断；真实密钥存在时，configured_model 在网络请求前拒绝错误模式。不宣称已支持 DeepSeek 思考模式。

## 独立验收部署

本机准备使用独立 Compose 项目名、新卷、回环端口8001和已检查不冲突的子网；实际项目名/端口记录在本机 `.env` 和 git 忽略的 `test-results/deepseek-local-deployment.json`。数据库密码本机随机生成，没有写入代码、报告或聊天。Docker 上下文也排除 `.env`。

```powershell
docker compose config --quiet
docker compose build api worker
docker compose up -d postgres redis api worker
docker compose ps
# 容器当前环境的离线检查；仅检查配置，不连接供应商：
docker compose exec -T api python -m repolens.preflight --tools-only --require postgres --require redis --json
```

基础服务只有 PostgreSQL、Redis、API、worker；不启动 Milvus、重排和浏览器 sidecar。API/worker 共用持久卷和相同配置，PostgreSQL/Redis 无宿主端口映射。页面使用 `.env` 中配置的 REPOLENS_PORT。启动前保留已有服务/数据，不对旧数据库做迁移或清理。

将密钥本机填入 `.env` 后，需要显式更新 API 和 worker 的进程环境：

```powershell
docker compose up -d api worker
docker compose exec -T api python -m repolens.preflight --require postgres --require redis --json
```

不要运行或对外分享 `docker compose config` 的展开结果、容器完整 inspect/env 输出，这些会含凭据；使用 config --quiet 和上述脱敏 preflight 即可。

## 验收与费用范围

本轮用户选定 DeepSeek，批准本轮真实模型联调费用上限10元人民币。该上限不是程序已实现的货币限额：现有任务预算为模型调用数、Token 和时间。没有本机有效密钥和保守费用核算前，不提交模型任务；不运行完整评测矩阵或故障重试实验。

先确认 `/health` 版本、postgres/api 角色、worker_ready 和 `/ready` 状态。它们只代表基础服务与租约状态，不验证模型凭据或工具调用。后续真实模型联调需单独记录供应商实际用量和费用；服务健康、编译通过不能写成“模型联调通过”。本轮不跑自动测试，也不导入/分析用户仓库来冒充模型验收。

源码提交包含非敏感配置、适配和操作文档；本机 `.env`、构建日志与环境收据保留在 git 忽略范围。实际部署结果以本次执行记录和本机收据为准。
