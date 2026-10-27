# #16 XLSX 普通表固定样本

全部为本地构造教学输入，不是实际报销政策或下载的公开数据。使用 openpyxl==3.1.5：

```powershell
python tests/testFile/build_xlsx_tabular_samples.py
```

测试仅读取已提交样本，不运行构造脚本。ZIP 元数据可能使重建摘要变化；下表固定当前提交版本。

| 样本 | 构造与独立预期 |
| --- | --- |
| xlsx_travel.xlsx | 差旅表：城市、住宿上限（元／晚）、餐补（元／天）；北京 500/100、上海 450/100、杭州 400/80 |
| xlsx_sheets.xlsx | 工作簿顺序：第一表、空表、隐藏、第二表；第一表 B2:C5 含北京 500／上海 450，第 4 行为空，H20 仅有格式；空表 C8 仅有格式；隐藏表杭州 400；第二表深圳 300 |
| xlsx_plain_values.xlsx | None、整数零、False、文本 00123、小数 12.5（0.00 格式）、无缓存公式 =B2+1、含管道符／反斜杠／换行／HTML 字符的文本；无外部软件重算 |
| xlsx_empty.xlsx | 无内容工作簿 |
| xlsx_header_only.xlsx | 仅表头城市／金额，无数据 |
| xlsx_duplicate_header.xlsx | 城市／城市重复表头 |
| xlsx_blank_header.xlsx | 第二列表头为空，但第二列有数据 500 |
| xlsx_atomic_failure.xlsx | 有效表北京 500 在前，只有表头的“无数据”工作表在后；必须整次失败 |
| xlsx_corrupt.xlsx | 明文 not an XLSX zip file，不是 ZIP，必须明确读取失败 |
| xlsx_merged_unsupported.xlsx | A2:A3 合并标签北京、金额 500／450；#16 明确拒绝，并报告实际合并范围 |

差旅业务共同上下文由调用方提供，不写在表外让解析器猜测。只提供北京行的证据不含上海；提供完整表或北京、上海两行时包含 500 和 450（相差 50 元／晚）。

## 固定字节核验

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| xlsx_travel.xlsx | 5006 | 2754db3acee36d1f9cc79ca8d4cddd818d8ee524669e75c8815a63bd6bd00881 |
| xlsx_sheets.xlsx | 6478 | 4517730479502e208f33836a9ff1572e7894f501038bf7817a8c9936a420c215 |
| xlsx_plain_values.xlsx | 5057 | 363645972fb50881ac12e7d44150197e4a736715ef575a816674ffd674329d6f |
| xlsx_empty.xlsx | 4783 | 1737cd5d9648d48887565d5640115b90e26c7b16875e8aad4b2aa96f06b05c62 |
| xlsx_header_only.xlsx | 4853 | d25f82b6407b8befa4e4c0004b7a3e450237532400dc9316b23888db9f4fc9c7 |
| xlsx_duplicate_header.xlsx | 4871 | 2aad4c0cf3bda9797e6fb603fc0bbf15a573344d78610695c748516aa61b2259 |
| xlsx_blank_header.xlsx | 4868 | 462079b1a2cb42f35df4627b234dee02266d7c40d74b85dc035233d181ee1406 |
| xlsx_atomic_failure.xlsx | 5405 | b8cdd00ebca30f82af5a092f7797cf97ea240ecf657b0bf4e29c157bf9e6dffc |
| xlsx_corrupt.xlsx | 20 | 32edb4439b0f709bca49d1433090771180df8e550def68e1315399be13055a3a |
| xlsx_merged_unsupported.xlsx | 4936 | f54d995454db61a56d81ad94b81657405b4d28d0b89a3339a70fefd6921ae346 |
