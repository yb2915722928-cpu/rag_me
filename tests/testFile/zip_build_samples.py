"""重建 ZIP 固定输入；只在维护样本时运行，回归测试不生成或下载输入。"""

from io import BytesIO
import hashlib
from pathlib import Path
import struct
import warnings
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo


SAMPLES = Path(__file__).resolve().parent


def archive(entries, *, compression=ZIP_DEFLATED):
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=compression) as container:
        for name, content in entries:
            info = ZipInfo(name, date_time=(2026, 10, 28, 0, 0, 0))
            info.filename = info.orig_filename = name
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = compression
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                container.writestr(info, content.encode("utf-8") if isinstance(content, str) else content)
    return buffer.getvalue()


def build():
    (SAMPLES / "zip_text.zip").write_bytes(archive([
        ("资料/说明.txt", "ZIP 容器示例\r\n两行原文\r\n"),
        ("guide.MD", "# 使用方法\n\n保留 **强调**。\n"),
    ]))
    (SAMPLES / "zip_lightweight.zip").write_bytes(archive([
        ("rules.json", '{"rules":[{"city":"北京","amount":500}]}'),
        ("rules.xml", '<rules version="1"><city>北京</city><!--保留--></rules>'),
        ("rates.csv", "城市;额度\r\n北京;00500\r\n上海;450\r\n".encode("gb18030")),
        ("legacy.txt", "正文编码独立于文件名。".encode("gb18030")),
    ]))
    (SAMPLES / "zip_members.zip").write_bytes(archive([
        ("docs/", ""), ("docs/readme.txt", "目录 A"),
        ("other/readme.txt", "目录 B"), ("same.txt", "首次"), ("same.txt", "再次"),
        ("__MACOSX/docs/._readme.txt", "metadata"), ("docs/.DS_Store", "metadata"),
        ("docs/._note.txt", "metadata"), ("docs/.hidden.txt", "合法隐藏文档"),
        ("nested.zip", archive([("inner.txt", "不能递归")])),
        ("unknown.bin", b"\x00\x01"), ("bad.json", "{bad"), ("last.txt", "仍然成功"),
    ]))
    rejected = bytearray(archive([
        ("../escape.txt", "拒绝"), ("dir/../escape.txt", "拒绝"),
        ("/absolute.txt", "拒绝"), ("C:\\drive.txt", "拒绝"),
        ("C:relative.txt", "拒绝"), ("\\\\host\\share\\file.txt", "拒绝"),
        ("dir\\..\\escape.txt", "拒绝"), ("encrypted.txt", "secret"),
        ("crc.txt", "CRC content"), ("unreadable.txt", "header content"),
        ("safe.txt", "后续正常"),
    ], compression=ZIP_STORED))
    with ZipFile(BytesIO(rejected)) as container:
        infos = container.infolist()
    central = rejected.index(b"PK\x01\x02")
    for info in infos:
        if info.filename == "encrypted.txt":
            struct.pack_into("<H", rejected, info.header_offset + 6, info.flag_bits | 1)
            struct.pack_into("<H", rejected, central + 8, info.flag_bits | 1)
        if info.filename == "crc.txt":
            name_length, extra_length = struct.unpack_from("<HH", rejected, info.header_offset + 26)
            rejected[info.header_offset + 30 + name_length + extra_length] ^= 1
        if info.filename == "unreadable.txt":
            rejected[info.header_offset] = 0
        name_length, extra_length, comment_length = struct.unpack_from("<HHH", rejected, central + 28)
        central += 46 + name_length + extra_length + comment_length
    (SAMPLES / "zip_rejected.zip").write_bytes(rejected)
    (SAMPLES / "zip_empty.zip").write_bytes(archive([]))
    (SAMPLES / "zip_metadata.zip").write_bytes(archive([
        ("docs/", ""), ("__MACOSX/hello.txt", "ignored"), (".DS_Store", "ignored"),
    ]))
    (SAMPLES / "zip_all_failed.zip").write_bytes(archive([
        ("bad.json", "{"), ("unsupported.exe", "data"),
    ]))
    (SAMPLES / "zip_corrupt.zip").write_bytes(b"not a ZIP container\x00")
    (SAMPLES / "zip_budgets.zip").write_bytes(archive([
        ("first.txt", "first"), ("large.txt", "X" * 100000),
        ("last.txt", "last"), ("__MACOSX/._large.txt", "metadata"),
    ]))
    crc_budget = bytearray(archive([
        ("first.txt", "first"), ("bad-crc.txt", "X" * 70000),
        ("last.txt", "last"),
    ], compression=ZIP_STORED))
    with ZipFile(BytesIO(crc_budget)) as container:
        offset = container.infolist()[1].header_offset
    name_length, extra_length = struct.unpack_from("<HH", crc_budget, offset + 26)
    crc_budget[offset + 30 + name_length + extra_length] ^= 1
    (SAMPLES / "zip_crc_budget.zip").write_bytes(crc_budget)
    legacy = archive([("name.txt", "独立正文编码".encode("utf-16"))])
    (SAMPLES / "zip_legacy_names.zip").write_bytes(legacy.replace(b"name.txt", "资料.txt".encode("gb18030")))
    (SAMPLES / "zip_samples.sha256").write_text(
        "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                for path in sorted(SAMPLES.glob("zip_*.zip"))),
        encoding="utf-8", newline="\n",
    )


if __name__ == "__main__":
    build()
