# Issue #4：本地构造 JSON 样本

本票新增样本均位于本目录，无外部下载。除特别注明外，以 UTF-8 无 BOM 保存，测试读取固定文件字节，不在运行期间生成输入。现有公开样本保持原始字节；其来源、大小与摘要继续由来源记录维护。

- `json_trailing_comma.json`：数组尾部含多余逗号，验证语法错误明确失败。
- `json_multiple_documents.json`：连续两个对象，验证不能只解析第一个对象并忽略剩余输入。
- `json_invalid_escape.json`：字符串使用 JSON 不允许的 `\q` 转义，验证严格解析。
- `json_nan.json`、`json_infinity.json`、`json_negative_infinity.json`：分别在根值、对象内数组及根数组放置 `NaN`、`Infinity`、`-Infinity`；这些不是合法 JSON 常量，必须失败。
- `json_utf8_bom.json`：Python 将固定对象文本以 UTF-8 编码并在前面添加 `codecs.BOM_UTF8`，末尾使用 CRLF。内容为城市“北京”、按序排列的“长江”“黄河”、以 U+FEFF 开头的字符串值及合法字符串“NaN Infinity -Infinity”。用于自动与显式 UTF-8 的 BOM 去除、中文原文、字符串内字符保留及纯正文导出。
- `json_empty.json`：零字节；`json_whitespace.json`：固定 ASCII 字节 `b' \t\r\n\r\n '`。都不是有效 JSON 文档，验证不能产生成功正文或导出文件。
- `json_types.json`：手写根数组，包含嵌套对象、数组、中文、转义换行和制表符、引号与反斜杠、空容器、空字符串、整数、小数、指数、布尔值及 null。包含整数 `9007199254740993`，用于检查整数精度；嵌套 `0` 与 `0.0` 用于区分数值类型；末端叶值为“末尾”，用于检查完整保留。
- `json_root_string.json`、`json_root_integer.json`、`json_root_float.json`、`json_root_true.json`、`json_root_false.json`、`json_root_null.json`、`json_root_empty_object.json`、`json_root_empty_array.json`：分别手写 `""`、`9007199254740993`、`-1.25`、`true`、`false`、`null`、`{}`、`[]`。验证每种合法根值，包括容易被误当作“无正文”的值。
- `json_gb18030.json`：本地 Python 读取已有构造 TXT 的固定 GB18030 段落，放入标题为“地理资料”的对象；使用 `json.dumps(..., ensure_ascii=False, indent=2)` 格式化，补一个 LF，再编码为 GB18030，无 BOM。用于验证编码探测、显式 GB18030、错误的显式 UTF-8，以及警告不混入实际导出文件。

本目录已有 `* -text` Git 属性，覆盖全部新增样本并保留原始字节。
