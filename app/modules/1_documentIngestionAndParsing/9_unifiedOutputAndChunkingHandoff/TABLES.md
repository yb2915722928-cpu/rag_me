# CSV / XLSX 交接

本适配接收第4节已经生成的原生结果，沿用统一公开入口及 UTF-8 JSON 导出。只做交接，不读取原文件、重渲染行文字、计算公式或调用服务。

```python
from importlib import import_module

tabular = import_module("app.modules.1_documentIngestionAndParsing.4_tabularFileProcessing")
handoff = import_module("app.modules.1_documentIngestionAndParsing.9_unifiedOutputAndChunkingHandoff")

native = tabular.convert_file("差旅标准.xlsx", mode="table")
report = handoff.adapt_result(native, business_id="差旅标准", version="修订二")
handoff.export_json(report, "交接.json")
```

## 内容与关系

- 每份原生结果对应一份文档，完整保留原 Markdown 正文；多工作表仍属于同一份原工作簿文档。
- 两种上游模式均复用已生成的按行表示。每个单元的 `kind` 为 `table_row`，`text` 原样取自上游，包含完整列名、单位、共同上下文和来源。
- `structure.tables` 是原生表、列、行、单元格、共同上下文及其来源的独立 dataclass 投影。保留合并表头各层来源、合并锚点与范围、原始值、显示文字、公式、缓存值、缓存状态和数字格式。
- 每个单元的 `metadata.table_index` / `metadata.row_index` 是从0开始的结构索引，指向 `structure.tables[table_index].rows[row_index]`。行的原生列、单元格与共同上下文继续在此结构中对应。
- 每行通过 `source_ids` 引用本报告内的 `table_row` 来源，来源的 `locator` 完整保留上游行定位及原文件来源。文档另保留 `document` 来源。报告内文档、来源和单元共用标识分配器。
- 表格行列位置不提供正文字符映射，因此所有行单元均为 `alignment="unmapped"`、`body_span=None`，不通过正文搜索猜测偏移。

CSV 的 `row_start` / `row_end` 表示原始记录序号，`line_start` / `line_end` 表示该记录覆盖的物理行，不能互换。XLSX 保留工作表名、原行列、单元格或范围坐标，CSV 物理行字段保持空。表头、单元格及合并区域的位置在各自结构项中保留，不以行来源替代。

原生空值保持空值，真实合并共同标签的显示文字仍由上游决定；不补零或向下填充原始值。表格上下文中的版本不是业务文档版本；未知业务标识和版本保持 `None`，仅显式传参时赋值。

## JSON 原生值

`HandoffReport.to_dict()` 返回独立的 JSON 投影，导出沿用同一投影；内存中的原生输入及交接报告不被改写。

| 原生值 | JSON 表示 |
| --- | --- |
| `date(2026, 10, 27)` | `"2026-10-27"` |
| `datetime(2026, 10, 27, 13, 4, 5)` | `"2026-10-27T13:04:05"` |
| `time(13, 4, 5)` | `"13:04:05"` |
| `timedelta` | 带符号的 ISO 持续时间总秒数，例如 `"PT93784.005S"`、`"-PT3600.005S"`、`"PT0S"` |
| 字符串、数值、布尔、空值 | 保持普通 JSON 标量类型 |

日期和时刻调用各自的 `isoformat()`，不补时区，原生日期时间也不因显示格式只有日期而被截短。持续时间按整数微秒表示为总秒数，保留符号及小数精度，不当作一天中的时刻。参见 [Python 日期时间文档](https://docs.python.org/3.12/library/datetime.html)。未识别对象由 JSON 编码器抛出 `TypeError`，不使用任意 `str()` 兜底。

公式表达式与文件缓存分别保留；缓存可能过期或缺失，不执行公式。缓存空文本、数值零、布尔 `False` 与未知缓存 `None` 保持区别。

## 诊断与验证

错误和警告沿用 `upstream_error` / `upstream_warning`，引用所属文档与原文件来源，不混入正文。失败保留来源和诊断，正文为 `None`，无行单元。成功状态不代表内容经过核验，`requires_review=False` 只表示上游没有给出待核验项。

运行 `python -m unittest tests.test_handoff_tables tests.test_handoff_text_web -v`。测试使用真实上游公开入口、既有 CSV/XLSX 固定样本及 JSON 回读；持续时间测试只在内存中用已有 openpyxl 给既有样本写入持续时间，再经真实解析入口处理，不构造替代原生结果或改写上游。
