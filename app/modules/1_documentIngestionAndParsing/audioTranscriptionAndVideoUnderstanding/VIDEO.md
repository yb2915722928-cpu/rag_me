# 视频理解（#35）

通过[公开文件／字节入口](__init__.py)显式选择 `task="video"`，仅提交画面任务，无音轨也可处理。支持能够复制视频码流封装成 MP4 的 MP4、MOV、MKV。FFmpeg 只做本地探测、切片和封装；不自动重编码，不运行本地视觉模型。

`question` 可省略以概括画面；提供时必须为非空字符串，原问题保留在结果中。具体问题要求模型保留金额、否定、条件、箭头与节点对应。画面缺失、截断或关系不清晰时，正常结果使用 `status="uncertain"`，保留可知内容、无法确认的关系和原因。提示词与结构化约束见 [prompts.py](prompts.py)，当前版本为 `video-v1`。

## 运行示例

使用项目现有 Python 与已有依赖，运行说明见[项目说明](../../../../README.md)；FFmpeg/FFprobe 需在 PATH 中。配置变量为 STEP_API_KEY、STEP_BASE_URL、STEP_MODEL；核心只读取显式配置或进程环境，不搜索环境文件。视频任务不要求 ASR 配置。

```python
from importlib import import_module

media = import_module("app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding")
result = media.convert_file(
    "tests/testFile/media_uncertain.mp4",
    source="training/approval.mp4",
    task="video",
    question="分别说明两条审批分支的条件与审批人；依据不足时说明原因。",
    media_id="approval-training",
    media_version="v1",
    options=media.ProcessingOptions(video_segment_seconds=60),
)
if result.success:
    print(result.status, result.text, result.requires_review)
else:
    print(result.error.code, result.error.stage, result.error.start_seconds)
```

字节入口使用同一结果契约：

```python
result = media.convert_bytes(
    video_bytes, format="mp4", source="upload/approval.mp4", task="video",
    question="分别说明两条审批分支的条件与审批人。",
    media_id="approval-training", media_version="v1",
)
```

命令行显式加载指定环境文件，不覆盖已有进程变量。以下命令从仓库根目录运行，会调用真实视频 API：

```powershell
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m app.modules.1_documentIngestionAndParsing.audioTranscriptionAndVideoUnderstanding `
  tests/testFile/media_uncertain.mp4 --task video --video-seconds 60 `
  --question '分别说明两条审批分支的条件与审批人；依据不足时说明原因。' `
  --env-file E:\aaa-project\rag-me\.env
```

省略 `--question` 即为画面概括。输出为 UTF-8 JSON，正常完成（包括 uncertain）退出 0，处理失败退出 1。需要语音时选 `transcribe` 或 `both`，详见[模块说明](README.md)。

## 来源与真实时间

[结果模型](models.py)保留输入位置、原始字节 SHA-256、媒体时长、可选业务标识与版本、原问题，以及每段请求模型、实际响应模型和提示词版本。画面片段标记 `kind="video"`，正文标注“画面信息”，不冒充 ASR 原话。结果始终待核验，`success=True` 不表示内容已经正确。

时间单位为从原媒体播放起点计算的秒，范围左闭右开，`time_precision="segment"`。目标时长只控制期望切点，实际边界受关键帧约束。例如目标为 2 秒、关键帧间隔 3 秒时，6 秒素材实际分成 [0,3)、[3,6)，不能标成均匀的 2 秒片段。模型内部可能漏掉短暂画面；片段范围不代表逐帧、逐句或逐词精度。

[媒体准备](media.py)保留原时间偏移，并将非零容器起点归一到播放起点。FFmpeg 的片段清单首段默认从零计数；视频晚于音轨出现时，首段来源起点采用视频流的实际时间。例如容器时长 6 秒、画面 1.25 秒才出现并在 5.25 秒结束时，两个画面片段为 [1.25,3.25)、[3.25,5.25)，不会把开头或尾部只有音轨的区间算作画面证据。

MKV 在缺少流时长时需要单独解释容器时长：FFmpeg 的 Matroska 封装器按最大包结束时间写入 duration，读取器直接披露该值。容器起于 5.125 秒、结束于 11.125 秒的固定样本，来源播放时长为 6 秒。实现只在 Matroska 的该回退路径扣除容器起点，不改变已有流时长的计算。依据为 [FFmpeg Matroska 封装实现](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/matroskaenc.c)和[读取实现](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/matroskadec.c)；[官方切片说明](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment)解释了关键帧切点限制。

每片通过原生内联视频串行提交，无公网托管或抽帧路线。片段超限返回独立诊断；关键帧间隔很长时，缩短目标时长仍可能无法减小片段，需要调用方预先处理原视频。

## 验证与限制

[补充契约测试](../../../../tests/test_video_contract_extra.py)使用公开入口、真实 FFmpeg/FFprobe 与本地 HTTP 服务。固定媒体及大小、摘要、构造方式见[样本清单](../../../../tests/testFile/video_extra_constructed.json)，重建入口为[生成器](../../../../tests/testFile/video_extra_build_samples.py)；默认测试不重建样本。

| 固定场景 | 可观察验收 |
| --- | --- |
| 首帧延迟 1.25 秒，含 B 帧和静音音轨 | 文件／字节结果相同；两个片段精确关联 [1.25,3.25)、[3.25,5.25)，解码实际上传片段后各有 40 帧，分别为红色与蓝色 |
| MKV 容器起点 5.125 秒 | 播放时长为 6 秒，目标 2 秒时仍按实际关键帧关联 [0,3)、[3,6) |
| 无法封装为 MP4 的 Huffyuv MKV | 准备阶段明确失败，不发 API 请求，保留原始摘要，无伪成功正文或片段 |
| 第二个视频片段 HTTP 503 | 标出实际失败起点 3.25 秒；保留问题和业务来源，整份正文为空、片段为空 |

首帧延迟与非零 MKV 时长各自先在基线复现断言失败，再做最小修复通过。原有[B 帧与多容器测试](../../../../tests/test_audio_video.py)继续覆盖目标 2 秒、实际 3 秒关键帧以及容器起点 5 秒，未重写基础实现。

```powershell
& E:\aaa-project\rag-me\.venv\Scripts\python.exe -m unittest tests.test_audio_video tests.test_video_contract_extra -v
```

本地固定响应只验证协议与媒体来源关系。真实模型验收由集成分支单独执行，证据保持原样：

- [关系不完整视频](../../../../tests/testFile/media_live_video_check.json)：原生视频 API 返回 uncertain，指出缺少终点及审批人，保留可见条件和具体原因，定向检查通过。
- [清晰审批图联合运行](../../../../tests/testFile/media_live_combined_check.json)：实际画面输出保留“超过 1 万元→负责人审批”“其他情况→财务审批”。历史检查未忽略数字间空白而误判失败；[同一响应复核](../../../../tests/testFile/media_live_combined_revalidated.json)已修正检查并通过，历史证据原样保留，详见[验证说明](../7_audioAndVideoProcessing/VALIDATION.md)。

当前网络存在间歇 TLS 中断，失败返回 network_error；上述有限样本不能证明服务稳定或任意动态视频均准确。重新运行、原媒体保存与人工内容核验由调用方决定。此补充实现不执行外部模型调用，也不覆盖已有运行证据。
