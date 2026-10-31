"""Static targets for standalone ingestion and ZIP member parsing policies."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FormatRoute:
    standalone_module: str
    zip_member_module: str | None
    zip_kind: str | None


# Aliases stay separate keys: each native parser owns its format metadata.
# ZIP documents deliberately use hosted parsing, including digital PDFs;
# standalone documents retain their native local defaults.
FORMAT_ROUTES = {
    format: FormatRoute(standalone, member, kind)
    for standalone, member, kind, formats in (
        ("2_textAndWebContent", "2_textAndWebContent", "text", ("txt", "md", "markdown")),
        ("2_textAndWebContent", "hosted_documents", "document", ("html", "htm", "mhtml", "mht")),
        ("pdfAndDocxExtraction", "hosted_documents", "document", ("pdf", "docx")),
        ("4_tabularFileProcessing", "4_tabularFileProcessing", "csv", ("csv",)),
        ("4_tabularFileProcessing", "hosted_documents", "document", ("xlsx",)),
        ("5_presentationsAndStructuredDocuments", "hosted_documents", "document", ("pptx",)),
        ("5_presentationsAndStructuredDocuments", "5_presentationsAndStructuredDocuments", "structured",
         ("json", "xml")),
        ("6_imageProcessing", "8_zipContainers.image_api", "image", ("png", "jpg", "jpeg", "webp")),
        ("audioTranscriptionAndVideoUnderstanding", "8_zipContainers.media_api", "media",
         ("wav", "mp3", "m4a", "ogg", "flac", "mp4", "mov", "mkv")),
        ("8_zipContainers", None, None, ("zip",)),
    )
    for format in formats
}
