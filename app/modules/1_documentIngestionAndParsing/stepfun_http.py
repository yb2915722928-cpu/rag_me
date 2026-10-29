from http.client import HTTPException
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class StepFunError(Exception):
    def __init__(self, code, message, http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def request_json(config, endpoint: str, body: bytes, content_type: str = "application/json"):
    """请求体可以是 JSON 或 multipart；失败诊断不回显服务错误正文。"""
    request = Request(config.base_url.rstrip("/") + endpoint, data=body,
                      headers={"Authorization": "Bearer " + config.api_key,
                               "Content-Type": content_type}, method="POST")
    try:
        with urlopen(request, timeout=config.timeout) as response:
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
