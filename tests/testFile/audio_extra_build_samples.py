"""显式生成补充音频样本；测试只读取固定文件，不运行生成器。"""

from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parent.resolve()


def main():
    path = ROOT / "audio_extra_tracks_offset.m4a"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=16000:duration=1.25",
        "-f", "lavfi", "-i", "sine=frequency=600:sample_rate=16000:duration=1.25",
        "-f", "lavfi", "-i", "sine=frequency=900:sample_rate=16000:duration=1.25",
        "-f", "lavfi", "-i", "sine=frequency=1800:sample_rate=48000:duration=3.75",
        "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[first]",
        "-map", "[first]", "-map", "3:a", "-c:a", "alac",
        "-disposition:a:0", "0", "-disposition:a:1", "default",
        "-output_ts_offset", "5", str(path),
    ], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    version = subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]
    manifest = {
        "source": "本地 FFmpeg lavfi 正弦音构造；原创测试素材，可自由复用；无语音、无外部模型。",
        "builder": Path(__file__).name,
        "ffmpeg": version,
        "container_start_seconds": 5,
        "tracks": [
            {"index": 0, "default": False, "duration_seconds": 3.75,
             "tones": [[0, 1.25, 300], [1.25, 2.5, 600], [2.5, 3.75, 900]]},
            {"index": 1, "default": True, "duration_seconds": 3.75,
             "tones": [[0, 3.75, 1800]]},
        ],
        "samples": [{"filename": path.name, "bytes": path.stat().st_size,
                     "sha256": sha256(path.read_bytes()).hexdigest()}],
        "limitation": "仅验证选轨、原时间及上传波形，不证明语音识别质量。不同 FFmpeg 版本重建后须重新核对并提交摘要。",
    }
    (ROOT / "audio_extra_samples.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
