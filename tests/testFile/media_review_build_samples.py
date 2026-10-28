"""显式构造延迟音轨回归素材；测试只读取固定样本，不运行本生成器。"""

from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parent.resolve()


def main():
    delayed = ROOT / "media_review_delayed_audio.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=red:s=160x120:r=20:d=6",
        "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=16000:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=600:sample_rate=16000:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=1800:sample_rate=16000:duration=6",
        "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1,asetpts=PTS+1.25/TB[first]",
        "-map", "0:v", "-map", "[first]", "-map", "3:a",
        "-c:v", "libx264", "-threads", "1", "-g", "40", "-bf", "0", "-c:a", "alac",
        "-disposition:a:0", "0", "-disposition:a:1", "default", str(delayed),
    ], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    offset = ROOT / "media_review_delayed_audio_offset.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(delayed), "-map", "0", "-c", "copy", "-output_ts_offset", "5", str(offset),
    ], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    manifest = {
        "source": "本地 FFmpeg lavfi 纯色画面与正弦音构造；原创测试素材，可自由复用，无语音、无外部模型。",
        "builder": Path(__file__).name,
        "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
        "playback_duration_seconds": 6,
        "video": {"index": 0, "range_seconds": [0, 6], "color": "red"},
        "audio_tracks": [
            {"index": 1, "default": False, "range_seconds": [1.25, 3.25],
             "sample_rate": 16000, "sample_count": 32000,
             "tones": [[1.25, 2.25, 300], [2.25, 3.25, 600]]},
            {"index": 2, "default": True, "range_seconds": [0, 6], "frequency_hz": 1800},
        ],
        "samples": [{"filename": path.name, "bytes": path.stat().st_size,
                     "sha256": sha256(path.read_bytes()).hexdigest(),
                     "container_start_seconds": origin}
                    for path, origin in ((delayed, 0), (offset, 5))],
        "limitation": "仅验证延迟首音轨的上传波形、原时间及联合排序，不证明模型识别质量；重建后须重新核对摘要。",
    }
    (ROOT / "media_review_samples.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
