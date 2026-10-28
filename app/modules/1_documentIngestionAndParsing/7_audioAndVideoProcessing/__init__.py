from hashlib import file_digest, sha256
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from .client import StepFunClient, StepFunConfig, StepFunError, resolve_config
from .media import AUDIO_FORMATS, VIDEO_FORMATS, MediaError, prepare, probe
from .models import ConversionResult, Diagnostic, ProcessingOptions, Segment, Source
from .prompts import VIDEO_PROMPT_VERSION


__all__ = ["convert_file", "convert_bytes", "StepFunConfig", "ProcessingOptions",
           "ConversionResult", "Source", "Segment", "Diagnostic"]


def convert_file(path, *, task=None, format=None, source=None, question=None,
                 media_id=None, media_version=None, config=None, options=None) -> ConversionResult:
    """只读取本地媒体；核心不加载 .env，时间定位始终为真实切片范围。"""
    source_info = Source(source if isinstance(source, str) else None)
    try:
        path = Path(path)
        if source is None:
            source_info.location = str(path)
        options = _validate(source_info, path.suffix if format is None else format,
                            task, question, media_id, media_version, options)
    except (TypeError, ValueError) as exc:
        return ConversionResult(None, source_info, task, error=Diagnostic("invalid_options", str(exc)))
    result = ConversionResult(None, source_info, task, question=question)
    try:
        with path.open("rb") as handle:
            source_info.sha256 = file_digest(handle, "sha256").hexdigest()
    except OSError:
        result.error = Diagnostic("file_read_error", "Could not read input media", "input")
        return result
    return _process(path, result, config, options)


def convert_bytes(data, *, format, source, task=None, question=None,
                  media_id=None, media_version=None, config=None, options=None) -> ConversionResult:
    source_info = Source(source if isinstance(source, str) else None)
    try:
        options = _validate(source_info, format, task, question, media_id, media_version, options)
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except (TypeError, ValueError) as exc:
        return ConversionResult(None, source_info, task, error=Diagnostic("invalid_options", str(exc)))
    result = ConversionResult(None, source_info, task, question=question)
    source_info.sha256 = sha256(data).hexdigest()
    try:
        with TemporaryDirectory(prefix="rag-media-input-") as directory:
            path = Path(directory) / ("input." + source_info.format)
            path.write_bytes(data)
            return _process(path, result, config, options)
    except OSError:
        result.error = Diagnostic("media_io_error", "Could not prepare temporary input media", "input")
        return result


def _process(path, result, config, options):
    stage, start = "probe", None
    try:
        info = probe(path, result.source.format, options)
        result.source.duration_seconds = info.duration
        result.source.media_type = "video" if info.video_stream is not None else "audio"
        wants_audio = result.task in ("transcribe", "both")
        wants_video = result.task in ("video", "both")
        if result.source.format in AUDIO_FORMATS and info.video_stream is not None:
            raise MediaError("format_mismatch", "Audio input contains a video stream")
        if result.source.format in VIDEO_FORMATS and info.video_stream is None:
            raise MediaError("missing_video", "Video input has no usable video stream")
        if wants_audio and info.audio_stream is None:
            raise MediaError("missing_audio", "Selected task requires an audio stream")
        result.source.audio_stream_index = info.audio_stream if wants_audio else None
        stage = "config"
        config = resolve_config(config, result.task)
        client = StepFunClient(config)
        segments = []
        with TemporaryDirectory(prefix="rag-media-") as directory:
            stage = "prepare"
            clips = []
            for kind, enabled in (("audio", wants_audio), ("video", wants_video)):
                if enabled:
                    clips.extend(prepare(path, Path(directory), kind, info, options))
            clips.sort(key=lambda clip: (clip.start, clip.kind))
            for clip in clips:
                stage, start = clip.kind, clip.start
                if clip.kind == "audio":
                    text = client.transcribe(clip.path)
                    segments.append(Segment("audio", clip.start, clip.end, text,
                                            "content" if text.strip() else "no_text", config.asr_model))
                else:
                    text, status, notes, response_model = client.video(clip.path, result.question)
                    segments.append(Segment("video", clip.start, clip.end, text, status,
                                            config.video_model, response_model,
                                            VIDEO_PROMPT_VERSION, review_notes=notes))
                clip.path.unlink()
    except (MediaError, StepFunError) as exc:
        result.error = Diagnostic(exc.code, str(exc), stage, start, getattr(exc, "http_status", None))
        return result
    except OSError:
        result.error = Diagnostic("media_io_error", "Could not read or write temporary media", stage, start)
        return result
    result.segments = segments
    result.status = ("uncertain" if any(s.status == "uncertain" for s in segments) else
                     "no_text" if all(s.status == "no_text" for s in segments) else "content")
    result.text = "\n\n".join(
        f"[{s.start_seconds:.3f}–{s.end_seconds:.3f} 秒 · "
        f"{'语音转写' if s.kind == 'audio' else '画面信息'}]\n{s.text}"
        for s in segments if s.text.strip())
    result.review_issues = ["媒体派生文字尚待对照同一版本原音视频核验。",
                            "时间仅定位实际处理片段，不是逐句或逐词时间。"]
    if wants_audio:
        result.warnings.append("同步 ASR 不提供说话人区分；speaker 保持未知。")
    if any(s.status == "no_text" for s in segments):
        result.warnings.append("部分或全部片段未取得可用转写，不证明原媒体没有语音。")
    if wants_video:
        result.warnings.append("视频模型可能遗漏短暂画面或动作；画面解释不能替代原视频证据。")
    return result


def _validate(source, format, task, question, media_id, media_version, options):
    if not isinstance(source.location, str) or not source.location.strip():
        raise ValueError("source must be a nonempty string")
    if not isinstance(format, str):
        raise ValueError("format must be a supported media format")
    format = format.lower().strip().lstrip(".")
    if format not in AUDIO_FORMATS | VIDEO_FORMATS:
        raise ValueError("Supported formats: wav, mp3, m4a, ogg, flac, mp4, mov, mkv")
    source.format = format
    if task not in ("transcribe", "video", "both"):
        raise ValueError("task must explicitly select transcribe, video, or both")
    if format in AUDIO_FORMATS and task != "transcribe":
        raise ValueError("Audio files only support transcribe")
    if question is not None and (task == "transcribe" or not isinstance(question, str) or not question.strip()):
        raise ValueError("A nonempty question is only accepted for video or both")
    for name, value in (("media_id", media_id), ("media_version", media_version)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{name} must be nonempty when provided")
    source.media_id, source.media_version = media_id, media_version
    options = ProcessingOptions() if options is None else options
    if not isinstance(options, ProcessingOptions):
        raise ValueError("options must be ProcessingOptions")
    for name in ("audio_segment_seconds", "video_segment_seconds", "media_timeout"):
        value = getattr(options, name)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    for name in ("ffmpeg", "ffprobe"):
        if not isinstance(getattr(options, name), str) or not getattr(options, name).strip():
            raise ValueError(f"{name} must name an executable")
    return options
