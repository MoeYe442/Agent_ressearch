# 公开 GitHub 导入：范围、验证与边界

日期：2026-11-12（Asia/Shanghai）。本轮为已批准 V1 后续顺序中的公开 GitHub 导入独立增量，版本 0.2.0 / 界面 V1.1。

## 使用

页面默认本地，切换“公开 GitHub”后输入 HTTPS 仓库根地址和可选 ref。不要将 `git@github.com:...` SSH 地址或 `/tree/main` 页面地址贴入字段；ref 在单独字段中填写。

后台流程：公开属性检查 → ref 解析为完整 commit → 读取 commit 对应完整 Git tree → 下载 SHA 对应归档 → 校验路径/类型/资源 → 对纳入文本核对 Git blob SHA-1 → 构造 SHA-256 内容清单 → AST/FTS5 索引 → 原子发布 ready。模型问题、工具调用与证据继续沿用原流程。

固定 commit 仅表示已纳入字节经 tree 校验，不表示所有仓库文件都已纳入，更不表示模型结论语义已独立验证。排除项包含依赖、密钥、过大文件、二进制、链接、子模块、编码失败或归档省略项。

## 配置与故障

可选 `REPOLENS_GITHUB_TOKEN` 从环境读取且用 SecretStr 持有，只用于公开元数据 API，不存数据库、不展示、不转给 codeload。模型密钥与 GitHub token 独立；导入本身不需要模型。

| error_code | 含义 |
|---|---|
| invalid_github_url / invalid_github_ref | 输入不符合受限 GitHub URL/ref 格式 |
| github_private_unsupported | 私有仓库不在本轮范围 |
| github_repository_not_found / github_ref_not_found | 仓库不可公开访问或版本不存在 |
| github_rate_limited / github_forbidden | GitHub 限流或权限拒绝，不长时间占 worker 等配额 |
| github_network_destination | DNS、连接地址或跳转不满足固定公网主机约束 |
| github_import_timeout / github_network_error | 总时限或网络错误 |
| github_tree_truncated | GitHub tree 返回不完整，拒绝以截断结果导入 |
| github_archive_path / github_archive_duplicate | 不安全路径、别名或重复成员 |
| github_download_limit / github_member_limit / github_unpacked_limit | 下载/归档资源超限 |
| github_blob_mismatch | 纳入源码与 commit blob 不一致，如 export-subst / LFS 展开 |
| interrupted_import | 进程退出留下的未完成导入，不是假恢复 |

下载文件只暂存在本次生成的 `.data/downloads/<id>.zip`，以排他方式创建，拒绝已存在文件和链接目录；导入结束后清理。失败与重启只清理从已登记生成 ID 推导出的本次目录，不使用持久化记录中的任意路径，不删除其他快照。被篡改为链接或文件系统拒绝删除时明确保留并报清理错误。来源/ref、解析出的 commit、归档 hash 与排除项可从已登记 snapshot 查询。旧快照新增字段使用默认值，不要求删除数据库，列表和详情均作兼容转换。

为使资源检查发生在标准库分配整个 ZIP 成员列表之前，先流式扫描中央目录并限制目录字节、实际成员数和解压总量。只接受 stored/deflate 压缩，不接受多卷、SFX 或 ZIP64 归档；当前文件数/体积上限均低于必须使用 ZIP64 的阈值。成员路径最多 80 层、UTF-8 最多 4096 字节，隐式目录也检查大小写和 Unicode 别名。

DNS 在单请求和总时限内运行；每个固定域名最多一个未完成的守护解析任务，取消调用方不等待 OS DNS 工作线程结束。HTTP 实际连接只使用已校验的公网数字 IP，原 Host、TLS SNI 和证书校验继续绑定 GitHub 域名，避免连接层再次解析到不同目的地。该适配使用已锁定的 httpcore 1.0.9 网络后端接口，不新增安装包。

关闭服务会取消在途 GitHub HTTP 操作、在解压/索引边界检查停止信号并等待自己的 worker 退出，避免旧 worker 在关闭返回后发布 ready。取消不是跨进程断点恢复。

## 当前实测

最终完整套件 **165 passed，142.93s**，包括 19 项浏览器测试（V1 的 10 项与本轮的 9 项）。覆盖 URL/ref、公开属性、SHA 固定、tree/归档 hash、路径/大小限制、幂等、持久状态、旧数据兼容、DNS/连接绑定、关闭/清理和浏览器提交/引用/刷新/窄屏。完整输出见 `test-results/pytest-github-final.txt`。

`python -m compileall src` 与 `python -m pip check` 通过；可编辑安装验证为 repolens 0.2.0。两条已知测试 warning 分别为现有 Starlette/AnyIO 的别名弃用提示，以及恶意 ZIP 重复成员 fixture 生成时的预期警告。未将警告掩盖为通过项目质量指标。

桌面 1440px 与手机 390px 截图已人工检查；GitHub 表单与结果还在 320/390/736/1024px 验证无页面横向溢出。测试页面明确显示测试环境，脚本模型与 HTTP transport 均只作为受控验收替身。

