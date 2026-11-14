# V3 本地持久恢复增量（0.5.0）

本轮实现 single/collaborative 调查的 SQLite 持久恢复闭环。尚未引入 Redis、PostgreSQL、多进程队列、等待人工输入或网页采集；这是 V3 的独立增量，并非全部工程化里程碑。模型与检索真实服务仍未配置，本轮只运行脚本供应商与本地故障注入。

## 使用

升级前先停止旧版本服务，不能让不理解租约的旧进程与新版本共用数据库。按 README 启动0.5.0服务；保持单worker、回环地址和原来的数据目录。

调查执行时按 Ctrl+C 停止服务，会等待已发请求返回/超时并保存可恢复的partial；用户点击“取消任务”仍是终止，不可恢复。直接进程退出时，下次启动会读取原始checkpoint和预算，将符合条件的旧running标为可恢复partial。旧版本没有checkpoint的任务继续failed/interrupted，不伪装恢复。原来已明确排队的任务仍重新排队。

重新打开任务，查看“恢复任务”入口、执行轮次、已用额度和原始截止时间，显式点击恢复。恢复沿用同一task、问题、快照、检索索引、模型及工具配置；每次恢复attempt/执行代号递增，事件序号不断开。刷新、丢失响应重试和双击均复用幂等恢复意图，不产生第三轮执行。

```powershell
# HTTP示例：只有具备有效checkpoint的中断partial才能恢复。
$body = @{ idempotency_key = [guid]::NewGuid().ToString('N') } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/tasks/TASK_ID/resume' -ContentType 'application/json' -Body $body
```

新调查公开字段包括 recovery_enabled、resume_available、recovery_error、recovery_deadline、attempt和execution_epoch。没有checkpoint可返回404；已成功/取消、过期、耗尽预算、版本配置或快照变化等返回409，不增加新模型调用。不开放任意checkpoint上传、反序列化、过滤或时间旅行API。

## 预算与重放

总上限仍为30模型、30工具、60,000输入/输出token、900秒；子任务工具累计上限8次。LLM、Embedding、Rerank共享调查预算与最多两路在途请求。900秒采用首次执行的绝对截止时间，包含停机和等待恢复时间，不能通过重启延长。超过时限需另建一项显式调查，不能继续原任务。

模型响应和预算结算同事务保存；成功保存的模型响应、失败响应和工具结果可重放，重放不会再次计量。工具结果先复核对应快照证据；缓存带完整性校验。未保存的只读工具可能重做，其次数仍累计。重放事件与真正开始/完成事件分别显示。

进程可能在供应商收到请求后、响应保存前退出。此时保留原预留及estimated，恢复若重发请求会再次扣剩余额度，可能重复费用；不承诺外部调用exactly-once。响应一旦连同结算保存，即使图节点未完成，恢复也会复用，不把已知用量清零。

模型、工具、图代码和配置指纹绑定原执行；API密钥与客户端不写入checkpoint/journal。配置或代码改变时保守拒绝原任务恢复，必要时还原配置或显式新建调查。没有真实供应商配置时只验证流程，不填真实金额或答案质量分数。

## 持久化与隔离

使用官方 [SqliteSaver](https://reference.langchain.com/python/langgraph.checkpoint.sqlite) 表格式与同步durability，保存真实LangGraph状态和pending writes；已完成并行分支不因另一分支中断而重跑。它是本地开发/单机能力，未来生产数据库迁移仍需单独验收。[官方持久化说明](https://docs.langchain.com/oss/python/langgraph/persistence)

单worker数据库租约每隔约1.7秒续租，默认有效期5秒。另一实例在租约有效时拒绝接管；崩溃后须等待旧租约到期。延迟心跳仅在owner/epoch未被替换时可续租；新epoch接管后，旧worker不能再写任务、图、报告、预算、journal或checkpoint。执行代号还隔离同一任务的旧轮次。

所有核心写入在SQLite写事务内检查租约；checkpoint沿用官方格式，仅在事务入口加fencing，并关闭pickle fallback。终态、报告、图、用量和恢复键/排队事件保持原子提交。SQLite仍是唯一权威，未用Redis作为事实存储。

恢复范围仅限调查。中断的仓库导入和向量建库仍失败，需要独立显式重试，不宣称这些作业可恢复。缓存/检查点与原始源码属于本地数据目录，不随Git和源码交付包发布。

## 故障注入复跑

以下命令只使用tests中的脚本供应商，不访问真实模型服务：

```powershell
$env:REPOLENS_RECOVERY_AUDIT_DIR = 'D:\code\Agent\test-results\recovery-cases'
$env:REPOLENS_RECOVERY_AUDIT_RUN = [guid]::NewGuid().ToString('N')
.\.venv\Scripts\python -m pytest tests/test_recovery_process.py tests/test_recovery_api.py -q
.\.venv\Scripts\python -m eval.recovery --results-dir $env:REPOLENS_RECOVERY_AUDIT_DIR --run-id $env:REPOLENS_RECOVERY_AUDIT_RUN --output test-results/recovery-synthetic.json
```

固定八个场景：响应已保存、请求在途、终态提交前、并行分支已保存，以及过期、模型配置变化、快照篡改、取消四个拒绝场景。前四个用真实子进程退出并由新worker接管；记录同一task、轮次、实际脚本调用、累计用量和estimated。负向场景不产生新provider调用。

汇总只接受本次run ID；缺失、失败或旧记录保留在固定分母中。恢复率只指这个固定机械测试集，不代表真实服务可用性、答案质量或费用节省。所有quality_pass保持null。
