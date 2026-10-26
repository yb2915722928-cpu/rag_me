# rag_me

RAG 项目。目前实现的文本与网页类内容模块将本地 TXT、Markdown、JSON、静态 HTML 和 MHTML 转为整篇 Markdown，并支持 UTF-8 导出。

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
- MHTML 优先采用明确指定的主 HTML 部分，否则按解码后字符数选择，并在结果中单独提供警告和选中来源；不合并所有框架。
- JSON 输出可重新解析的 JSON 代码围栏，保留原结构和值；Markdown 规范化保护代码空白和已有结构。
- 成功正文、来源信息、编码及警告分别返回；失败结果没有正文，不能导出。导出只包含正文。

模块处理已取得的文件内容，不抓取网址、不执行 JavaScript，也不进行最终文档切块。图片只保留空扩展点。
