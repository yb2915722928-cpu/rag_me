# 本地构造的 JSON/XML 关系样本

新增 JSON/XML 样本迁自 #21 seed，补充公开格式覆盖和编码回退样本，由 [build_structured_samples.py](/E:/aaa-project/rag-me/tests/testFile/build_structured_samples.py) 重建，无外部下载或真实订单数据。退款规则为虚构教学规则：普通订单由客服办理；企业订单金额不超过 10000 元时由企业财务办理；大于 10000 元时先由企业财务核验，追加企业专属负责人审批，再由企业财务执行退款。

三条规则是并列条件规则，其排列不表示跨规则流程。每条规则的步骤数组表达业务步骤顺序；对象字段排列不表达业务步骤顺序。

在仓库根目录手动执行 `python tests/testFile/build_structured_samples.py` 可重建以下 34 个固定文件（JSON 6 个、XML 28 个）。脚本写入字节以固定编码与换行，不改动其他既有样本，也不生成 PPTX 样本。[JSON 公开测试](/E:/aaa-project/rag-me/tests/test_presentations_json.py) 与 [XML 公开测试](/E:/aaa-project/rag-me/tests/test_presentations_xml.py) 只读取保存后的文件，测试期间不生成输入。

## JSON Pointer

使用 [RFC 6901 JSON Pointer](https://www.rfc-editor.org/rfc/rfc6901.html)。根为 `""`，根的父路径为 `None`；成员名先将 `~` 转为 `~0`，再将 `/` 转为 `~1`；数组按原顺序从 `0` 编号。空键对应 `/`，键 `~1` 对应 `/~01`。根、容器和值都有来源；`kind` 为 `json_node`，`node_type` 为 `object`、`array`、`string`、`number`、`boolean` 或 `null`。

整数和小数在正文中保持原解析类型，节点类型均为 JSON 的 `number`。所有 JSON 来源的正文字符区间均为 `None`，节点路径不冒充字符偏移。

## JSON 固定样本

| 样本 | 构造与验证目的 |
| --- | --- |
| [json_refund_rules.json](/E:/aaa-project/rag-me/tests/testFile/json_refund_rules.json) | UTF-8、LF；三条退款规则保留条件、负责人、步骤数组的父子归属与顺序。 |
| [json_refund_reordered.json](/E:/aaa-project/rag-me/tests/testFile/json_refund_reordered.json) | 调换根和规则对象字段排列，保留数组；节点路径、父路径和值类型保持一致。 |
| [json_refund_invalid_gb18030.json](/E:/aaa-project/rag-me/tests/testFile/json_refund_invalid_gb18030.json) | 删除退款规则根对象的末尾闭合括号，编码为 GB18030、无 BOM；失败保留探测编码与警告，不返回部分节点。 |
| [structured_json_pointers.json](/E:/aaa-project/rag-me/tests/testFile/structured_json_pointers.json) | 空键、`/`、`~`、`~1`、中文、对象数字键，以及整数、小数、false、null、空对象、空数组和空字符串。 |
| [structured_json_overflow.json](/E:/aaa-project/rag-me/tests/testFile/structured_json_overflow.json) | `1e999` 被解析为非有限数后，沿用旧模块在渲染阶段拒绝的行为。 |
| [structured_json_override.txt](/E:/aaa-project/rag-me/tests/testFile/structured_json_override.txt) | 退款 JSON 原字节使用 TXT 后缀；默认识别失败，显式 JSON 格式覆盖后成功。 |

测试还复用既有 JSON 类型、全部合法根值、BOM、GB18030、公开 JSON Schema 与非法 JSON 文件，对比新旧公开入口的正文、成功状态、失败原因、编码与警告。既有样本来源见 [constructed-json.md](/E:/aaa-project/rag-me/tests/testFile/constructed-json.md)，不由本脚本重建。

## XML 元素路径与原文

XML 路径每段为“百分号转义后的展开名称 `[同名序号]`”，段间使用 `/`。展开名称为 `{命名空间 URI}局部名`；没有命名空间时只用局部名。整段名称按 UTF-8 百分号转义，URI 中的 `/` 不会与路径分隔符混淆。同名序号在同父、同展开名称的兄弟元素之间从 1 开始；根也使用 `[1]`，其父路径为 `None`。例如无命名空间的第二条规则为 `/refund[1]/rule[2]`；默认命名空间 `urn:refund:rules` 内的根为 `/%7Burn%3Arefund%3Arules%7Drules[1]`。不同前缀映射到同一 URI 时属于同一展开名称，不同 URI 或无命名空间则分别计数。本约定只定位元素，不提供 XPath 求值。

XML 的 `kind` 为 `xml_element`、`node_type` 为 `element`，覆盖全部元素并按文档先序排列。属性、text、tail、注释和处理指令不单独建立来源；它们与 CDATA、实体写法、命名空间声明、原始 CRLF 一起保留在代码围栏内的解码原文中，不重新序列化。围栏前后各添加一个换行，原文不裁剪、不规范化；原文出现反引号串时加长围栏。两类来源的 Markdown 字符区间均保持 `None`，不将结构节点路径冒充字符偏移。

## XML 固定样本

除特别注明外均为 UTF-8 无 BOM。

| 样本 | 构造与验证目的 |
| --- | --- |
| [xml_refund_rules.xml](/E:/aaa-project/rag-me/tests/testFile/xml_refund_rules.xml) | LF；退款条件位于属性，负责人和步骤为元素，三条同名规则与同名步骤必须有独立路径。 |
| [xml_refund_override.txt](/E:/aaa-project/rag-me/tests/testFile/xml_refund_override.txt) | 退款 XML 原字节使用 TXT 后缀；默认识别失败，显式 XML 格式覆盖后成功并保留来源。 |
| [xml_relationships.xml](/E:/aaa-project/rag-me/tests/testFile/xml_relationships.xml) | CRLF；默认命名空间、多个不同命名空间、相同 URI 的不同前缀、清空命名空间、重复元素、属性、混合 text/tail、注释、处理指令、CDATA 与实体写法。URI 仅为固定标识符，不访问其地址。 |
| [xml_fenced.xml](/E:/aaa-project/rag-me/tests/testFile/xml_fenced.xml) | CDATA 含三连及四连反引号，要求五连反引号围栏且正文完整。 |
| [xml_utf8_bom.xml](/E:/aaa-project/rag-me/tests/testFile/xml_utf8_bom.xml) | UTF-8 BOM；分别自动解码和显式 UTF-8 解码，保留各自解码后的原文。 |
| [xml_utf16_le_bom.xml](/E:/aaa-project/rag-me/tests/testFile/xml_utf16_le_bom.xml)、[xml_utf16_be_bom.xml](/E:/aaa-project/rag-me/tests/testFile/xml_utf16_be_bom.xml) | UTF-16 对应端序 BOM 与 XML 声明；自动解码以及显式指定对应端序。 |
| [xml_utf32_le_bom.xml](/E:/aaa-project/rag-me/tests/testFile/xml_utf32_le_bom.xml)、[xml_utf32_be_bom.xml](/E:/aaa-project/rag-me/tests/testFile/xml_utf32_be_bom.xml) | UTF-32 对应端序 BOM 与 XML 声明，防止与 UTF-16 BOM 前缀混淆。 |
| [xml_utf16_le_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_utf16_le_declaration.xml)、[xml_utf16_be_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_utf16_be_declaration.xml) | UTF-16 无 BOM；按 XML 声明的固定起始字节确定端序，作为格式依据交给共用解码器。 |
| [xml_utf32_le_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_utf32_le_declaration.xml)、[xml_utf32_be_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_utf32_be_declaration.xml) | UTF-32 无 BOM；按 XML 起始字节确定端序，不能先误判为 UTF-16 或 UTF-8。 |
| [xml_gb18030_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_gb18030_declaration.xml) | GB18030 无 BOM，正确 XML 声明；声明优先于 UTF-8 和探测。 |
| [xml_latin1_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_latin1_declaration.xml) | ISO-8859-1 无 BOM，单引号声明及 `café`，验证不能仅依靠 UTF-8。 |
| [xml_explicit_over_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_explicit_over_declaration.xml) | 原字节为 GB18030，声明为 UTF-8；显式 GB18030 优先且不改写原声明。 |
| [xml_bom_over_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_bom_over_declaration.xml) | UTF-8 BOM 与 GB18030 声明冲突；BOM 优先且不改写原声明。 |
| [xml_unknown_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_unknown_declaration.xml) | UTF-8 字节，声明编码不存在；沿用共用解码器警告后回退 UTF-8，警告不写入正文。 |
| [xml_failed_declaration.xml](/E:/aaa-project/rag-me/tests/testFile/xml_failed_declaration.xml) | UTF-8 中文字节声明为 ASCII；声明无法解码时先记录独立警告，再回退 UTF-8，原声明保留。 |
| [xml_invalid_gb18030.xml](/E:/aaa-project/rag-me/tests/testFile/xml_invalid_gb18030.xml) | GB18030 字节，编码声明不可用且结束标签错误；失败保留声明警告、探测警告与已知编码。 |
| [xml_mismatched_tags.xml](/E:/aaa-project/rag-me/tests/testFile/xml_mismatched_tags.xml) | 开闭标签不匹配。 |
| [xml_multiple_roots.xml](/E:/aaa-project/rag-me/tests/testFile/xml_multiple_roots.xml) | 两个根元素，不能只接受第一份文档。 |
| [xml_unbound_prefix.xml](/E:/aaa-project/rag-me/tests/testFile/xml_unbound_prefix.xml) | 未声明的命名空间前缀。 |
| [xml_duplicate_attribute.xml](/E:/aaa-project/rag-me/tests/testFile/xml_duplicate_attribute.xml) | 同一元素含重复属性。 |
| [xml_external_entity.xml](/E:/aaa-project/rag-me/tests/testFile/xml_external_entity.xml) | 外部实体引用由标准库解析器拒绝；不读取指向的外部文件。 |
| [xml_empty.xml](/E:/aaa-project/rag-me/tests/testFile/xml_empty.xml)、[xml_bom_only.xml](/E:/aaa-project/rag-me/tests/testFile/xml_bom_only.xml) | 零字节与仅 UTF-8 BOM，均无 XML 根元素。 |
| [xml_truncated_utf16.xml](/E:/aaa-project/rag-me/tests/testFile/xml_truncated_utf16.xml) | UTF-16 LE BOM 后仅一个字节，严格解码失败。 |

编码选择复用原模块的“显式编码 → BOM → XML 声明 → UTF-8 → 编码探测”优先级。来源字段保留输入位置与已校验格式；解析失败时不输出正文或部分节点来源，保留已成功解码所得的编码和警告。

这些新增文件可能被已有 `testfile/` 忽略规则覆盖，脚本不会改动忽略规则或暂存文件；主任务收集变更时需显式包含它们。

XML 调用与导出契约见 [XML.md](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/5_presentationsAndStructuredDocuments/XML.md)。所有 XML 固定文件都通过公开转换入口验证；导出覆盖成功原文与换行保留、警告不混入正文、失败不创建或覆盖文件。
