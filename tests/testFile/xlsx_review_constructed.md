# Issue #14 评审回归固定样本

由 [build_xlsx_review_samples.py](/E:/aaa-project/rag-me/tests/testFile/build_xlsx_review_samples.py) 使用 openpyxl 构造真实 XLSX。需要人为预设缓存或损坏内容的样本由构造器修改指定 OOXML 条目；不手改生成文件。缓存不来自办公软件重算，不证明公式执行能力或缓存新鲜度。

测试仅读取已提交的固定文件，不在运行时重建，也不导入生产实现生成期望值。[公开入口回归](/E:/aaa-project/rag-me/tests/test_tabular_review_regressions.py) 覆盖 table/rows 模式和 convert_file/convert_bytes。

| 固定文件 | 构造与独立已知预期 |
| --- | --- |
| [xlsx_review_string_cache.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_review_string_cache.xlsx) | B2 为 `=IF(1=1,"","x")`，预设 `t="str"` 和空 `<v/>`；缓存应为 `''`、cached，正文明确“文件缓存：空文本”。B3 预设文本 x；B4 `=1+1` 不设缓存，应为 None、unknown，且只有 B4 有未知警告。 |
| [xlsx_review_array_formula.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_review_array_formula.xlsx) | B2 为 openpyxl ArrayFormula，已有表达式 `=SUM(IF(A2="A",1,0))`，范围 B2:B2；原值、公式和正文保留表达式，不含对象地址，不计算，缓存未知。 |
| [xlsx_review_blank_merge.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_review_blank_merge.xlsx) | A2:A3 合并，锚点为三个空格；A4 为“有效”，B4 为数字 0。只有 A4:B4 是数据行，保留原坐标及零值，不制造合并值说明。 |
| [xlsx_review_blank_merge_no_data.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_review_blank_merge_no_data.xlsx) | 只有表头和上述空白合并；显式区域 A1:B3 时应整次失败，无正文或部分表。 |
| [xlsx_review_corrupt_shared_string.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_review_corrupt_shared_string.xlsx) | 第一张“有效表”含正常数据；第二张“损坏表”的 A2 改为共享字符串索引 999，无对应字符串。两个入口均应返回 XLSX reading failed，不能泄露 IndexError 或部分正文／表。 |
| [xlsx_review_iso_date.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_review_iso_date.xlsx) | iso_dates=True，B2 保存 date(2026, 10, 27)，格式 yyyy-mm-dd。保留 date 类型及 ISO 文本 2026-10-27，不误报警告。 |

## 红→绿记录

在专属修复 worktree、指定解释器中，逐项新增测试并先运行，再改生产代码：

| 评审项 | 红阶段实际观察 | 绿阶段 |
| --- | --- | --- |
| P2-1 | 四个入口／模式组合均得到 (None, unknown)，而非 ('', cached) | 1 项测试通过 |
| P2-2 | 原值为 ArrayFormula 对象，文件／字节结果因内存地址不同而不等 | 累计 2 项测试通过 |
| P2-3 | 返回 A2:B2、A3:B3 假数据行；无数据样本误报成功，共 8 个失败子用例 | 累计 3 项测试通过 |
| P2-4 | 四个入口／模式组合均泄露 IndexError: list index out of range | 累计 4 项测试通过 |
| ISO date | 四个入口／模式组合均误报 unsupported number format yyyy-mm-dd | 累计 5 项测试通过 |

P3-1 将表头发现、合并跨界、完整列名展开及去重归入 [表头读取](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/xlsx_content.py)；P3-2 将 CSV/XLSX 的上下文诊断、行表示及正文组装归入 [共同收尾](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/4_tabularFileProcessing/__init__.py)。这两项纯重构前后表格专项均为 46 项通过，未新增镜像测试。

最终验证（指定解释器）：

- `python -m unittest discover -s tests -p 'test_tabular*.py' -q`：46 项通过。
- `python -m unittest discover -s tests -v`：163 项，161 通过，2 项既有 live 验收跳过，无失败。
