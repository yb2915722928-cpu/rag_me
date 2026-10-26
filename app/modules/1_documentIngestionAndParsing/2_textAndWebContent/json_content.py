import json


def convert_json(text: str) -> str:
    value = json.loads(text.removeprefix("\ufeff"), parse_constant=_reject_constant)
    body = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    return f"```json\n{body}\n```\n"


def _reject_constant(value: str):
    raise ValueError(f"{value} is not a JSON constant")
