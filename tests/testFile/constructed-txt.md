# Issue #2：本地构造 TXT 样本

本票样本全部位于本目录；无外部下载。测试读取固定字节，不在测试期间生成输入。

- `txt_undecodable.txt`：`bytes(range(256))`，按顺序包含全部单字节值；不是有效 UTF-8，charset-normalizer 对该控制字节密集样本无法给出可用编码。
- `txt_truncated_utf16.txt`：UTF-16 LE BOM 后只有一个 `0x17` 字节；UTF-16 码元被截断，必须报告严格解码失败，不能忽略字节或回退猜测。

- `txt_empty.txt`：零字节。
- `txt_whitespace.txt`：ASCII 字节 `b' \t\r\n\r\n  \n'`，只有空白。
- `txt_bom_only.txt`：仅 UTF-8 BOM 三字节 `EF BB BF`，没有正文。

- `txt_utf8_bom.txt`、`txt_utf16_le_bom.txt`、`txt_utf16_be_bom.txt`、`txt_utf32_le_bom.txt`、`txt_utf32_be_bom.txt`：同一固定文本 `北京是中国的首都。\r\n\r\n长江流经武汉。\r\n`，分别使用 Python 对应 Unicode codec 编码，再添加对应 `codecs.BOM_*` 签名。用于核对 BOM 优先级、字节序和签名移除。

- `txt_utf8_layout.txt`：UTF-8 无 BOM；第一段“北京是中国的首都”，第二段“长江流经武汉”。以 CRLF、CR、LF 混合分隔，包含空行、四空格缩进、制表符与末尾双换行，用于核对文字和空白保留。
- `txt_gb18030.txt`：以下固定中文段落以 Python `str.encode('gb18030')` 编码，无 BOM；用于显式编码与自动探测，事实断言依据固定段落：

  > 中国地理与文化知识。北京是中国的首都，故宫位于北京市中心。长江流经武汉，黄河流经兰州。上海位于长江入海口，杭州的西湖是著名景点。成都位于四川盆地，广州位于珠江沿岸。阅读时必须保留城市名称与河流的对应关系，不能删除文字或替换成乱码。
  >
  > 这份资料用于文本转换验证。转换后的正文应完整保留中文标点、段落与实际事实。编码探测只能提供可能的编码，调用方知道来源编码时可以显式指定，以便准确还原内容。
