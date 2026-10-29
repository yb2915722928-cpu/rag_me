import base64
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from ..stepfun_http import StepFunError, request_json
from .prompts import VIDEO_PROMPT, VIDEO_SCHEMA


@dataclass(frozen=True)
class StepFunConfig:
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    asr_model: str | None = None
    video_model: str | None = None
    timeout: float = 180


def resolve_config(config, task):
    """只为所选任务读取模型配置，不把视觉模型名当作 ASR 模型名。"""
    config = StepFunConfig() if config is None else config
    if not isinstance(config, StepFunConfig):
        raise StepFunError("invalid_config", "config must be StepFunConfig")
    values = {}
    fields = [("api_key", "STEP_API_KEY", None), ("base_url", "STEP_BASE_URL", None)]
    if task in ("transcribe", "both"):
        fields.append(("asr_model", "STEP_ASR_MODEL", "stepaudio-2.5-asr"))
    if task in ("video", "both"):
        fields.append(("video_model", "STEP_MODEL", None))
    for name, env, default in fields:
        value = getattr(config, name)
        value = os.environ.get(env, default) if value is None else value
        if value is None or value == "":
            raise StepFunError("missing_config", f"Set {env} or StepFunConfig.{name}")
        if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
            raise StepFunError("invalid_config", f"Invalid {env}")
        values[name] = value
    try:
        url = urlsplit(values["base_url"])
        valid = url.scheme in ("http", "https") and url.hostname and not (
            url.username or url.password or url.query or url.fragment)
        url.port
    except ValueError:
        valid = False
    if not valid or not values["api_key"].isascii():
        raise StepFunError("invalid_config", "Invalid STEP_BASE_URL or STEP_API_KEY")
    if (type(config.timeout) not in (int, float) or not math.isfinite(config.timeout)
            or config.timeout <= 0):
        raise StepFunError("invalid_config", "timeout must be finite and positive")
    return StepFunConfig(**values, timeout=config.timeout)


class StepFunClient:
    def __init__(self, config: StepFunConfig):
        self.config = config

    def transcribe(self, path: Path):
        audio = _read_media(path, 100_000_000)
        boundary = "media-" + uuid4().hex
        parts = []
        for name, value in (("model", self.config.asr_model), ("response_format", "json")):
            parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                          f"\r\n\r\n{value}\r\n").encode("utf-8"))
        parts.extend([(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                       'filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode("ascii"),
                      audio, f"\r\n--{boundary}--\r\n".encode("ascii")])
        payload = request_json(self.config, "/audio/transcriptions", b"".join(parts),
                               f"multipart/form-data; boundary={boundary}")
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise StepFunError("protocol_error", "ASR response requires a text string")
        return payload["text"]

    def video(self, path: Path, question: str | None):
        video = base64.b64encode(_read_media(path, 128_000_000)).decode("ascii")
        prompt = VIDEO_PROMPT + ("\n本次问题：\n" + question if question else "")
        body = {
            "model": self.config.video_model,
            "messages": [{"role": "user", "content": [
                {"type": "video_url", "video_url": {"url": "data:video/mp4;base64," + video}},
                {"type": "text", "text": prompt},
            ]}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "video_task", "strict": True, "schema": VIDEO_SCHEMA}},
            "reasoning_effort": "low", "max_tokens": 4096, "stream": False,
        }
        payload = request_json(self.config, "/chat/completions",
                               json.dumps(body, ensure_ascii=False).encode("utf-8"))
        return _read_video(payload)


def _read_media(path, limit):
    try:
        if path.stat().st_size >= limit:
            raise StepFunError("media_too_large", "Segment exceeds API limit; use shorter segments")
        return path.read_bytes()
    except OSError:
        raise StepFunError("media_read_error", "Could not read prepared media segment") from None


def _read_video(payload):
    """在 API 响应边界验证完成原因及视频任务结构，不接受截断的正文。"""
    try:
        choices = payload["choices"]
        if len(choices) != 1 or choices[0]["finish_reason"] != "stop":
            raise ValueError
        message = choices[0]["message"]
        if message.get("refusal"):
            raise ValueError
        result = json.loads(message["content"])
        if set(result) != {"status", "text", "review_notes"}:
            raise ValueError
        status, text, notes = result["status"], result["text"], result["review_notes"]
        if (status not in ("content", "uncertain") or not isinstance(text, str) or not text.strip()
                or not isinstance(notes, list)
                or any(not isinstance(n, str) or not n.strip() for n in notes)
                or (status == "uncertain" and not notes)):
            raise ValueError
        model = payload.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise ValueError
        return text, status, notes, model
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise StepFunError("protocol_error", "Video response is incomplete or has invalid fields") from None
