from importlib import import_module

from ..format_routes import FORMAT_ROUTES
from .models import ZipLimits


class UnsupportedFormat(ValueError):
    pass


def convert_member(data: bytes, *, format: str, source: str, parser_options: dict,
                   limits: ZipLimits, deadline: float):
    """共享格式路由；ZIP 类别选项与预算仍只交给所选原生入口。"""
    route = FORMAT_ROUTES.get(format)
    if route is None or route.zip_member_module is None:
        raise UnsupportedFormat(f"Unsupported format: {format or '(no suffix)'}")
    parser = import_module(".." + route.zip_member_module, __package__)
    kind = route.zip_kind
    options = {"format": format, "source": source}
    if kind in ("document", "image"):
        options["limits"] = limits
    if kind == "document":
        options["deadline"] = deadline
    return kind, parser.convert_bytes(data, **options, **parser_options.get(kind, {}))
