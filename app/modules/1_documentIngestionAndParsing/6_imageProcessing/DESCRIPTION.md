# 图像描述（#29）

公开文件与字节入口显式选择 `task="describe"`，取得用于按主题寻找图片的画面概括。沿用静态 PNG、JPEG、WebP、显式格式覆盖及配置契约；描述不接受 `question`，包括空字符串。一次只发送本次实际图片和描述提示，调用一次既有 StepFun API。

```python
import importlib
from pathlib import Path
from dotenv import load_dotenv

images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
# 由调用方显式加载指定文件；模块核心只读取传入配置或进程环境。
load_dotenv(dotenv_path=Path("E:/aaa-project/rag-me/.env"), override=False)

result = images.convert_file(
    "tests/testFile/image_description_approval.png", task="describe",
)
image_bytes = Path("tests/testFile/image_description_camping.png").read_bytes()
result = images.convert_bytes(
    image_bytes, format="png", source="upload/camping.png", task="describe",
)
if result.success:
    print(result.text, result.source, result.prompt_version, result.requires_review)
else:
    print(result.error.code, result.error.message)
```

配置沿用 `STEP_API_KEY`、`STEP_BASE_URL`、`STEP_MODEL`，也可显式传 `images.StepFunConfig(...)`。两个示例是两个独立调用；相同输入遵循同一契约，真实模型的独立输出不保证逐字一致。文件来源默认保留路径，字节来源由调用方提供，SHA-256 对应实际原始图片字节，尺寸来自真实解码。

提示与严格 schema 位于 [prompts.py](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/6_imageProcessing/prompts.py)，描述版本为 `describe-v1`。正常描述必须是非空白文字，状态为 `content`；`no_text` 只属于 OCR，不能充当空描述。空响应、无效状态或正文、截断及协议错误返回 `failed`、`text=None` 和独立诊断；已取得的来源、尺寸、请求模型与提示版本仍保留。沿用原客户端的鉴权、限流、网络、超时与服务错误语义，无自动重试或回退。

结果中的 `requested_model` / `response_model` 如实保留请求及响应披露的标识，不推测模型修订。每个正常描述均包含 `unverified_model_output`，模型提供的 `review_notes` 另保留为 `model_uncertainty`；待核验事项与正文分离。调用成功不清除待核验状态，也不表示程序能检测全部模型错误。

描述围绕可见对象、画面与主题，不是 OCR 原文或完整流程关系还原。提示明确禁止将一个条件分支扩成通用业务规则。需要判断具体条件关系时，应由相应任务直接查看原图；本 ticket 不实现问题理解、裁剪映射、索引或原图托管。

本实现复用[阶跃星辰官方图像结构化示例](https://platform.stepfun.com/cookbook/step-5-vision-structured)的实际图片 data URL、任务文字和严格 JSON Schema。与其固定表格字段示例相比，此处以 `status/text/review_notes` 表达主题概括，并在响应入口按任务验证正文；结构化格式约束不能证明描述内容正确。客户端与结果模型未修改。

## 固定样本与来源

全部样本由[构造脚本](/E:/aaa-project/rag-me/tests/testFile/build_image_description_samples.py)绘制，无新增下载或模型生成的参考答案。原创图形样本采用 CC0-1.0；系统字体仅用于绘制，不分发字体文件。[构造记录](/E:/aaa-project/rag-me/tests/testFile/image_description_constructed.json)保存方法、参考事实、Pillow 与字体摘要，以及每份图片的字节数和 SHA-256。测试不调用构造脚本，重建需人工执行。

- [露营场景 PNG](/E:/aaa-project/rag-me/tests/testFile/image_description_camping.png)：960×640，橙色帐篷、湖水、两座山、树木和太阳，无人物、无文字。另有真实 JPEG 与 WebP 编码，离线验证三种格式及文件／字节入口等价。
- [付款审批图](/E:/aaa-project/rag-me/tests/testFile/image_description_approval.png)：1200×780，申请后按金额分支；超过 1 万元由负责人审批，其他情况由财务审批。图中没有所有付款统一交给某一个审批人的规则。

两张原图已直接查看，文字与分支箭头清晰可核对。语义真值来自构造规则与原图，不取自被测模型的输出。

## TDD 与离线验证

测试只经过已确认的公开 `convert_file` / `convert_bytes`，使用真实解码、提示、HTTP 客户端、解析和结果建立。本地 HTTP 服务为外部 API 边界提供可控响应，检查收到的实际原图字节、MIME、描述提示与严格 schema，以及每次仅一个请求；它不证明真实视觉能力。

| 纵向切片 | 先观察到的红 | 最小实现后的绿 |
| --- | --- | --- |
| 可追溯描述 | `describe` 被公开入口拒绝为非法任务 | 独立版本提示／schema，非空描述、来源、模型与待核验分离 |
| 描述状态 | 服务端 `no_text` 被错误接受为正常空结果 | 按任务校验，描述拒绝 `no_text`，OCR 正常空结果保留 |
| 问题参数 | 错误提示仍声称正在执行 OCR | 两个入口明确提示 `describe does not accept question`，不发送图片 |

补充三种编码入口等价、13 类不可用响应、401／429／503 和超时等测试在已有实现上直接通过，不虚构红灯。描述离线 6 个方法与 OCR 9 个方法全部通过；仓库默认回归为 215 项、4 项显式云端测试跳过。

```powershell
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest tests.test_image_description tests.test_image_ocr -v
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest discover -s tests
# 显式真实验收：只由测试入口加载明确给出的环境文件，不打印凭据。
$env:STEP_DESCRIPTION_LIVE_TEST = '1'
$env:STEP_ENV_FILE = 'E:\aaa-project\rag-me\.env'
$env:STEP_DESCRIPTION_LIVE_EVIDENCE = 'tests/testFile/image_description_live_initial.json'
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest tests.test_image_description_live -v
```

## 真实 API 验收记录

2026-10-28 显式载入上述环境文件，实际请求／响应模型均为 `step-5-preview`，提示版本 `describe-v1`。

| 样本／入口 | 结果与人工对照 |
| --- | --- |
| 露营 PNG／文件，首次 | 约 0.280 秒连接失败，`network_error`、无正文；保留来源、摘要、尺寸和请求模型。 |
| 审批 PNG／文件 | 约 13.275 秒成功。输出为“付款审批流程”，按可见箭头分别描述超过 1 万元→负责人、其他情况→财务，未扩成全局规则。 |
| 露营 PNG／字节，单次显式复验 | 约 8.853 秒成功。输出为卡通露营场景，描述太阳、雪顶山、蓝湖、草地、橙色帐篷和树木；与可见画面一致，未添造人物或业务规则。 |

首轮原始结果见[首次证据](/E:/aaa-project/rag-me/tests/testFile/image_description_live_initial.json)，只对连接失败样本进行的一次显式复验见[露营复验证据](/E:/aaa-project/rag-me/tests/testFile/image_description_live_camping_repeat.json)。两份记录保留图片 SHA-256、完整输出、任务、模型、提示版本、错误及待核验信息。复验直接调用公开字节入口，未修改客户端或加入自动重试。

共 3 次调用，2 次成功、1 次连接失败；两个固定场景各取得一次成功质量证据。首轮 live unittest 因瞬时连接失败退出失败，不能宣称整轮全绿或服务稳定。live 测试的主题词和明显通用审批断言只作有限语义筛查，允许合理措辞；此处另直接对照两张原图。固定样本通过不保证任意画面、复杂流程或模糊图可靠，也不宣称能自动发现全部扩写与遗漏，正常输出仍须核验。
