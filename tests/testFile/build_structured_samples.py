"""生成固定 JSON/XML 样本；仅手动运行，测试不调用此脚本。"""

import codecs
import json
from pathlib import Path


SAMPLES = Path(__file__).parent


def build_samples():
    refund = {
        "title": "退款办理规则",
        "rules": [
            {
                "condition": {"order_type": "普通订单"},
                "owner": "客服",
                "steps": ["提交退款申请", "客服核验订单", "原路退款"],
            },
            {
                "condition": {"order_type": "企业订单", "amount_max_inclusive": 10000},
                "owner": "企业财务",
                "steps": ["提交企业退款申请", "企业财务核验", "企业财务退款"],
            },
            {
                "condition": {"order_type": "企业订单", "amount_gt": 10000},
                "owner": "企业专属负责人",
                "steps": ["提交企业退款申请", "企业财务核验", "企业专属负责人审批", "企业财务执行退款"],
            },
        ],
    }
    refund_text = json.dumps(refund, ensure_ascii=False, indent=2) + "\n"
    reordered = {
        "rules": [dict(reversed(tuple(rule.items()))) for rule in refund["rules"]],
        "title": refund["title"],
    }
    pointers = {
        "": {"a/b": {"m~n": [0, 0.0, False, None, {}, [], "", {"企业/退款~": "末尾"}]}},
        "~1": "波浪线加数字不是斜线",
        "0": "对象数字键",
    }
    fixtures = {
        "json_refund_rules.json": refund_text.encode("utf-8"),
        "structured_json_override.txt": refund_text.encode("utf-8"),
        "json_refund_reordered.json": (
            json.dumps(reordered, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "json_refund_invalid_gb18030.json": refund_text.rstrip()[:-1].encode("gb18030"),
        "structured_json_pointers.json": (
            json.dumps(pointers, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "structured_json_overflow.json": b'{"amount": 1e999}\n',
    }
    refund_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<refund title="退款办理规则">
  <rule order_type="普通订单"><owner>客服</owner><steps><step>提交退款申请</step><step>客服核验订单</step><step>原路退款</step></steps></rule>
  <rule order_type="企业订单" amount_max_inclusive="10000"><owner>企业财务</owner><steps><step>提交企业退款申请</step><step>企业财务核验</step><step>企业财务退款</step></steps></rule>
  <rule order_type="企业订单" amount_gt="10000"><owner>企业专属负责人</owner><steps><step>提交企业退款申请</step><step>企业财务核验</step><step>企业专属负责人审批</step><step>企业财务执行退款</step></steps></rule>
</refund>
'''
    relationships = '''<?xml version="1.0" encoding="UTF-8"?>
<?workflow preserve="yes"?>
<!--退款条件不能串到其他分支-->
<rules xmlns="urn:refund:rules" xmlns:corp="https://example.invalid/refund/corporate" xmlns:alias="https://example.invalid/refund/corporate" xmlns:other="urn:refund:other" version="2026" note="&quot;保留&quot;">
  <branch id="ordinary">普通订单<owner>客服</owner>核验后退款<!--归属注释--></branch>
  <branch id="enterprise">企业订单<corp:owner code="finance">企业财务</corp:owner><other:owner>审计</other:owner><owner xmlns="">无命名空间负责人</owner></branch>
  <corp:branch id="large"><corp:owner>企业专属负责人</corp:owner><alias:owner>企业财务执行退款</alias:owner></corp:branch>
  <note>金额 <em>10000</em> 元以下；<![CDATA[大于10000 <企业> & 专属]]>。</note>
</rules>
'''.replace("\n", "\r\n")
    chinese = "普通订单由客服办理；企业订单由企业财务办理；金额大于10000元的企业订单由企业专属负责人审批。"
    declaration_body = f"<refund><rule>{chinese}</rule></refund>\n"
    fixtures.update({
        "xml_refund_rules.xml": refund_xml.encode("utf-8"),
        "xml_refund_override.txt": refund_xml.encode("utf-8"),
        "xml_relationships.xml": relationships.encode("utf-8"),
        "xml_fenced.xml": "<note><![CDATA[保留代码\n```xml\nx\n````\n]]></note>".encode("utf-8"),
        "xml_gb18030_declaration.xml": (
            '<?xml version="1.0" encoding="GB18030"?>\n' + declaration_body
        ).encode("gb18030"),
        "xml_latin1_declaration.xml": (
            "<?xml version='1.0' encoding='ISO-8859-1'?>\n<note>café</note>"
        ).encode("iso-8859-1"),
        "xml_explicit_over_declaration.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n' + declaration_body
        ).encode("gb18030"),
        "xml_bom_over_declaration.xml": codecs.BOM_UTF8 + (
            '<?xml version="1.0" encoding="GB18030"?>\n' + declaration_body
        ).encode("utf-8"),
        "xml_unknown_declaration.xml": (
            '<?xml version="1.0" encoding="unknown-structured-codec"?>\n' + declaration_body
        ).encode("utf-8"),
        "xml_failed_declaration.xml": (
            '<?xml version="1.0" encoding="ASCII"?>\n' + declaration_body
        ).encode("utf-8"),
        "xml_invalid_gb18030.xml": (
            '<?xml version="1.0" encoding="unknown-structured-codec"?>\n'
            f"<refund><rule>{chinese}</refund>"
        ).encode("gb18030"),
        "xml_mismatched_tags.xml": b"<refund><rule></refund>",
        "xml_multiple_roots.xml": b"<refund/><refund/>",
        "xml_unbound_prefix.xml": b"<refund><corp:owner>finance</corp:owner></refund>",
        "xml_duplicate_attribute.xml": b'<refund type="ordinary" type="enterprise"/>',
        "xml_external_entity.xml": (
            '<!DOCTYPE refund [<!ENTITY external SYSTEM '
            '"file:///__structured_external_resource_must_not_be_read__">]>'
            '<refund>&external;</refund>'
        ).encode("utf-8"),
        "xml_empty.xml": b"",
        "xml_bom_only.xml": codecs.BOM_UTF8,
        "xml_truncated_utf16.xml": codecs.BOM_UTF16_LE + b"<",
    })
    for suffix, codec, signature, declaration in (
        ("utf8", "utf-8", codecs.BOM_UTF8, "UTF-8"),
        ("utf16_le", "utf-16-le", codecs.BOM_UTF16_LE, "UTF-16"),
        ("utf16_be", "utf-16-be", codecs.BOM_UTF16_BE, "UTF-16"),
        ("utf32_le", "utf-32-le", codecs.BOM_UTF32_LE, "UTF-32"),
        ("utf32_be", "utf-32-be", codecs.BOM_UTF32_BE, "UTF-32"),
    ):
        text = f'<?xml version="1.0" encoding="{declaration}"?>\n{declaration_body}'
        fixtures[f"xml_{suffix}_bom.xml"] = signature + text.encode(codec)
        if suffix != "utf8":
            fixtures[f"xml_{suffix}_declaration.xml"] = text.encode(codec)
    for name, data in fixtures.items():
        (SAMPLES / name).write_bytes(data)


if __name__ == "__main__":
    build_samples()
