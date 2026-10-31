# 联合处理：#36 验收补充

[事项 #36](https://github.com/yb2915722928-cpu/rag_me/issues/36) 的联合处理已由现有实现支持。本轮补齐 5 项公开入口验收测试，逐项运行均通过；未发现需要修正的行为，因此未修改生产代码，也未人为制造红测。复用既有固定样本和本地 HTTP 服务，不增加媒体样本或外部 API 调用。

## 使用与结果契约

[文件／字节入口](__init__.py)和 [CLI](__main__.py)必须显式选择任务：

| task | 输入 | 处理 |
| --- | --- | --- |
| transcribe | 音频或带音轨视频 | 仅语音转写；不接受画面问题 |
| video | 视频，可无音轨 | 仅画面信息；不调用 ASR |
| both | 带音轨视频 | 语音与画面分别处理；缺少音轨明确失败 |

调用方可将已准备好的显式配置 `config` 同时用于两个入口：

```python
from importlib import import_module
from pathlib import Path

media = import_module("app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding")
path = Path("tests/testFile/media_rules.mp4")
kwargs = dict(
    task="both", source="training:combined", question="两个条件分支分别由谁审批？",
    media_id="training", media_version="v2", config=config,
    options=media.ProcessingOptions(audio_segment_seconds=5, video_segment_seconds=6),
)
file_result = media.convert_file(path, **kwargs)
byte_result = media.convert_bytes(path.read_bytes(), format="mp4", **kwargs)
```

相同原始字节、来源及选项在固定 API 响应下得到相同结果。来源保留原媒体 SHA-256、业务标识与版本、时长及首个音轨索引；未知业务版本保持未知。配置变量、运行前提与完整命令示例沿用[使用说明](README.md)。

联合 CLI 在原有命令中选择 `--task both`，通过 `--question` 传入画面问题，用 `--audio-seconds`、`--video-seconds` 分别指定目标片长；`--timeout` 控制单次 API 请求。`--env-file` 必须显式指定，已有进程变量优先。ASR 使用 `STEP_ASR_MODEL`，画面使用 `STEP_MODEL`，两者独立。正常完成输出 JSON 并退出 0，处理失败输出失败 JSON 并退出 1。

语音与画面片段按原播放起点的秒数排列；同起点时语音在前。两种片长可以不同，不强行切成一一对应的片段，也不把画面解释并入语音原话。视频复制码流可能在关键帧处切分，必须读取实际范围；音轨和视频的末端也可以不同。

每段独立保留内容类型、真实范围、状态、请求模型及可知响应模型；视频还保留提示词版本和具体不确定性。结果整体保留待核验事项和警告。正常空转写保留 `no_text`，有画面内容时联合状态仍可为 `content`；全部派生文字仍需对照原媒体核验。说话人保持未知，时间精度仅为片段级。

任一必需片段失败，整份结果的 `text` 为 `None`、`segments` 为空、状态为 `failed`；已完成的语音或画面不会作为部分成功返回。错误保留阶段、可知起点和 HTTP 状态，已取得的原始来源与问题仍保留。

## 新增默认验收

[联合处理补充测试](../../../../tests/test_media_combined_extra.py)只经公开文件／字节入口或实际 CLI 子进程运行，使用真实 FFmpeg/FFprobe、真实 HTTP 客户端和本地服务；不替换内部协作者。

| 验收项 | 独立判据 |
| --- | --- |
| 两者模式文件／字节一致 | 同来源和业务版本下完整结果一致；原媒体摘要、语音原稿、画面内容、模型、提示词版本与待核验状态分别保留 |
| 两种切片长度与延迟画面 | 音轨目标 2.5 秒、画面目标 2 秒；音轨累计 96,000 个 16 kHz 样本，定位止于 6 秒；视频真实范围为 [1.25,3.25)、[3.25,5.25)，上传首帧分别为红、蓝；联合顺序为语音、画面、语音、画面、语音 |
| 先取得语音，后续画面失败 | 第四次请求在视频 3.25 秒处返回 HTTP 503；此前语音和画面已成功，文件／字节入口仍一致返回无正文、无部分片段的失败及原来源 |
| 联合 CLI 的问题及配置传递 | 实际 HTTP 请求包含问题；ASR 模型从指定临时配置文件读取，视频模型及凭据采用已有进程变量；两个片长分别生效，成功退出 0 |
| 联合 CLI 的超时与失败结果 | 本地服务延迟 0.15 秒、CLI 超时 0.03 秒；首个语音请求失败后不继续画面任务，退出 1，JSON 无部分内容并保留来源 |

时间真值来自既有[延迟画面样本清单](../../../../tests/testFile/video_extra_constructed.json)和实际上传的 WAV 样本数、解码像素；金额与问答原稿来自[媒体清单](../../../../tests/testFile/media_constructed.json)，不使用模型输出建立真值。

非零容器起点、首个音轨选择、仅语音／仅画面的模式隔离、缺少音轨及其他媒体／协议错误，继续由[基础测试](../../../../tests/test_audio_video.py)、[音频补充测试](../../../../tests/test_audio_contract_extra.py)、[视频补充测试](../../../../tests/test_video_contract_extra.py)覆盖，不重复枚举。

从工作树根目录运行：

```powershell
& 'E:\aaa-project\rag-me\.venv\Scripts\python.exe' -m unittest tests.test_audio_video tests.test_audio_contract_extra tests.test_video_contract_extra tests.test_media_combined_extra -v
```

2026-10-28 上述 35 项测试全部通过，其中本轮新增 5 项。

## 联合真实 API 证据

集成提交 `330889d` 新增的[联合完整运行证据](../../../../tests/testFile/media_live_combined_verified.json)记录了一次重新执行并完整通过的联合调用，不是仅对历史响应复核。本轮读取该证据，没有再次执行外部调用。

- 输入原始 SHA-256：`c54cbbc7b370fec4a656184987e45fec784fe4f46190c396681e2657f13d4d78`。
- ASR：`stepaudio-2.5-asr`；视频请求及响应模型：`step-5-preview`；视频提示词：`video-v1`。耗时 24.125 秒。
- 转写保留一万元条件、问句、“不是，其他由财务审批”和“未经批准不得付款”；画面分别保留“超过 1 万元→负责人”“其他情况→财务”。记录的质量检查全部通过。
- 语音定位为 [0,15.023991) 秒，画面为 [0,15) 秒；未知说话人、片段级时间和待核验事项保留。

既有[验证记录](../7_audioAndVideoProcessing/VALIDATION.md)继续保留历史响应、网络失败及局限。语音为合成样本；其中空间指代与画面位置的差异仍需人工核验，联合输出不会自动消解这一差异。网络可能间歇性 TLS 中断，本模块无自动重试。

验收仅说明这些固定短样本上的媒体准备、API 协议和派生内容来源关系成立；不证明任意媒体均准确，也不代表切块、入库、索引、检索或完整问答链路已经实现。
