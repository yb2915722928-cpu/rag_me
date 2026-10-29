# rag_me

RAG 项目。文本与网页模块将本地 TXT、Markdown、JSON、静态 HTML 和 MHTML 转为整篇 Markdown，并支持 UTF-8 导出。PDF 与 Word 模块通过同一公开调用方式处理数字 PDF、DOCX 和需要 MinerU 官方 API 识字的扫描 PDF，正文与来源、诊断分别返回。演示文稿与结构化文档模块提供 PPTX 演示页归属及 JSON 节点来源，待核验关系独立返回。

## 安装与验证

使用 Python 3.11 或更新版本：

```shell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

验收使用仓库内的固定样本，无需联网下载。六个公开样本的来源、大小及 SHA-256 见[来源记录](/E:/aaa-project/rag-me/tests/testFile/sources.json)。补充样本的构造方式记录在同目录。

## 转换与导出

目录名包含数字前缀，使用 `importlib.import_module` 取得[公开接口](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/2_textAndWebContent/__init__.py)：

```python
from importlib import import_module

text_web = import_module(
    "app.modules.1_documentIngestionAndParsing.2_textAndWebContent"
)

result = text_web.convert_file("tests/testFile/alice_utf8.txt")
if result.success:
    text_web.export_markdown(result, "alice.md")
    print(result.source, result.encoding, result.warnings)
else:
    print(result.error)

result = text_web.convert_bytes(
    "<article><h1>说明</h1><p>已有的静态页面正文。</p></article>".encode("utf-8"),
    format="html",
    source="upload.html",
    mode="article",
)
```

- 文件入口按扩展名识别格式，也可显式指定 `format`；字节入口必须提供格式与来源。
- `encoding` 可指定已知编码。解码依次考虑显式编码、BOM、适用的格式内声明、UTF-8 和编码探测；显式编码失败直接报告。编码探测是启发式判断，已知来源编码时应显式提供。
- HTML 默认 `mode="article"` 提取正文；`mode="full"` 转换整页。两种模式均清除脚本和样式，保留必要的标题、列表、表格、文字链接和代码结构。
- MHTML 优先采用明确指定的主 HTML 部分，否则按解码后字符数选择，并在结果中单独提供警告和选中来源；不合并所有框架。选中来源的 `content_id`、`content_location` 和 `mime_index` 分别对应 MIME 头及遍历序号（归档根为 0），缺失头部保持为空。
- JSON 输出可重新解析的 JSON 代码围栏，保留原结构和值；Markdown 规范化保护代码空白和已有结构。
- 成功正文、来源信息、编码及警告分别返回；失败结果的 `markdown` 为 `None`，`error` 提供失败原因。导出失败结果会抛出 `ValueError`，不会创建或覆盖目标文件；成功导出只包含正文，写入错误按普通文件 I/O 异常处理。

模块处理已取得的文件内容，不抓取网址、不执行 JavaScript，也不进行最终文档切块。独立图片由后述图片模块处理；本模块不自动提取或识别网页内嵌图片。

## PDF 与 DOCX 解析

```python
from importlib import import_module

documents = import_module(
    "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
)

result = documents.convert_file("manual.docx")
if result.success:
    print(result.markdown)
    print(result.source, result.sources, result.warnings)
else:
    print(result.error)

result = documents.convert_bytes(
    pdf_bytes, format="pdf", source="manual.pdf",
    mineru=documents.MinerUConfig(language="en"),
)
```

数字 PDF 优先在本地读取可用文本层；DOCX 按正文顺序读取标题、段落和普通表格。需要识字的 PDF 页面使用 MinerU 官方 API，调用前将本机 Token 配置为进程环境变量 `MINERU_API_TOKEN`，或通过 `MinerUConfig` 显式传入。库不会自动读取环境文件；凭据仅在调用进程中使用，不写入代码和提交。

混合 PDF 仅复制需要识字的原页组成一份 PDF 上传，按原始页序合并正文与来源。例如 API 0、1 映射回原第 2、4 页，数字第 1、3 页保留本地文本。缺少扫描页正文时整篇失败，诊断指向原页；不会把已有数字页当作整篇处理成功。

文本层非空不代表正文完整：扫描正文可能只有页码或页眉可提取。调用方对照原页发现此问题后，可在两个公开入口传 `ocr_pages=(2,)`，以 MinerU 结果替换原 PDF 实际第 2 页的文本层；其余数字页保留本地结果，无文字扫描页仍自动识字。参数为整数元组，使用从 1 开始的实际 PDF 页序；类型错误或超出页数时返回诊断，不能填写印刷页码。

正文来源使用左闭右开的字符区间关联到实际 PDF 页序，或 DOCX 章节与正文块位置。PDF 页序不等于印刷页码，DOCX 正文块号不等于页码。失败结果的正文为 `None`，诊断不会拼进正文。本模块不承担最终切块或完整检索问答验证。

默认测试使用固定文件和本地 HTTP 服务验证 API 协议，不向云端提交任务。真实扫描验收需显式设置 `MINERU_LIVE_TEST=1`，混合验收使用 `MINERU_MIXED_LIVE_TEST=1`。调用说明见 [PDF 与 Word 模块](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/app/modules/1_documentIngestionAndParsing/3_pdfAndWordParsing/README.md)，混合输入摘要、真实结果、耗时及局限见[固定样本记录](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/testFile/constructed-mixed-pdf.md)。

## CSV 与 XLSX 表格文件

[表格模块](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/README.md)提供真实 CSV／XLSX 的文件和字节转换入口，支持整表 Markdown 与按行文本。行记录可独立取得完整列名、共同上下文和来源；XLSX 来源包含工作表与原始单元格位置。

```python
from importlib import import_module

