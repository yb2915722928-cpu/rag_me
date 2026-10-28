from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

from .client import StepFunClient, StepFunConfig, StepFunError, read_completion, resolve_config
from .models import ConversionResult, Diagnostic, ReviewIssue, Source
from .prompts import TASK_PROMPTS


def convert_file(path, *, task=None, format=None, source=None, question=None, config=None) -> ConversionResult:
    """文件后缀可由 format 覆盖；核心不查找或读取 .env。"""
    source_info = Source(source if isinstance(source, str) else None)
    try:
        path = Path(path)
        source_info.location = str(path) if source is None else source_info.location
        source_info = _validate_options(path.suffix if format is None else format,
                                        source_info.location, task, question)
    except (TypeError, ValueError) as exc:
        code = exc.code if isinstance(exc, InputError) else "invalid_options"
        return ConversionResult(None, source_info, task, error=Diagnostic(code, str(exc)))
    try:
        data = path.read_bytes()
    except OSError:
        return ConversionResult(None, source_info, task,
                                error=Diagnostic("file_read_error", "Could not read input file"))
    return _convert_content(data, source_info, task, config)


def convert_bytes(data, *, format, source, task=None, question=None, config=None) -> ConversionResult:
    source_info = Source(source if isinstance(source, str) else None)
    try:
        source_info = _validate_options(format, source, task, question)
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except ValueError as exc:
        code = exc.code if isinstance(exc, InputError) else "invalid_options"
        return ConversionResult(None, source_info, task, error=Diagnostic(code, str(exc)))
    return _convert_content(data, source_info, task, config)


def _convert_content(data, source, task, config):
    source.sha256 = sha256(data).hexdigest()
    version, prompt, schema = TASK_PROMPTS[task]
    result = ConversionResult(None, source, task, prompt_version=version)
    try:
        source.width, source.height = _decode_image(data, source.format)
    except InputError as exc:
        result.error = Diagnostic(exc.code, str(exc))
        return result
    try:
        config = resolve_config(config)
        result.requested_model = config.model
        payload = StepFunClient(config).complete(data, source.format, prompt, schema)
        content, result.response_model = read_completion(payload)
        output = _read_ocr(content)
    except StepFunError as exc:
        result.error = Diagnostic(exc.code, str(exc), exc.http_status)
        return result
    result.text, result.status = output["text"], output["status"]
    result.review_issues = [ReviewIssue("unverified_model_output", "模型产出尚待对照原图核验。")]
    result.review_issues.extend(ReviewIssue("model_uncertainty", note) for note in output["review_notes"])
    if result.status == "no_text":
        result.warnings.append("本次未取得可用文字，不证明图片没有文字。")
    return result


def _read_ocr(content):
    """模型业务输出只在此校验；空 OCR 必须显式声明 no_text 且 text 恰为空。"""
    try:
        output = json.loads(content)
    except ValueError:
        raise StepFunError("protocol_error", "OCR content is not JSON") from None
    if not isinstance(output, dict) or set(output) != {"status", "text", "review_notes"}:
        raise StepFunError("protocol_error", "OCR content does not match the required fields")
    status, text, notes = output["status"], output["text"], output["review_notes"]
    if (not isinstance(status, str) or status not in ("content", "no_text")
            or not isinstance(text, str) or not isinstance(notes, list)
            or any(not isinstance(note, str) or not note.strip() for note in notes)):
        raise StepFunError("protocol_error", "OCR content has invalid field types or values")
    if (status == "content" and not text.strip()) or (status == "no_text" and text != ""):
        raise StepFunError("protocol_error", "OCR status and text are inconsistent")
    return output


class InputError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _decode_image(data, declared_format):
    try:
        with Image.open(BytesIO(data)) as image:
            actual = image.format.lower()
            if actual not in ("png", "jpeg", "webp"):
                raise InputError("unsupported_format", "Decoded image format is not supported")
            if actual != declared_format:
                raise InputError("format_mismatch", "Declared format differs from decoded image")
            if getattr(image, "n_frames", 1) != 1 or getattr(image, "is_animated", False):
                raise InputError("multiframe_image", "Only single-frame static images are supported")
            image.load()
            return image.size
    except InputError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise InputError("image_decode_error", "Could not fully decode image") from None


def _validate_options(format, source, task, question):
    if not isinstance(task, str) or task not in TASK_PROMPTS:
        raise ValueError("task must explicitly select ocr")
    if question is not None:
        raise ValueError("OCR does not accept question")
    if not isinstance(format, str) or not format.strip():
        raise ValueError("format must be a nonempty string")
    normalized = format.strip().lower().lstrip(".")
    if normalized == "jpg":
        normalized = "jpeg"
    if normalized not in ("png", "jpeg", "webp"):
        raise InputError("unsupported_format", "Unsupported image format")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a nonempty string")
    return Source(source, normalized)
