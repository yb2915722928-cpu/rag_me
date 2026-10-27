# XLSX 表头与真实合并关系（#17）

本说明补充既有公开入口 [convert_file](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/__init__.py:19) / [convert_bytes](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/__init__.py:43) 的结构行为。仍使用 `XlsxOptions` / `XlsxSheetOptions`，不自动猜多层表头，不改变值适配器。

- `header_rows` 使用原工作表从 1 开始的连续行号，例如 `(2, 3)`。没有配置时仍以选区第一条非空行为单层表头。
- 完整列名用 ` / ` 连接同一列的非空层名，保留原文字和单位。只有真实合并区域内才借用锚点标签；纵向同一合并标签只加入名称一次，普通空白不向旁边或向下填充。
- `Column.source` 继续指向选定的第一层原始单元格；新增 `Column.header_sources` 按层保留所有原始单元格来源，包括空白层。被合并覆盖的来源保留自身坐标，并通过 `merged_anchor` / `merged_range` 指向真实关系。
- 数据区覆盖格的 `raw_value` 仍为原始空值，类型和数字格式也来自该格。文本共同标签的 `text` 明示“合并共同标签”、锚点和范围；可独立读取的行文本及整表 Markdown 都保留此说明。
- 数字、公式、布尔等非文本合并值仅在锚点出现，文本标记“仅锚点记录”及范围。覆盖格只表示“值见锚点……；非本行独立值”，不复制数值、公式、公式缓存或类型。范围外普通空白仍为空。
- 默认区域包含非空锚点的真实合并覆盖范围；仅因共同标签／合并值覆盖而存在的行也保留原始行号。只有实际无内容、无可表示合并归属的行才跳过。
- 完整列名为空或重复、显式表头层为空、区域切断必要合并关系、合并跨越表头与数据边界时明确失败。失败诊断包含工作表和相关坐标；任一选中表失败，整次不返回正文或部分表。

固定样本及构造说明见仓库 [xlsx_structure_constructed.md](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_constructed.md)。测试仅通过公开入口读取保存的 XLSX，不在测试期间重建样本，不用生产实现生成期望。

验证：`python -m unittest tests.test_tabular_xlsx_structure tests.test_tabular_xlsx tests.test_tabular_csv -q`；默认回归：`python -m unittest discover -s tests -q`。
