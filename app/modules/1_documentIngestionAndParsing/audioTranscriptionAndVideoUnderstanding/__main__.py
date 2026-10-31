import argparse
from dataclasses import asdict
import json
import sys

from dotenv import load_dotenv

from . import ProcessingOptions, StepFunConfig, convert_file


def main():
    parser = argparse.ArgumentParser(description="通过阶跃 API 转写音视频或理解视频画面")
    parser.add_argument("input")
    parser.add_argument("--task", required=True, choices=("transcribe", "video", "both"))
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--question")
    parser.add_argument("--source")
    parser.add_argument("--format")
    parser.add_argument("--audio-seconds", type=float, default=30)
    parser.add_argument("--video-seconds", type=float, default=60)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    load_dotenv(dotenv_path=args.env_file, override=False)
    options = ProcessingOptions(audio_segment_seconds=args.audio_seconds,
                                video_segment_seconds=args.video_seconds)
    result = convert_file(args.input, task=args.task, format=args.format, source=args.source,
                          question=args.question, config=StepFunConfig(timeout=args.timeout), options=options)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
