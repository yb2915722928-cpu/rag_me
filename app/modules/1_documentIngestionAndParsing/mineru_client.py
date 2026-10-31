"""Shared MinerU transport; callers interpret the downloaded service archive."""

from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPSConnection, HTTPException
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit


@dataclass
class MinerUConfig:
    token: str | None = field(default=None, repr=False)
    api_base: str = "https://mineru.net/api/v4"
    language: str = "ch"
    poll_interval: float = 3
    request_timeout: float = 30
    max_wait: float = 300


class MinerUError(Exception):
    pass


class MinerUClient:
    def __init__(self, config: MinerUConfig):
        self.config = config

    def extract_document(self, data: bytes, *, filename: str, model_version: str = "vlm",
                         is_ocr: bool | None = None, max_archive_bytes: int | None = None,
                         check_result_deadline=None) -> bytes:
        """保留服务结果包；可选截止回调只协作检查结果下载，不中断上传或轮询。"""
        request = {
            "files": [{"name": filename}], "model_version": model_version,
        }
        if model_version != "MinerU-HTML":
            request.update(language=self.config.language, enable_table=True)
            if is_ocr is not None:
                request["files"][0]["is_ocr"] = is_ocr
        headers = {"Authorization": f"Bearer {self.config.token}"}
        applied = self._json("/file-urls/batch", headers, request)
        self._upload(applied["file_urls"][0], data)
        deadline = time.monotonic() + self.config.max_wait
        while time.monotonic() < deadline:
            result = self._json(
                f"/extract-results/batch/{applied['batch_id']}", headers,
            )["extract_result"][0]
            if result["state"] == "failed":
                raise MinerUError(f"MinerU parsing failed: {result.get('err_msg', '')}")
            if result["state"] == "done":
                break
            time.sleep(min(self.config.poll_interval, max(0, deadline - time.monotonic())))
        else:
            raise MinerUError("MinerU polling timed out")
        return self._read(result["full_zip_url"], max_bytes=max_archive_bytes,
                          check_deadline=check_result_deadline)

    def _json(self, endpoint, headers, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data is not None:
            headers = headers | {"Content-Type": "application/json"}
        try:
            response = json.loads(self._read(self.config.api_base + endpoint, headers, data))
        except (ValueError, UnicodeError):
            raise MinerUError("MinerU returned invalid JSON") from None
        if not isinstance(response, dict) or "code" not in response:
            raise MinerUError("MinerU returned an invalid response envelope")
        if response["code"] != 0:
            raise MinerUError(f"MinerU API {response['code']}: {response.get('msg', '')}")
        result = response.get("data")
        if not isinstance(result, dict):
            raise MinerUError("MinerU response data must be an object")
        if endpoint == "/file-urls/batch":
            urls = result.get("file_urls")
            if (not isinstance(result.get("batch_id"), str)
                    or not isinstance(urls, list) or len(urls) != 1
                    or not isinstance(urls[0], str) or not _http_url(urls[0])):
                raise MinerUError("MinerU upload response requires batch_id and one file_urls entry")
        else:
            items = result.get("extract_result")
            if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
                raise MinerUError("MinerU poll response requires one extract_result entry")
            item = items[0]
            if item.get("state") not in {"waiting-file", "pending", "running", "converting", "done", "failed"}:
                raise MinerUError("MinerU returned an unknown task state")
            if item["state"] == "done" and not _http_url(item.get("full_zip_url")):
                raise MinerUError("MinerU completed response requires full_zip_url")
        return result

    def _read(self, url, headers=None, data=None, method=None, max_bytes=None, check_deadline=None):
        if check_deadline is not None:
            check_deadline()
        request = Request(url, data=data, headers=headers or {}, method=method)
        try:
            with urlopen(request, timeout=self.config.request_timeout) as response:
                if max_bytes is None:
                    return response.read()
                content = bytearray()
                while True:
                    chunk = response.read(min(64 * 1024, max_bytes - len(content) + 1))
                    if check_deadline is not None:
                        check_deadline()
                    if len(content) + len(chunk) > max_bytes:
                        raise MinerUError("MinerU result ZIP exceeds max_archive_bytes")
                    if not chunk:
                        return bytes(content)
                    content.extend(chunk)
        except HTTPError as exc:
            raise MinerUError(f"MinerU request HTTP {exc.code}") from None
        except (URLError, OSError, HTTPException):
            raise MinerUError("MinerU network request failed or timed out") from None

    def _upload(self, url: str, data: bytes):
        """签名 PUT 不附带认证或 Content-Type；urllib 会自动添加表单类型，导致签名拒绝。"""
        parts = urlsplit(url)
        connection_type = HTTPSConnection if parts.scheme == "https" else HTTPConnection
        connection = connection_type(parts.hostname, parts.port, timeout=self.config.request_timeout)
        try:
            target = parts.path + ("?" + parts.query if parts.query else "")
            connection.request("PUT", target, body=data)
            response = connection.getresponse()
            if response.status != 200:
                raise MinerUError(f"MinerU upload HTTP {response.status}")
            response.read()
        except (OSError, HTTPException):
            raise MinerUError("MinerU upload failed or timed out") from None
        finally:
            connection.close()


def _http_url(value) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.netloc)
