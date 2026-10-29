# ZIP 文档 API（#41）

PDF（数字、扫描、混合）、DOCX、PPTX、XLSX 默认整份提交 MinerU 托管精准 API；HTML/HTM 使用 `MinerU-HTML`，MHTML/MHT 先复用既有 MIME 主 HTML 选择再提交 HTML。无需启用开关。配置缺失及远端失败是具体成员失败，不触发本地文档重解析，后续成员仍可成功。

## 调用与配置

公开接缝仍为 [ZIP 文件／字节入口](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/__init__.py)，`parser_options["document"]["mineru"]` 接受既有 [MinerUConfig](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/3_pdfAndWordParsing/mineru.py) 或普通 mapping。省略时使用默认配置；`token=None` 从进程环境 `MINERU_API_TOKEN` 取值，显式空字符串表示配置不可用。库函数不读取环境文件。

```python
from importlib import import_module

zip_parser = import_module("app.modules.1_documentIngestionAndParsing.8_zipContainers")
mineru = import_module("app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing.mineru")
result = zip_parser.convert_file(
    "documents.zip",
    parser_options={"document": {"mineru": mineru.MinerUConfig(language="en")}},
)
report = result.to_dict()
```

CLI 的 `--parser-options` 对应 JSON 可为 `{"document":{"mineru":{"language":"en","max_wait":300}}}`。mapping 仅接受现有配置字段：`token`、`api_base`、`language`、`poll_interval`、`request_timeout`、`max_wait`。时长有限且为正数，轮询间隔允许零；未知字段及无效类型在文档入口拒绝，错误不回显配置值。实际凭据使用环境，避免写入命令行。报告不包含配置对象或签名 URL。退出码沿用成功 0、部分成功 2、失败 1。

其他文档请求模型固定 `vlm`，表格识别开启，语言沿用配置；不额外强制 `is_ocr`，服务处理整份 PDF。HTML 不发送文档 OCR、表格或语言参数。上传名为 `document.<真实格式>`，HTM 与选出的 MHTML 主部分统一为 `document.html`；原始成员身份仍由成员来源保存。MHTML 主部分按原解码编码重新编码，不把 MIME 包直接上传；保留 `content_id/content_location/mime_index/encoding` 与选择警告。

共享客户端新增 `extract_document`，复用原 `_json/_upload`、轮询、`_read`。旧扫描 PDF `extract` 仍使用 `document.pdf/vlm/is_ocr=true` 并走原内容列表适配，不改变独立 PDF 模块的默认行为。

## 原生产物与来源

[托管文档模块](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/hosted_documents.py) 返回 `DocumentResult`，容器 `result_kind=document`。结果类型与解析实现独立于容器，统一交接也直接引用该模块：

| 字段 | 含义 |
| --- | --- |
| `source/format` | `容器!/成员#序号` 身份及原后缀 |
| `provider/requested_model` | `mineru` 与请求模型；不推断服务内部实际模型或 Office 转换路线 |
| `markdown/markdown_file` | UTF-8 解码后的原始 `full.md`，保留空白及顺序，不从块列表拼接 |
| `structured_json` | 以实际产物名为键的完整 JSON 值，包括 V1、V2、layout/model；不把任意 JSON 数组当 V1 |
| `content_list_file` | 实际 V1 名称，仅识别 `content_list.json` 或 `*_content_list.json` |
| `html/html_file` | 服务实际提供的 `main.html`；HTML 可以只有 `full.md/main.html`，不强求 PDF 内容列表 |
| `artifacts` | 服务包的文件名；图片、原文件等二进制附件只计量校验，不落盘或返回其内容 |
| `sources` | V1 产物名、零基块序号、原始服务页索引及来源含义；原始 bbox 保留在 JSON |
| `warnings/main_html` | MIME 选择等普通诊断和实际主部分身份 |
| `review_items/requires_review` | 阅读顺序、表格对应关系及缺失来源的待核验说明，独立于解析成功 |
| `error/success` | 有效非空正文且无错误才成功；失败清空正文、结构 JSON 和来源，不返回部分正文 |

PDF `service_page_index + 1` 表示上传的整份 PDF 页序，不是印刷页码。Office 的 `page_origin=service_page_unverified`，`pdf_page_number=None`；不能据服务页索引声称获得原 Word 页码、正文块、幻灯片对象或工作表/A1 地址/公式缓存结果。Office 缺页索引可以保留未知，PDF V1 块缺有效页索引则失败。

所有来源的 `markdown_start/markdown_end=None`，服务没有提供 JSON 块与原始 Markdown 的字符区间映射。HTML 来源没有 DOM 路径；MHTML 主部分身份来自本地 MIME 选择。待核验项不会使成功成员失败，也不表示质量已通过。Markdown 可能引用未返回内容的图片附件。

## 结果 ZIP 预算

调用方同一 `ZipLimits` 透传文档入口；该名称沿用[共享归档预算](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/archive_budget.py)中的 `ArchiveLimits` 定义。每个远端结果包分别应用压缩下载量 `max_archive_bytes`、中央目录条目数 `max_members`、单产物展开量 `max_member_bytes`、累计产物展开量 `max_total_bytes`。不是硬编码另一套默认值，也不从解析器选项覆盖预算。

