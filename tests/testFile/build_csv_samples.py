"""重建固定 CSV 样本；测试仅读取生成后的文件，不运行此脚本。"""

from pathlib import Path
import codecs


SAMPLES = Path(__file__).resolve().parent
TEXTS = {
    "csv_quote_unclosed.csv": '城市,说明\n北京,正常\n上海,"未结束\n第二行',
    "csv_quote_trailing.csv": '城市,说明\n北京,正常\n上海,"结束"多余\n',
    "csv_quote_bare.csv": '城市,说明\n北京,正常\n上海,错"引号\n',
    "csv_empty.csv": "",
    "csv_blank.csv": "\r\n , \r\n\r\n",
    "csv_header_only.csv": "城市,住宿\n",
    "csv_no_data.csv": "城市,住宿\n,\n\n , \n",
    "csv_header_empty.csv": "城市, ,餐补\n北京,500,100\n",
    "csv_header_duplicate.csv": "城市,城市,餐补\n北京,500,100\n",
    "csv_width_short.csv": "城市,住宿\n北京,500\n上海\n",
    "csv_width_long.csv": "城市,住宿\n北京,500\n上海,450,100\n",
    "csv_markdown.csv": (
        "列|名,路径,说明\r\n"
        '值|A,C:\\临时\\file,"第一行\r\n第二行<br>&"\r\n'
    ),
    "csv_quoted.csv": (
        "\r\n编号,说明,金额,备注\r\n"
        '00123,"含逗号,与""引号""\r\n第二行",=1+2,\r\n'
        ",,,\r\n\r\n00002,普通文本,0,尾\r\n"
    ),
    "csv_travel.csv": (
        "城市,住宿上限（元／晚）,餐补（元／天）\r\n"
        "北京,500,100\r\n"
        "上海,450,100\r\n"
        "杭州,400,80\r\n"
    ),
}


if __name__ == "__main__":
    for filename, text in TEXTS.items():
        (SAMPLES / filename).write_bytes(text.encode("utf-8"))
    for suffix, signature, codec in (
        ("utf8_bom", codecs.BOM_UTF8, "utf-8"),
        ("utf16_le_bom", codecs.BOM_UTF16_LE, "utf-16-le"),
        ("utf16_be_bom", codecs.BOM_UTF16_BE, "utf-16-be"),
        ("utf32_le_bom", codecs.BOM_UTF32_LE, "utf-32-le"),
        ("utf32_be_bom", codecs.BOM_UTF32_BE, "utf-32-be"),
    ):
        (SAMPLES / f"csv_travel_{suffix}.csv").write_bytes(signature + TEXTS["csv_travel.csv"].encode(codec))
    (SAMPLES / "csv_explicit_gb18030.csv").write_bytes((
        "导出说明，不是表头\r\n\r\n城市;住宿上限（元／晚）;餐补（元／天）\r\n"
        "北京;500;100\r\n上海;450;100\r\n"
    ).encode("gb18030"))
    (SAMPLES / "csv_truncated_utf16.csv").write_bytes(codecs.BOM_UTF16_LE + b"\x61")
    (SAMPLES / "csv_undecodable.csv").write_bytes(bytes(range(256)))
    (SAMPLES / "csv_bom_only.csv").write_bytes(codecs.BOM_UTF8)
