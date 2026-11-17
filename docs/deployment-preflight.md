# 0.10.0 部署配置检查与验收顺序

新增 `python -m repolens.preflight`。只读取当前进程配置、发行包版本和目录权限提示；不读取 `.env` 内容、不连接服务、不构造应用/数据库/worker、不创建业务数据或触发模型调用。

## 1. 离线配置检查

```powershell
.\.venv\Scripts\python -m repolens.preflight
.\.venv\Scripts\python -m repolens.preflight --json
# 只检查工具/仓库运行准备，不要求模型：
.\.venv\Scripts\python -m repolens.preflight --tools-only --json
# 完整拆分环境：需先在当前终端设置 execution_mode=api 和相应真实配置。
.\.venv\Scripts\python -m repolens.preflight --require postgres --require redis --require rerank --require renderer --json
```

默认要求真实模型配置。`--require` 可重复，支持 model/postgres/redis/hybrid/rerank/documents/renderer；要求 rerank 时也要求 hybrid，要求 renderer 时也要求 documents。可选能力全未配置时跳过，部分配置给警告；必选能力缺项返回阻塞错误。PostgreSQL 只要被选择就必须能解析 DSN；Redis 在拆分模式配置后必须能解析 URL，但未配置 Redis 时仍可数据库轮询。embedded 模式不会使用 Redis 唤醒，不能满足 `--require redis`。

退出码：0=本次要求的配置项齐备，1=配置/依赖存在阻塞项，2=命令参数错误。`configuration_ready` 仅表示离线检查，`runtime_verified` 永远 false，不能据此宣称服务、认证、模型工具调用或恢复已验收。JSON 使用 ASCII 转义，避免 Windows 重定向编码差异；报告不输出密钥、DSN、服务 URL、模型名称或原始异常。

包存在不代表锁定版本已安装或二进制可导入，仍需按 requirements.lock 安装并运行 pip check。目录权限只用 os.access 作提示，没有试写，不保证启动时实际能读写。没有查询 Docker 引擎；docker_cli_found 只表示命令能被定位。Linux API 声明 renderer socket 和站点允许列表，也不证明隔离浏览器已启动。

Python 进程仍不自动读取 `.env`。把配置写进文件后直接运行原生 CLI，不能据此判断 Compose 已配置或未配置。请在本机设置进程环境，不在聊天中发送密钥。URL/名称必须替换示例值；模型检查拒绝 `.example` 端点和 `.env.example` 的默认模型/密钥占位值。

## 2. 在实际 Compose 环境复核

以下是后续操作步骤，本轮未执行。先按 [infrastructure.md](infrastructure.md) 准备本地 `.env`；设置独立项目名、未占用端口与不冲突子网，使用新的验收数据，不让旧服务和新版本共用数据库。不要删除原数据卷或迁移原数据来验证安装。

```powershell
# 静态解析，不构建、不启动。
docker compose --project-name repolens-acceptance config --quiet
# 后续实际部署阶段才构建镜像；可能下载依赖。
docker compose --project-name repolens-acceptance build api worker
# 在容器的实际配置/挂载环境检查；替换默认 CMD 为 preflight，不启动应用。
# 此命令会创建临时容器及所需挂载，不是宿主机纯离线检查。
docker compose --project-name repolens-acceptance run --rm --no-deps api python -m repolens.preflight --require postgres --require redis --json
```

Windows 宿主机检查 renderer 会提示需要 Linux；应在 Linux API 容器环境检查 renderer 配置。若需要动态资料，再显式加 `--require renderer`，并配置网页允许站点。Redis/PostgreSQL 认证、容器间网络和共享卷权限还需要下面的真实服务步骤。

## 3. 真实服务验收（待执行）

1. 在独立验收环境启动 PostgreSQL、Redis、API 和 worker；检查健康状态与日志。API `/health` 记录应为当前源码版本、postgres 后端、api 角色；`/ready` 必须反映有效 worker 租约。
2. 停止 worker，等待租约过期，确认 `/ready` 变为503；重新启动后恢复200。此阶段不提交分析任务，不调用模型。
3. 导入一个公开小型仓库固定 commit，检查快照文件 hash、代码检索与证据读取。关键词工具不需要 Embedding；导入会使用网络和写入验收数据。
4. 再检查已配置的 Redis 通知降级、PostgreSQL 持久检查点、SSE 补发。动态网页、MCP 分别按 [web-documents-mcp.md](web-documents-mcp.md) 进行限定来源采集和只读工具验收。

这些操作会改变独立验收环境，不能当作本轮已完成。`/ready` 为200只证明 worker 租约存在，不代表模型、Milvus 或网页采集已正常。

## 4. 小规模真实调查与评测（待配置预算后执行）

先在本机设置模型凭据、确认可用模型与供应商费用预算，再用一个开发问题和一次重复；默认调查上限仍为30次模型请求、60000输入/输出 token、900秒，不是金额上限。混合检索和建库另有实际 Embedding/重排调用，不应在关键词连通前启用。

先完成单 Agent 的报告/引用查看，再尝试协作、显式中断恢复、取消可恢复任务并保留部分报告。记录实际调用量、未知预留和失败，不能用旧版合成验证结果替代本版真实验收。中断场景可能产生未知请求或重复费用。

最后按 [evaluation.md](evaluation.md) 和 [evaluation-baselines.md](evaluation-baselines.md) 新建小矩阵，独立人工审核标注与事实/结论/引用。当前30题标注仍为草案；没有独立批准时，不发布正式质量率，不运行完整810槽位矩阵，也不填写提升百分比。录像与简历实测结果在这些步骤之后补充。

## 当前交付状态

本轮实现离线检查并对本机真实进程环境做了只读清点。没有模型、PostgreSQL、Redis 或混合/重排配置，也没有 `.env`；14个检查范围内的依赖发行包可定位，Docker CLI 可定位，Docker 引擎未查询。未运行测试、服务、容器、迁移、网页采集、模型或评测。环境报告保存在 git 忽略的 test-results 目录，避免把本机环境快照当成其他人的验收结果。
