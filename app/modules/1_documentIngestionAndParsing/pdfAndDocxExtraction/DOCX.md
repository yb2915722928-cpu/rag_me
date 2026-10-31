# DOCX 原生解析（Issue #10）

DOCX 与数字 PDF 复用本模块的公开文件、字节入口和结果类型。先由调用方确认材料是同版本且内容完整，才适合优先利用 DOCX 原生结构；本模块不比较两个文件的版本或完整性，也不自动优选 PDF/DOCX。

## 公开调用

在仓库根目录、安装根依赖后执行以下代码。入口见 [__init__.py](__init__.py)，原生处理见 [docx.py](docx.py)。

```python
import importlib
from pathlib import Path

parsing = importlib.import_module(
    "app.modules.1_documentIngestionAndParsing.pdfAndDocxExtraction"
)
path = Path("tests/testFile/docx_sections.docx")
result = parsing.convert_file(path)
same = parsing.convert_bytes(path.read_bytes(), format=" .DOCX ", source=str(path))
assert result == same
if result.success:
    print(result.markdown)
    for block in result.sources:
        print(result.source.location, block.section_path,
              block.body_block_number, block.section_block_number, block.block_type,
              result.markdown[block.markdown_start:block.markdown_end])
else:
    print(result.error)
print(result.warnings)
```

文件入口默认以扩展名确定格式和路径标识来源，也支持显式覆盖。字节入口必须传入 bytes、格式和非空来源字符串。格式规范化后只接受 PDF/DOCX；旧版二进制 `.doc` 不支持，改扩展名也不会把二进制 Word 变成 DOCX。无法读取、损坏 ZIP、非法 XML、缺少正文部件、整篇没有可用文字都会返回失败：`markdown=None`、`sources=[]`、独立 `error`。已有格式与来源校验只在公开入口执行。

## 来源与计数规则

`result.source.location` 是整份输入的文档标识；`source.format` 为 `docx`。每个有输出文字的顶层正文块对应一个 `ContentSource`：

| 字段 | 含义 |
| --- | --- |
| `markdown_start`、`markdown_end` | Python 字符串的左闭右开切片，包含该块结尾换行；生成的块间空行不属于任一块 |
| `extraction_method` | `docx_native` |
| `pdf_page_number` | 始终为 None，不生成 Word 页码或 PDF 页序 |
| `section_path` | 从父标题到当前标题的原文标题元组；标题前的前言为 `()` |
| `body_block_number` | 顶层段落和表格按原生顺序从 1 连续编号，整篇不重置 |
| `section_block_number` | 前言从 1 开始；每遇到非空标题重置，该标题作为新章节第 1 块 |
| `block_type` | `heading`、`paragraph`、`table` |
| `heading_level` | 标题原生级别 1–9；段落和表格为 None |

标题在两种计数中都参与。空段落、空标题和空表格也占正文块位置，但不输出正文或来源区间；空标题不改变章节、不重置计数。表格整体占一块，表内行、单元格及其段落不单独计数；Word 节属性不算正文块。相同标题再次出现仍开启新章节，文档标识加整篇 `body_block_number` 可区分同名章节位置。

例如补充样本中的设备周期表是整篇第 4 块、章节“设备维护”内第 3 块；“例行检查”后的空段落是整篇第 7 块，不输出，后续说明对应整篇第 8 块、该章节第 3 块。章节内第 3 块不表示第 3 页或第 3 段。

新增来源字段均有默认值，追加在原有四个必填字段之后；既有 PDF 的位置参数构造和页来源保持兼容。

## 正文与普通表格范围

使用 python-docx 1.2.0，按顶层正文中的段落/表格原生顺序遍历。标题读取段落及样式继承链中的原生大纲级别，不根据视觉字号或样式名称猜测；保留父子章节与同级切换。1–6 级输出 Markdown 标题；Markdown 最深只支持 6 级，因此 DOCX 7–9 级渲染为 6 级，来源仍保存原级别，独立警告标识具体正文块和级别。

普通矩形表格以首行为表头、其余为数据行，保留行列关系。单元格内的竖线和反斜杠进行 Markdown 转义，换行及多个段落用 `<br>` 留在同一单元格内；表格仍位于相邻说明之间。去除段落、单元格首尾空白，用空行分隔输出块。空表的分隔符不当作可用正文。

这不承诺复杂 DOCX 无损：合并/嵌套/不规则表格、页眉页脚、图片与文字框、脚注、自动编号、修订/内容控件、复杂内联排版均不在已验证恢复范围。成功结果包含独立的范围警告；警告不写入正文，也不代表已识别图片或恢复复杂表格关系。不进行 OCR、渲染页码、导出或最终切块。

## 验证

首次实现 #10 时使用共享项目环境的 Python 3.12.8、python-docx 1.2.0（lxml 6.1.3）；根 [requirements.txt](../../../../requirements.txt) 声明依赖版本。自动化测试只调用公开入口，使用真实包读取与转换，无 mock。

```powershell
python -m unittest tests.test_pdf_word_docx tests.test_pdf_word_digital -v
python -m unittest discover -s tests -v
```

[DOCX 行为测试](../../../../tests/test_pdf_word_docx.py)验证完整正文、两组设备周期关系、原生标题、章节来源、空块与表格计数、失败及诊断隔离；[样本说明](../../../../tests/testFile/constructed-docx.md)记录原始来源、构造方法、摘要与 red→green 观察。
