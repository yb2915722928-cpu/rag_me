"""Shared StepFun configuration checks and chat-completion envelopes."""

import math
import os
from urllib.parse import urlsplit

from .stepfun_http import StepFunError


def resolve_config_values(config, fields):
    """Resolve only the fields selected by the image or media task."""
    values = {}
    for name, env, default in fields:
        value = getattr(config, name)
        value = os.environ.get(env, default) if value is None else value
        if value is None or value == "":
            raise StepFunError("missing_config", f"Set {env} or StepFunConfig.{name}")
        if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
            raise StepFunError("invalid_config", f"Invalid {env}")
        values[name] = value
    return values


def is_api_base_url(value):
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in ("http", "https") and parsed.hostname and not (
            parsed.username or parsed.password or parsed.query or parsed.fragment
        )
        parsed.port
    except ValueError:
        return False
    return bool(valid)


def is_positive_timeout(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def read_completion(payload):
    """Read a normally finished completion, leaving task content validation to callers."""
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
