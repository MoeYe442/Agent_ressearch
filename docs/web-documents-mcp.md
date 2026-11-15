# 网页资料与 MCP（0.7.0）

本轮提供显式网页采集、不可变段落证据、任务附件、可选Playwright断网侧车及只读MCP stdio适配。遵守AGENT.md，**只编译，不运行测试、真实网页、模型、MCP会话或容器**；以下启动方法是操作说明，不代表已完成运行验收。原有服务未重启，升级需按说明停止旧进程后启动同一版本API/worker。

## 允许站点与静态采集

默认不允许任何站点，旧仓库调查不受影响。原生PowerShell本地设置后启动：

```powershell
$env:REPOLENS_DOCUMENT_HOSTS='docs.python.org,example.readthedocs.io'
.\.venv\Scripts\python -m repolens.main
```

独立API/worker需使用一致配置，Compose在本地`.env`设置相同变量后重新创建对应服务。只支持精确主机名，不含通配符、任意端口、HTTP、IP地址直连或带用户名密码的URL。每次解析全部DNS结果并拒绝非公网地址，实际连接使用已校验数字IP，TLS与Host仍使用原域名；重定向每一跳重新校验，最多三跳。不会读取环境代理、转发模型密钥、站点登录Cookie或Authorization。

每次采集总计30秒，最多20次HTTP请求（包括重定向与动态资源）、单响应2MiB、所有资源合计8MiB。拒绝压缩响应，不进行解压；仅支持UTF-8 HTML/XHTML/纯文本/Markdown正文。剔除脚本、导航等元素，正文存为规范化段落，超长段落切为每段最多4000字符，最多2000段/256KiB。网页引用中的“行号”是保存后的段落编号，不是原HTML源码行号。每个快照最多100份资料，每项调查最多10份附件。

页面在新建调查中填写每行一个URL，可勾选动态渲染。采集完成后才提交调查；相同提交意图的刷新/网络重试复用采集键，新的显式调查会创建新的资料记录。失败不会无提示忽略附件，需修正URL或移除该资料后再提交。

API示例（快照必须已ready，URL仅为示例，不会由此文档自动访问）：

```text
POST /repositories/{snapshot_id}/documents
{"url":"https://docs.python.org/3/library/ast.html","render":false,"declared_version":"Python 3","idempotency_key":"document-intent"}

GET /documents/{document_id}
GET /repositories/{snapshot_id}/documents
POST /documents/{document_id}/cancel

POST /tasks
{"snapshot_id":"...","question":"比较当前代码与文档","mode":"collaborative","document_ids":["..."] ,"idempotency_key":"analysis-intent"}
```

列表/状态API返回元数据，正文由工具按段落读取。`declared_version`只是用户声明，`version_match`始终为unverified，不自动声称与当前commit匹配。网页说明不能单独证明当前代码行为。

## 固定引用与恢复

ready资料不在原ID上刷新；新采集创建新ID。正文、SHA256、最终URL、标题、采集时间、声明版本及降级原因保存在数据库。任务与恢复指纹固定所附ID、hash和元数据；每次读取/重放重新核验正文hash。引用同时绑定快照和资料ID，不能给其他快照附加，也不能通过retrieve_evidence绕过附件许可。

完整URL（包含用户明确填写的查询串）作为来源元数据保存，可能随工具结果进入所配置模型的上下文；不根据参数名字猜测并删除查询条件。

新增list_documents、search_documents与fetch_document工具只读取任务附件，**不会发网络请求**。关键词查询最多返回三个匹配段落；按范围读取最多40段/24KB。代码scope禁止网页读取；协作docs角色可读取附加资料，即使仓库没有Markdown。每次读取仍消耗共享工具额度；页面引用展示URL、段落、采集时间、未核验版本与降级原因，打开原网页时提示远端内容可能已变化。

