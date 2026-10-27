# CSV 与 XLSX 表格文件处理

通过公开文件／字节入口读取真实表格，返回整表 Markdown 或可独立取得的按行表示；两种模式具有相同结构化表、列、行、单元格、共同上下文和来源。依赖见 [requirements.txt](/E:/aaa-project/rag-me/requirements.txt)：XLSX 使用 openpyxl==3.1.5，不执行公式计算。

公开入口：[convert_file](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/__init__.py:19)、[convert_bytes](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/__init__.py:43)。

## 使用

```python
from importlib import import_module
from pathlib import Path

tabular = import_module(
    "app.modules.1_documentIngestionAndParsing.4_tabularFileProcessing"
)
context = tabular.TableContext(
    name="员工国内差旅标准", version="2026示例版",
    applicability="普通员工，国内出差", notes="教学数据，不是实际报销政策",
)
result = tabular.convert_file("tests/testFile/xlsx_travel.xlsx", context=context)
if result.success:
    print(result.markdown)
    beijing = result.tables[0].rows[0]
    print(beijing.text, beijing.columns, beijing.context, beijing.source)
    print(beijing.cells[1].raw_value, beijing.cells[1].source.coordinate)
else:
    print(result.error)

options = tabular.XlsxOptions(sheets=(
    tabular.XlsxSheetOptions(
        sheet="第一表", cell_range="B1:C5", header_rows=(2,), context=context,
    ),
    tabular.XlsxSheetOptions(sheet="隐藏", context=tabular.TableContext(name="旧版标准")),
))
rows = tabular.convert_bytes(
    Path("tests/testFile/xlsx_sheets.xlsx").read_bytes(),
    format="xlsx", source="upload.xlsx", mode="rows", xlsx=options,
)

csv = tabular.convert_file(
    "tests/testFile/csv_explicit_gb18030.csv",
    encoding="gb18030", delimiter=";", header_record=3, context=context,
)
```

两个入口接受相同选项；文件入口按后缀识别，也可显式指定格式。字节入口要求 bytes、格式和非空来源字符串。

| 参数 | 默认 | 契约 |
| --- | --- | --- |
| format | 文件后缀／字节入口必填 | csv、xlsx，忽略大小写和前导点 |
| source | 文件路径／字节入口必填 | 仅标识来源，不推断业务上下文 |
| mode | "table" | 整表 Markdown；"rows" 为各行独立文本以空行连接 |
| context | None | CSV 的上下文；XLSX 中作为未指定每表上下文时的默认值 |
| encoding | None | CSV 显式编码 → BOM → UTF-8 → 必要时探测；严格解码 |
| delimiter | "," | CSV 单字符分隔符，不接受引号或换行，不猜分隔符 |
| header_record | None | CSV 默认第一条非空记录；显式值为从 1 开始的原始记录序号 |
| xlsx | None | XLSX 专用 XlsxOptions；CSV 不接受此选项 |

encoding、delimiter、header_record 不参与 XLSX 读取；XLSX 表头配置使用 header_rows。

## XLSX 选择规则

- XlsxOptions.sheets=None（也包括省略 xlsx）按工作簿顺序选择非空可见工作表，跳过空表和隐藏表。一张工作表视为一张矩形表。空白指 None 或纯空白文本；零和 False 均有内容。
- 默认区域是实际非空内容的最小包围矩形，只有格式的外围单元格不会扩大区域。区域内第一条非空行为默认单层表头；空数据行被跳过，原始行号不重排。
- sheets 显式提供非空 XlsxSheetOptions 元组时，只选择列出的工作表，可包括隐藏表；输出仍按工作簿顺序，不按配置顺序。不存在或空的显式选表失败。
- XlsxSheetOptions.sheet 为工作表原名，不能重复。cell_range=None 使用默认区域；显式区域为封闭 A1 矩形，如 B2:D8 或 $B$2:$D$8，也接受单格 A1。不能带表名、使用整行／整列或多个区域；行列不能倒置或超出 XLSX 边界。
- header_rows=None 自动选择；显式配置使用原工作表从 1 开始的行号元组，必须在选区内。支持单行或连续多层表头，如 (3,) 或 (2, 3)，各层名称沿真实归属展开为完整列名。显式表头为空时失败，不回退自动选择。
- 合并标签只按文件记录的实际覆盖范围展开；普通空白不向下填充，合并数值不复制为各行独立测量。选区切断必要合并关系时明确失败。详见[表头与合并关系](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/TABLE_STRUCTURE.md)。
- 每表 context 整体覆盖入口 context；没有提供的上下文为 TableContext()。name、version、applicability、notes 为非空字符串或 None；前三项未知时正文表达“未知”并分别返回带工作表定位的警告。未知备注不制造文本，也不根据文件名／工作表名推断业务含义。

