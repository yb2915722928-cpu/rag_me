from dataclasses import asdict
from importlib import import_module

from .models import ContentUnit, Diagnostic, Document, HandoffReport, IdAllocator, Source


ImageResult = import_module("..6_imageProcessing", __package__).ConversionResult
MediaResult = import_module("..7_audioAndVideoProcessing", __package__).ConversionResult


def adapt_image(
    result: ImageResult, ids: IdAllocator, *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """整图派生文字没有原图字框或正文字符映射；裁剪来源仅保留已知事实。"""
    source = Source(ids.new_id("source"), "image", asdict(result.source))
    document = Document(
        ids.new_id("document"), result.text, "text", result.status,
        business_id=business_id, version=version, sources=[source], requires_review=result.requires_review,
        metadata={
            "task": result.task, "question": result.question,
            "requested_model": result.requested_model, "response_model": result.response_model,
            "prompt_version": result.prompt_version,
        },
    )
    unit_id = None
    if result.success:
        unit = ContentUnit(
            ids.new_id("unit"), result.task, result.text,
            source_ids=[source.id], alignment="document", status=result.status,
        )
        document.units.append(unit)
        unit_id = unit.id
    document.diagnostics = [
        Diagnostic("review", issue.code, issue.message,
                   document_id=document.id, unit_id=unit_id, source_id=source.id)
        for issue in result.review_issues
    ]
    document.diagnostics.extend(
        Diagnostic("warning", "upstream_warning", message, document_id=document.id, source_id=source.id)
        for message in result.warnings
    )
    if result.error is not None:
        document.diagnostics.append(Diagnostic(
            "error", result.error.code, result.error.message,
            document_id=document.id, source_id=source.id, details=asdict(result.error),
        ))
    return HandoffReport(result.status, documents=[document])


def adapt_media(
    result: MediaResult, ids: IdAllocator, *,
    business_id: str | None = None, version: str | None = None,
) -> HandoffReport:
    """正文原样交接；片段时间不能转换为逐词时间或推测的正文字符区间。"""
    source = Source(ids.new_id("source"), "media", asdict(result.source))
    document = Document(
        ids.new_id("document"), result.text, "text", result.status,
        business_id=business_id, version=version, sources=[source],
        requires_review=result.requires_review,
        metadata={"task": result.task, "question": result.question},
        structure={"segments": [asdict(segment) for segment in result.segments]},
    )
    document.diagnostics = [
        Diagnostic("review", "upstream_review", message, document_id=document.id, source_id=source.id)
        for message in result.review_issues
    ]
    document.diagnostics.extend(
        Diagnostic("warning", "upstream_warning", message, document_id=document.id, source_id=source.id)
        for message in result.warnings
    )
    for segment in result.segments:
        segment_source = Source(ids.new_id("source"), "media_segment", {
            **asdict(result.source), "kind": segment.kind,
            "start_seconds": segment.start_seconds, "end_seconds": segment.end_seconds,
            "time_precision": segment.time_precision, "speaker": segment.speaker,
        })
        document.sources.append(segment_source)
        unit = ContentUnit(
            ids.new_id("unit"), segment.kind, segment.text,
            source_ids=[segment_source.id], status=segment.status,
            metadata={
                key: value for key, value in asdict(segment).items()
                if key not in ("kind", "text", "start_seconds", "end_seconds")
            },
        )
        document.units.append(unit)
        document.diagnostics.extend(
            Diagnostic("review", "model_uncertainty", note,
                       document_id=document.id, unit_id=unit.id, source_id=segment_source.id)
            for note in segment.review_notes
        )
    if result.error is not None:
        document.diagnostics.append(Diagnostic(
            "error", result.error.code, result.error.message,
            document_id=document.id, source_id=source.id, details=asdict(result.error),
        ))
    return HandoffReport(result.status, documents=[document])
