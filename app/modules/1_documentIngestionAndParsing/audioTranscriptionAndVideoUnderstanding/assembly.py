"""Pure assembly of completed media segments into their native result."""

from .models import ConversionResult, Segment, Source


def assemble_result(source: Source, task: str, question: str | None,
                    segments: list[Segment]) -> ConversionResult:
    """Keep the actual segment order and ranges supplied by orchestration."""
    status = ("uncertain" if any(s.status == "uncertain" for s in segments) else
              "no_text" if all(s.status == "no_text" for s in segments) else "content")
    text = "\n\n".join(
        f"[{s.start_seconds:.3f}–{s.end_seconds:.3f} 秒 · "
        f"{'语音转写' if s.kind == 'audio' else '画面信息'}]\n{s.text}"
        for s in segments if s.text.strip())
    review_issues = ["媒体派生文字尚待对照同一版本原音视频核验。",
                     "时间仅定位实际处理片段，不是逐句或逐词时间。"]
    warnings = []
    if task in ("transcribe", "both"):
        warnings.append("同步 ASR 不提供说话人区分；speaker 保持未知。")
    if any(s.status == "no_text" for s in segments):
        warnings.append("部分或全部片段未取得可用转写，不证明原媒体没有语音。")
    if task in ("video", "both"):
        warnings.append("视频模型可能遗漏短暂画面或动作；画面解释不能替代原视频证据。")
    return ConversionResult(text, source, task, status=status, question=question,
                            segments=segments, review_issues=review_issues, warnings=warnings)
