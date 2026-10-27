# #17 固定结构样本

所有文件由同目录 [build_xlsx_structure_samples.py](/E:/aaa-project/rag-me/tests/testFile/build_xlsx_structure_samples.py) 使用 openpyxl 3.1.5 离线构造，无下载来源、无生产模块依赖。使用指定 Python 运行该脚本可重建工作簿内容；ZIP 时间戳可能改变文件摘要。测试只读取当前保存的文件，不运行构造脚本。以下预期按构造的单元格内容和合并记录手工列出。

| 文件 | 固定内容及预期 |
| --- | --- |
| [xlsx_structure_layers.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_layers.xlsx) | 层级表 A1 为说明；表头2–3行，数据4–5行。完整列名为“对象 / 城市”“标准 / 住宿（元／晚）”“餐补（元／天）”“备注”。C2 和 D3 是普通空白，不传播。北京住宿500、上海450。 |
| [xlsx_structure_merges.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_merges.xlsx) | 合并表头 A1:A3 地区、B1:C1 差旅标准、D1:D3 备注；B2住宿、C2餐补，B3元／晚、C3元／天。数据 A4:A5 华北、D4:D5共同说明；第6行A/D真空白；B7:D7横向共同标签。覆盖格原值均空。 |
| [xlsx_structure_measurements.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_measurements.xlsx) | 测量表B2:B3数值900、C2:C3公式=B2+1、D2:D3布尔True；第3行对象乙，不能取得900、公式或True作为本行值。第4行丙的B/C/D为空且无合并。公式没有保存缓存、不执行计算。 |
| [xlsx_structure_vertical_data.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_vertical_data.xlsx) | 结构表A1标签；A2:A4共同。默认区域A1:A4，保留数据行2/3/4；第3/4行原值空但文本标明共同归属。 |
| [xlsx_structure_duplicate.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_duplicate.xlsx) | 两列表头均为“标准 / 金额”，应失败。 |
| [xlsx_structure_blank.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_blank.xlsx) | 两层中B列均空，但B3有数字2，应因空完整列名失败。 |
| [xlsx_structure_empty_level.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_empty_level.xlsx) | 第2表头层全部为空，不能忽略配置后继续解析。 |
| [xlsx_structure_cross_boundary.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_cross_boundary.xlsx) | A1:A2跨默认表头与数据区边界，应失败。 |
| [xlsx_structure_atomic.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_atomic.xlsx) | 先有有效表，再有A1:A2跨界表；整次失败，不返回第一张表。 |

切断关系验收使用同一合并样本的 C1:D7、A1:B7、A1:D4、A5:D7 和从第2层开始的表头；也使用仅选 A3:A4、锚点A2不在选区的情况。必须报相关合并范围，不凭空补回范围外值。

## 保存版本的大小和 SHA-256

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| [xlsx_structure_atomic.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_atomic.xlsx) | 5448 | 242e9f79c025735f8323a30458f3c3be5de4c48f31e22ceed342c88a5e841c24 |
| [xlsx_structure_blank.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_blank.xlsx) | 4894 | b1d38b45b10b14f8162b9ca8289002ef84356183f122de4e18b9197986a49385 |
| [xlsx_structure_cross_boundary.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_cross_boundary.xlsx) | 4919 | 51aa4117d184b85b9065bfa4c4590feb21253ffa9933bf082455d6f4a204efce |
| [xlsx_structure_duplicate.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_duplicate.xlsx) | 4904 | e267865946c02dd4ddebd2452d0154a29fb0686dc3d6fe02feeaaa8a9e6e5970 |
| [xlsx_structure_empty_level.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_empty_level.xlsx) | 4903 | c2ca440a22279f499e0fd35ab746084328a8eaa62965073b8da78855ea74c314 |
| [xlsx_structure_layers.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_layers.xlsx) | 5073 | 8b0feda1c19ca10d97c3343f3467646028345fc018931ca1255c5c9cf8a78c09 |
| [xlsx_structure_measurements.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_measurements.xlsx) | 5022 | ebb7a1fc38c84039adac8cba7908512271c228d2d8404cb88fd62aff001d5663 |
| [xlsx_structure_merges.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_merges.xlsx) | 5120 | 830fde331d96e53035c6b6eccbd8e289ab5c58186879ac5d18f2006268263858 |
| [xlsx_structure_vertical_data.xlsx](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_vertical_data.xlsx) | 4903 | b89dfd317ddb32838429509e379a69db71c8cb055c1285e712fb951f537c31bf |
