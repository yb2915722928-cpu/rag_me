# PDF、DOCX 与托管文档交接

任务 [#47](https://github.com/yb2915722928-cpu/rag_me/issues/47) 的适配实现见
[documents.py](/C:/Users/29157/.codex/worktrees/47-handoff-documents/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/documents.py)。
通过模块[公开入口](/C:/Users/29157/.codex/worktrees/47-handoff-documents/rag-me/app/modules/1_documentIngestionAndParsing/9_unifiedOutputAndChunkingHandoff/__init__.py)接收：

- 第 3 节的 PDF/DOCX `ConversionResult`，包括上游已经完成的 OCR 结果。
- 第 8 节的托管 `DocumentResult`；调用方可从 ZIP 成员的 `result` 取得它。本票不适配 ZIP 容器本身。

```python
from importlib import import_module

parsing = import_module("app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing")
handoff = import_module("app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff")

native = parsing.convert_file("maintenance.docx")
report = handoff.adapt_result(native, business_id="维护规程", version="修订二")
handoff.export_json(report, "maintenance-handoff.json")
```

交接只读取原生结果，不再次读取输入文件、解析文档或访问模型服务。未知业务标识、版本保持 `None`；JSON 中为 `null`。所有适配器使用调用方提供的同一 `IdAllocator`，仅保证本次报告内引用唯一。

## 原生 PDF / DOCX

`Document.body` 完整保留原 Markdown。每个上游内容来源生成一个精确内容单元，其 `body_span` 是原 Markdown 上的 Python 字符半开区间，`text == body[start:end]`，`alignment="exact"`。页间、块间未被区间覆盖的分隔内容仍在完整正文内，不通过拼接单元重建正文。

文档级来源保留 `location`、`format`；细粒度来源同时保留全部原生字段：

- PDF 来源种类为 `pdf_page`，单元种类同名；保留实际 `pdf_page_number` 和 `extraction_method`（例如 `text_layer`、`mineru_api`），不解释为印刷页码。
- DOCX 来源种类为 `docx_block`，单元种类沿用 `heading`、`paragraph`、`table`。保留 `section_path`、`body_block_number`、`section_block_number`、`block_type`、原始 `heading_level`；块号不变成页码，重复章节名不用于猜测父单元。

`structure.sources` 另存完整上游来源投影。上游警告与错误分别成为 `upstream_warning`、`upstream_error` 诊断，关联文档和文档级来源，均不写入正文。上游没有独立的质量通过标记；`requires_review=False` 不代表内容已经核验，原警告仍须读取。

## ZIP 托管文档

完整 Markdown 生成一个 `alignment="document"` 的整篇单元，不填写字符区间。每个真实服务来源另生成一个 `service_block` 单元与来源：

- `alignment="unmapped"`，`body_span=None`、`text=None`；块内容从 `structure.structured_json[artifact][block_index]` 回查，不能把它当作 Markdown 的切片。
- 保留 `artifact`、零基 `block_index`、`service_page_index`、`pdf_page_number`、`page_origin` 和上游空字符区间。
- PDF 的 `page_origin="uploaded_pdf"` 与 Office 的 `service_page_unverified` 分开表达；Office 服务页序不被升级为 Word 正文块、演示页/对象或工作表/单元格位置。

`structure` 保存 `structured_json`、`sources`、`artifacts`、`markdown_file`、`content_list_file`、`html`、`html_file`；`metadata` 保存 `provider`、`requested_model`、`main_html`、`review_items`。这些都是独立投影，包含 V1/V2/布局 JSON、产物名称、HTML 正文和 MHTML 实际主部分选择信息。

`requires_review` 沿用上游属性；每条待核验事项另成为 `upstream_review` 诊断。正文字符对齐、阅读顺序、表格关系和 Office 原生位置的缺口保持可见。技术 `success` 不抹去这些限制。

两种适配器都保留失败文档及其来源、诊断和可用结构；失败时 `body=None`、`units=[]`，仍可导出 JSON。

## 验证

[test_handoff_documents.py](/C:/Users/29157/.codex/worktrees/47-handoff-documents/rag-me/tests/test_handoff_documents.py) 复用现有真实 PDF/DOCX、ZIP 固定样本，以及已有的本地 OCR / 托管文档 HTTP 服务。测试边界为真实上游结果 → 公开适配 → JSON 回读；核验字符切片、章节/页序、完整结构、来源缺口、诊断、输入不变、ID 引用及交接不增加网络请求。

```powershell
python -m unittest tests.test_handoff_documents tests.test_handoff_text_web -v
```
