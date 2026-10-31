# 音视频处理

本模块将本地媒体交给阶跃 ASR／原生视频 API，输出媒体派生文字和可回查的片段级时间定位。模型计算在云端，本机仅用 FFmpeg/FFprobe 探测、提取音轨、切片及复制视频码流。

规格与事项：[规格 #33](https://github.com/yb2915722928-cpu/rag_me/issues/33)、[音频 #34](https://github.com/yb2915722928-cpu/rag_me/issues/34)、[视频 #35](https://github.com/yb2915722928-cpu/rag_me/issues/35)、[联合处理 #36](https://github.com/yb2915722928-cpu/rag_me/issues/36)。

正式 Python 包为 `app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding`。旧包 `app.modules.1_documentIngestionAndParsing.7_audioAndVideoProcessing` 与其 `models`、`client`、`media`、`prompts`、`assembly` 子模块继续兼容，公开函数、结果类型、配置类型与错误类型共用同一实现。旧 `__main__` 转发到同一 CLI，两个包的 `python -m` 命令均保留退出码和 JSON 契约，不产生迁移警告。

## 运行

使用项目现有 Python 环境与依赖，并保证 FFmpeg、FFprobe 在 PATH 中。无需 GPU 或本地模型。凭据继续保存在本地环境文件，模板为[环境示例](../../../../.env.example)。

| 变量 | 用途 |
| --- | --- |
| STEP_API_KEY | 现有阶跃 API 凭据 |
| STEP_BASE_URL | API 基址，例如 https://api.stepfun.com/v1 |
| STEP_ASR_MODEL | ASR 模型，未设置时使用 stepaudio-2.5-asr |
| STEP_MODEL | 视频理解模型，当前验收使用 step-5-preview |

从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding tests/testFile/media_rules.wav --task transcribe --env-file .env

.\.venv\Scripts\python.exe -m app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding tests/testFile/media_rules.mp4 --task both --env-file .env --question "分别说明两条审批分支的条件与审批人。"
```

CLI 输出 UTF-8 JSON。正常完成退出 0，处理失败退出 1；参数缺失由 argparse 处理。可用 `--audio-seconds`、`--video-seconds` 调整目标切片时长，默认分别为 30、60 秒；`--timeout` 为每次 API 请求超时，默认 180 秒。

## Python 入口

[公开文件与字节入口](__init__.py)使用同一契约，核心不搜索或加载环境文件。

```python
from importlib import import_module
from dotenv import load_dotenv

load_dotenv(dotenv_path="E:/aaa-project/rag-me/.env", override=False)
media = import_module(
    "app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding"
)
result = media.convert_file(
    "tests/testFile/media_rules.mp4",
    task="both",
    question="超过一万元和其他情况分别由谁审批？",
    media_id="training", media_version="v1",
    options=media.ProcessingOptions(audio_segment_seconds=30, video_segment_seconds=60),
)
if result.success:
    print(result.text)
    for segment in result.segments:
        print(segment.kind, segment.start_seconds, segment.end_seconds, segment.text)
else:
    print(result.error)
```

已取得的字节可传给 `convert_bytes(data, format="mp4", source="training-v1", task="both")`。显式配置采用 `StepFunConfig(api_key=..., base_url=..., asr_model=..., video_model=...)`；未提供的字段按所选任务从进程环境读取。API key 不出现在配置的 repr 或结果中。

| task | 输入 | API 调用 |
| --- | --- | --- |
| transcribe | 音频或带音轨视频 | 仅同步 ASR |
| video | 视频，可无音轨 | 仅原生视频理解 |
| both | 带音轨视频 | ASR 与视频理解，逐片串行 |

视频任务可选非空问题；没有问题时概括可见画面。纯转写不接受问题。音频支持 WAV、MP3、M4A、OGG、FLAC；视频支持可复制码流封装为 MP4 的 MP4、MOV、MKV。不能封装的编码需调用方预先转码，模块会明确报错，不自动进行整片重编码。

单独任务的输入和定位说明见[音频转写](AUDIO.md)与[视频理解](VIDEO.md)。

## 结果与边界

[结果模型](models.py)分别保存整份派生文字、片段列表、来源、警告、待核验事项和错误：

- `source.sha256` 对应原始媒体字节；文件入口流式计算摘要。业务媒体标识、版本与文件来源分别保留，未知值不猜补。
- `segments` 按原时间起点和类型排列，`audio` 为语音转写，`video` 为画面信息；每段保存请求模型、可知的响应模型及视频提示词版本。
- 时间单位为从原媒体播放起点计算的秒，范围左闭右开。`time_precision="segment"` 仅代表实际切片范围；关键帧切点可能晚于目标时长，没有逐句／逐词对齐。
- `speaker=None` 表示未知，同步 ASR 不提供说话人区分。系统不根据文字猜讲师、学员或其他身份。
- `status="no_text"` 为正常空转写，`uncertain` 为画面关系无法确认。两者都保留待核验，不代表原媒体没有语音或答案已可靠。
- 全部模型产出均需对照原媒体核验。问题与回答不自动归纳为制度规则；画面解释不冒充原话。
- 任一必需片段失败时，整份结果的文字为 None、片段为空，错误保留阶段和可知时间位置，已知输入来源仍在。API 请求不自动重试；重新运行需要调用方决定。

[媒体准备](media.py)使用临时文件，完成后清理。单片音频小于 100 MB、视频小于 128 MB；超过限制会提示缩短目标片段。关键帧间隔过长时，仅缩短目标值可能仍无法减小视频片段，需预先转码或调整原素材。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_audio_video tests.testFile.test_media_compatibility -v

$env:STEP_MEDIA_LIVE_TEST = '1'
$env:STEP_ENV_FILE = 'E:\aaa-project\rag-me\.env'
$env:STEP_MEDIA_LIVE_EVIDENCE = 'tests/testFile/media_live_new_run.json'
.\.venv\Scripts\python.exe -m unittest tests.test_audio_video_live -v
```

真实验收要求新的证据文件名，可用 STEP_MEDIA_LIVE_CASE 选择 audio、both、uncertain 中的一项。默认测试使用本地 HTTP 服务，不消耗外部 API。固定响应验证协议，真实 API 运行才用于核验识别内容；已有证据、首次连接失败及最终结果见[验证记录](../7_audioAndVideoProcessing/VALIDATION.md)。

模块止于媒体处理与表示，不承担媒体托管、最终切块、索引、召回、问答或播放器。调用方负责保存可回查的同版本原媒体。
