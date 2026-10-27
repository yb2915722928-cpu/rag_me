# CSV 构造样本与固定预期

本组是人为构造的教学／失败样本，不是真实报销政策。所有文件由 [build_csv_samples.py](/E:/aaa-project/rag-me/tests/testFile/build_csv_samples.py) 按固定文字和编码写出；不调用被测模块，不生成测试期望。测试使用已经提交的字节文件，不在运行时重建。

重建命令（仓库根目录）：

```powershell
python tests/testFile/build_csv_samples.py
```

| 样本 | 构造与固定预期 |
| --- | --- |
| csv_travel.csv | UTF-8、CRLF、3 列、3 条数据。表头为城市／住宿上限（元／晚）／餐补（元／天）；北京 500／100，上海 450／100，杭州 400／80。数据原始记录分别为 2、3、4 |
| csv_travel_utf8_bom.csv | 同一差旅表，UTF-8 BOM；自动解码返回 utf-8-sig，显式 utf-8 也不把 BOM 当作首列名称 |
| csv_travel_utf16_le_bom.csv、csv_travel_utf16_be_bom.csv | 同一差旅表，明确大小端与 BOM；实际解码标签 utf-16 |
| csv_travel_utf32_le_bom.csv、csv_travel_utf32_be_bom.csv | 同一差旅表，明确大小端与 BOM；实际解码标签 utf-32，不能被 UTF-16 BOM 前缀误识别 |
| csv_explicit_gb18030.csv | GB18030、CRLF。记录 1 是说明，记录 2 为空，记录 3 为分号表头，记录 4／5 为北京／上海。显式 encoding、delimiter、header_record=3；也验证可用编码探测与独立警告 |
| csv_quoted.csv | 记录 1 为空，记录 2 为表头；记录 3 的字段为 00123、含逗号及转义引号的两行说明、=1+2、空字符串。记录 3 占物理行 3–4；记录 4 全为空、记录 5 为空；记录 6 为 00002／普通文本／0／尾，占物理行 7。表来源为记录 2–6、物理行 2–7 |
| csv_markdown.csv | 表头及数据含管道符、反斜杠、CRLF、字面量 `<br>` 和 &。Markdown 分别转义／换行／实体表示，结构化原文不变 |
| csv_width_short.csv、csv_width_long.csv | 表头及北京记录有效；上海为原始记录 3，字段数分别缺 1／多 1，整次失败而非返回北京的部分成功 |
| csv_header_empty.csv、csv_header_duplicate.csv | 表头记录 1 分别含纯空白列名／重复“城市”，明确失败 |
| csv_quote_unclosed.csv | 上海记录 3 的引号字段跨物理行 3–4 后仍未闭合，整次失败 |
| csv_quote_trailing.csv | 上海记录 3 的闭引号后有多余文字，整次失败 |
| csv_quote_bare.csv | 上海记录 3 的未加引号字段含裸双引号；标准库 strict 仍会接受，模块明确拒绝 |
| csv_empty.csv、csv_blank.csv | 零字节／仅空记录，没有表头，明确失败 |
| csv_header_only.csv、csv_no_data.csv | 只有表头／表头后仅空记录，没有数据，明确失败 |
| csv_bom_only.csv | 仅 UTF-8 BOM；自动或显式 UTF-8 都没有表头 |
| csv_truncated_utf16.csv | UTF-16 LE BOM 后只有一个字节，严格解码失败 |
| csv_undecodable.csv | bytes(range(256))，无可用编码探测结果，失败而不替换坏字符 |

共同上下文由调用方明确传入：表名“员工国内差旅标准”、版本“2026示例版”、适用“普通员工，国内出差”。未知上下文保持 None，不从文件名猜测。备注只在调用方提供时出现。

三组证据均从公开转换结果取得：北京单行仅提供北京 500 元／晚；整表和北京加上海两行均提供北京 500 与上海 450 元／晚，且上下文一致。测试中的 50 元／晚是固定例子的算术核验，不是生产解析器的问答能力；单行未含上海不代表按行策略整体效果差。

既有公开样本 [seaborn_iris.csv](/E:/aaa-project/rag-me/tests/testFile/seaborn_iris.csv) 保持下载原字节；来源、大小、SHA-256 和 Git blob SHA 沿用 [sources.json](/E:/aaa-project/rag-me/tests/testFile/sources.json)。公开入口验收 5 列、150 条数据，首条为 5.1／3.5／1.4／0.2／setosa。