真实网络 smoke 已尝试 `https://github.com/pallets/itsdangerous`。本机 DNS 将 api.github.com 解析到 `198.18.0.80`、codeload.github.com 解析到 `198.18.0.174`，均为非公网地址，安全校验以 `github_network_destination` 拒绝。此为明确阻塞记录，**没有完成真实 GitHub 导入，不能把 mock 通过当作真实网络验收**。记录见 `test-results/github-real-smoke.json`。

正式本地服务已启动在 `http://127.0.0.1:8000`，health 返回 version=0.2.0、github_import=true、test_environment=false、model_configured=false。通过正式页面再次尝试同一公开仓库，确认错误可见、没有 JavaScript 异常、手机无页面溢出；这次 DNS 返回 `198.18.0.11` / `198.18.0.39`，仍是非公网地址。记录见 `test-results/github-production-startup.json` 和 `github-production-*.png`。两次均未调用模型。

未配置真实模型，本轮不声称已完成真实 Agent 调查或质量/成本评测。私有仓库、子模块/LFS 拉取、多 Agent、完整 Git 历史和网络代理配置不在本轮范围。

## 决策

- 复用当前 checkout 并在 feature/github-import 分支工作；没有增加工作树。保护原 main，避免复制运行环境。
- 沿用现有依赖和数据库形状，通过默认字段兼容历史记录。
- 没有因本机非公网 DNS 结果而放宽公网限制或改动用户网络；代价是本机真实导入需网络环境满足约束。这类地址常见于 Fake-IP 配置，但本轮没有修改或确认用户具体网络软件。
- 审查提出的协议错误归一化、旧记录列表默认字段、提交中可改表单虽然标为 Minor，但分别涉及计划明确的稳定 error_code、旧数据兼容和请求一致性，实施者按实际使用影响提升为需修复项。代价：增加小型回归测试，没有扩展产品范围。
- 网络连接与清理逻辑拆为 github_network.py / import_storage.py，分别承担固定目的地连接和生成 ID 的存储所有权，避免在 API 或 ZIP 遍历中混入另一套边界。代价：升级 HTTPX/HTTPCore 时必须重新验证适配器；当前版本均已锁定。
- 本轮在 feature/github-import 本地提交，main 和远程旧版本保留；不把此前一次推送解释为对所有未来阶段的自动发布授权。代价：尚需按用户后续选择合并或推送。
- Windows / 当前 Python 3.12 环境已测试；其他操作系统和接近 50,000 成员上限时的吞吐没有实测。上限是保护阈值，不是性能承诺；原有逐文件读取完整 manifest 的索引开销仍需后续独立测量。

## 独立审查与修复对照

一次只读独立审查发现 6 项 Important、3 项 Minor，无 Critical。以下修复均先复现失败再实现；修复由作者运行回归和完整套件验证，没有声称进行了第二次独立审查。

| 审查项 | 修复与回归 |
|---|---|
| DNS 校验和实际连接分离 | PinnedBackend 只连接已校验的数字 IP；test_connection_uses_checked_ip_while_preserving_sni_and_host 验证 IP、Host 与 SNI |
| DNS 超时与线程退出 | 守护解析任务按域名去重，放进单请求时限；test_dns_obeys_request_deadline、test_blocked_os_dns_does_not_delay_run_shutdown |
| ZIPInfo 分配、特殊压缩与深路径资源 | 中央目录预扫描、stored/deflate 白名单、路径长度/层数上限；test_central_directory_limit_precedes_zipinfo_allocation、test_only_bounded_archive_compression_is_accepted、test_deep_archive_path_is_rejected_before_writing |
| Windows 隐式目录别名与保留设备名 | 记录所有目录前缀原拼写，按 Windows 保留设备语义检查；test_implicit_directory_aliases_rejected、test_all_windows_reserved_device_spellings_rejected |
| 关闭后的旧 worker 发布 | HTTP 取消监视、解压/索引取消与 worker 排空；test_shutdown_cannot_publish_ready_after_return |
| 文件所有权与失败/重启缓存 | 排他下载、只删已拥有文件及合法生成 ID 对应缓存；test_download_does_not_truncate_or_remove_preexisting_file、test_symlinked_download_directory_is_not_followed、test_restart_cleans_only_interrupted_import_artifacts、test_indexing_failure_removes_own_snapshot |
| 非法上游 JSON / redirect | 统一 github_protocol_error；test_upstream_non_object_json_is_stable_protocol_error、test_malformed_archive_redirect_is_stable_protocol_error |
| 历史快照列表兼容 | 列表/详情均通过 RepositorySnapshot 默认字段转换；test_persisted_legacy_snapshot_is_normalized_in_list |
| 导入中改来源造成状态混淆 | 请求期间锁定来源、地址、ref 与问题；test_request_fields_are_locked_during_github_import |

独立审查未判断的真实 GitHub 互通、真实模型质量/成本和上限吞吐，均按前文边界保留，未把未知标记为已通过。

## 官方资料

归档按 commit 固定及内容稳定性参考 [GitHub 源码归档](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives)；接口约定参考 [commits](https://docs.github.com/en/rest/commits/commits)、[trees](https://docs.github.com/en/rest/git/trees) 和 [源码归档 API](https://docs.github.com/en/rest/repos/contents)。

连接后端参考 [HTTPCore Network Backends](https://www.encode.io/httpcore/network-backends/)，保留正常 Host 与 TLS origin，限定 TCP 连接目的地。
