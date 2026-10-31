# JSON 完整结构与节点来源

本模块在既有 JSON 正文转换上增加节点来源，保留根值、容器、值类型及数组顺序，不把字段和值改写成业务自然语言。处理离线完成，不调用模型。

```python
from importlib import import_module

documents = import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
result = documents.convert_file("tests/testFile/json_refund_rules.json")
if result.success:
    for node in result.sources:
        print(node.node_path, node.parent_path, node.node_type)
    documents.export_markdown(result, "refund.md")
else:
    print(result.error)

uploaded = documents.convert_bytes(
    b'{"steps": ["apply", "review", "refund"]}',
    format="json", source="upload.json",
)
```

## 公开契约

[公开入口](__init__.py) 提供：

- `convert_file(path, *, format=None, source=None, encoding=None)`：默认按扩展名识别格式，显式 `format` 可覆盖扩展名；未指定 `source` 时记录传入路径。
- `convert_bytes(data, *, format, source, encoding=None)`：要求 `bytes`、明确格式和非空字符串来源。格式忽略大小写、两端空白及开头的点。
- `export_markdown(result, path)`：只导出成功正文为 UTF-8，无 BOM；复用既有导出行为。失败结果抛出 `ValueError`，不创建或覆盖目标；文件写入异常正常抛出。

[共享结果模型](models.py) 分开承载以下内容：

| 字段 | 含义 |
| --- | --- |
| `markdown` | 成功时为完整 JSON 代码围栏，失败时为 `None`。 |
| `source` | 输入位置 `location` 与规范化格式 `format`。 |
| `sources` | 容器与值的节点来源，不含推测的正文偏移。 |
| `encoding` | 实际使用的编码；解码未成功时为 `None`。 |
| `warnings` | 自动编码探测等普通警告，不进入正文。 |
| `review_issues` | 待核验关系的代码、原因及具体来源，独立于正文。 |
| `error` | 读取、选项、解码或转换失败原因，成功时为 `None`。 |
| `success` | 约定提取已完成，不表示语义已经核验。 |
| `requires_review` | 是否存在待核验关系；与 `success` 独立。纯结构 JSON 不增加待核验关系。 |

不支持或尚未接入的格式返回明确的 `Unsupported format` 失败结果。JSON/XML 的公共入口直接分派到 [结构化转换边界](structured.py)。编码选项仅适用于 JSON/XML。

## 结构与节点路径

JSON 使用 [RFC 6901 JSON Pointer](https://www.rfc-editor.org/rfc/rfc6901.html)。根路径为 `""`，根的父路径为 `None`；对象成员名先将 `~` 转为 `~0`，再将 `/` 转为 `~1`；数组成员从 `0` 开始编号。空键对应 `/`，键 `~1` 对应 `/~01`。根、每个容器和每个值均有来源。

节点的 `kind` 为 `json_node`；`node_type` 为 `object`、`array`、`string`、`number`、`boolean` 或 `null`。整数和小数在正文中保持原解析类型，两者的节点类型均为 JSON 的 `number`。节点来源按原结构先序列出；数组保持源顺序，对象字段排列不证明业务步骤顺序。`markdown_start` 与 `markdown_end` 均为 `None`，节点路径不能用作 Markdown 字符偏移。

退款样本中 `/rules/2/condition/amount_gt` 的父路径是 `/rules/2/condition`，追加审批始终归属金额超过 10000 元的企业订单规则。财务核验、负责人审批、执行退款按该规则的 `steps` 数组顺序保留，普通订单不会获得企业专属条件。样本中的三条规则是并列条件规则，不能据其排列推断跨规则执行流程。

## 兼容性、编码与失败

[共享文本支持](../text_support.py)提供严格 JSON 解析与渲染，既有文本入口继续重导出同一实现。新入口复用同一份解析结果建立节点来源；支持合法根标量、空对象、空数组、中文及嵌套结构，不做预分组或切块。

沿用已有解码优先级：显式编码 → BOM → UTF-8 → 编码探测。显式编码未知或解码失败时不回退；自动探测产生独立警告。非法 JSON、NaN、Infinity、-Infinity 和渲染时产生的非有限数均失败。解析或渲染失败时不返回部分正文或节点，保留已成功取得的编码与警告。

这里只提供文件解析和正文表示，不接 HTTP 上传、数据库、最终切块或检索问答。

## 固定样本与验证

样本构造与来源见 [结构化样本说明](../../../../tests/testFile/constructed-structured.md)。新增 JSON 样本和 [JSON 公开测试](../../../../tests/test_presentations_json.py) 从 seed 迁入；[通用契约测试](../../../../tests/test_presentations_contract.py) 只观察公开入口及导出行为，不依赖私有实现。

```shell
python -m unittest tests.test_presentations_json tests.test_presentations_contract tests.test_text_web_json -v
python -m unittest discover -s tests -q
```

测试读取已保存的固定文件，不调用构造脚本，不以模型输出作为验收依据。教学退款样本不代表真实企业规则或检索问答效果。
