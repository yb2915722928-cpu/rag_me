# ZIP 音视频 API（#43）

ZIP 文件/字节入口默认使用既有阶跃 API。适配器仅转换选项并调用原媒体字节入口，未引入本地模型、API 启用开关或失败回退。实现见 [media_api.py](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/media_api.py)，现有媒体实现见 [媒体公开入口](../audioTranscriptionAndVideoUnderstanding/__init__.py)。

支持 WAV/MP3/M4A/OGG/FLAC 与 MP4/MOV/MKV。后缀只决定分派，实际容器和编码由 FFprobe/FFmpeg 检查；视频沿用复制码流重封装，不能保证任意 MKV 编码可放入 MP4。部署仍需 FFmpeg、FFprobe 和临时磁盘，媒体准备仍占 CPU/磁盘，模型计算由 API 完成。成员名不会作为落盘路径，原字节入口以受控临时目录写入输入和切片，退出时清理。

调用方在 `parser_options["media"]` 中明确指定任务：

| 选项 | 含义 |
| --- | --- |
| task | 必填：transcribe（语音）、video（画面）、both（联合）；纯音频只支持 transcribe |
| question | ZIP 的 video/both 必填非空问题；transcribe 不接受问题。既有独立媒体入口的可选概括行为不变 |
| media_id / media_version | 可选业务身份与版本，沿用原媒体语义 |
| config | 可选既有 StepFunConfig 或同字段 mapping；支持 api_key、base_url、asr_model、video_model、timeout |
| options | 可选既有 ProcessingOptions 或同字段 mapping；支持 audio_segment_seconds、video_segment_seconds、media_timeout、ffmpeg、ffprobe |

mapping 供 CLI JSON 使用；其字段的业务校验交给既有媒体模块。未知 mapping 字段返回成员级 invalid_options。format、source 由 ZIP 提供，不能覆盖。生产适配器调用正式包 `audioTranscriptionAndVideoUnderstanding`；旧包兼容入口导出的 `StepFunConfig`、`ProcessingOptions` 与原生结果类型具有相同身份，已有进程内调用仍可使用。

配置优先级：显式 config 字段优先，缺省字段由既有客户端读取进程环境。STEP_API_KEY、STEP_BASE_URL 必需；视频模型使用 **STEP_MODEL**，ASR 使用可选 STEP_ASR_MODEL（默认 stepaudio-2.5-asr）。timeout 默认 180 秒。ZIP 核心不读取环境文件；调用应用负责准备进程环境。缺配置返回 missing_config，该成员失败而其他成员继续。

默认音频切片 30 秒、视频切片 60 秒、媒体工具超时 300 秒；实际片段按真实采样/关键帧边界返回，不能用配置秒数推造时间。容器截止是成员间与读取间的协作检查，不硬性中止正在运行的 FFmpeg 或请求。

从 [ZIP 公开入口](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/__init__.py) 使用进程中已经配置的 API：

```python
import importlib

zip_parser = importlib.import_module("app.modules.1_documentIngestionAndParsing.8_zipContainers")
options = {"media": {"task": "both", "question": "两条审批分支的条件和审批人分别是什么？",
                     "options": {"audio_segment_seconds": 30, "video_segment_seconds": 60}}}
result = zip_parser.convert_file("training.zip", parser_options=options)
# 已取得 ZIP 字节时使用相同选项：
result = zip_parser.convert_bytes(archive_bytes, source="training.zip", parser_options=options)
report = result.to_dict()
```

成员 result_kind 为 media，result 保留原生结果：语音/画面各自的片段、片段起止时间、源字节 SHA-256、业务版本、问题、请求/响应模型、提示词版本、warnings 和 review_issues。成员内来源为 `容器!/原始成员路径#中央目录序号`，外层成员来源仍分别保留容器、路径和序号。未知 speaker 保持 None，不生成词级时间；媒体派生文字仍需对照同版本原媒体。

正常空转写的原生 no_text 是成员成功；画面 uncertain 也是带待核验事项的成员成功，均不按正文长度误判。任何本地准备或后续请求失败时，原媒体入口不返回半成品正文/片段，原生 Diagnostic 与成员错误同时可见，后续成员继续。

固定输入、来源摘要及成员清单见 [zip_media_samples.json](/E:/aaa-project/rag-me/tests/testFile/zip_media_samples.json)。只运行独立 [zip_media_build_samples.py](/E:/aaa-project/rag-me/tests/testFile/zip_media_build_samples.py) 可重建本票 ZIP；测试运行不构造或下载输入。媒体直接复用本仓库固定原创素材，语音为 Microsoft Huihui 合成语音、画面为审批图示；来源、许可、真值见 [media_constructed.json](/E:/aaa-project/rag-me/tests/testFile/media_constructed.json) 和 [video_extra_constructed.json](/E:/aaa-project/rag-me/tests/testFile/video_extra_constructed.json)。延迟视频真值为 1.25–3.25 秒红色、3.25–5.25 秒蓝色，音轨持续 0–6 秒。

默认 [test_zip_media.py](/E:/aaa-project/rag-me/tests/test_zip_media.py) 从 ZIP 文件/字节入口调用真实网络客户端、真实 FFmpeg/FFprobe 和既有本地 HTTP 服务，覆盖八种格式、三任务、真实上传 WAV 时长、延迟画面时间、空/无法确认状态、缺配置、后续片段失败、成员隔离以及 CLI JSON/退出码和临时目录清理。默认测试清除真实 STEP 配置，显式指向本地服务；不会请求收费 API。CLI 子进程使用 sys.executable。

在本票工作树中执行：

```powershell
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m unittest tests.test_zip_media tests.test_zip_media_live -v
```

本票默认测试 10 项通过，live 入口默认跳过。连同 ZIP 基础及既有媒体回归共 66 项，64 通过、2 个 live 跳过。该结果只证明协议与行为契约，不证明真实识别质量。

真实验收入口见 [test_zip_media_live.py](/E:/aaa-project/rag-me/tests/test_zip_media_live.py)，仅供主代理在授权环境执行。本次 worker 未运行真实云端验收。设置 **ZIP_MEDIA_LIVE_TEST=1** 才允许加载 STEP_ENV_FILE 并请求真实 API；ZIP_MEDIA_LIVE_CASE 可为 audio/video/both，不设置则顺序运行全部三任务。audio 使用固定 WAV ZIP，video/both 使用固定审批图示视频 ZIP，均从 ZIP 公开文件入口处理并保留 TXT 兄弟成员。

```powershell
$env:ZIP_MEDIA_LIVE_TEST = '1'
$env:STEP_ENV_FILE = '由主代理指定的环境文件绝对路径'
$env:ZIP_MEDIA_LIVE_CASE = 'both'
$env:ZIP_MEDIA_LIVE_EVIDENCE = 'tests/testFile/zip_media_live_new_both.json'
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m unittest tests.test_zip_media_live -v
```

每次使用新的证据文件名，保留失败记录。证据先写入、再断言自动核验；包括归档及媒体来源摘要、实际逐成员结果、模型、时间范围、耗时、否定/审批分支核验与局限，不保存环境文件位置、配置、URL 或 token。人工需复核实际输出与原始媒体，manual_review 初始为 pending。跳过、调用失败或自动检查失败均不能记为质量通过。
