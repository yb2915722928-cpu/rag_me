"""生成固定 JSON 样本；仅手动运行，测试不调用此脚本。"""

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
    for name, data in fixtures.items():
        (SAMPLES / name).write_bytes(data)


if __name__ == "__main__":
    build_samples()
