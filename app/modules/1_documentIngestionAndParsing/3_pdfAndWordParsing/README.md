# PDF 与 Word 解析

当前实现 Issue #9：数字 PDF 的文本层提取。文件和字节入口返回相同的本模块结果类型，不经过上传 API、格式总路由或最终切块。

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

- `convert_file(path, *, format=None, source=None)`：默认用扩展名确定格式、路径字符串标识来源；可显式覆盖格式和来源。
- `convert_bytes(data, *, format, source)`：接收 `bytes`、明确格式及非空来源字符串；格式接受大小写、前置点和两端空白，例如 `.PDF`。
- `ConversionResult`：`markdown: str | None`、`source: Source`、`sources: list[ContentSource]`、`warnings: list[str]`、`error: str | None`，以及只读 `success` 属性。
- `Source`：文档的 `location` 和规范化 `format`。
- `ContentSource`：`markdown_start`、`markdown_end`、`pdf_page_number`、`extraction_method`。区间按 Python 字符串索引、左闭右开；不是 UTF-8 字节偏移。页序从 1 开始，表示文件中的实际 PDF 页序，不推测印刷页码。当前处理路径是 `text_layer`。

每页非空文字占一个来源区间；页间额外的空行是生成的分隔符，不属于原文页面。失败的 `markdown` 为 `None`、`sources` 为空；错误和警告不会写入正文。后续 DOCX 和 MinerU 路径可以沿用并扩充本模块结果，无需依赖其他模块。

## 已验证范围与局限

使用 pypdf 6.21.2，按实际页序提取文本层，去除页面文字两端空白，统一用空行分隔页面。已核验教学样本的标题文字、断电规则、每月检查周期和顺序；两页补充样本的印刷页码 41、7 仍对应 PDF 页序 1、2。输出是普通 Markdown 文本，未推测标题层级。

警告会明确说明：文本可提取不等于任意标题层级、双栏或表格对应关系已经恢复。当前不实现通用版面恢复或业务事实纠错；代表样本通过不能推广为复杂 PDF 无损。

无文字且含图像的页面报告需要 OCR；整份结果失败，不把已提取的部分或图片占位当成整篇正文。扫描页后续由 Issue #11 接 MinerU 官方托管 API，本切片不安装或调用本地识字引擎。无图像且无文字的页面单独报告无可用正文、不生成来源区间；整篇均无正文时失败。页面解析异常会指出实际 PDF 页序。

## 复现

在仓库根目录，用已安装项目依赖的 Python 执行：

```powershell
python -m unittest tests.test_pdf_word_digital -v
python -m unittest discover -s tests -v
```

固定输入及摘要见[样本说明](/C:/Users/29157/.codex/worktrees/pdf-word-digital/rag-me/tests/testFile/constructed-digital-pdf.md)。测试读取真实文件，通过公开入口断言正文与来源，不替换 pypdf、不调用内部辅助函数。测试不访问网络。

## 扫描 PDF

Issue #11 已接通 MinerU 官方精准解析 API，公开入口新增可选 `mineru=MinerUConfig(...)`，默认从 `MINERU_API_TOKEN` 读取凭据。纯扫描 PDF 的上传、轮询、正文、页序及失败约定见 [MINERU.md](/C:/Users/29157/.codex/worktrees/pdf-word-mineru/rag-me/app/modules/1_documentIngestionAndParsing/3_pdfAndWordParsing/MINERU.md)。混合 PDF 的逐页处理由 #12 接续。
