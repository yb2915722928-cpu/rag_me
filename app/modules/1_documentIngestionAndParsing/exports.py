"""UTF-8 report and Markdown exports, independent of parser orchestration."""

import json
from pathlib import Path


def export_json(report, path) -> Path:
    """包括失败报告在内均可导出；写入异常按普通 I/O 错误向调用方传播。"""
    data = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    path = Path(path)
    path.write_bytes((data + "\n").encode("utf-8"))
    return path


def export_markdown(result, path) -> Path:
    if not result.success:
        raise ValueError(f"Cannot export failed conversion: {result.error}")
    path = Path(path)
    path.write_bytes(result.markdown.encode("utf-8"))
    return path
