# PDF 与 Word 解析

数字 PDF 使用本地文本层提取（#9），DOCX 使用原生结构（#10），扫描 PDF 使用 MinerU 官方 API（#11）；混合 PDF 逐页选择路径，只上传扫描页并按原页序合并（#12）。文件和字节入口返回相同的本模块结果类型，不依赖摄取上传服务、格式总路由或最终切块。

Issue #10 的 DOCX 原生解析复用相同入口，调用示例、来源字段和计数规则见 [DOCX 说明](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/app/modules/1_documentIngestionAndParsing/3_pdfAndWordParsing/DOCX.md)。

```python
import importlib
from pathlib import Path

parsing = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing"
)
path = Path("tests/testFile/pdf_digital_teaching.pdf")
result = parsing.convert_file(path)
same = parsing.convert_bytes(path.read_bytes(), format="pdf", source=str(path))

if result.success:
    print(result.markdown)
    for page in result.sources:
        print(page.pdf_page_number,
              result.markdown[page.markdown_start:page.markdown_end])
else:
    print(result.error)
print(result.warnings)
```

## 入口与结果

- `convert_file(path, *, format=None, source=None, mineru=None, ocr_pages=())`：默认用扩展名确定格式、路径字符串标识来源；可显式覆盖格式和来源。
- `convert_bytes(data, *, format, source, mineru=None, ocr_pages=())`：接收 `bytes`、明确格式及非空来源字符串；格式接受大小写、前置点和两端空白，例如 `.PDF`。
- `ConversionResult`：`markdown: str | None`、`source: Source`、`sources: list[ContentSource]`、`warnings: list[str]`、`error: str | None`，以及只读 `success` 属性。
- `Source`：文档的 `location` 和规范化 `format`。
- `ContentSource`：`markdown_start`、`markdown_end`、`pdf_page_number`、`extraction_method`。区间按 Python 字符串索引、左闭右开；不是 UTF-8 字节偏移。页序从 1 开始，表示输入文件中的实际 PDF 页序，不推测印刷页码。PDF 路径为 `text_layer` 或 `mineru_api`，混合 PDF 可以同时出现两者；选页上传不会改变来源页序。

每页非空文字占一个来源区间；页间额外的空行是生成的分隔符，不属于原文页面。失败的 `markdown` 为 `None`、`sources` 为空；错误和警告不会写入正文。DOCX 的章节与正文块位置沿用本模块结果类型。

## 已验证范围与局限

使用 pypdf 6.21.2，按实际页序提取文本层，去除页面文字两端空白，统一用空行分隔页面。已核验教学样本的标题文字、断电规则、每月检查周期和顺序；两页补充样本的印刷页码 41、7 仍对应 PDF 页序 1、2。输出是普通 Markdown 文本，未推测标题层级。

警告会明确说明：文本非空不代表文本层质量或完整性，也不等于任意标题层级、双栏或表格对应关系已经恢复。默认非空文字走本地，无文字且含图像时送入 MinerU；这不是通用文字质量检测，不能自动发现非空但错误、不完整的隐藏文本层。当前不实现通用版面恢复或业务事实纠错；代表样本通过不能推广为复杂 PDF 无损。

若调用方核验发现扫描正文只带可提取页码、页眉或不完整隐藏文字，可显式传 `ocr_pages=(2,)`，将原 PDF 实际第 2 页送到 MinerU，以其返回正文替换该页文本层结果。两个入口的参数相同，默认为空元组；只接受整数元组，不接受布尔值、浮点数、字符串或列表。页序从 1 开始，范围为实际 PDF 页数，与印刷页码无关；类型或范围错误返回失败诊断。非空选择仅用于 PDF，DOCX 会返回明确错误。参数不检测文本质量，由调用方核验后选择。

```python
result = parsing.convert_file("mixed.pdf", mineru=parsing.MinerUConfig(language="en"), ocr_pages=(2,))
same = parsing.convert_bytes(pdf_bytes, format="pdf", source="mixed.pdf",
                             mineru=parsing.MinerUConfig(language="en"), ocr_pages=(2,))
```

无文字且含图像的页面以及显式选择的页面由 MinerU 官方托管 API 识字；无凭据时返回明确失败，不把图片引用当成正文。混合 PDF 用 pypdf 将这些原页按原页序复制为一份选页 PDF，一次上传；不重渲染扫描图，其余数字页保持本地文本。API 的零基页索引映射回原 PDF 页序后，再按原顺序合并正文与来源，每页只保留一次正文。任一待识字页没有可用正文或识字失败，整篇返回失败，诊断指出原页；不会退回只有页码的文本层或返回遗漏扫描页的部分成功。未选中且无图像无文字的页面单独报告无可用正文、不生成来源区间；整篇均无正文时失败。页面解析异常会指出实际 PDF 页序。

## 复现

在仓库根目录，用已安装项目依赖的 Python 执行：

```powershell
python -m unittest tests.test_pdf_word_digital -v
python -m unittest tests.test_pdf_word_mixed -v
python -m unittest discover -s tests -v
```

固定输入及摘要见[数字样本说明](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/testFile/constructed-digital-pdf.md)和[混合样本说明](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/tests/testFile/constructed-mixed-pdf.md)。测试读取真实文件，通过公开入口断言正文与来源，不替换 pypdf、不调用内部辅助函数。默认混合测试只连接真实本地 HTTP 服务，不调用云 API。

## 扫描 PDF

Issue #11 已接通 MinerU 官方精准解析 API，公开入口提供可选 `mineru=MinerUConfig(...)`，默认从 `MINERU_API_TOKEN` 读取凭据。纯扫描和混合 PDF 的上传、轮询、正文、页序及失败约定见 [MINERU.md](/C:/Users/29157/.codex/worktrees/pdf-word-integration/rag-me/app/modules/1_documentIngestionAndParsing/3_pdfAndWordParsing/MINERU.md)。#12 的四页真实混合样本验收已通过，原第 2、4 页识字后准确插回第 1、3 数字页之间及之后。
