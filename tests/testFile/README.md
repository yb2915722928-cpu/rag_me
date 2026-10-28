# 文本与网页转换测试样本

以下六个文件于 2026-10-26 下载，保持来源提供的原始字节。文件大小和 SHA-256 见[来源记录](/E:/aaa-project/rag-me/tests/testFile/sources.json)。测试读取本地固定副本，通过公开转换、导出入口核验实际正文与导出文件。

| 样本 | 格式 | 来源 | 主要用途 |
| --- | --- | --- | --- |
| [alice_utf8.txt](/E:/aaa-project/rag-me/tests/testFile/alice_utf8.txt) | TXT | [Project Gutenberg：Alice's Adventures in Wonderland](https://www.gutenberg.org/ebooks/11) | UTF-8 长文本、段落、已知正文与非 ASCII 标点 |
| [pypa_sampleproject.md](/E:/aaa-project/rag-me/tests/testFile/pypa_sampleproject.md) | Markdown | [Python Packaging Authority](https://github.com/pypa/sampleproject/blob/main/README.md) | 标题、段落与引用式文字链接保留 |
| [python_datastructures.html](/E:/aaa-project/rag-me/tests/testFile/python_datastructures.html) | HTML | [Python 官方教程：Data Structures](https://docs.python.org/3.11/tutorial/datastructures.html) | 文章主体、导航噪声、层级标题与代码示例 |
| [json_schema_2020_12.json](/E:/aaa-project/rag-me/tests/testFile/json_schema_2020_12.json) | JSON | [JSON Schema 2020-12 元模式](https://json-schema.org/draft/2020-12/schema) | 嵌套对象、数组、布尔值及结构保留；不要求本项目实现 JSON Schema 验证 |
| [chromium_simple_page_unmht.mht](/E:/aaa-project/rag-me/tests/testFile/chromium_simple_page_unmht.mht) | MHTML | [Chromium 单页面归档](https://github.com/chromium/chromium/blob/main/third_party/blink/web_tests/mhtml/simple_page_unmht.mht) | MIME 解包、ISO-8859-1 声明、标题与正文提取 |
| [chromium_multi_frames_contentid.mht](/E:/aaa-project/rag-me/tests/testFile/chromium_multi_frames_contentid.mht) | MHTML | [Chromium 多框架归档](https://github.com/chromium/chromium/blob/main/third_party/blink/web_tests/mhtml/multi_frames_contentid.mht) | 五个 HTML 部分、候选选择、来源记录与启发式警告 |

## 本地构造样本

编码、失败及结构边界样本与公开样本保存在同一目录，构造方式分别记录于：

- [TXT 样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-txt.md)
- [Markdown 样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-markdown.md)
- [JSON 样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-json.md)
- [HTML 样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-html.md)
- [MHTML 样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-mhtml.md)
- [集成验收样本说明](/E:/aaa-project/rag-me/tests/testFile/constructed-integration.md)

## 验收使用约定

- 测试读取固定本地副本，不在测试运行期间重新下载。
- 下载文件通过本目录的 [Git 属性](/E:/aaa-project/rag-me/tests/testFile/.gitattributes) 保持原始字节，避免换行转换导致来源摘要变化。
- 后续需要的编码变体、表格、脚本空页面、无 HTML 归档、明确主页面标识、非法 JSON 等补充输入，也全部保存在本目录。新增时注明是公开下载还是本地构造，并记录来源或构造方式。
- 断言内容及结构事实，不只检查非空或无异常。JSON 可从输出围栏重新解析以比较原始层级和值；MHTML 按实际选择规则核验，不要求合并所有框架。
- 文本与网页模块的图片钩子仍为空扩展点，不据此验收网页嵌图识别；独立图片的 OCR、描述与视觉理解由图片模块单独验收。
- 下载样本的版权与许可沿用原来源；保留原文件中的署名、许可及来源信息。

## 表格文件样本

2026-10-27 新增两个公开下载样本，保持原始字节。来源、Git blob SHA、大小及 SHA-256 同样记录在[来源记录](/E:/aaa-project/rag-me/tests/testFile/sources.json)。

| 样本 | 来源 | 已核对事实与用途 |
| --- | --- | --- |
| [seaborn_iris.csv](/E:/aaa-project/rag-me/tests/testFile/seaborn_iris.csv) | [seaborn-data 的 Iris 数据](https://github.com/mwaskom/seaborn-data/blob/master/iris.csv) | UTF-8，5 列、150 条数据；首条为 5.1、3.5、1.4、0.2、setosa。用于真实 CSV 读取与行列对应验收。 |
| [pandas_test1.xlsx](/E:/aaa-project/rag-me/tests/testFile/pandas_test1.xlsx) | [pandas 的 Excel 测试数据](https://github.com/pandas-dev/pandas/blob/main/pandas/tests/io/data/excel/test1.xlsx) | ZIP 完整，包含 Sheet1–Sheet4；Sheet1 的 B1:E8 是 4 列表头 A–D 与 7 条数据。其他区域含空表头或仅表头工作表，需按验收目标显式配置区域，或验证默认规则下的明确失败。 |

表格模块通过固定真实文件验收。补充样本及构造方法见 [CSV](/E:/aaa-project/rag-me/tests/testFile/constructed-csv.md)、[XLSX 普通表](/E:/aaa-project/rag-me/tests/testFile/constructed-xlsx-tabular.md)、[表头与合并](/E:/aaa-project/rag-me/tests/testFile/xlsx_structure_constructed.md)、[值与公式缓存](/E:/aaa-project/rag-me/tests/testFile/xlsx_values_constructed.md)。这些样本与公开下载文件均保存在本目录，测试不联网下载。

空文本缓存、数组公式、空白合并区、损坏共享字符串及 ISO 日期类型的补充回归见[评审样本说明](/E:/aaa-project/rag-me/tests/testFile/xlsx_review_constructed.md)。

## 独立图片样本

图片固定输入、构造脚本、来源／许可及真实 API 输出均保存在本目录：

- [OCR 样本与验收](/E:/aaa-project/rag-me/tests/testFile/image-ocr.md)：PNG／JPEG／WebP、空图片、损坏及多帧输入，以及官方公开表格图片的下载来源与许可。
- [图像描述验收](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/6_imageProcessing/DESCRIPTION.md)：固定露营场景和审批图的主题概括。
- [视觉理解验收](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/6_imageProcessing/UNDERSTANDING.md)：明确箭头的双分支审批图，以及连接模糊和底部截断图片。
- [原图映射验收](/E:/aaa-project/rag-me/tests/testFile/image_provenance_acceptance.md)：原图与固定裁剪图、文档来源、像素区域及真实文字回查。

默认回归只连接本地 HTTP 服务验证协议与来源行为；真实模型质量使用显式开关分别验收。原始失败记录保留，不把预设响应、来源可回查或高置信度当作内容正确的证明。