下载逐块读取，不依赖 Content-Length；超过上限时只多探测一个字节。展开先检查声明大小，再逐块计量并检查 CRC；二进制附件也占预算。没有解压目录，不按产物路径写文件。远端预算失败是当前文档失败，其他成员仍能继续；容器 `total_bytes_read` 继续只表示输入成员读取量，远端结果量不冒充输入读取量。

请求超时与轮询期限不超过该次文档的 `limits.timeout_seconds`。结果下载和展开沿用整个输入 ZIP 开始时的绝对截止，不为每份文档重新计时；下载开始前、每块下载返回后及产物展开块间协作检查。截止通过专用停止信号返回容器，当前未完成和后续文档记为未处理，已完成结果保留，已知元数据仍忽略；即使当前文档是末成员也记录 `stop_reason=deadline_exceeded`。普通 API 错误仍为成员失败。上传、轮询和其他格式 API 保留既有超时，不强杀正在进行的网络请求，没有新增重试或调度框架。

## 固定样本与离线验证

[构造源头](/E:/aaa-project/rag-me/tests/testFile/zip_documents_build_samples.py) 生成独立 `zip_document*` 输入、模拟结果包及 live 输入。运行时仅读取已提交字节；协议服务是 [真实本地 HTTP 夹具](/E:/aaa-project/rag-me/tests/zip_document_support.py)，不 mock 客户端和内部解析器。模拟 Markdown 故意与 V1 文本不同，以检验原始正文没有被重建。

既有 PDF、DOCX、PPTX、XLSX、MHTML 副本均在 [固定样本目录](/E:/aaa-project/rag-me/tests/testFile)。新增两页演示样本检查标题与表格页归属；新增双工作表样本含横向合并表头及无保存计算缓存的公式 `SUM(B3:B4)`。新增 HTML/MHTML 有断电规则、泵／阀周期表与表后重新启动规则。输入摘要及独立预期由 [live 清单](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_manifest.json) 固定。

本地 XLSX 差旅样本的来源说明是“本地构造教学输入”；主代理已有真实 XLSX 探针的公开来源未知，该探针也不是本票 ZIP 验收。此前探针可说明曾返回哪些产物，不能作为本实现质量通过证据。

```powershell
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m unittest tests.test_zip_documents tests.test_zip_documents_cli tests.test_zip_documents_live -v
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m unittest tests.test_pdf_word_mineru tests.test_pdf_word_mixed -v
```

TDD 切片依次得到数字 PDF unsupported 红测、Office unsupported 红测、HTML unsupported 红测、无效产物误成功红测、远端三种展开预算误成功红测、CLI mapping 配置失败红测、空正文误成功红测；分别补最小实现后通过。缺 Token、鉴权字符串码、限流、格式拒绝、上传/轮询/下载/任务失败及超时通过真实本地服务覆盖，配置和错误均验证未回显 Token/签名 URL。

## 显式真实 API 验收（由主代理运行）

[live 测试](/E:/aaa-project/rag-me/tests/test_zip_documents_live.py) 默认跳过。只有 `ZIP_DOCUMENT_LIVE_TEST=1` 才读取 `STEP_ENV_FILE` 指定的环境文件；不会在默认测试时加载凭据。用包含 `MINERU_API_TOKEN` 的现有环境文件，主代理在本工作树执行：

```powershell
$env:ZIP_DOCUMENT_LIVE_TEST = '1'
$env:STEP_ENV_FILE = '<主代理指定的环境文件绝对路径>'
$env:ZIP_DOCUMENT_LIVE_EVIDENCE = 'C:/Users/29157/.codex/tmp/zip39-20261028/document-live-run-01.json'
$env:ZIP_DOCUMENT_LIVE_CASES = 'pdf_digital,pdf_scan,pdf_mixed,docx,pptx,xlsx,html,mhtml'
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m unittest tests.test_zip_documents_live -v
Remove-Item Env:ZIP_DOCUMENT_LIVE_TEST
```

可以筛选一个或多个 case；省略 `ZIP_DOCUMENT_LIVE_CASES` 就运行全部八项。证据路径必须是新文件，父目录须存在，分次运行用不同路径。按样本交替覆盖 ZIP 文件／字节入口。每次请求前保存输入/容器摘要核验；请求后先保存完整脱敏结果、产物形状、事实/表格/顺序/实际页来源检查，再断言。URL 和 Token 在整个证据对象中脱敏，不保存请求配置。Office 原生来源与公式缓存仍明确未知；PPTX 核验代表样本的服务页归属不升级为普遍原生页契约。

本票实施者未运行收费 API，未读取环境文件。离线协议通过不代表数字/扫描识字或 Office/HTML 托管质量通过；真实质量以主代理保存的本次证据为准。

协议依据：[MinerU 官方托管文档](https://mineru.net/apiManage/docs)；参考 [官方云端 SDK 结果读取](https://github.com/opendatalab/MinerU-Ecosystem/blob/95357b542987cb9dba62e7ec3f2edf8ae4d7554e/sdk/python/src/mineru/_zip.py) 的独立产物读取思路，但不采用其任意 JSON 数组作为内容列表的后备逻辑。托管与新版开源 DocVortex 输出不是同一契约。
