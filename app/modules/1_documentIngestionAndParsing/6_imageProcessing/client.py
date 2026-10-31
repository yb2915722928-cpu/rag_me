import base64
from dataclasses import dataclass, field
import json

from ..stepfun_http import StepFunError, request_json
from ..stepfun_support import (
    is_api_base_url, is_positive_timeout, read_completion, resolve_config_values,
)


@dataclass(frozen=True)
class StepFunConfig:
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    model: str | None = None
    timeout: float = 90


def resolve_config(config):
    """仅在配置入口合并进程环境；不隐式搜索或载入环境文件。"""
    if config is None:
        config = StepFunConfig()
    if not isinstance(config, StepFunConfig):
        raise StepFunError("invalid_config", "config must be StepFunConfig")
    values = resolve_config_values(config, (
        ("api_key", "STEP_API_KEY", None), ("base_url", "STEP_BASE_URL", None),
        ("model", "STEP_MODEL", None),
    ))
    if not is_api_base_url(values["base_url"]):
        raise StepFunError("invalid_config", "STEP_BASE_URL must be an HTTP(S) API base URL")
    if not values["api_key"].isascii():
        raise StepFunError("invalid_config", "Invalid STEP_API_KEY")
    if not is_positive_timeout(config.timeout):
        raise StepFunError("invalid_config", "timeout must be a finite positive number of seconds")
    return StepFunConfig(**values, timeout=config.timeout)


class StepFunClient:
    def __init__(self, config: StepFunConfig):
        self.config = config

    def complete(self, data: bytes, format: str, prompt: str, schema: dict):
        mime = "image/jpeg" if format == "jpeg" else f"image/{format}"
        body = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii"),
                    "detail": "high",
                }},
            ]}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "image_task", "strict": True, "schema": schema,
            }},
            "reasoning_effort": "low", "max_tokens": 4096, "stream": False,
        }
        return request_json(
            self.config, "/chat/completions",
            json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
