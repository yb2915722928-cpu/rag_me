from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from . import ContentSource, ConversionResult, Source


def extract_pdf(data: bytes, source: Source, mineru=None, ocr_pages: tuple[int, ...] = ()) -> ConversionResult:
    try:
        reader = PdfReader(BytesIO(data))
        pages = list(reader.pages)
        _validate_ocr_page_range(ocr_pages, len(pages))
    except ValueError as exc:
        return ConversionResult(None, source, error=str(exc))
    except PyPdfError as exc:
        return ConversionResult(None, source, error=f"PDF parsing failed: {exc}")
    page_bodies = {}
    warnings = []
    pages_to_ocr = []
    for page_number, page in enumerate(pages, start=1):
        if page_number in ocr_pages:
            pages_to_ocr.append(page_number)
            warnings.append(f"PDF page {page_number}: OCR explicitly requested; replacing text layer")
            continue
        try:
            text = page.extract_text().strip()
            has_images = bool(page.images) if not text else False
        except PyPdfError as exc:
            return ConversionResult(
                None, source, warnings=warnings,
                error=f"PDF page {page_number} extraction failed: {exc}",
            )
        if not text:
            if has_images:
                pages_to_ocr.append(page_number)
                warnings.append(f"PDF page {page_number}: no usable text layer; OCR required")
            else:
                warnings.append(f"PDF page {page_number}: no usable text body")
            continue
        page_bodies[page_number] = (text + "\n", "text_layer")
    has_text_layer = bool(page_bodies)
    if pages_to_ocr:
        from .mineru import extract_scanned_pdf

        result = extract_scanned_pdf(
            _selected_pdf(data, pages, pages_to_ocr), source, pages_to_ocr, mineru,
        )
        warnings.extend(result.warnings)
        if not result.success:
            return ConversionResult(None, source, warnings=warnings, error=result.error)
        for page in result.sources:
            page_bodies[page.pdf_page_number] = (
                result.markdown[page.markdown_start:page.markdown_end], page.extraction_method,
            )
    if not page_bodies:
        return ConversionResult(None, source, warnings=warnings, error="No usable text body")
    markdown = ""
    sources = []
    for page_number, (text, method) in sorted(page_bodies.items()):
        if markdown:
            markdown += "\n"
        start = len(markdown)
        markdown += text
        sources.append(ContentSource(start, len(markdown), page_number, method))
    if has_text_layer:
        warnings.append(
            "Nonempty text does not establish text-layer quality or completeness. "
            "PDF text-layer extraction does not reconstruct heading levels, columns or "
            "table relationships; verify content and reading order against the PDF"
        )
    return ConversionResult(markdown, source, sources, warnings)


def _validate_ocr_page_range(page_numbers: tuple[int, ...], page_count: int):
    for number in page_numbers:
        if not 1 <= number <= page_count:
            raise ValueError(f"ocr_pages page {number} is outside actual PDF page range 1..{page_count}")


def _selected_pdf(data: bytes, pages, page_numbers: list[int]) -> bytes:
    """复制待识字原页，不渲染图片；全页入选时保留原始上传字节。"""
    if len(page_numbers) == len(pages):
        return data
    writer = PdfWriter()
    for number in page_numbers:
        writer.add_page(pages[number - 1])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
