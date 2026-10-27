# PPTX 演示页归属与待核验关系

使用固定依赖 `python-pptx==1.0.2` 在本地提取实际幻灯片对象和演讲者备注，不需要安装 PowerPoint，也不上传资料。文件、字节与导出调用及共享结果见 [模块说明](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/README.md)。旧版 PPT 和 PPTX 文本编码选项明确拒绝。

```python
from importlib import import_module
from pathlib import Path

documents = import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
result = documents.convert_bytes(
    Path("tests/testFile/pptx_refund.pptx").read_bytes(),
    format="pptx", source="refund-upload.pptx",
)
if result.success:
    for position in result.sources:
        print(position.slide_number, position.slide_title,
              position.shape_path, position.bounds_emu)
    for issue in result.review_issues:
        print(issue.code, issue.message, issue.source)
    documents.export_markdown(result, "refund.md")
else:
    print(result.error)
```

## 提取与来源

[PPTX 提取实现](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/pptx_content.py) 按原页序输出页标识，保留真实标题、独立文本对象、原段落顺序与层级，以及每页讲者备注占位符中的文字。无标题页不根据首段编造标题。文本中的 Markdown/HTML 符号按输出语境转义，软换行保留为 `<br>`。

普通表格使用 HTML 的 `table`、`tr`、`td` 保留行列与文本；合并起始单元格保留 `rowspan`、`colspan`，被覆盖的格不重复输出。不把第一行臆定为表头，不把原文中的 HTML 当成标签。

| 来源字段 | 约定 |
| --- | --- |
| `slide_number`、`slide_title` | 实际原页序及真实标题；页序从 1 开始。 |
| `shape_path`、`shape_name` | 原对象 ID 的层级路径及名称，组合子对象保留祖先 ID。 |
| `bounds_emu` | `(left, top, width, height)`，单位为 EMU，属于对象的父容器；不对组合坐标做页内绝对换算。 |
| `paragraph_number`、`level` | 原段落序号从 1 开始，保留空段落所占序号；层级保留 PowerPoint 原生 0 起始值。 |
| `row_number`、`column_number` | 表格原始网格位置，从 1 开始；合并格使用起始位置。 |
| `markdown_start`、`markdown_end` | 左闭右开的输出字符区间，包含对应 Markdown/HTML 标记；页来源只覆盖页标识，段落及单元格各有独立区间。 |

没有正文的组合、图片、连接线、图表及其他未提取对象只提供定位，不伪造正文区间。原对象坐标用于回查，不能证明对象的业务关系。

## 待核验诊断

对象按文件图层顺序输出，不根据坐标猜测左右分栏的阅读路径。每页均有 `reading_order_unverified`，提醒核验阅读顺序、分栏和条件归属。以下诊断均带具体原页及对象来源，存放在 `review_issues`，不拼进可导出的正文：

| 代码 | 待核验内容 |
| --- | --- |
| `reading_order_unverified` | 图层顺序不代表阅读或业务步骤顺序。 |
| `group_relationships_unverified` | 组合含义、子对象坐标及归属。 |
| `shape_relationships_unverified` | 图形文字已提取，形状含义、箭头及关系尚未核验。 |
| `connector_unverified` | 连接线方向、端点及分支。 |
| `picture_unverified` | 图片文字、图文对应及视觉信息。 |
| `chart_unverified` | 图表、标签及视觉含义。 |
| `merged_table_unverified` | 已保留单元格跨度，表头和条件归属仍需核验。 |
| `unsupported_object_unverified` | 其他未提取对象，包括嵌入文件。 |

图片页可以返回 `success=True`、`requires_review=True`，正文只有原页标识；这不表示执行过 OCR。成功提取也不表示审批流程、条件归属或其他视觉语义已确认。

## 失败与范围

没有幻灯片、损坏 ZIP、成员解压错误、非法页 XML 或后续页对象解析失败时，整篇返回失败；不会暴露已有前几页正文、来源或待核验诊断。失败结果不能创建或覆盖导出文件。

不展开母版、版式中的背景与继承文字、嵌入文件；不执行页面渲染、OCR 或视觉模型，不还原箭头方向、业务分支、颜色图例或图文语义。对照原资料时仍需检查这些内容。

## 固定验收与依据

[公开测试](/E:/aaa-project/rag-me/tests/test_presentations_pptx.py) 验证原第 8 页退款条件与备注、反向创建的左右栏、组合内坐标、表格与跨度、转义、视觉对象、空包、两种末页损坏、解压错误及导出。只读取已保存的固定文件，不使用模型回答；[构造脚本](/E:/aaa-project/rag-me/tests/testFile/build_pptx_samples.py) 和 [来源说明](/E:/aaa-project/rag-me/tests/testFile/constructed-pptx.md) 支持重建。

教学退款样本不代表真实企业资料已经核验，也不证明下游检索问答效果。

```shell
python -m unittest tests.test_presentations_pptx tests.test_presentations_contract tests.test_presentations_json tests.test_text_web_json -v
```

实现依据：[python-pptx 图层顺序与组合](https://python-pptx.readthedocs.io/en/latest/api/shapes.html)、[演讲者备注](https://python-pptx.readthedocs.io/en/latest/user/notes.html)、[表格跨度](https://python-pptx.readthedocs.io/en/latest/api/table.html)。