## 数据、来源与失败

| 类型 | 主要字段 |
| --- | --- |
| ConversionResult | success、markdown、source、tables、encoding、warnings、error；失败 markdown=None、tables=[] |
| Source | location、规范化 format |
| Table | columns、rows、context、source |
| Column | name 保留完整列名／单位；source 指向首层表头，header_sources 保留 XLSX 各层来源 |
| Row | cells、columns、context、source、text；两种模式均填充独立 text |
| Cell | raw_value、text、source、data_type、number_format、formula、cached_value、cache_status |
| SourcePosition | source、row_start/end、column_start/end、line_start/end、sheet、coordinate、merged_anchor、merged_range |

所有来源行列区间均从 1 开始且两端包含。XLSX 的 sheet 为真实工作表名，coordinate 为单格或矩形 A1 地址；表来源覆盖表头到最后一条数据，行与列来源保留实际坐标，line_start/end=None。实际合并单元格通过 merged_anchor/merged_range 记录锚点与覆盖范围，普通单元格保持为 None。

XLSX 保留 openpyxl 读取的原值、类型码与原始 number_format；日期可能由库读取为日期／时间对象。普通空白为 None，数字零、布尔、文本、数值保持各自类型。常见整数／小数、百分比、金额与日期／时间提供明确显示文本；不支持的自定义格式保留原值与格式并独立提示。

公式的 raw_value 和 formula 保留表达式，cached_value 单独保存文件中的缓存值；cache_status 区分有缓存和结果未知，不把缓存说成实时计算结果。缺少缓存时 text 明确表达结果未知，并返回独立警告；缓存零仍为数值零。读取器使用同一份字节的公式／缓存视图，不执行公式重算。具体支持格式及状态见[单元格值与公式](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/CELL_VALUES.md)。

CSV 字段始终为原始文本，不推断数字、日期或公式，保留前导零和字段内换行。CSV row_start/end 为逻辑记录序号，column_start/end 为字段序号，line_start/end 为包含该字段的整条记录占用的物理文本行范围。空记录仍计入原始记录序号。

两种表示共用原有 Markdown 转义：反斜杠、管道符、HTML 字符及字段换行不会破坏列归属，换行展示为 `<br>`；不改变结构化原值。警告与错误独立于正文。

表头为空／重复、无数据、非法选项、损坏文件或任何选中表失败，整次转换失败，不返回部分表格。XLSX 中缺少尾部单元格就是空白，不作为 CSV 的行宽不一致；CSV 仍严格拒绝不一致行宽及坏引号。本模块不执行检索、问答、最终切块、HTTP 摄取或导出。

## 模块职责

- [CSV 读取](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/csv_content.py) 处理记录、字段与物理行来源。
- [XLSX 结构读取](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/xlsx_content.py) 处理选表、区域、表头与合并关系。
- [XLSX 值适配](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/xlsx_values.py) 处理原值、公式缓存与显示文本。
- [结果模型](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/models.py) 与[文本表示](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/rendering.py) 供两种格式复用。

## 验证

```powershell
python -m unittest discover -s tests -p "test_tabular_*.py" -v
python -m unittest discover -s tests -q
```

样本、构造脚本和说明均位于 tests/testFile。固定样本由测试直接读取，测试不联网、不重建、不调用语言模型。见 [XLSX 样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-xlsx-tabular.md) 和 [CSV 样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-csv.md)。
