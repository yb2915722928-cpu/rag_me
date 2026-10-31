# 独立图片处理

公开的 `convert_file` / `convert_bytes` 一次显式选择一种任务。支持真实解码后的单帧静态 PNG、JPEG／JPG、WebP；拒绝损坏、声明格式不符、动画、多帧与其他格式。此处只处理图片及派生文字，不承担原图存储、数据库、上传 API、embedding 或切块。

| 任务 | 用途 | 问题参数 |
| --- | --- | --- |
| `ocr` | 忠实识别可辨认的文字 | 不接受 `question` |
| `describe` | 提供画面与主题的概括，供下游寻找图片 | 不接受 `question` |
| `understand` | 结合原图解释具体问题中的条件、箭头与节点关系 | 必须提供非空 `question` |

详细约定与各任务证据见[图像描述](DESCRIPTION.md)、[视觉理解](UNDERSTANDING.md)及[文档来源与原图映射](PROVENANCE.md)。三种任务统一使用同一个阶跃星辰 API；视觉理解直接发送本次图片和问题，不从已有 OCR 或描述推断原图关系。

```python
from importlib import import_module

images = import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")

# config 字段为 None 时分别读取进程环境 STEP_API_KEY / STEP_BASE_URL / STEP_MODEL。
# 核心不会查找 .env；也可显式传 StepFunConfig(api_key=..., base_url=..., model=...)。
result = images.convert_file("scan.png", task="ocr", config=images.StepFunConfig(timeout=90))

result = images.convert_bytes(
    image_bytes, format="png", source="upload/scan.png", task="ocr",
)
if result.success:
    print(result.text, result.status, result.source, result.requires_review)
else:
    print(result.error.code, result.error.message)
```

文件入口按后缀识别格式，`format` 可覆盖后缀，`source` 可指定调用方的来源标识，默认保留传入路径。字节入口必须给出格式和非空来源。`.JPG` 等大小写与扩展名前导点会归一为 `jpeg`。相同字节、来源和配置经过两个入口遵循同一结果契约；真实模型的独立请求不保证逐字确定性。

任务提示及独立版本集中于 [prompts.py](prompts.py)。`TASK_PROMPTS` 分派所选任务，没有隐式执行三个任务的调用链、多提供方框架、自动重试或回退。

```python
description = images.convert_file("scene.png", task="describe")
understanding = images.convert_file(
    "approval.png", task="understand",
    question="请根据条件和箭头说明两条分支由谁审批；依据不足时说明无法确认的关系。",
)
```

可选的 `document`、`crop` 与 `is_cropped` 参数在共同入口建立来源：文档标识、业务版本和有类型的实际页／幻灯片位置保持独立，已裁剪输入必须给出原图标识、原图尺寸和原图像素矩形。详细数据类与示例见原图映射说明；未知来源保持为空，不让模型猜测或改写。

## 本地命令行

在仓库根目录运行。明确指定原仓库已有环境文件，CLI 只加载这一文件；已注入的进程变量优先，不打印密钥。

```powershell
uv pip install --python E:\aaa-project\rag-me\.venv\Scripts\python.exe -r requirements.txt
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m app.modules.1_documentIngestionAndParsing.6_imageProcessing `
  tests/testFile/image_ocr_rules.png --task ocr --env-file E:\aaa-project\rag-me\.env
```

三项配置分别是 `STEP_API_KEY`、`STEP_BASE_URL`（例如中国站 `https://api.stepfun.com/v1`）、`STEP_MODEL`（本次真实验收为 `step-5-preview`）。地址是 API 基址，客户端添加 `/chat/completions`。`--format`、`--source` 和 `--timeout` 可覆盖默认值。CLI 输出结构化 JSON，成功退出 0，转换失败退出 1；缺少命令参数由 argparse 报错。

CLI 同样支持 `--task describe` 和 `--task understand`，后者通过 `--question` 提供问题。来源及裁剪对象通过 Python 公开入口传入，不增加额外上传或存储服务。

## 结果契约

[models.py](models.py) 定义模块局部数据类：

