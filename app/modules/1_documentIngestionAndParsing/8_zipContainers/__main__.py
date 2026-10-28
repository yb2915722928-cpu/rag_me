import argparse
import json
import sys

from . import ZipLimits, convert_file


def main():
    arguments = _arguments()
    result = convert_file(
        arguments.path, source=arguments.source, metadata_encoding=arguments.metadata_encoding,
        parser_options=arguments.parser_options,
        limits=ZipLimits(
            max_archive_bytes=arguments.max_archive_bytes,
            max_members=arguments.max_members,
            max_member_bytes=arguments.max_member_bytes,
            max_total_bytes=arguments.max_total_bytes,
            timeout_seconds=arguments.timeout_seconds,
        ),
    )
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return {"success": 0, "partial_success": 2, "failed": 1}[result.status]


def _arguments():
    parser = argparse.ArgumentParser(description="读取 ZIP 容器并输出逐成员 JSON 报告")
    parser.add_argument("path", help="ZIP 文件路径")
    parser.add_argument("--source", help="报告中的容器来源，默认输入路径")
    parser.add_argument("--metadata-encoding", help="ZIP 名称编码，与成员正文编码独立")
    parser.add_argument("--parser-options", type=json.loads, help="按处理器类别分组的 JSON 选项")
    defaults = ZipLimits()
    parser.add_argument("--max-archive-bytes", type=int, default=defaults.max_archive_bytes)
    parser.add_argument("--max-members", type=int, default=defaults.max_members)
    parser.add_argument("--max-member-bytes", type=int, default=defaults.max_member_bytes)
    parser.add_argument("--max-total-bytes", type=int, default=defaults.max_total_bytes)
    parser.add_argument("--timeout-seconds", type=float, default=defaults.timeout_seconds)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
