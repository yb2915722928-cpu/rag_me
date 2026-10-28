import base64
from dataclasses import dataclass, field
from http.client import HTTPException
import json
import math
import os
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class StepFunConfig:
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    model: str | None = None
    timeout: float = 90


class StepFunError(Exception):
    def __init__(self, code, message, http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def resolve_config(config):
    """仅在配置入口合并进程环境；不隐式搜索或载入环境文件。"""
    if config is None:
        config = StepFunConfig()
    if not isinstance(config, StepFunConfig):
        raise StepFunError("invalid_config", "config must be StepFunConfig")
    values = {}
    for field_name, env in (("api_key", "STEP_API_KEY"), ("base_url", "STEP_BASE_URL"), ("model", "STEP_MODEL")):
        value = getattr(config, field_name)
        value = os.environ.get(env) if value is None else value
        if value is None or value == "":
            raise StepFunError("missing_config", f"Set {env} or StepFunConfig.{field_name}")
        if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
            raise StepFunError("invalid_config", f"Invalid {env}")
        values[field_name] = value
    try:
        parsed = urlsplit(values["base_url"])
        valid_url = parsed.scheme in ("http", "https") and parsed.hostname and not (
            parsed.username or parsed.password or parsed.query or parsed.fragment
        )
        parsed.port
    except ValueError:
        valid_url = False
    if not valid_url:
        raise StepFunError("invalid_config", "STEP_BASE_URL must be an HTTP(S) API base URL")
    if not values["api_key"].isascii():
        raise StepFunError("invalid_config", "Invalid STEP_API_KEY")
    if (type(config.timeout) not in (float, int) or not math.isfinite(config.timeout)
            or config.timeout <= 0):
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
        request = Request(
            self.config.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.config.api_key,
                     "Content-Type": "application/json"}, method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            status = exc.code
            exc.close()
            code = ("authentication_error" if status in (401, 403) else
                    "rate_limited" if status == 429 else
                    "service_error" if status >= 500 else "http_error")
            raise StepFunError(code, f"StepFun request HTTP {status}", status) from None
        except TimeoutError:
            raise StepFunError("timeout", "StepFun request timed out") from None
        except URLError as exc:
            code = "timeout" if isinstance(exc.reason, TimeoutError) else "network_error"
            raise StepFunError(code, "StepFun connection failed or timed out") from None
        except (OSError, HTTPException):
            raise StepFunError("network_error", "StepFun network request failed") from None
        except (ValueError, UnicodeError):
            raise StepFunError("protocol_error", "StepFun returned invalid JSON") from None


def read_completion(payload):
    """HTTP JSON 的唯一协议校验边界；拒绝截断、拒答及缺少正文的响应。"""
    if not isinstance(payload, dict):
        raise StepFunError("protocol_error", "StepFun response must be an object")
    model = payload.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise StepFunError("protocol_error", "Invalid response model identifier")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise StepFunError("protocol_error", "StepFun response requires one completion")
    choice = choices[0]
    message = choice.get("message")
    if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
        raise StepFunError("protocol_error", "StepFun completion was not normally finished")
    content = message.get("content")
    if message.get("refusal") or not isinstance(content, str) or not content.strip():
        raise StepFunError("protocol_error", "StepFun response has no usable content or was refused")
    return content, model
