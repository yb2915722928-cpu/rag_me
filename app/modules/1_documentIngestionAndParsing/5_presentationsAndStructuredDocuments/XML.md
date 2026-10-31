# XML 原文与元素来源

通过文件或字节入口取得 Markdown 正文、实际输入来源、编码、元素路径及独立诊断。实现复用既有公开入口、结果模型、字节解码器和 UTF-8 正文导出，离线处理，不调用模型或读取外部资源。

```python
from importlib import import_module

documents = import_module(
    "app.modules.1_documentIngestionAndParsing.5_presentationsAndStructuredDocuments"
)
result = documents.convert_file("tests/testFile/xml_refund_rules.xml")
if result.success:
    for element in result.sources:
        print(element.node_path, element.parent_path, element.node_type)
    documents.export_markdown(result, "refund.md")
else:
    print(result.error)

uploaded = documents.convert_bytes(
    b"<refund><rule>ordinary</rule></refund>",
    format="xml", source="uploaded-refund.xml",
)
```

## 公开契约

[公开入口](__init__.py) 提供：

- `convert_file(path, *, format=None, source=None, encoding=None)`：默认按后缀识别格式，显式 `format="xml"` 可覆盖后缀；未指定来源时，记录传入路径。
- `convert_bytes(data, *, format, source, encoding=None)`：要求 `bytes`、明确格式和非空字符串来源。格式忽略大小写、两端空白及开头的点，例如 `" .XML "`。
- `export_markdown(result, path)`：只导出成功正文，统一写为 UTF-8 字节，无额外 BOM，不转换原文换行。失败结果抛出 `ValueError`，不创建或覆盖目标；写入错误正常抛出 I/O 异常。

[共享结果](models.py) 的 `source` 保留输入位置与规范化后的 `xml` 格式；`encoding` 为实际使用的编码；`warnings`、`review_issues` 和 `error` 均独立于正文。`success` 表示完成约定提取，不证明业务语义已经核验。纯结构 XML 不新增待核验诊断，`requires_review` 为 `False`。

## 原文与元素路径

[结构化转换](structured.py) 先用标准库 ElementTree 校验整篇 XML，再将完整解码原文放入带 `xml` 标识的代码围栏。解析树只用于元素归属；不重新序列化，不裁剪空白，不重排属性、子元素或命名空间声明。

属性、text、tail、混合正文、注释、处理指令、CDATA、实体写法、声明及 CRLF 均保留在原文中。围栏使用至少三个反引号，并长于原文中的所有连续反引号串；围栏前后各添加一个换行，原文自身保持不变。

元素来源按原文先序排列，`kind="xml_element"`、`node_type="element"`。每段路径是百分号转义的展开名称，加上 `[同名兄弟序号]`，段间用 `/`：

- 展开名称为 `{命名空间 URI}局部名`，无命名空间时只用局部名；名称按 UTF-8 百分号转义，URI 内的 `/` 编码为 `%2F`，不会成为路径分隔符。
- 同父、同展开名称的元素从 `[1]` 开始分别编号；同 URI 的不同前缀属于同一名称，不同 URI 或无命名空间的名称分别计数。
- 根也带 `[1]`，其 `parent_path` 为 `None`。例如第二条退款规则为 `/refund[1]/rule[2]`；默认命名空间 `urn:refund:rules` 内的根为 `/%7Burn%3Arefund%3Arules%7Drules[1]`。

属性、text、tail、注释和处理指令不单独建来源。`markdown_start` 与 `markdown_end` 均为 `None`；节点路径用于回查元素，不是正文字符区间，也不提供 XPath 求值。

退款固定样本的普通订单、企业订单及大于 10000 元的企业追加审批条件保持原有属性和父子归属。每条规则下的步骤元素保持原顺序；不把企业专属条件扩展到普通订单，不根据三条并列规则的排列推断跨规则流程。

## 编码与失败

编码优先级沿用共用解码器：显式编码 → BOM → 适用的 XML 编码声明或起始字节序依据 → UTF-8 → 编码探测。支持 UTF-8、UTF-16/32 的 BOM，以及无 BOM UTF-16/32 声明的对应字节序；中文 GB18030 和单引号编码声明均有固定文件验证。

显式编码未知或严格解码失败时直接失败，不回退。XML 声明未知或无法解码时，共用解码器保留独立警告并继续后续选择；自动探测也有独立警告。BOM 或显式编码优先于冲突声明，原文中的声明不被改写。导出的 Markdown 使用 UTF-8，其中 XML 原声明仅描述输入字节，不是 Markdown 文件编码。

读取失败、标签不匹配、多个根、未绑定前缀、重复属性、空文档和解码错误均返回失败，正文为 `None`，元素来源与待核验诊断为空，不暴露有效前半部分。成功解码后出现解析错误时，保留已知编码与普通警告；解码失败时沿用公共失败结果。外部实体引用由标准库解析器拒绝，不读取指向的文件，也不联网获取资源；不提供 DTD/XSD 校验或通用 XML 查询框架。

## 固定样本与验证

[XML 公开测试](../../../../tests/test_presentations_xml.py) 独立迁入 seed 的 `StructuredXmlTests`，补充格式覆盖、声明解码回退和导出契约；只使用已确认的公开文件、字节转换与导出入口。构造方法、固定编码及路径约定见 [结构化样本说明](../../../../tests/testFile/constructed-structured.md)。

```shell
python -m unittest tests.test_presentations_xml tests.test_presentations_json tests.test_presentations_contract tests.test_text_web_json -v
python -m unittest discover -s tests -q
```

测试只读取已保存的固定文件，测试期间不运行构造脚本，不联网，不调用模型。教学规则不代表真实企业资料或检索问答效果；模块止于解析与表示，不接数据库、切块或检索。
