from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProcessingOptions:
    audio_segment_seconds: float = 30
    video_segment_seconds: float = 60
    media_timeout: float = 300
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"


@dataclass
class Source:
    location: str | None
    format: str | None = None
    sha256: str | None = None
    media_type: str | None = None
    duration_seconds: float | None = None
    media_id: str | None = None
    media_version: str | None = None
    audio_stream_index: int | None = None


@dataclass
class Diagnostic:
    code: str
    message: str
    stage: str | None = None
    start_seconds: float | None = None
    http_status: int | None = None


@dataclass
class Segment:
    kind: str
    start_seconds: float
    end_seconds: float
    text: str
    status: str
    requested_model: str
    response_model: str | None = None
    prompt_version: str | None = None
    speaker: str | None = None
    time_precision: str = "segment"
    review_notes: list[str] = field(default_factory=list)


@dataclass
class ConversionResult:
    """失败不暴露部分正文或片段；no_text 仅表示本次没有取得可用转写。"""

    text: str | None
    source: Source
    task: str | None
    status: str = "failed"
    question: str | None = None
    segments: list[Segment] = field(default_factory=list)
    review_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: Diagnostic | None = None

    @property
    def success(self) -> bool:
        return self.status != "failed" and self.error is None

    @property
    def requires_review(self) -> bool:
        return bool(self.review_issues)
