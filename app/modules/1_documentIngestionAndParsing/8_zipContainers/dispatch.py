from importlib import import_module

from .models import ZipLimits


class UnsupportedFormat(ValueError):
    pass


def convert_member(data: bytes, *, format: str, source: str, parser_options: dict,
                   limits: ZipLimits, deadline: float):
    """类别选项只在此处分派，原生解析器继续负责自己的格式与选项约束。"""
    if format in ("txt", "md", "markdown"):
        parser = import_module("..2_textAndWebContent", __package__)
        return "text", parser.convert_bytes(
            data, format=format, source=source, **parser_options.get("text", {}),
        )
    if format in ("json", "xml"):
        parser = import_module("..5_presentationsAndStructuredDocuments", __package__)
        return "structured", parser.convert_bytes(
            data, format=format, source=source, **parser_options.get("structured", {}),
        )
    if format == "csv":
        parser = import_module("..4_tabularFileProcessing", __package__)
        return "csv", parser.convert_bytes(
            data, format=format, source=source, **parser_options.get("csv", {}),
        )
    if format in ("pdf", "docx", "pptx", "xlsx", "html", "htm", "mhtml", "mht"):
        parser = import_module(".document_api", __package__)
        return "document", parser.convert_bytes(
            data, format=format, source=source, limits=limits, deadline=deadline,
            **parser_options.get("document", {}),
        )
    if format in ("png", "jpg", "jpeg", "webp"):
        parser = import_module(".image_api", __package__)
        return "image", parser.convert_bytes(
            data, format=format, source=source, limits=limits, **parser_options.get("image", {}),
        )
    if format in ("wav", "mp3", "m4a", "ogg", "flac", "mp4", "mov", "mkv"):
        parser = import_module(".media_api", __package__)
        return "media", parser.convert_bytes(
            data, format=format, source=source, **parser_options.get("media", {}),
        )
    raise UnsupportedFormat(f"Unsupported format: {format or '(no suffix)'}")
