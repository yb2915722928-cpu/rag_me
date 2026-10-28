# ZIP 评审修复（Refs #39 #41）

实施位置：`fix/39-zip-review`，起点 `b77460d`。完成前已通过 `git merge --no-edit feat/39-zip-integration` 快进合入最新集成 tip `4541b24`，包含 `c6daba8` 的脱敏实测证据及 VALIDATION/CODE_REVIEW 记录。实施和提交均在独立 worktree，未修改主工作区。

## 修复行为与范围

两轴评审只有一个 P2：文档结果展开的协作截止被通用异常捕获包装成解析失败。现在 ZIP 容器与文档适配器共用专用停止信号，容器在收到信号时立即把当前成员记为 `unprocessed` 并设置 `stop_reason=deadline_exceeded`，不依赖下一成员触发检查。随后文档未处理、确定的系统元数据仍忽略，已完成的 TXT 和文档原生结果保留；当前未完成文档不暴露部分正文。

文档适配器接收整个输入 ZIP 开始时确定的绝对截止，不再从当前文档开始重新计时。该截止用于结果下载开始前、每个下载块返回后及每个结果产物展开块间的协作检查。共享 MinerU 客户端只新增一个可选的结果下载检查回调，不依赖 ZIP 模块，避免循环依赖；旧扫描 PDF 调用不传此回调。上传、任务轮询、图片及媒体 API 沿用既有超时，没有统一硬超时、强制中断、字符串匹配错误、重试或通用防护框架。

普通配置、服务拒绝、网络/轮询超时及无效产物继续是当前成员的 `failed/parse_error`，不触发容器协作停止。输入层同时保留容器对绝对截止的控制，解析选项不能覆盖 `deadline`。

另按用户追加要求，真实文档验收的首次 `open` 和全部 `write_text` 在生成源头明确指定 `newline="\n"`。没有增加这个输出格式的测试，没有改动模型请求，也没有重新执行真实 API 或重新生成已有实测证据；已有证据的 LF 规范化来自合入的集成提交。

## Red → green 证据

接缝沿用已批准的 ZIP 公开文件/字节入口，使用固定样本、真实 ZIP、真实 MinerU HTTP 客户端和本地 HTTP 服务；只替换系统 `time.monotonic`。测试不调用私有解析函数，不 mock 内部协作者，不等待真实 300 秒。

1. 单 PDF、没有下一成员：本地结果响应将时钟从 0 推进到 301 秒。初始红测实际返回 `failed=1/unprocessed=0`，与期望相反；专用停止信号贯通后为 `failed=0/unprocessed=1/stop_reason=deadline_exceeded`。日志：[red-single](/C:/Users/29157/.codex/tmp/zip39-20261028/review-fix-red-single.log)、[green-single](/C:/Users/29157/.codex/tmp/zip39-20261028/review-fix-green-single.log)。
2. 整包绝对截止：前一 PDF 在 250 秒完成，后一 PDF 在 301 秒返回。只修信号时仍错误保留 3 个成功项；透传整包截止后正确为 2 成功、3 未处理、4 忽略，同时通过文件和字节入口验证。日志：[red-archive](/C:/Users/29157/.codex/tmp/zip39-20261028/review-fix-red-archive.log)、[green-archive](/C:/Users/29157/.codex/tmp/zip39-20261028/review-fix-green-archive.log)。
3. 下载阶段截止：在真实 HTTP 结果响应时越过截止，分别返回损坏包和超过下载大小预算的包。未加下载协作检查时，两项均错误得到 `stop_reason=None`；补上结果下载检查后均为当前成员未处理。日志：[red-download](/C:/Users/29157/.codex/tmp/zip39-20261028/review-fix-red-download.log)、[green-download](/C:/Users/29157/.codex/tmp/zip39-20261028/review-fix-green-download.log)。

另保留下载完成后、结果展开期间时钟继续推进的公开入口回归，确认即使已取得部分产物也不返回不完整文档。普通 API 错误的既有测试补充断言 `failed/parse_error` 且 `stop_reason=None`。文档模块最终 13 项全部通过：[green-documents](/C:/Users/29157/.codex/tmp/zip39-20261028/review-fix-green-documents.log)。

固定混合截止样本由构造源头生成，成员预期和 SHA-256 记录在下方样本说明中；只生成新增样本，未重新构造其他 live 样本。

## 最终验证

- ZIP 容器、预算、CLI、文档、图片、媒体及旧 MinerU/混合 PDF/数字 PDF/DOCX 定向回归：99 项通过，20.268 秒。[日志](/C:/Users/29157/.codex/tmp/zip39-20261028/review-fix-targeted.log)
- `python -m unittest discover -s tests -v`：323 项，313 通过、10 跳过，45.154 秒。执行进程显式关闭全部真实 API 测试开关；未加载环境文件或调用收费 API。[日志](/C:/Users/29157/.codex/tmp/zip39-20261028/review-fix-full.log)
- `git diff --check` 通过。提交前再次检查暂存改动和集成 tip。

## 本次文件清单

- 实现：[容器入口](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/__init__.py)、[分派](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/dispatch.py)、[文档适配器](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/document_api.py)、[共享停止信号](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/models.py)、[MinerU 结果下载](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/3_pdfAndWordParsing/mineru.py)。
- 测试及样本：[公开入口回归](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/tests/test_zip_documents.py)、[本地 HTTP 服务](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/tests/zip_document_support.py)、[验收证据生成源头](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/tests/test_zip_documents_live.py)、[样本构造源头](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/tests/testFile/zip_documents_build_samples.py)、[固定截止 ZIP](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/tests/testFile/zip_document_deadline.zip)。
- 文档：[文档 API 约束](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/DOCUMENTS.md)、[分派契约](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/README.md)、[样本预期与摘要](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/tests/testFile/zip_samples.md)、本修复记录。
