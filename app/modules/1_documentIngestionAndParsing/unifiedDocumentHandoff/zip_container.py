from dataclasses import asdict
from importlib import import_module

from .models import Diagnostic, HandoffReport, IdAllocator


ZipResult = import_module("..8_zipContainers", __package__).ZipResult


def adapt_zip(
    result: ZipResult, ids: IdAllocator, *, adapt_member,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """成员使用同一静态分派；容器业务身份不传给成员文档。"""
    report = HandoffReport(result.status, metadata={
        "container": {
            "source": result.source, "business_id": business_id, "version": version,
            "error": result.error, "stop_reason": result.stop_reason,
            "counts": result.counts, "total_bytes_read": result.total_bytes_read,
            "requires_review": result.requires_review,
        },
        "members": [],
    })
    for member in result.members:
        record = {
            "source": asdict(member.source), "format": member.format,
            "status": member.status, "result_kind": member.result_kind,
            "error": member.error, "reason": member.reason,
            "bytes_read": member.bytes_read, "document_ids": [],
        }
        report.metadata["members"].append(record)
        if member.result is not None:
            child = adapt_member(member.result, ids)
            report.documents.extend(child.documents)
            report.diagnostics.extend(child.diagnostics)
            record["document_ids"] = [document.id for document in child.documents]
    if result.error is not None:
        report.diagnostics.append(Diagnostic(
            "error", "zip_error", result.error,
            details={"container": result.source, "stop_reason": result.stop_reason},
        ))
    return report
