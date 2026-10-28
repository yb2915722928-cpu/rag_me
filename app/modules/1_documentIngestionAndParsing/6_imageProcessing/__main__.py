import argparse
from dataclasses import asdict
import json
from pathlib import Path

from dotenv import load_dotenv

from . import StepFunConfig, convert_file
from .prompts import TASK_PROMPTS


def main():
    parser = argparse.ArgumentParser(description="单图处理；显式选择任务与环境文件")
    parser.add_argument("image", type=Path)
    parser.add_argument("--task", required=True, choices=TASK_PROMPTS)
    parser.add_argument("--question")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--format")
    parser.add_argument("--source")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if not args.env_file.is_file():
        parser.error("--env-file must name an existing environment file")
    load_dotenv(dotenv_path=args.env_file, override=False)
    result = convert_file(args.image, task=args.task, question=args.question,
                          format=args.format, source=args.source,
                          config=StepFunConfig(timeout=args.timeout))
    print(json.dumps(asdict(result) | {"success": result.success, "requires_review": result.requires_review},
                     ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