| 字段 | 语义 |
| --- | --- |
| `text` | `content` 时为所选任务的派生文字，`no_text` 时恰为 `""`，`uncertain` 保留可知内容与无法确认的说明，失败时为 `None` |
| `task` / `status` | 任务为 `ocr`、`describe` 或 `understand`；`no_text` 仅用于 OCR，`uncertain` 仅用于视觉理解，`failed` 表示处理失败 |
| `question` | 视觉理解所回答的调用方原始问题 |
| `source` | 实际输入来源 `location`、归一格式、原始字节 SHA-256、解码宽高（像素），以及可选文档来源和裁剪原图映射 |
| `requested_model` / `response_model` | 实际请求及响应披露的模型标识；未披露修订保持未知，不推测模型版本 |
| `prompt_version` | 所选任务的提示词版本 |
| `review_issues` / `requires_review` | 所有正常结果都含 `unverified_model_output`；模型报告的不确定性另以 `model_uncertainty` 保留，不能通过高置信度自动清除 |
| `warnings` | 普通诊断；空 OCR 只表示本次未取得可用文字，不证明图中没有文字 |
| `error` | 失败诊断 `code`、固定可识别的 `message`、可选 `http_status`；成功时为 `None` |
| `success` | 正常完成任务，与 `requires_review` 独立 |

失败不会暴露部分正文。已读取字节仍保留 SHA-256；未完成解码时尺寸为空；缺配置或服务失败保留已解码尺寸。请求时只发送原始图片字节及任务提示，不发送文件名或参考答案。SHA-256 区分字节版本，不提供可打开的原图地址。

错误码：`invalid_options`、`unsupported_format`、`file_read_error`、`format_mismatch`、`multiframe_image`、`image_decode_error`、`missing_config`、`invalid_config`、`authentication_error`、`rate_limited`、`service_error`、`http_error`、`timeout`、`network_error`、`protocol_error`。上游错误正文和异常原文不进入诊断，以免携带凭据。参数、图片、配置和服务响应只在各自边界校验。

## 官方契约与验证

已核对[官方图像结构化示例](https://platform.stepfun.com/cookbook/step-5-vision-structured)、[模型输入格式](https://platform.stepfun.ai/docs/en/guides/models/step-5-preview)、[结构化输出](https://platform.stepfun.ai/docs/en/guides/developer/json-mode)及 [Chat Completions](https://platform.stepfun.ai/docs/en/api-reference/chat/chat-completion-create)。沿用官方最小 urllib、Bearer 认证、Base64 data URL、`detail=high`、非流式及严格 JSON Schema。官方模型支持 PNG／JPEG／WebP；示例自己的 PNG／10 MB 限制不是模型统一限制，本模块没有照搬该示例限制。

与示例读取固定表格字段不同，本模块按任务分别提取文字、概括主题或回答图片问题，用 `status/text/review_notes` 区分内容、空识字和不确定性；额外验证 `finish_reason=stop`、非拒答、正文 JSON 形状及任务与状态一致性。结构化输出只约束格式，不保证文字事实正确。

```powershell
# 离线公开接缝：真实图片解码、真实本地 HTTP 客户端，不访问外部 API。
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest tests.test_image_ocr -v
# 仓库默认回归；真实 API 测试默认跳过。
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest discover -s tests -v
# 显式 live 验收：载入明确文件，证据写入指定位置。
$env:STEP_OCR_LIVE_TEST = '1'
$env:STEP_ENV_FILE = 'E:\aaa-project\rag-me\.env'
$env:STEP_OCR_LIVE_EVIDENCE = 'tests/testFile/image_ocr_live_evidence.json'
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest tests.test_image_ocr_live -v
```

固定图片、下载许可、构造方法、红绿记录与 OCR 实际质量结论见[样本与验收记录](../../../../tests/testFile/image-ocr.md)。图像描述、视觉理解与裁剪来源的独立证据见各自说明。真实验收需要区分任务内容核验与连接失败，不将离线预设响应或早期提示词的成功冒充最终版本的完整视觉验收。
