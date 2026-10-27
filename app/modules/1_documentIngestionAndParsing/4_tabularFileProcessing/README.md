# CSV 表格文件处理

通过公开文件／字节入口读取 CSV，提供整表 Markdown 和可独立取得的按行表示。实现只依赖 Python 标准库及仓库已有的严格解码器；本次不支持 XLSX。

## 使用

目录名含数字前缀，使用 importlib 导入。文件入口按后缀识别，也可显式传 format="csv"；字节入口必须传格式和来源。

```python
from importlib import import_module
from pathlib import Path

tabular = import_module(
    "app.modules.1_documentIngestionAndParsing.4_tabularFileProcessing"
)
context = tabular.TableContext(
    name="员工国内差旅标准",
    version="2026示例版",
    applicability="普通员工，国内出差",
    notes="教学数据，不是实际报销政策",
)
path = Path("tests/testFile/csv_travel.csv")

# 默认返回整表表示；结构化行在两种模式下始终可用。
result = tabular.convert_file(path, context=context)
if result.success:
    print(result.markdown)
    beijing = result.tables[0].rows[0]
    print(beijing.text, beijing.columns, beijing.context, beijing.source)
    print(beijing.cells[1].raw_value, beijing.cells[1].source)
else:
    print(result.error)

rows = tabular.convert_bytes(
    path.read_bytes(), format="csv", source="upload/travel.csv",
    mode="rows", context=context,
)

configured = tabular.convert_file(
    "tests/testFile/csv_explicit_gb18030.csv",
    encoding="gb18030", delimiter=";", header_record=3,
    context=context,
)
```

两个入口具有相同选项：

| 参数 | 默认 | 约定 |
| --- | --- | --- |
| mode | "table" | "table" 为整表 Markdown；"rows" 为各行文本以空行连接 |
| context | None | 一张 CSV 对应一个 TableContext；未知项用 None |
| encoding | None | 显式编码 → BOM → UTF-8 → 必要时探测，严格解码，不忽略坏字符 |
| delimiter | "," | 单字符分隔符，不接受双引号或换行；不猜分隔符 |
| header_record | None | 默认第一条非空记录；显式值为从 1 开始的原始 CSV 记录序号 |
| format | 文件后缀／字节入口必填 | 当前接受 csv、.CSV 等大小写和前导点变体 |
| source | 文件路径／字节入口必填 | 非空来源字符串；不会据此猜表名、版本或适用条件 |

TableContext 的 name、version、applicability、notes 均为非空字符串或 None。前三项未知时在正文中表达“未知”，同时分别返回警告；备注未知时不制造备注。CSV 只有一张表，后续工作簿支持可按表复用同一个上下文模型。

## 局部结果契约

公开类型定义于 [models.py](/C:/Users/29157/.codex/worktrees/tabular-implementation/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/models.py)，由 [模块入口](/C:/Users/29157/.codex/worktrees/tabular-implementation/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/__init__.py) 导出。

| 类型 | 字段与含义 |
| --- | --- |
| ConversionResult | success、markdown、source、tables、encoding、warnings、error；失败时 markdown=None、tables=[] |
| Source | location 是原文件或调用方来源；format 是规范化格式 |
| Table | columns、rows、context、source；CSV 成功时恰有一张表 |
| Column | name 是完整列名，保留来源已有单位与空白；source 指向表头字段 |
| Row | cells、columns、context、source、text；两种模式都填充 text，单行可独立解释 |
| Cell | raw_value、text、source；CSV 原值与显示文本均为字符串，不推断数值、日期或公式 |
| TableContext | name、version、applicability、notes；相同表内行共享上下文 |
| SourcePosition | source、row_start/end、column_start/end、line_start/end；所有区间两端包含 |

CSV 的 row_start/end 指原始记录序号，column_start/end 指原始字段序号，均从 1 开始。line_start/end 是**所在 CSV 记录**占用的物理文本行范围；单元格通过字段序号定位，其物理行范围沿用包含它的记录，不表示字段的字符偏移。字段内换行使记录可能跨越多条物理行，空记录仍计入原始序号。表来源覆盖表头到最后一条数据，含中间被跳过的空记录；列来源指向真实表头。

