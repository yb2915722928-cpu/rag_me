# 单图视觉理解（#30）

公开文件／字节入口显式选择 `task="understand"`，并要求非空字符串 `question`。每次把本次原始图片字节、独立视觉理解指令及原始问题放在同一请求中；不读取历史 OCR 或描述，不串联多次推理。问题只用去空白判断是否为空，保存与发送仍保留调用方原文。

```python
from importlib import import_module
from dotenv import load_dotenv

load_dotenv(dotenv_path="E:/aaa-project/rag-me/.env", override=False)
images = import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")
question = "请根据条件和箭头说明两条分支由谁审批；依据不足时说明无法确认的关系和原因。"
result = images.convert_file("approval.png", task="understand", question=question)
result = images.convert_bytes(
    image_bytes, format="png", source="upload/approval.png", task="understand", question=question,
)
if result.success:
    print(result.status, result.question, result.text, result.requires_review)
else:
    print(result.error.code, result.error.message)
```

核心仅使用显式配置或已注入的进程环境，不查找或隐式载入环境文件。`question` 不可传给 OCR 或图像描述；缺失、空白或非法类型在公开入口失败，不发 HTTP 请求。图片格式、解码、模型配置、传输和完成响应沿用 OCR 已建立的边界。

## 结果与核验

| 字段／状态 | 语义 |
| --- | --- |
| `status="content"` | 正常回答问题，保留可见条件、箭头和节点的对应 |
| `status="uncertain"` | 正常完成，但问题所需关系依据不足；正文保留可知内容、未确认关系和原因 |
| `status="failed"` | 输入、读取、配置、协议或服务失败；`text=None`，独立 `error` 提供诊断 |
| `question` | 本次原始问题，正常和已经通过选项校验后的读取／调用失败均可追溯 |
| `source` | 输入来源、真实字节 SHA-256、格式与解码尺寸 |
| `requested_model` / `response_model` | 请求及提供方实际披露的模型标识，不伪造未知修订 |
| `prompt_version` | 当前为 `understand-v2`，与 OCR、图像描述版本分开 |
| `review_issues` | 正常结果总含 `unverified_model_output`；原因另以 `model_uncertainty` 保留 |

视觉理解使用严格任务 JSON Schema：必填 `status`、`text`、`review_notes`，状态限定为 `content`／`uncertain`，不接收额外字段。模型响应在业务入口校验一次：正文必须非空，备注必须是非空字符串列表元素，`uncertain` 必须至少有一条原因。不通过关键词搜索把普通答案改判成不确定结果，也不把不确定结果当成网络错误。协议失败不暴露部分正文。

所有正常视觉理解均 `requires_review=True`。`success=True` 表示正常完成请求，不表示事实已核验。来源可以回查只证明结果关联到哪份字节；内容核验仍需人对照原图逐条检查，结构化状态也不能自动检测全部猜补。

