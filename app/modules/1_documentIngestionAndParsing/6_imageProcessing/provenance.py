from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DocumentPosition:
    """原文档实际排列位置，从 1 开始；不表示印刷页码或正文块序号。"""

    kind: Literal["pdf_page", "slide"]
    index: int


@dataclass(frozen=True)
class DocumentSource:
    document_id: str | None = None
    business_version: str | None = None
    position: DocumentPosition | None = None


@dataclass(frozen=True)
class CropMapping:
    """原图左上为原点、0 基像素坐标；bbox=(left, top, right, bottom)，右下不含。"""

    original_image_id: str | None = None
    original_width: int | None = None
    original_height: int | None = None
    bbox: tuple[int, int, int, int] | None = None


def validate_provenance(document):
    """仅在公开入口校验调用方元数据；内部与模型输出不再解释来源事实。"""
    if document is None:
        return
    if not isinstance(document, DocumentSource):
        raise ValueError("document must be DocumentSource")
    for value in (document.document_id, document.business_version):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError("Known document identifiers and versions must be nonempty strings")
    position = document.position
    if position is not None and (
        not isinstance(position, DocumentPosition) or position.kind not in ("pdf_page", "slide")
        or type(position.index) is not int or position.index < 1
    ):
        raise ValueError("position must identify a pdf_page or slide with a positive integer index")


def validate_crop(crop, is_cropped):
    """调用方声明已裁剪时，即使整组映射缺失也失败；不从图片推断是否裁剪。"""
    if type(is_cropped) is not bool:
        raise ValueError("is_cropped must be a boolean")
    if crop is None:
        if is_cropped:
            raise ValueError("A cropped input requires its original image mapping")
        return
    if not isinstance(crop, CropMapping):
        raise ValueError("crop must be CropMapping")
    if not isinstance(crop.original_image_id, str) or not crop.original_image_id.strip():
        raise ValueError("crop requires a nonempty original_image_id")
    if any(type(size) is not int or size <= 0 for size in (crop.original_width, crop.original_height)):
        raise ValueError("crop requires positive integer original dimensions")
    bbox = crop.bbox
    if not isinstance(bbox, tuple) or len(bbox) != 4 or any(type(value) is not int for value in bbox):
        raise ValueError("crop bbox must contain four integer pixel coordinates")
    left, top, right, bottom = bbox
    if not (0 <= left < right <= crop.original_width and 0 <= top < bottom <= crop.original_height):
        raise ValueError("crop bbox must be nonempty and within the original image")
