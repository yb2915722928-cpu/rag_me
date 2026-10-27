# 演示文稿与结构化文档

通过本地文件或字节入口取得 Markdown 正文，并分别返回输入来源、内容来源、编码、普通警告、待核验关系和错误。

- [PPTX](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/PPTX.md)：保留演示页归属、独立对象、段落层级、表格与演讲者备注；复杂视觉关系明确待核验。
- [JSON](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/JSON.md)：复用既有完整结构表示，补充 JSON Pointer 及父节点来源。
- XML 使用同一结构化分派入口，具体实现由 [#23](https://github.com/yb2915722928-cpu/rag_me/issues/23) 交付。

```python
from importlib import import_module

documents = import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
result = documents.convert_file("tests/testFile/pptx_refund.pptx")
if result.success:
    print(result.source, result.requires_review)
    for issue in result.review_issues:
        print(issue.code, issue.source.slide_number, issue.source.shape_path)
    documents.export_markdown(result, "refund.md")
else:
    print(result.error)
```

## 公开契约

[公开入口](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/__init__.py) 与 [结果模型](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/models.py) 供调用方直接使用：

- `convert_file(path, *, format=None, source=None, encoding=None)` 按扩展名识别格式，允许显式格式覆盖。默认来源为传入路径。
- `convert_bytes(data, *, format, source, encoding=None)` 要求 `bytes`、明确格式及非空字符串来源。格式忽略两端空白、大小写及开头的点。
- `export_markdown(result, path)` 只导出成功正文为 UTF-8，不包含来源或诊断。失败结果抛出 `ValueError`，不创建或覆盖文件；写入异常正常抛出。
- `success` 表示完成约定提取；`requires_review` 根据独立的 `review_issues` 表达待核验关系，两者可以同时为真。
- 读取或解析失败时 `markdown=None`，`sources` 与 `review_issues` 为空，`error` 给出原因；后续页失败也不返回部分正文。
- `source` 表示实际输入；`sources` 定位正文或原结构。字符区间左闭右开，没有正文的视觉对象及结构节点不伪造字符区间。
- `encoding` 仅适用于 JSON/XML，PPTX 明确拒绝文本编码选项。JSON/XML 的解码警告独立返回。

模块止于解析与表示，不接 HTTP 上传、数据库、最终切块、向量索引或模型问答。

## 验证

```shell
python -m unittest discover -s tests -p "test_presentations_*.py" -v
python -m unittest discover -s tests -q
```

测试使用保存后的真实固定文件，来源与重建方法见 [PPTX 样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-pptx.md) 及 [结构化样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-structured.md)。默认回归离线进行，真实 MinerU 云端验收沿用既有显式开关。
