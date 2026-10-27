# 本地构造的 JSON 关系样本

新增样本迁自 #21 seed 的 JSON 部分，由 [build_structured_samples.py](/E:/aaa-project/rag-me/tests/testFile/build_structured_samples.py) 重建，无外部下载或真实订单数据。退款规则为虚构教学规则：普通订单由客服办理；企业订单金额不超过 10000 元时由企业财务办理；大于 10000 元时先由企业财务核验，追加企业专属负责人审批，再由企业财务执行退款。

三条规则是并列条件规则，其排列不表示跨规则流程。每条规则的步骤数组表达业务步骤顺序；对象字段排列不表达业务步骤顺序。

在仓库根目录手动执行 `python tests/testFile/build_structured_samples.py` 可重建以下 6 个固定文件。脚本写入字节以固定编码与换行，不改动既有样本，也不生成 XML/PPTX 样本。[JSON 公开测试](/E:/aaa-project/rag-me/tests/test_presentations_json.py) 只读取保存后的文件，测试期间不生成输入。

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