采集作为显式document作业走原队列和租约，登记与派发同事务。queued作业继续派发，旧running采集启动后失败/interrupted，需要新显式采集，避免自动重复请求。取消在网络分块/渲染交互边界或整体超时后生效。SQLite历史迁移拒绝未结束的采集；已保存正文在entities中随历史导入，任务恢复仍受版本/存储变化限制。

## 可选断网动态渲染

```powershell
docker compose --profile browser up -d --build
```

renderer使用官方Playwright Python镜像与固定1.51.0版本，`network_mode:none`，启动还会拒绝存在非loopback接口的环境；没有仓库、数据卷、模型密钥或数据库凭据挂载。只共享UID10001可访问的Unix socket目录。浏览器开启sandbox、禁Service Worker/WebSocket/下载/弹窗，仅允许当前主文档与受控GET脚本、CSS、XHR/fetch。资源请求通过socket交回主进程，每个请求仍受上述公网/白名单/大小/时间限制；不直接使用浏览器网络。不允许导航到其他页面或加载子框架。

每个渲染作业独立子进程，侧车父进程32秒后清理进程组；容器限制768MiB、128进程，临时目录256MiB，根文件系统只读。Chromium sandbox需要宿主机允许用户命名空间；不兼容时失败降级，不能通过关闭sandbox或改host网络绕过限制。镜像较大，内存不足时可以保持静态模式。

仅Linux容器支持此动态路径。原生Windows、未启用browser profile、socket不可用、资源失败或渲染超时时，会保留静态正文并记录`static_fallback:<原因>`；静态正文也为空则采集失败。使用降级资料的调查保留局限并标记partial，不把动态失败包装为完整采集成功。JavaScript需要POST、未允许CDN、图片文字或登录状态的页面不在支持范围内。

## MCP stdio

使用[官方Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)的stdio传输，对外复用相同ToolRegistry、参数schema、scope与证据校验；没有新增HTTP监听端口，不替代Agent调度，也不启动任意第三方MCP命令。

```powershell
$env:REPOLENS_WORKSPACE='D:\code'
$env:REPOLENS_DATA='D:\code\Agent\.data'
.\.venv\Scripts\python -m repolens.mcp_server --snapshot SNAPSHOT_ID --document DOCUMENT_ID --scope docs
```

`--document`可重复最多10个，必须同一快照且ready；默认不开放任何网页ID。`--scope code`拒绝网页附件；不支持仓库导入、采集、取消任务、Shell或模型调用。关键词工具不触发Embedding/Rerank网络。输出仅为MCP协议，启动错误只写stderr稳定错误码；不要向stdout增加调试print。

客户端配置示例（快照/资料须事先由本地API登记，按实际路径替换）：

```json
{"mcpServers":{"repolens":{"command":"D:\\code\\Agent\\.venv\\Scripts\\python.exe","args":["-m","repolens.mcp_server","--snapshot","SNAPSHOT_ID","--scope","all"],"env":{"REPOLENS_WORKSPACE":"D:\\code","REPOLENS_DATA":"D:\\code\\Agent\\.data"}}}}
```

该MCP进程只提供读取，仍会写入证据/调用审计。每个stdio进程独立限制30次工具调用/900秒，不持久化MCP会话预算，不等同恢复调查的持久共享预算；重启建立新会话。不要暴露stdio转发到未经授权的远程客户端。

## 当前验收边界

仅记录Python/Jinja编译、JavaScript语法、依赖一致性及Compose配置检查；不填写网页提取通过率、动态渲染成功率、MCP互通或模型质量指标。原先0.5.0的339项回归结果不代表0.7.0通过。完整实际采集/取消/崩溃/跨快照拒绝/渲染沙箱/MCP客户端联调仍待后续运行验收。

一次只读全分支静态审查发现两项重要问题并修复：浏览器脚本/活动资源报错会标记动态失败并降级；协作最终文档检查接受已附网页。修复后只编译，没有运行测试。暂缓一项轻微问题：动态采集标题可能显示正文首行，来源URL/hash/段落不受影响。执行记录见[web-mcp-execution.md](web-mcp-execution.md)。
