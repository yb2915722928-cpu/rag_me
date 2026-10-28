# ZIP 集成两轴评审

固定点：4a788b3cb43c8bae75a036039b55d710178d7fe1；首次评审提交：f07a31b4035c4d780909c77c678dc6a4a82df873。比较命令：`git diff 4a788b3cb43c8bae75a036039b55d710178d7fe1...HEAD`。两个独立子代理并行评审；以下分别保留结论，不合并两轴排序。

## Standards

Standards 轴：未发现有具体失败场景、需要修复的问题。硬性规范违反 0 项；代码异味判断项 0 项。

范围：集成分支 feat/39-zip-integration，固定点 4a788b3cb43c8bae75a036039b55d710178d7fe1，HEAD f07a31b4035c4d780909c77c678dc6a4a82df873；按三点 diff 检查，核对了包含合并的提交列表。

已检查指定标准源、执行上下文及全部新增代码和测试。薄适配层符合规格要求；未发现无意义单次 helper、重复内部防御、测试复制业务算法或直接依赖新增私有实现等可报告问题。

验证：73 项定向离线测试全部通过（19.392 秒），覆盖 ZIP、文档/图片/媒体本地 HTTP、CLI、FFmpeg 和旧 PDF 入口回归。未调用收费 API；仓库文件及 HEAD 保持原状。

报告：[standards-review.md](/C:/Users/29157/.codex/tmp/zip39-20261028/standards-review.md)


## Spec

Spec 轴：发现 1 项 P2；未发现有具体证据的范围扩张。

- **[P2] 文档协作截止被误报为解析失败** — [document_api.py](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/document_api.py:90)。[规格 #39](/C:/Users/29157/.codex/tmp/zip39-20261028/issue-39.md:71) 要求：“将当前未完成项及其后尚未处理的文档标为未处理，记录停止原因”。结果 ZIP 展开触发截止时，异常被通用捕获包装成 `parse_error`，当前成员因此记为 `failed`。离线复现：固定单 PDF ZIP、本地 HTTP 服务，时钟在结果展开前从 0 推进到 301 秒；得到 `failed=1、unprocessed=0、stop_reason=null`。带尾随 TXT 时也只有尾项被正确标为未处理。最小修复：将截止作为独立停止信号传回容器，当前项置为 `unprocessed` 并记录 `deadline_exceeded`，保留已完成结果。

验证：19 项定向离线测试通过；另用可控时钟确认上述偏差。未修改仓库文件，未调用收费 API。


首次结果：Standards 0 项；Spec 1 项 P2，最严重问题为文档协作截止的状态传递。修复记录由独立实施分支提供，合并后更新最终状态。

## 修复复核

Spec 复核通过：提交 d2c50e9a10b05c5c0216c6c5e02e551562fb2522 无剩余 Spec 发现，原 P2 已解决。

- 结果 ZIP 下载与展开共用整包绝对截止，专用停止信号不会被包装成解析错误；[容器入口](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/__init__.py:120)立即将当前成员置为 `unprocessed`，设置 `stop_reason=deadline_exceeded`，不依赖后续成员。
- [新增回归](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/tests/test_zip_documents.py:9)覆盖展开中途截止、单文档、文件/字节入口及兄弟成员：未完成正文不返回，已完成结果保留，后续文档未处理，元数据仍忽略。
- [MinerU 客户端](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/3_pdfAndWordParsing/mineru.py:38)的下载截止回调默认关闭；旧扫描 PDF 入口不传回调，上传/轮询及普通 API 错误语义保留。

已核对 [REVIEW_FIX.md](/C:/Users/29157/.codex/worktrees/zip-review-fix/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/REVIEW_FIX.md:25)及日志：定向 99 项通过，全仓 323 项中 313 通过、10 跳过。本次只读复核，未重跑全仓或调用 API。


修复提交 d2c50e9 已通过合并提交 59ef795 纳入集成分支；定向 99 项和全仓 323 项（313 通过、10 跳过）完成，合并后相关 31 项通过。细节见 [REVIEW_FIX.md](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/REVIEW_FIX.md)。最终未解决项：Standards 0；Spec 0。
