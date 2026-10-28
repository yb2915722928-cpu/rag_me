from dataclasses import dataclass, field

from .provenance import CropMapping, DocumentSource


@dataclass
class Source:
    location: str | None
    format: str | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    document: DocumentSource | None = None
    crop: CropMapping | None = None


@dataclass
class Diagnostic:
    code: str
    message: str
    http_status: int | None = None


@dataclass
class ReviewIssue:
    code: str
    message: str


@dataclass
class ConversionResult:
    """空 OCR 为 ''，uncertain 保留解释，失败为 None；question 保留原始问题。"""

    text: str | None
    source: Source
    task: str | None
    status: str = "failed"
    requested_model: str | None = None
    response_model: str | None = None
    prompt_version: str | None = None
    review_issues: list[ReviewIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: Diagnostic | None = None
    question: str | None = None

    @property
    def success(self) -> bool:
        return self.status != "failed" and self.error is None

    @property
    def requires_review(self) -> bool:
        return bool(self.review_issues)
