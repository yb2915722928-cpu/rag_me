from dataclasses import dataclass, field


@dataclass
class Source:
    location: str
    format: str | None = None


@dataclass
class ContentSource:
    """正文区间左闭右开；幻灯片、段落、行列从 1 开始，level 保留原始的 0 起始层级。

    shape_path 使用原始对象 ID；bounds_emu 是对象在其父容器中的原始坐标，
    不将组合内坐标冒充页内绝对坐标。节点路径定位原结构，不是正文字符偏移。
    """

    kind: str
    markdown_start: int | None = None
    markdown_end: int | None = None
    slide_number: int | None = None
    slide_title: str | None = None
    shape_path: tuple[int, ...] = ()
    shape_name: str | None = None
    bounds_emu: tuple[int, int, int, int] | None = None
    paragraph_number: int | None = None
    level: int | None = None
    row_number: int | None = None
    column_number: int | None = None
    node_path: str | None = None
    parent_path: str | None = None
    node_type: str | None = None


@dataclass
class ReviewIssue:
    code: str
    message: str
    source: ContentSource


@dataclass
class ConversionResult:
    """success 表示完成提取；requires_review 独立表示尚待对照原资料核验的关系。"""

    markdown: str | None
    source: Source
    sources: list[ContentSource] = field(default_factory=list)
    review_issues: list[ReviewIssue] = field(default_factory=list)
    encoding: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.markdown is not None and self.error is None

    @property
    def requires_review(self) -> bool:
        return bool(self.review_issues)
