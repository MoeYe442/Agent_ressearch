# V3.1 工程化增量（0.6.0）

支持独立API进程、独立worker、PostgreSQL存储/官方检查点、Redis唤醒和Docker Compose。本轮遵守AGENT.md：只编译与静态检查，**没有运行测试、容器、真实服务或模型**，不能将0.5.0的339项测试结果视作本版本验收。

## 运行方式

默认`REPOLENS_EXECUTION_MODE=embedded`，未配置`REPOLENS_DATABASE_URL`时仍使用原SQLite。拆分时API用`api`，worker入口为`python -m repolens.worker`，自动选择worker角色。API不启动执行线程、不取得执行租约、不在启动时中断任务；API停机不停止独立worker。

两个进程必须使用同一数据库、同一代码版本、相同模型/检索/预算设置，并且**共享相同绝对路径的数据目录和仓库目录**。API登记的快照路径由worker执行文件操作，随后API也要读取快照证据。角色、网络白名单、Redis通知配置不计入执行指纹；模型、预算、检索配置、存储后端与全部Python代码仍绑定。

原生PowerShell示例（数据库与Redis由操作者配置，密钥在本地设置）：

```powershell
$env:REPOLENS_WORKSPACE='D:\code'
$env:REPOLENS_DATA='D:\code\Agent\.data-split'
$env:REPOLENS_DATABASE_URL='postgresql://repolens@127.0.0.1:5432/repolens'
# PGPASSWORD由本地安全输入；也可按psycopg支持的凭据文件方式提供。
$env:REPOLENS_REDIS_URL='redis://127.0.0.1:6379/0'
$env:REPOLENS_EXECUTION_MODE='api'
.\.venv\Scripts\python -m repolens.main
# 另一终端设置同样的变量后：
.\.venv\Scripts\python -m repolens.worker
```

省略Redis地址时，拆分模式仍用数据库轮询。`/health`展示存储、执行角色、worker租约和本进程Redis通知降级状态；`/ready`在无有效worker租约时返回503。Redis降级字段只代表当前进程最近一次通信，不是集群监控。`python -m repolens.worker --health`读取全局worker租约，不调用模型。

## Docker Compose

在仓库根目录本地创建`.env`，不要提交凭据：

```dotenv
POSTGRES_PASSWORD=your-local-strong-password
REPOLENS_REPOSITORIES=D:/code
REPOLENS_PORT=8001
```

需要真实模型时再在该文件配置模型URL、名称和密钥。Compose读取`.env`，原生Python不读取。PGPASSWORD通过进程环境提供，DSN不拼接密码，支持密码中的URL特殊字符。API/worker环境一致。

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail 80 api worker
docker compose stop worker
docker compose start worker
```

默认端口8000，如原生服务正在运行则使用示例中的8001；浏览器访问`http://127.0.0.1:8001`。页面仓库路径写`/workspace/仓库名`，使用容器中的路径。仓库挂载只读，快照与运行状态写入共享命名卷。API和worker以UID10001运行，根文件系统只读，临时目录使用tmpfs；PostgreSQL/Redis不映射宿主机端口。服务内存上限分别512/128/512/512MiB，Docker自身还需要额外内存。

Compose桥接子网默认`172.29.37.0/24`，仅该显式网段及环回地址可访问API；发生网段冲突时修改`REPOLENS_NETWORK_SUBNET`，白名单同步替换。原生模式仍仅允许环回访问。容器禁用代理头信任，不能通过伪造X-Forwarded-For绕过网段判断。Host及跨源POST检查保持开启。此配置是单机开发部署，不包含公网认证、TLS或多主机文件系统。

## 派发、并发与恢复

数据库`dispatch_jobs`与任务/导入/建库登记同事务保存。Redis只携带作业类型和ID，提交成功后发送最多保留1000条的可丢弃通知。worker每次先从数据库事务领取pending记录，空闲时短暂等待Redis；Redis不可用时回退轮询。重复/丢失通知不决定是否执行，也不会存储报告或预算。

仍保持**一个活跃worker**：全局租约、心跳及递增epoch决定执行权。第二个worker等待旧租约到期；没有横向分摊任务的承诺。PostgreSQL短事务使用统一advisory事务锁，API读改写、worker事件、预算、派发表和检查点写入在同一锁域内检查权限，避免取消/恢复与状态覆盖竞争。SQLite使用重入事务，保留既有查询和FTS5；PostgreSQL全文查询用simple tsvector/GIN与ts_rank_cd，排名不等同SQLite BM25。

worker退出时排空在途调用并保留partial；超出180秒容器停止宽限仍可能被强制结束，未保存响应保留未知预留。重新启动后旧running调查变为可恢复partial，必须显式恢复；旧queued继续执行。已经领取的导入/建库中断仍标为失败，需要显式重试；从未领取的pending登记继续执行。已完成派发记录保留用于判重，后续需单独设计归档保留策略。

PostgreSQL检查点使用[官方PostgresSaver](https://reference.langchain.com/python/langgraph.checkpoint.postgres)，迁移在autocommit连接中执行，应用检查点写入使用显式事务与fencing，关闭pickle并限制msgpack构造器。Redis不是持久事实源，不提供外部模型调用exactly-once。不得让不理解新租约规则的旧进程共用数据库。

## SQLite历史迁移

该CLI只迁移已结束、不可恢复的任务历史。先停止旧服务，完成或取消所有queued/running/可恢复partial调查，并处理未结束的导入/建库。保留完整`.data`备份（包括SQLite数据库与snapshots）；不要在旧库仍有写入时复制文件。旧检查点保持在原备份，不能跨SQLite/PostgreSQL直接继续执行；代码指纹变化也会拒绝旧任务恢复。

目标PostgreSQL及快照卷必须为空，目标API/worker必须停止。原生环境设置目标数据库/数据目录后：

```powershell
.\.venv\Scripts\python -m repolens.migrate --source-data D:\backups\repolens-data
```

Compose的全新部署可在API/worker首次启动前迁移：

```powershell
# .env中另设置REPOLENS_MIGRATION_DIR=D:/backups/repolens-data
docker compose up -d postgres redis
docker compose --profile migration run --rm --build migrate
docker compose up -d api worker
```

源库只读；迁移实体、事件、累计用量/journal、符号与全文内容，复制ready快照前逐文件验证hash，并重写快照根目录到目标路径。旧仓库source路径作为历史保留，新导入需填写当前工作目录中的路径。向量索引代标为需要重建，不假定旧Milvus仍有效。任何不完整任务、非空目标或快照校验失败都会拒绝；数据库事务回滚，但失败期间复制的目标文件可能残留。不要覆盖或删除原备份；检查目标后再使用新的空目录/空库重试。

## 验收状态

仅记录编译、依赖一致性、JavaScript语法与Compose静态配置检查。按用户要求，没有运行任何测试，未执行Docker build/up、数据库迁移、Redis断线、API-worker联调或崩溃恢复验收，也没有重启现有原生服务。部署前仍需真实环境验证这些路径；本轮不填写通过率或性能数据。