未来 XLSX 可继续使用表／行／列／单元格／上下文的结构与 mode="table"／"rows"，再添加工作表、合并和公式等格式信息；当前行列位置没有伪装成工作表坐标。表示函数位于 [rendering.py](/C:/Users/29157/.codex/worktrees/tabular-implementation/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/rendering.py)，独立于 [CSV 读取](/C:/Users/29157/.codex/worktrees/tabular-implementation/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/csv_content.py)。

## 内容与失败规则

- 标准双引号、字段内逗号／换行与双引号转义由 csv.reader 真实读取。补充拒绝 strict 模式仍接受的未加引号字段中的裸双引号。
- 前导零、等号开头文本、空字符串、"0" 保持区别；不去掉数据字段原有空白。空记录指没有字段或所有字段均为空白，跳过它不重编号。
- 表头字段不可为空白，完整列名不可重复。显式表头记录为空或不存在时失败，不退回自动选择。
- Markdown 对反斜杠和管道符转义，将 CRLF／CR／LF 显示成 `<br>`；字面量 HTML 字符转成实体。结构化原值和 Cell.text 保持解码后的原文本。
- 行宽不一致、坏引号、无表头／无数据、读取或解码错误、非法参数均返回明确错误。记录解析错误包含记录位置及物理行范围，失败不返回已经读到的部分表格。解码后解析失败仍保留实际编码和已有解码警告。
- warnings 与 error 独立于正文。正文中的共同上下文和来源用于解释证据；不会产生切块、索引、问答、HTTP 或导出行为。

## 验证

```powershell
python -m unittest tests.test_tabular_csv -v
python -m unittest discover -s tests -q
```

固定样本、构造命令、来源和关键预期见 [CSV 样本说明](/C:/Users/29157/.codex/worktrees/tabular-implementation/rag-me/tests/testFile/constructed-csv.md)。测试仅读取本地文件，不下载、不重建、不调用语言模型。

本次沿公开 convert_file／convert_bytes 逐个纵向切片实施。保留的代表性红→绿证据如下：

| 行为 | 首次红证据 | 最小实现后 |
| --- | --- | --- |
| 固定 Iris CSV 字节读取 | AttributeError: convert_bytes 不存在 | 1 个测试通过 |
| 文件入口等价 | AttributeError: convert_file 不存在 | 2 个测试通过 |
| 独立行共同上下文 | AttributeError: TableContext 不存在 | 3 个测试通过 |
| 引号、空记录与原始位置 | 预期 4 列，实际空表头 [] | 4 个测试通过 |
| 显式编码／分隔符／表头位置 | TypeError: 不接受 encoding 参数 | 5 个测试通过 |
| 未知上下文独立警告 | 预期 3 条警告，实际 0 | 6 个测试通过 |
| Markdown 特殊字符 | 原管道符未转义，字段换行破坏表行 | 7 个测试通过 |
| 非法入口参数 | 21 个 subTest 失败、10 个异常 | 8 个测试通过 |
| 行宽不一致整次失败 | 4 个 subTest 错误返回成功 | 9 个测试通过 |
| 空／重复表头 | 2 个 subTest 错误返回成功 | 10 个测试通过 |
| 无表头／无数据／显式空表头 | 1 个错误成功、5 个异常 | 11 个测试通过 |
| 三类坏引号 | 1 个错误成功、2 个未转换异常 | 12 个测试通过 |
| 显式 UTF-8 的 BOM 表头 | 实际列名包含 U+FEFF | 13 个测试通过 |

另补充 4 个验收测试，直接验证已有严格解码器、文件读取错误及三组证据范围，无需新增实现。当前 CSV 17 个测试全部通过；完整仓库发现 134 个测试，通过 132 个、按已有开关跳过 2 个云端 live 验收。
