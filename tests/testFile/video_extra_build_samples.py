"""显式重建视频时间定位样本；默认测试只读取固定文件。"""

from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parent.resolve()


def main():
    delayed = ROOT / "video_extra_delayed.mp4"
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=red:s=160x120:r=20:d=2",
        "-f", "lavfi", "-i", "color=blue:s=160x120:r=20:d=2",
        "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=6",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,setpts=PTS+1.25/TB[v]",
        "-map", "[v]", "-map", "2:a", "-fps_mode", "passthrough",
        "-c:v", "libx264", "-threads", "1", "-g", "40", "-keyint_min", "40",
        "-sc_threshold", "0", "-bf", "2", "-c:a", "alac", str(delayed),
    ]
    subprocess.run(command, check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    offset = ROOT / "video_extra_offset.mkv"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(ROOT / "media_timeline.mp4"), "-c", "copy", "-output_ts_offset", "5.125",
        str(offset),
    ], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    incompatible = ROOT / "video_extra_huffyuv.mkv"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=red:s=160x120:r=10:d=1",
        "-c:v", "huffyuv", "-threads", "1", str(incompatible),
    ], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    manifest = {
        "source": "本仓库 FFmpeg 本地构造；颜色和时间由生成命令定义，未使用模型输出作为真值。",
        "license": "测试用途原创纯色画面与静音音轨，无外部素材。",
        "builder": Path(__file__).name,
        "samples": [{
            "filename": delayed.name,
            "bytes": delayed.stat().st_size,
            "sha256": sha256(delayed.read_bytes()).hexdigest(),
            "timeline": "容器和静音音轨起于 0 秒，止于 6 秒；视频 1.25–3.25 秒红色、3.25–5.25 秒蓝色；20 fps，含 B 帧，每 2 秒关键帧。",
        }, {
            "filename": offset.name,
            "bytes": offset.stat().st_size,
            "sha256": sha256(offset.read_bytes()).hexdigest(),
            "timeline": "media_timeline.mp4 原码流封装为 MKV；容器起点 5.125 秒、末帧结束于 11.125 秒，播放时长 6 秒；相对播放起点 0–2 秒红、2–4 秒绿、4–6 秒蓝。",
        }, {
            "filename": incompatible.name,
            "bytes": incompatible.stat().st_size,
            "sha256": sha256(incompatible.read_bytes()).hexdigest(),
            "timeline": "1 秒红色 Huffyuv 画面，无音轨；MKV 可读但 MP4 无法直接容纳该编码，应在准备阶段明确失败。",
        }],
    }
    (ROOT / "video_extra_constructed.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
