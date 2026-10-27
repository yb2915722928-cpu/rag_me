# XLSX 单元格值与公式缓存

本实现仅负责值适配，不选择区域、构造表头或传播合并共同标签。由调用方传入同一输入字节、同一坐标的公式视图和缓存视图。两种表示共用相同的结构化单元格及显示文本。

## 公式与保存值

- raw_value 和 formula 保留公式表达式，data_type 保留 `f`，number_format 和 source 保留原始格式及来源。
- 有保存值时 cached_value 保留 openpyxl 读取的值，cache_status 为 `cached`；text 同时展示表达式、“文件缓存”和“非实时计算结果”。零、False 和错误缓存不会因真假判断而丢失。
- 缺缓存时 cached_value 为 None，cache_status 保持既有 `unknown`；text 表达“结果未知”，warnings 包含工作表及单元格定位的 formula 提示。
- 不执行公式，不声称缓存是最新结果。错误值使用“错误：”前缀，不经过数值格式化；缓存错误同样处理。
- 非公式的 formula、cached_value、cache_status 仍为 None。普通空白保留 None／空文本，零保持数值，布尔和文本不套用数字格式。CSV 的等号文本行为不受影响。

## 明确支持的格式子集

| 格式 | 显示语义／固定样例 |
| --- | --- |
| General | 使用所读值的文本，不猜测单位 |
| 0、0.0 至六个小数位的连续 0 | 定点数，补足小数位；2.675 在 0.00 下为 2.68 |
| #,##0 及其上述小数形式 | 千位分隔；-1234.5 → -1,234.50 |
| 上述数值格式后加 % | 乘 100 并带百分号；0.2 在 0% 下为 20% |
| 上述数值格式前加 $、¥、￥、€、£（可双引号包裹） | 明确货币符号，负号在符号之前；不与百分号组合 |
| yyyy-mm-dd | 日期对象显示为 ISO 日期，如 2026-10-27 |
| yyyy-mm-dd h:mm:ss | 日期时间对象显示为 ISO 日期时间，如 2026-10-27T13:04:05 |
| h:mm:ss | 时间对象显示为 ISO 时间，如 13:04:05 |

支持格式同样应用于文件保存的公式缓存。日期原值是 openpyxl 按工作簿日期系统和格式读取的对象，仍原样保留；不是原始 OOXML 序列数字。ISO 文本不附加推测的时区。数值显示采用十进制 ROUND_HALF_UP，原数值不改变。

未识别的数字／日期格式保留原值及原始格式，text 使用原值文本，并在 warnings 提供 `unsupported number format` 和真实坐标。文字、布尔、空白及错误值不尝试解释数值格式。自定义单位、倍率、颜色、条件、多段格式、会计格式、区域设置代码和任意日期格式不属于完整还原范围。

## 验证

通过公开 convert_file／convert_bytes 读取固定真实 XLSX，不直接测试内部格式化函数。覆盖整表和按行两种表示、结构化元数据、来源、独立警告及入口等价性。

- [独立行为测试](/C:/Users/29157/.codex/worktrees/tabular-values/rag-me/tests/test_tabular_xlsx_values.py)
- [样本构造及固定期望说明](/C:/Users/29157/.codex/worktrees/tabular-values/rag-me/tests/testFile/xlsx_values_constructed.md)

运行 `python -m unittest tests.test_tabular_xlsx_values tests.test_tabular_xlsx tests.test_tabular_csv -v`；默认回归沿用 `python -m unittest discover -s tests -v`。
