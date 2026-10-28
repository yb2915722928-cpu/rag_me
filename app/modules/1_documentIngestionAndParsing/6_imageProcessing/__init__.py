from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

from .client import StepFunClient, StepFunConfig, StepFunError, read_completion, resolve_config
from .models import ConversionResult, Diagnostic, ReviewIssue, Source
from .prompts import TASK_PROMPTS
from .provenance import CropMapping, DocumentPosition, DocumentSource, validate_crop, validate_provenance


def convert_file(path, *, task=None, format=None, source=None, question=None, config=None,
                 document: DocumentSource | None = None, crop: CropMapping | None = None,
                 is_cropped: bool = False) -> ConversionResult:
    """文件后缀可由 format 覆盖；核心不查找或读取 .env。"""
    source_info = Source(source if isinstance(source, str) else None)
    try:
        path = Path(path)
        source_info.location = str(path) if source is None else source_info.location
        validate_provenance(document)
        source_info.document = document
        validate_crop(crop, is_cropped)
        source_info.crop = crop
        source_info = _validate_options(path.suffix if format is None else format,
                                        source_info, task, question)
    except (TypeError, ValueError) as exc:
        code = exc.code if isinstance(exc, InputError) else "invalid_options"
        return ConversionResult(None, source_info, task, error=Diagnostic(code, str(exc)))
    try:
        data = path.read_bytes()
    except OSError:
        return ConversionResult(None, source_info, task, question=question,
                                error=Diagnostic("file_read_error", "Could not read input file"))
    return _convert_content(data, source_info, task, config, question)


def convert_bytes(data, *, format, source, task=None, question=None, config=None,
                  document: DocumentSource | None = None, crop: CropMapping | None = None,
                  is_cropped: bool = False) -> ConversionResult:
    source_info = Source(source if isinstance(source, str) else None)
    try:
        validate_provenance(document)
        source_info.document = document
        validate_crop(crop, is_cropped)
        source_info.crop = crop
        source_info = _validate_options(format, source_info, task, question)
        if not isinstance(data, bytes):
            raise ValueError("data must be bytes")
    except ValueError as exc:
        code = exc.code if isinstance(exc, InputError) else "invalid_options"
        return ConversionResult(None, source_info, task, error=Diagnostic(code, str(exc)))
    return _convert_content(data, source_info, task, config, question)


def _convert_content(data, source, task, config, question):
    source.sha256 = sha256(data).hexdigest()
    version, prompt, schema = TASK_PROMPTS[task]
    result = ConversionResult(None, source, task, prompt_version=version, question=question)
    if task == "understand":
        prompt += "\n\n本次问题：\n" + question
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
        output = _read_output(content, task)
    except StepFunError as exc:
        result.error = Diagnostic(exc.code, str(exc), exc.http_status)
        return result
    result.text, result.status = output["text"], output["status"]
    result.review_issues = [ReviewIssue("unverified_model_output", "模型产出尚待对照原图核验。")]
    result.review_issues.extend(ReviewIssue("model_uncertainty", note) for note in output["review_notes"])
    if result.status == "no_text":
        result.warnings.append("本次未取得可用文字，不证明图片没有文字。")
    return result


def _read_output(content, task):
    """模型业务输出按任务 Schema 校验；仅 OCR 允许空正文。"""
    try:
        output = json.loads(content)
    except ValueError:
        raise StepFunError("protocol_error", f"{task} content is not JSON") from None
    if not isinstance(output, dict) or set(output) != {"status", "text", "review_notes"}:
        raise StepFunError("protocol_error", f"{task} content does not match the required fields")
    status, text, notes = output["status"], output["text"], output["review_notes"]
    statuses = TASK_PROMPTS[task][2]["properties"]["status"]["enum"]
    if (not isinstance(status, str) or status not in statuses
            or not isinstance(text, str) or not isinstance(notes, list)
            or any(not isinstance(note, str) or not note.strip() for note in notes)):
        raise StepFunError("protocol_error", f"{task} content has invalid field types or values")
    if (status != "no_text" and not text.strip()) or (status == "no_text" and text != ""):
        raise StepFunError("protocol_error", f"{task} status and text are inconsistent")
    if status == "uncertain" and not notes:
        raise StepFunError("protocol_error", "Uncertain understanding requires a reason in review_notes")
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
        raise ValueError("task must explicitly select " + ", ".join(TASK_PROMPTS))
    if task == "understand" and (not isinstance(question, str) or not question.strip()):
        raise ValueError("understand requires a nonempty question")
    if task != "understand" and question is not None:
        raise ValueError(f"{task} does not accept question")
    if not isinstance(format, str) or not format.strip():
        raise ValueError("format must be a nonempty string")
    normalized = format.strip().lower().lstrip(".")
    if normalized == "jpg":
        normalized = "jpeg"
    if normalized not in ("png", "jpeg", "webp"):
        raise InputError("unsupported_format", "Unsupported image format")
    if not isinstance(source.location, str) or not source.location.strip():
        raise ValueError("source must be a nonempty string")
    source.format = normalized
    return source
