# 协作调查增量（0.3.0 / V2.0）

默认 single 保留原调查流程；新建分析可选择 collaborative。追问继承当前模式和固定快照。API `POST /tasks` 的 `mode` 缺省 single，`GET /tasks/{id}/graph` 返回公开计划、子任务、补查轮次与模型评审摘要。旧任务 JSON、旧幂等记录和旧 Markdown 引用继续可用。

实际 LangGraph StateGraph 由 Planner、code/docs 调查、Reviewer 与确定性 Reporter 组成。首次最多四个无环子任务，实际模型请求峰值为二；最多两轮、每轮两个针对性补查，没有新证据即停止。Planner/Reviewer JSON 只修正一次，计入总预算。Reporter 仅归并已有、已观察并复核过的引用，不调用模型增加事实。

所有角色共享原有总上限：30 次模型请求、30 次工具调用、60,000 输入加输出 token、900 秒。每个协作子任务另有累计八次工具上限。预留原子化；模型重试和 JSON 修正都计费。失败或缺 usage 的请求保留保守估算，不能当成零用量。单角色请求由统一 ModelGateway 发出。

文档限同一快照已纳入的 Markdown/RST/TXT、README/LICENSE/COPYING/CHANGELOG；不打开外部网页，也不回读原仓库补证据。代码和文档的读取范围由服务端强制隔离。模型判断单独标为“模型评审”，只校验引用位置不等于验证语义。冲突、缺证据、失败分支、预算或轮次耗尽会明确 partial。

图详情和 SSE 事件保存于现有 SQLite。终态、报告、图状态与总用量同事务提交。取消等待在途调用结算后停止；running 在重启时标记 interrupted，没有 checkpoint、resume 或持久图恢复。单 worker 管理一项调查，不能使用多进程共享数据库。

## 同预算比较

```powershell
.\.venv\Scripts\python -m eval.compare --base-url http://127.0.0.1:8000 --tasks eval/collaborative_tasks.jsonl --output test-results/comparison.json
```

五题覆盖入口、状态保存、恢复缺口、陈旧 README 与实现冲突、不存在功能。每题两个模式共用同一快照、模型配置和总预算。导出 manifest、模型标识、提示词版本、预算、状态、claims、引用、角色用量及耗时。导入失败也保留两条失败记录；未知 usage 为 null。提示词随模式不同，版本分别记录。

`quality_pass` 和 `quality_improvement` 均待人工语义评审；流程成功、结构通过和模型支持均不能赋予质量分数。`synthetic: true` 只验证集成，不能证明协作优于 single。本地测试替身只位于 tests。

外部文档网页、Milvus、持久图恢复仍属于后续总体路线。当前环境没有真实模型配置，未做真实模型效果评测；GitHub 导入仍受当前 Fake-IP 保留地址解析限制，未修改网络或放宽保护。

## 本轮功能比较记录

2026-11-12，Windows / Python 3.12，锁定 LangGraph 1.2.20。隔离安装确认 FastAPI 0.115.12 与 Pydantic 2.11.4 保持兼容后，才安装相同锁文件到项目环境。

五题 synthetic 比较输出见 [完整 JSON](results/collaborative-synthetic.json)。两种模式各五题、同一固定 fixture manifest、相同 30/30/60,000/900s 总预算；模型标识为 synthetic:ComparisonModel。

| 模式 | 流程 succeeded | 产出报告 | 结构通过 | 待人工质量评审 | 脚本 token（输入/输出） |
|---|---:|---:|---:|---:|---:|
| single | 5/5 | 5/5 | 5/5 | 5 | 1250 / 350 |
| collaborative | 4/5 | 5/5 | 5/5 | 5 | 4000 / 1100 |

协作 conflict 题为 partial，是预期保留的冲突状态。上述 token 是测试替身返回的固定数字，不代表真实供应商消耗；本次不报告模型质量提升、金额或性能收益。
