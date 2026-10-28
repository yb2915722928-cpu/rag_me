from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import threading


SAMPLES = Path(__file__).parent / "testFile"
zip_containers = importlib.import_module("app.modules.1_documentIngestionAndParsing.8_zipContainers")
mineru = importlib.import_module("app.modules.1_documentIngestionAndParsing.3_pdfAndWordParsing.mineru")
SERVICE_MARKDOWN = "# Service original\n\nKeep **formatting**, order and trailing spaces.  \n"


@dataclass
class Service:
    config: object = None
    requests: list = field(default_factory=list)
    uploads: list = field(default_factory=list)
    polls: int = 0


@contextmanager
def document_server(*, failure=None, result_name=None, result_bytes=None, no_length=False):
    """真实本地 HTTP 服务只替代网络边界，上传与结果均由实际客户端处理。"""
    service = Service()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, value, status=200):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            if not no_length:
                self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            service.requests.append(body)
            if self.path != "/api/v4/file-urls/batch" or self.headers.get("Authorization") != "Bearer test-token":
                return self.reply({}, 401)
            if failure in ("auth", "quota", "format"):
                code = {"auth": "A0202", "quota": -50001, "format": -60001}[failure]
                return self.reply({"code": code, "msg": "test-token https://private.invalid/?token=secret rejected"})
            if failure == "apply-http":
                return self.reply(b"unavailable", 503)
            if failure == "invalid-json":
                return self.reply(b"{")
            service.polls = 0
            self.reply({"code": 0, "data": {"batch_id": "batch", "file_urls": [base + "/upload"]}})

        def do_PUT(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            if self.headers.get("Authorization") or self.headers.get("Content-Type"):
                return self.reply(b"unexpected signed-upload headers", 400)
            service.uploads.append(data)
            self.reply(b"", 503 if failure == "upload" else 200)

        def do_GET(self):
            if self.path == "/result":
                if self.headers.get("Authorization"):
                    return self.reply(b"unexpected result credentials", 400)
                if failure == "download":
                    return self.reply(b"unavailable", 503)
                name = result_name or ("zip_document_html_result.zip" if
                       service.requests[-1]["model_version"] == "MinerU-HTML" else "zip_document_result.zip")
                return self.reply(result_bytes if result_bytes is not None else (SAMPLES / name).read_bytes())
            if self.path != "/api/v4/extract-results/batch/batch" or self.headers.get("Authorization") != "Bearer test-token":
                return self.reply({}, 401)
            if failure == "poll":
                return self.reply(b"unavailable", 503)
            service.polls += 1
            state = "pending" if service.polls == 1 or failure == "timeout" else "done"
            if failure == "failed":
                state = "failed"
            self.reply({"code": 0, "data": {"extract_result": [{
                "state": state, "full_zip_url": base + "/result",
                "err_msg": "test-token https://private.invalid/?signature=secret parsing failed",
            }]}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{server.server_port}"
    service.config = mineru.MinerUConfig(token="test-token", api_base=base + "/api/v4",
                                          poll_interval=0.001, max_wait=1)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield service
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
