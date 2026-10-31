from collections.abc import Mapping
from importlib import import_module


media = import_module("..audioTranscriptionAndVideoUnderstanding", __package__)


def convert_bytes(data, *, format, source, task=None, question=None, config=None, options=None,
                  media_id=None, media_version=None):
    """只将 ZIP/CLI 的映射选项转为既有类型，媒体准备和 API 仍由原字节入口完成。"""
    try:
        if task in ("video", "both") and question is None:
            raise ValueError("question must explicitly describe the video task")
        config = media.StepFunConfig(**config) if isinstance(config, Mapping) else config
        options = media.ProcessingOptions(**options) if isinstance(options, Mapping) else options
    except ValueError as exc:
        return media.ConversionResult(
            None, media.Source(source, format=format), task, question=question,
            error=media.Diagnostic("invalid_options", str(exc)))
    except TypeError:
        return media.ConversionResult(
            None, media.Source(source, format=format), task, question=question,
            error=media.Diagnostic("invalid_options", "Unknown media config or processing option"))
    return media.convert_bytes(
        data, format=format, source=source, task=task, question=question,
        config=config, options=options, media_id=media_id, media_version=media_version)