tabular = import_module(
    "app.modules.1_documentIngestionAndParsing.4_tabularFileProcessing"
)
context = tabular.TableContext(
    name="员工国内差旅标准", version="2026示例版",
    applicability="普通员工，国内出差",
)
result = tabular.convert_file(
    "tests/testFile/xlsx_travel.xlsx", context=context, mode="rows",
)
if result.success:
    beijing = result.tables[0].rows[0]
    print(beijing.text, beijing.cells[1].raw_value, beijing.source)
else:
    print(result.error)
```

CSV 保留字段文本、前导零及字段内换行，并支持显式编码、分隔符和表头记录。XLSX 可显式指定工作表、区域与连续表头行；[表头和合并关系](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/TABLE_STRUCTURE.md)只按真实覆盖范围表示，普通空白不会填成零或上一行的值。

[公式和单元格值](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/CELL_VALUES.md)保留原值、类型与数字格式，支持明确的常见显示格式；公式表达式和文件缓存分别保存，不执行重算。正文、来源和诊断分别返回，任一选中表解析失败时不返回部分成功结果。本模块止于表格解析与表示，不执行最终切块、检索或模型问答。

## PPTX 与结构化文档

[演示文稿与结构化文档模块](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/README.md) 沿用文件、字节与 UTF-8 正文导出入口。[PPTX](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/PPTX.md) 在本地保留原页、标题、独立文本对象、段落层级、表格跨度与演讲者备注，并返回对象 ID 路径及父容器内坐标。

```python
from importlib import import_module

presentations = import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
result = presentations.convert_file("tests/testFile/pptx_refund.pptx")
if result.success:
    print(result.requires_review, result.review_issues)
    presentations.export_markdown(result, "refund.md")
else:
    print(result.error)
```

`success` 与 `requires_review` 独立：完成提取后，分栏阅读顺序、箭头、图文对应和条件归属仍需对照原页。图片页不宣称 OCR；母版、版式继承内容与嵌入文件不展开。无需安装 PowerPoint，不调用视觉模型或上传资料。损坏包及后续页解析失败时整篇失败，导出失败结果不会覆盖文件。固定文件与重建方法见 [PPTX 样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-pptx.md)。

[JSON](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/JSON.md) 复用原有严格解析和完整结构表示，补充 JSON Pointer 及父节点来源，保留值类型与数组顺序，不把对象字段排列推断为业务步骤。

## 独立图片处理

[图片模块](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/6_imageProcessing/README.md)通过文件或字节入口处理静态 PNG、JPEG、WebP，一次明确选择图像识字（OCR）、图像描述或按问题进行视觉理解。三类任务统一调用阶跃星辰视觉 API，使用 STEP_API_KEY、STEP_BASE_URL、STEP_MODEL 配置；可运行入口负责明确载入本地环境文件，核心模块使用运行时环境或显式配置。

结果将图片派生文字与图片版本标识、来源信息、模型及提示词版本、待核验事项和错误分开返回。未识别到文字、无法确认关系与调用失败有不同含义；成功不等于内容已核验。裁剪图可以携带原图映射和文档来源，模块不推测缺失区域之外的关系。

所有固定样本位于[测试样本目录](/E:/aaa-project/rag-me/tests/testFile/)。默认回归使用本地 HTTP 服务验证真实请求与结果契约，真实识图质量通过显式启用的阶跃星辰验收记录核对。模块止于图片处理与表示，不提供原图存储、自动嵌图提取、向量索引或完整 RAG 问答。

## 音视频处理

[音视频模块](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/7_audioAndVideoProcessing/README.md)通过文件、字节或命令行处理本地音视频，可选择语音转写、视频画面理解或两者。模型计算使用阶跃 API，本机仅运行 FFmpeg/FFprobe 做媒体准备，默认逐片串行处理。

结果区分语音原话与画面派生文字，保留原媒体版本、真实片段范围和待核验状态；时间为片段级定位，说话人保持未知。本模块提供后续 RAG 的媒体表示，不包含上传、存储、索引和完整问答。

## ZIP 容器

[ZIP 模块](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/README.md)通过文件、字节或命令行逐成员处理资料包，返回整包摘要、成员来源和独立解析结果。一个成员失败时保留其他成员结果并报告部分成功；目录和系统元数据单独计为忽略项，不拼成一篇 Markdown。

```python
from importlib import import_module

