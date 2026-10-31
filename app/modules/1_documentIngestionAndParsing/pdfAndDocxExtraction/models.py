from dataclasses import dataclass, field


@dataclass
class Source:
    location: str
    format: str | None = None


@dataclass
class ContentSource:
    """正文区间采用字符串切片；PDF 页序与 DOCX 章节/正文块位置分别表达，均非印刷页码。"""

    markdown_start: int
    markdown_end: int
    pdf_page_number: int | None
    extraction_method: str
    section_path: tuple[str, ...] = ()
    body_block_number: int | None = None
    section_block_number: int | None = None
    block_type: str | None = None
    heading_level: int | None = None


@dataclass
class ConversionResult:
    markdown: str | None
    source: Source
    sources: list[ContentSource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.markdown is not None and self.error is None
