from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from . import ContentSource, ConversionResult, Source


def extract_pdf(data: bytes, source: Source, mineru=None) -> ConversionResult:
    try:
        reader = PdfReader(BytesIO(data))
        pages = list(reader.pages)
    except PyPdfError as exc:
        return ConversionResult(None, source, error=f"PDF parsing failed: {exc}")
    markdown = ""
    sources = []
    warnings = []
    ocr_pages = []
    for page_number, page in enumerate(pages, start=1):
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
                ocr_pages.append(page_number)
                warnings.append(f"PDF page {page_number}: no usable text layer; OCR required")
            else:
                warnings.append(f"PDF page {page_number}: no usable text body")
            continue
        text += "\n"
        if markdown:
            markdown += "\n"
        start = len(markdown)
        markdown += text
        sources.append(ContentSource(start, len(markdown), page_number, "text_layer"))
    if ocr_pages:
        if not sources:
            from .mineru import extract_scanned_pdf

            return extract_scanned_pdf(data, source, len(pages), ocr_pages, mineru)
        return ConversionResult(
            None, source, warnings=warnings,
            error=f"OCR required for PDF pages: {', '.join(map(str, ocr_pages))}",
        )
    if not markdown:
        return ConversionResult(None, source, warnings=warnings, error="No usable text body")
    warnings.append(
        "PDF text-layer extraction does not reconstruct heading levels, columns or "
        "table relationships; verify content and reading order against the PDF"
    )
    return ConversionResult(markdown, source, sources, warnings)