containers = import_module(
    "app.modules.1_documentIngestionAndParsing.8_zipContainers"
)
result = containers.convert_file(
    "资料包.zip",
    parser_options={"image": {"task": "ocr"}, "media": {"task": "transcribe"}},
)
print(result.to_dict())
```

面向低配置服务器，PDF（含数字 PDF）、DOCX、PPTX、XLSX 和 HTML 默认走 MinerU API，MHTML 轻量选择主 HTML 部分后提交。图片和音视频沿用阶跃 API；ZIP、TXT/Markdown、JSON/XML/CSV 及现有媒体准备在本地完成。按[配置示例](/E:/aaa-project/rag-me/.env.example)提供 MINERU_API_TOKEN 和 STEP 配置，核心入口只使用运行时环境或显式配置，不自行加载环境文件。API 缺配置或失败明确报告，不自动回退本地重解析。

成员数量、压缩大小、单成员和累计展开量及协作式截止均有限制；首版不递归内嵌 ZIP、不解密密码包、不按成员原路径解压。API 返回的来源粒度与本地解析器可能不同，缺少的原生单元格或对象位置如实说明。语义关系和生成内容仍需核验，API 成功不等于内容质量通过。

## 托管文档解析

[托管文档模块](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/hosted_documents.py)集中处理 MinerU 文档请求、结果包读取和来源表示，支持直接提交文档字节。ZIP 分派与统一交接共同依赖此模块；[归档预算](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/archive_budget.py)供输入资料包和服务结果包复用，ZIP 原有的 ZipLimits 名称继续可用。

```python
from importlib import import_module
from pathlib import Path
import time

hosted = import_module("app.modules.1_documentIngestionAndParsing.hosted_documents")
budget = import_module("app.modules.1_documentIngestionAndParsing.archive_budget")
limits = budget.ArchiveLimits()
parsed = hosted.convert_bytes(
    Path("manual.pdf").read_bytes(), format="pdf", source="manual.pdf",
    limits=limits, deadline=time.monotonic() + limits.timeout_seconds,
)
```

该入口沿用 PDF、DOCX、PPTX、XLSX、HTML/HTM 和 MHTML/MHT 的既有托管处理；来源由调用方传入，归档预算和绝对截止沿用本次处理上下文。PDF/Word 等独立格式入口的默认路线遵循各自原有约定。

## 统一输出与切分交接

现有解析结果可通过统一入口交给后续切分：保留完整正文、表示方式、交接内容单元、结构、真实来源及独立诊断，支持 UTF-8 JSON 导出。

```python
from importlib import import_module

text_web = import_module(
    "app.modules.1_documentIngestionAndParsing.2_textAndWebContent"
)
handoff = import_module(
    "app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff"
)

parsed = text_web.convert_bytes(
    "普通商品签收后7天内，未拆封可退。".encode("utf-8"),
    format="txt", source="售后政策.txt",
)
report = handoff.adapt_result(parsed, business_id="policy-001", version="2026-09")
handoff.export_json(report, "handoff.json")
```

同一入口接收文档、表格、演示文稿、JSON/XML、图片、音视频及 ZIP 的既有原生解析结果。ZIP 成功成员各自形成独立文档，失败、忽略、未处理和部分成功继续保留；文档业务标识与版本未知时为空，不从文件名或内容摘要推断。

原生正文区间仍指向完整原正文；节点、行列、服务结构或媒体片段没有字符映射时保留实际粒度，不伪造精确对齐。无文字、无法确认、技术失败与待核验分别表达，技术完成不代表内容已核验。交接不会重新解析文件或调用模型，也不执行实际切块；扩大块无法恢复上游已经遗漏的信息。完整范围和任务见[规格 #45](https://github.com/yb2915722928-cpu/rag_me/issues/45)。