实现复用 [client.py](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/6_imageProcessing/client.py)，未修改通用请求协议；独立指令与 Schema 位于 [prompts.py](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/6_imageProcessing/prompts.py)。沿用[阶跃星辰官方图像结构化示例](https://platform.stepfun.com/cookbook/step-5-vision-structured)的图文同请求和严格 Schema；区别是此处保留原始问题，且允许有明确原因的 `uncertain`。结构格式正确仍不代表关系正确。

## CLI

任务选项直接取自 `TASK_PROMPTS`，`--question` 传给公开文件入口；仍显式指定环境文件，不打印凭据。

```powershell
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m app.modules.1_documentIngestionAndParsing.6_imageProcessing `
  tests/testFile/image_understanding_clear.png --task understand `
  --question '请根据图中的条件和箭头说明两条分支由谁审批。' `
  --env-file E:\aaa-project\rag-me\.env
```

CLI 本地 HTTP 验证记录见 [image_understanding_cli_evidence.json](/E:/aaa-project/rag-me/tests/testFile/image_understanding_cli_evidence.json)：问题确实发送，结果保留原问题，缺问题退出 1 且不发请求。本地服务返回预设关系只验证协议，不证明真实视觉质量。

## 固定样本与独立真值

全部图片为本仓库原创 Pillow 构图，无外部下载；无需引入外部图片许可。未分发本机字体文件。构造脚本 [build_image_understanding_samples.py](/E:/aaa-project/rag-me/tests/testFile/build_image_understanding_samples.py) 明确画出条件、连续折线及箭头，未调用被测模型。每张的大小、SHA-256、生成方法和人工可核对的预期保存在 [image_understanding_constructed.json](/E:/aaa-project/rag-me/tests/testFile/image_understanding_constructed.json)。测试运行期间不生成或下载输入。

| 图片 | 人工可核对的依据与预期 |
| --- | --- |
| [清晰图](/E:/aaa-project/rag-me/tests/testFile/image_understanding_clear.png) | 菱形“金额超过 1 万元？”的“是”沿连续折线和箭头到“负责人审批”；“否（其他情况）”到“财务审批”；必须分别核对两个分支 |
| [模糊图](/E:/aaa-project/rag-me/tests/testFile/image_understanding_blurred.png) | 中间 y=[350,640) 连线带高斯模糊；金额条件、否标签及两个审批框可见，但无法确认条件与审批框的完整对应；是标签也在模糊区域内 |
| [截断图](/E:/aaa-project/rag-me/tests/testFile/image_understanding_truncated.png) | 只保留 y=[0,350)，底部节点和箭头终点不存在于输入；无法确认两分支终点，不应从完整原图或常识补齐 |

发送的问题不含审批人名字或预期答案，三个样本使用同一个问题。样本名称、哈希、人工预期仅供本地记录与核对，不进入模型提示。

## TDD 与真实验收记录

按已确认的公开 `convert_file`／`convert_bytes` seam 红绿实施，使用真实图片解码及本地 HTTP 服务，无内部协作者 mock：

1. 文件／字节图文同请求：初始 `invalid_options`（只有 OCR）→ 任务分派、问题追溯和图文请求通过。
2. 缺失／空白／非法类型问题：初始错误发请求或拼接异常 → 入口一次校验并在 HTTP 前失败。
3. `uncertain` 缺原因：初始误作正常成功 → 响应入口拒绝，失败无部分答案；有效模糊／截断响应保留可知内容、原因、来源及待核验状态。
4. 文件读取失败：初始丢失有效原始问题 → 结果保留问题，读取诊断独立。

离线测试另验证 `no_text` 不可冒充视觉理解状态、无效 JSON／字段／类型拒绝、鉴权与服务失败保留图片身份。测试位于 [test_image_understanding.py](/E:/aaa-project/rag-me/tests/test_image_understanding.py)，真实测试位于 [test_image_understanding_live.py](/E:/aaa-project/rag-me/tests/test_image_understanding_live.py)。

真实验收显式加载 `E:/aaa-project/rag-me/.env`，模型请求／响应披露均为 `step-5-preview`。共 8 次单次请求，3 次取得模型输出、5 次连接失败；核心没有自动重试、回退或隐式环境搜索。原始记录全部保留，没有把失败重写为成功：

| 证据 | 实际结论 |
| --- | --- |
| [首轮 v1](/E:/aaa-project/rag-me/tests/testFile/image_understanding_live_initial.json) | 清晰图两个分支均正确；模糊图连接失败；截断图明确无法确认并保留可知条件，但额外写了图中不存在的“黑色遮挡”，不能当成完全准确的内容 |
| [模糊图补验 1](/E:/aaa-project/rag-me/tests/testFile/image_understanding_live_blurred.json)／[补验 2](/E:/aaa-project/rag-me/tests/testFile/image_understanding_live_blurred_final.json) | 均连接失败，没有模型质量结论 |
| [修正提示后 v2](/E:/aaa-project/rag-me/tests/testFile/image_understanding_live_v2.json) | 模糊图正常 `uncertain`，保留条件、两个节点及“未显示连接／终点”的原因，不猜分支。原自动原因词表过窄，误记为未通过；已修正未来测试匹配，原始证据不改。清晰图和截断图本轮连接失败 |

v2 针对实际输出问题增加“不可见区域只写未显示，不猜遮挡颜色／遮挡物／缺失节点”，并要求 `review_notes` 只写不确定原因。人工核对记录见 [image_understanding_live_review.json](/E:/aaa-project/rag-me/tests/testFile/image_understanding_live_review.json)。**最终 v2 的清晰图和截断图尚无成功响应，不能宣称最终提示的三样本真实验收全部通过。** 已停止反复调用；不将网络失败当成视觉理解质量失败，也不把 v1 的成功冒充 v2 的验证。

```powershell
# 默认离线回归，不消耗外部 API。
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest tests.test_image_understanding -v
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 仅显式授权运行；输出路径必须未存在，以免覆盖失败证据。
$env:STEP_UNDERSTANDING_LIVE_TEST = '1'
$env:STEP_ENV_FILE = 'E:\aaa-project\rag-me\.env'
$env:STEP_UNDERSTANDING_LIVE_EVIDENCE = 'tests/testFile/image_understanding_live_new_run.json'
# 可选 STEP_UNDERSTANDING_LIVE_SAMPLE 指定单个已有样本文件名。
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest tests.test_image_understanding_live -v
```

固定样本通过也不推广为任意流程图、截图或扫描质量可靠。本任务不扩展多图、存储、索引或召回；来源文档／裁剪元数据由 #31 单独扩展。
