# V2.1 可配置混合检索（0.4.0）

本轮按用户选择完成可配置接入与离线回归，真实 Milvus / Embedding / Rerank 配置后另行验收。当前 Docker daemon 未运行，空闲物理内存约3 GB，没有新增服务配置；未启动容器、下载模型或请求真实供应商。默认关键词流程保持可用。

## 配置与使用

先按官方 [Milvus 2.6 部署要求](https://milvus.io/docs/v2.6.x/prerequisite-docker.md)与[Windows Docker 说明](https://milvus.io/docs/v2.6.x/install_standalone-windows.md)准备服务。Standalone 官方列出8 GB内存要求，本轮没有在当前机器上启动它。使用专用的 collection；不要将未经认证的数据库端口发布到公网。示例配置只指向本机回环地址：

```powershell
$env:REPOLENS_MILVUS_URL = 'http://127.0.0.1:19530'
$env:REPOLENS_MILVUS_COLLECTION = 'repolens_chunks_v1'
$env:REPOLENS_EMBEDDING_URL = 'https://your-provider.example/v1'
$env:REPOLENS_EMBEDDING_MODEL = 'your-versioned-embedding-model'
$env:REPOLENS_EMBEDDING_DIMENSIONS = '768' # 必须改成所选模型实际维度
# 按 README 的本机 SecureString 方式设置 EMBEDDING_KEY、MILVUS_TOKEN（若需要）。
$env:REPOLENS_RERANK_URL = 'https://your-provider.example/v1'
$env:REPOLENS_RERANK_MODEL = 'your-reranker'
# 按相同方式设置 REPOLENS_RERANK_KEY；不启用重排时不需要配置。
.\.venv\Scripts\python -m repolens.main
```

服务 URL 由本机配置固定，模型和请求不能指定。远程要求 HTTPS，本机回环可 HTTP；禁止 URL 凭据/查询串、redirect 和环境代理继承。密钥只放环境，不写进任务、索引状态或报告；不是所有兼容服务都支持相同协议，真实联调失败不能当成检索效果。

Embedding 使用 `POST /embeddings`，输入 model/input/encoding_format=float，返回 data[index,embedding] 与可选 usage；重排使用 `POST /rerank`，输入 query/documents/top_n，返回 index/relevance_score 与可选 tokens/usage。参考[供应商公开协议](https://github.com/siliconflow-inc/siliconflow-api/blob/main/openapi.yaml)。所有向量须有限、非零且维度一致；重排必须返回无重复的全部合法位置。服务端响应最多2 MiB，单请求有整体超时，不自动重发付费请求。

页面选择“混合检索”，可另选重排。首次显式选择后，导入快照、创建向量索引，再启动调查；源码会发送至配置的 Embedding 服务，可能产生费用。建库与调查各有独立的上限预算：30次模型请求、60,000输入/输出token、900秒；调查中的 LLM、Embedding、Rerank 共享这同一份总预算和最多两路在途请求。缺 usage 和失败调用保守预留，异常超预留锁存停止，不裁剪实际值。

默认关键词不调用新增服务。重排只能随 hybrid 使用；未配置、维度改变、索引未就绪或辅助服务失败均明确报错，不静默回退后仍标为 hybrid。追问继承检索方式、重排和快照；新建分析恢复 keyword/single。失联重试复用任务及建库键。

## 索引与来源约束

Python AST/Markdown 标题产生带父符号的原文块，长块按最多120行或8,000 UTF-8字节、最多20行重叠细分。超长单行明确失败。块记录 snapshot/path/range/hash/chunker_version；语法错误仍可按窗口纳入。旧 FTS 和旧 evidence ID 不迁移、不改写。

Milvus 只保存向量和标识，SQLite 保存权威块。每次建库有独立 generation，全部上传成功才原子发布 ready。中途失败的 generation 不可查询；相同幂等键不会自动重新付费，新的明确重试建立新 attempt。重启将未完成建库标为 interrupted，不伪称恢复。失败上传留下的非公开向量可在后续运维中清理，不会通过当前 generation 检索。

查询在 Milvus 端先过滤 snapshot/generation/scope，本地再核验块归属与新读取的原文 hash。符号、FTS、向量各最多20候选，经 RRF(k=60)融合去重，可选重排最多20份原文。Milvus 的路径/行号不是权威。模型只能引用成功工具实际返回的原文；向量相似分数和重排分数均不是事实正确率。

## API 与复跑

- `POST /repositories/{snapshot_id}/retrieval-index`：显式登记，JSON可含 idempotency_key；`GET`同一路径轮询 queued/building/ready/failed及用量。
- `POST /repositories/{snapshot_id}/search`：query、retrieval_mode(keyword/hybrid)、rerank、scope(all/code/docs)、limit(1..20)，返回验证过的原文证据与用量。
- `POST /tasks`：新增 retrieval_mode 默认keyword、rerank默认false；二者参与幂等指纹。旧记录自动采用默认值。

```powershell
.\.venv\Scripts\python -m eval.retrieval --base-url http://127.0.0.1:8000 --tasks eval/retrieval_tasks.jsonl --output test-results/retrieval-real.json
```

三种配置使用同一快照与标注，导出候选、原文、配置、用量、延迟和Recall@K。失败保留各配置分母，未知费用不记零；建库用量是共享成本，不能按每题重复求和。Recall仅检查人工标注来源是否进入候选，不是答案质量。quality_pass与quality_improvement保持待人工；离线 toy 向量只验证协议，不能证明真实语义召回提升。

真实验收需配置服务后复跑固定语料，验证建库/过滤/用量与实际来源，人工检查召回、重排及引用语义。当前交付不包含真实供应商的模型质量、延迟或金额结论。外部文档网页和持久图恢复仍是后续路线。

## 本轮离线记录

五题三配置共15条检索完成记录，使用同一 fixture 快照和真实原文。输出见 [完整 JSON](results/retrieval-synthetic.json)。最终修复后重新导出：每个配置均5/5执行成功，质量值15/15待人工；关键词、混合、混合加重排的标注来源 Recall@5 分别为1.0、0.6、0.2。重排替身刻意把候选逆序，作为负向对照。这些 toy 结果只说明评测能保留退化结果，不能说明实际神经向量或重排效果。

API/任务/图回归52项、浏览器回归36项通过；辅助服务的 HTTP、预算、分块与索引测试覆盖响应异常、维度、假块、scope、失败发布、重试和未知用量。全部原235项回归保留，最终全量与独立审查结果在完成后记入验证记录。

## 独立审查与收尾

一次 fresh-context 全分支审查发现六项重要问题，无 Critical。另将“畸形 upsertCount 可错误发布 ready”按索引完整性影响升为重要问题；以下均先复现，再一次修复：

- 混合 search_text 失败后即使 read_file 得到有效引用，也保留错误原因并 partial，协作汇总同步保留该缺口。
- 本地有对应范围块但强一致无阈值向量查询返回空时，标记该 generation 不可用；旧键重放不重建，新的显式 attempt 可修复。真正空 scope 不误判损坏。
- 关键词/符号命中先映射到最多120行、8,000字节的真实原文窗口，再重排；本地无效输入在预算预留前拒绝，不计为已发送模型请求。
- 首次 Embedding 前验证已有 collection 所需字段、VarChar容量、向量维度、额外必填字段及索引；上传计数必须精确整数，不接受 bool/float。
- 失败查询也返回安全错误码、已结算 usage/estimated、角色用量、generation 和重排模型；比较导出保留这些字段与失败分母。
- 切块过程中检查数量、时间和取消，达到10,001块即停止，不继续读取后续文件；Milvus入口前再次检查。

计划中的“Embedding物理错序一律拒绝”修正为按合法唯一 index 还原；索引缺失、重复、越界仍拒绝。独立审查认可该取舍。

暂缓两项轻微诊断问题：协作辅助模型事件的 subtask_id 当前归到调查级，不能单独追踪每个子任务的辅助费用；工具定义仍将 search_text 简述为关键词检索。总预算、固定模式及服务端权限不受影响。

审查未判断真实服务的可用性、延迟、金额和语义质量，按用户选择留待配置后验收。失败 generation 的远端清理、多进程 worker、外部网页和持久图恢复也不在本轮范围；本地仅发布成功 generation，失败向量可能占远端空间，需要后续运维清理。

最终验证：292项测试通过（273.96s），含36项浏览器回归；compileall src和pip check通过。正式0.4.0服务已重启验证，桌面/手机截图已查看。执行取舍、RED→GREEN与暂缓项见 [执行记录](hybrid-execution.md)。
