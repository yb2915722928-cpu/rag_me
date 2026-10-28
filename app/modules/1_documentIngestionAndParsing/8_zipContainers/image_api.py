from importlib import import_module


def convert_bytes(data, *, format, source, limits, task=None, question=None, config=None,
                  document=None, crop=None, is_cropped=False, **unknown_options):
    """复用图片入口；未知选项诊断不回显参数名，以免字符串凭据进入成员报告。"""
    parser = import_module("..6_imageProcessing", __package__)
    if unknown_options:
        return parser.ConversionResult(
            None, parser.Source(source), task,
            error=parser.Diagnostic("invalid_options", "Unsupported image options"),
        )
    return parser.convert_bytes(
        data, format=format, source=source, task=task, question=question, config=config,
        document=document, crop=crop, is_cropped=is_cropped,
    )
