# Web documents and MCP Implementation Plan

> Use superpowers:executing-plans inline, one final fresh-context static reviewer. User AGENT.md overrides tests: compile only.

**Goal:** 用户指定网页采集、不可变网页证据、调查固定附件、只读stdio MCP适配。
**Spec:** docs/RepoLens-Design-v1.md §7/8/9/12；用户明确选择“网页资料采集与MCP工具接入”。
**Architecture:** 采集作为显式排队作业，限制HTTPS精确主机白名单、公网DNS数字IP固定连接、跳转/大小/时间。保存规范化段落与hash，任务固定附件ID/hash，Agent仅读取已采集内容。动态渲染通过可选network:none Playwright侧车及Unix socket双向受限资源代理；MCP仅stdio暴露同一ToolRegistry读取与校验。

## Constraints
- 不运行测试、服务、容器或真实网页/模型；只编译、依赖/语法/Compose静态检查，不宣称实际采集或MCP互通已验收。
- 网页是非可信数据，不改变指令或权限；代码scope不能读网页，附件绑定同一snapshot，不混用其他任务授权。
- 数据库为权威；现有worker租约隔离全部采集写入。旧running采集失败，不自动产生新请求；queued采集继续。
- renderer无网络、无仓库/密钥挂载；仅受控GET经主进程校验代理，限请求数与总字节；缺浏览器或渲染失败保留静态正文并标注。
- 不做全网搜索、不接入任意第三方MCP命令；MCP仅作为现有工具传输适配。
- 保留用户 .gitignore/AGENT.md 改动，沿用新分支当前目录；不推送/合并。

## Tasks
- [x] 1. HTTPS限制采集、HTML正文、只读保存及网页证据校验。
- [x] 2. 断网Playwright renderer/Unix socket受控资源代理及Compose可选profile。
- [x] 3. 采集作业/API与任务附件、Agent/协作/恢复/迁移集成。
- [x] 4. 页面提交/引用来源展示与只读stdio MCP，共用schema/scope/预算校验。
- [x] 5. 编译/静态检查、一次全分支静态审查、修复、文档与提交。

## Review Focus
1. DNS rebinding、重定向、压缩炸弹、内网与file/非GET、renderer资源/进程/时间边界。
2. 附件授权/快照与hash、工具重放/恢复、MCP参数与scope一致、代码scope不可读网页。
3. 采集崩溃/取消/重复派发/旧worker写入隔离、终态/持久队列、幂等请求。
4. 网页版本/采集时间/段落位置展示、降级说明、非可信数据指令不能变更权限。
5. Compose profile断网及路径/权限、迁移兼容、SDK锁与当前依赖、旧默认无网页模式保持可用。
