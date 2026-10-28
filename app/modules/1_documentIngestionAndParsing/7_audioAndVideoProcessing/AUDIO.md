# 音频转写（#34）

[事项 #34](https://github.com/yb2915722928-cpu/rag_me/issues/34)的音频入口使用阶跃同步 ASR。支持 WAV、MP3、M4A、OGG、FLAC；实际容器、音轨和时长由 FFprobe 检查。完整模块用法见 [README](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/7_audioAndVideoProcessing/README.md)，需求依据见[规格](/E:/aaa-project/rag-me/docs/specs/audio-and-video-processing.md)。

## 运行

在仓库或工作树根目录，使用项目现有 Python 依赖，并确保 FFmpeg/FFprobe 在 PATH 中：

```powershell
& 'E:\aaa-project\rag-me\.venv\Scripts\python.exe' -m app.modules.1_documentIngestionAndParsing.7_audioAndVideoProcessing tests/testFile/media_rules.wav --task transcribe --env-file '<本地配置文件>' --audio-seconds 30
```

将配置文件占位符替换为本地路径。CLI 显式加载指定文件，已有进程变量优先；成功退出 0、处理失败退出 1，并输出 UTF-8 JSON。纯音频任务为 `transcribe`，不接受画面问题。

| 进程变量 | 行为 |
| --- | --- |
| STEP_API_KEY | 阶跃凭据，必需 |
| STEP_BASE_URL | API 基址，必需；例如 https://api.stepfun.com/v1 |
| STEP_ASR_MODEL | 独立 ASR 模型；未设置时为 stepaudio-2.5-asr |
| STEP_MODEL | 音频转写不使用此视觉模型变量 |

[公开文件／字节入口](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/7_audioAndVideoProcessing/__init__.py)只读取显式配置或进程环境，不搜索环境文件。以下示例在调用方已经设置好环境变量后运行：

```python
from dataclasses import asdict
from importlib import import_module
import json
from pathlib import Path

media = import_module("app.modules.1_documentIngestionAndParsing.7_audioAndVideoProcessing")
path = Path("tests/testFile/media_rules.wav")
kwargs = dict(
    task="transcribe", source="training-recording",
    media_id="training", media_version="v1",
    config=media.StepFunConfig(asr_model="stepaudio-2.5-asr"),
    options=media.ProcessingOptions(audio_segment_seconds=30),
)
file_result = media.convert_file(path, **kwargs)
byte_result = media.convert_bytes(path.read_bytes(), format="wav", **kwargs)
print(json.dumps(asdict(file_result), ensure_ascii=False, indent=2))
```

显式 `StepFunConfig` 字段优先于同名进程变量。文件入口允许 `path` 为 Path；`source` 必须是非空字符串或省略。省略时来源为输入路径。字节入口必须提供 `bytes`、格式和非空字符串来源；相同来源、输入字节、选项及 API 响应下，两入口返回同一结果契约。文件入口可显式覆盖后缀格式，但仍检查实际容器。

## 结果与边界

- 原音轨转为单声道、16 kHz、16 bit PCM WAV，默认按 30 秒目标时长切片，逐片串行请求。选择首个音轨，不因后续音轨具有默认标记而切换或混合音轨；结果记录所选音轨编号。
- 时间以原媒体播放起点为零，单位为秒，范围左闭右开；非零容器起点归一化。边界来自真实切片，末段止于实际结束；`time_precision="segment"`，不提供逐句或逐词时间。
- `source.sha256` 是原始输入字节的摘要；文件入口流式计算。它不对应转码后的 WAV 或转写文字。来源名相同也可能有不同摘要；未传业务标识与版本时保留 None，不从文件名猜补。
- `speaker=None`，同步 ASR 不区分说话人，也不根据问句或文字猜身份。结果中的请求模型与无法取得的响应模型分别记录。
- 正文、来源、待核验事项、警告与错误分别表达。所有模型文字仍需回听同版本原媒体；正常空转写为 `no_text`，仍有待核验事项，不证明原媒体没有语音。
- 失败时正文为 None、片段为空；已知来源和独立诊断保留。工具缺失、媒体准备错误、缺配置、鉴权、限流、超时、无效响应及中途片段失败不会变成完整成功。诊断可包含阶段和失败片段起点。
- 成功、探测失败、准备失败及中途 API 失败后均清理临时输入、切片和清单。调用方仍负责保存原媒体供回查。
- 非字符串 `source` 返回 `invalid_options`，失败来源保持 None，能够通过 `json.dumps(asdict(result))` 序列化。

## 验收记录

从工作树根目录运行默认离线测试：

```powershell
& 'E:\aaa-project\rag-me\.venv\Scripts\python.exe' -m unittest tests.test_audio_video tests.test_audio_contract_extra -v
```

基线 18 项与[补充契约测试](/E:/aaa-project/rag-me/tests/test_audio_contract_extra.py)7 项共 25 项通过。测试使用真实 FFmpeg/FFprobe、HTTP 客户端与本地 HTTP 服务；固定响应只证明协议和结果契约。

补充验收覆盖实际上传的首音轨波形、5 秒容器起点归一化、多个切片的完整 PCM 和实际范围、文件／字节入口的成功与失败等价、临时残留、原始字节版本、压缩格式正常空转写，以及运行时／显式 ASR 配置优先级。

唯一新增业务修复是文件入口的无效来源处理：先加入公开入口回归测试，复现 Path 导致 JSON 序列化报错、整数残留在来源字段；随后仅调整来源赋值，两入口均返回可序列化的失败结果。其余补充行为在已有实现上通过，未重写媒体准备或 HTTP 客户端。

[补充样本清单](/E:/aaa-project/rag-me/tests/testFile/audio_extra_samples.json)记录来源、大小、SHA-256、FFmpeg 版本及已知音轨频率；[生成器](/E:/aaa-project/rag-me/tests/testFile/audio_extra_build_samples.py)只在显式重建时运行。样本为本地构造的双音轨 M4A，不包含语音，不用于证明 ASR 质量；测试期间不重建或下载样本。

主代理在 2026-10-28 的[真实音频证据](/E:/aaa-project/rag-me/tests/testFile/media_live_audio_check.json)记录 stepaudio-2.5-asr 成功转写固定中文合成语音，金额条件、问句上下文、否定与另一审批分支、禁止付款及未知说话人检查均通过。输入摘要对应[原始固定样本清单](/E:/aaa-project/rag-me/tests/testFile/media_constructed.json)，实际处理范围为 0–15.02425 秒。本轮补充实现未重跑外部模型；完整真实运行过程与连接情况沿用主代理的[验证记录](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/7_audioAndVideoProcessing/VALIDATION.md)。有限固定样本通过不代表任意录音均准确。
