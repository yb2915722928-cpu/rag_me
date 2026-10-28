# ZIP 图片 API（#42）

PNG、JPG/JPEG、单帧 WebP 默认复用现有阶跃客户端。ZIP 只负责成员读取和来源归属，图片解码、任务约束、配置、请求超时及响应校验均沿用图片模块。API 配置缺失或失败只影响当前成员，没有本机 OCR/视觉模型回退。

## 公共选项

从 [ZIP 公开入口](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/__init__.py) 传入 `parser_options={"image": {...}}`：

| 选项 | 既有契约 |
| --- | --- |
| task | 必须显式选择 `ocr`、`describe`、`understand` |
| question | 仅 `understand` 必须给非空问题，其他任务不接受 |
| config | 图片模块的 `StepFunConfig` 对象或 `None`；普通字典仍为 `invalid_config` |
| document | `DocumentSource`，可带 `DocumentPosition("pdf_page"/"slide", index)` |
| crop | `CropMapping`，原图 ID、尺寸及像素 bbox，右下不含 |
| is_cropped | 沿用图片入口；声明裁剪时必须提供完整原图映射 |

这些类型均从 [图片模块](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/6_imageProcessing/__init__.py) 导出。来源对象和配置对象不从 JSON 自动构造。配置空缺字段由 `STEP_API_KEY`、`STEP_BASE_URL`、`STEP_MODEL` 进程环境补齐；核心不加载环境文件，默认请求超时仍为 90 秒，显式对象可指定 timeout。未知选项为成员级 `invalid_options`，固定错误信息不回显参数名和值。`format/source/limits` 由 ZIP 层提供，不能由成员选项覆盖。

```python
import importlib

zips = importlib.import_module("app.modules.1_documentIngestionAndParsing.8_zipContainers")
images = importlib.import_module("app.modules.1_documentIngestionAndParsing.6_imageProcessing")

result = zips.convert_file(
    "tests/testFile/zip_image_understand.zip", source="上传.zip",
    parser_options={"image": {"task": "understand", "question": "两条分支分别由谁审批？",
                              "config": images.StepFunConfig(timeout=90)}},
)
report = result.to_dict()
```

字节入口接受相同选项，必须给容器 source。图片任务作用于该包中全部图片；不推测某个成员的任务。

## 来源与 JSON

[适配器](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/image_api.py) 原样返回既有 `ConversionResult`。外层 `MemberSource` 保留容器、原始路径、中央目录 1 起始序号；原生图片 source.location 为 `容器!/路径#序号`。SHA-256 对应实际成员图片字节，尺寸来自解码；document/crop 保持原义，不从模型输出猜造来源。

JSON 中 `result_kind="image"`，result 保留 task、question、status、text、source、requested_model、response_model、prompt_version、warnings、review_issues、error，并显式投影 success/requires_review。当前提示词版本为 `ocr-v1`、`describe-v1`、`understand-v2`。响应未披露模型版本时保持空值。

正常空 OCR 为 `no_text`、`text=""`、success=true；无法确认的视觉理解为 `uncertain`，保留解释及待核验原因，仍是成功处理。待核验状态不等于语义已核实。失败为 `text=null`，error 保留原生 code/message/http_status；例如 401/403 为 authentication_error，429 为 rate_limited，5xx 为 service_error，无效响应为 protocol_error。其他文本成员继续处理，形成 partial_success。

## 固定样本

全部新增样本都在既有测试目录；[独立构造脚本](/E:/aaa-project/rag-me/tests/testFile/zip_image_build_samples.py) 只打包已有图片，固定 ZIP 元数据，不重新绘图或下载。归档与成员摘要保存在 [清单](/E:/aaa-project/rag-me/tests/testFile/zip_image_samples.json)，原始绘图方法与真值沿用各图片 manifest。

| ZIP | 可核验内容 |
| --- | --- |
| zip_image_formats.zip | 前后 TXT 和中文目录下四种后缀；金额规则图片 |
| zip_image_ocr.zip | 金额超过 1 万元→负责人审批；其他情况→财务；未经批准不得付款；60°C/30天 |
| zip_image_describe.zip | 湖边橙色帐篷、山、树、太阳，无人物 |
| zip_image_understand.zip | 两条连续箭头对应负责人/财务审批 |
| zip_image_blank.zip | 空白图，正常空 OCR |
| zip_image_uncertain.zip | 审批终点被截去，不能猜补分支对应 |
| zip_image_crop.zip | 原图区域 (120,180,1120,440)，1000×260，仅裁剪范围内规则 |
| zip_image_corrupt.zip | 前后 TXT 和截断的损坏 PNG |

## 复现

workdir 使用当前检出的工作树。以下 CLI 在运行环境已配置时会调用 API；协议回归自行使用本地 HTTP 服务，不访问云端：

```powershell
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m app.modules.1_documentIngestionAndParsing.8_zipContainers tests/testFile/zip_image_ocr.zip --parser-options '{"image":{"task":"ocr"}}'
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m unittest tests.test_zip_images -v
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' tests/testFile/zip_image_build_samples.py
```

CLI 输出同一原生 JSON 投影，success/partial_success/failed 分别退出 0/2/1，不输出配置。任务/问题可通过 CLI JSON 传入；配置使用进程环境。文件 API 还能接受显式配置和来源对象。

[默认验收](/E:/aaa-project/rag-me/tests/test_zip_images.py) 经 ZIP 公开 file/bytes 入口使用真实图片模块及真实 HTTP 客户端，复用现有本地服务夹具。先验证无图片分派时失败，再增加最小分支；未知参数泄露风险亦先写失败测试再加固定诊断。其他已由原生入口支持的行为只补公开边界验收，不复制实现或更改原生逻辑。

## 显式真实 API 验收

[live 入口](/E:/aaa-project/rag-me/tests/test_zip_images_live.py) 仅在 `STEP_ZIP_IMAGE_LIVE_TEST=1` 时运行，必须给 `STEP_ENV_FILE` 和新的 `STEP_ZIP_IMAGE_LIVE_EVIDENCE` 输出路径。使用 `load_dotenv(override=False)`，运行环境优先。可选 `STEP_ZIP_IMAGE_LIVE_CASE` 单独选择 `ocr/describe/understand/no_text/uncertain/crop`；不设置则六例。

```powershell
$env:STEP_ZIP_IMAGE_LIVE_TEST = '1'
$env:STEP_ENV_FILE = '<明确批准的环境文件绝对路径>'
$env:STEP_ZIP_IMAGE_LIVE_EVIDENCE = '<新的证据文件绝对路径>'
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m unittest tests.test_zip_images_live -v
```

每例一次请求，无重试；uncertain 经 ZIP bytes，其余经 file。逐例先写证据再断言，保留 ZIP/图片摘要、入口、耗时、完整报告、各项核验和局限，不记录配置、环境文件位置、URL/token。自动语义检查仍需人工对照原图；协议通过不能证明真实识字或理解质量。

本工单 worker 未读取环境文件、未调用收费 API，live 默认跳过；真实云端验收由主代理执行，不能以既有单图片历史证据代替 ZIP 集成结果。

2026-10-28 本工作树验证：本票默认 9 项通过；ZIP 与图片相关回归 57 项、56 通过/1 live 跳过；完整默认回归 297 项、289 通过/8 live 跳过（35.868 秒）。全部 live 开关显式关闭。8 个固定 ZIP 重新构造后摘要一致；`git diff --check` 通过。完成前执行 `git merge --no-edit feat/39-zip-integration`，当时 tip 为 `582dc16`，已是最新。
