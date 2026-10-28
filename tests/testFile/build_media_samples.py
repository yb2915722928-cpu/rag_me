"""显式运行以重建固定媒体；默认测试只读取样本，不执行本生成器。"""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import wave


ROOT = Path(__file__).parent.resolve()
SCRIPT = (
    "企业订单超过一万元，按右侧分支处理。"
    "是不是所有订单都要负责人审批？不是，其他由财务审批。未经批准不得付款。"
)
QUESTION = "请根据视频中的条件与箭头，分别说明两个分支由谁审批；依据不足时明确说明无法确认的关系及原因。"


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    wav = ROOT / "media_rules.wav"
    speech = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SelectVoice('Microsoft Huihui Desktop'); $s.Rate = 0; "
        "$s.SetOutputToWaveFile('" + str(wav).replace("'", "''") + "'); "
        "$s.Speak('" + SCRIPT + "'); $s.Dispose()"
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", speech], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with wave.open(str(wav)) as handle:
        speech_seconds = handle.getnframes() / handle.getframerate()
    with wave.open(str(ROOT / "media_silence.wav"), "wb") as handle:
        handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        handle.writeframes(b"\0" * (16000 * 2 * 2))
    for extension, codec in (("mp3", "libmp3lame"), ("m4a", "aac"),
                             ("ogg", "libvorbis"), ("flac", "flac")):
        ffmpeg("-i", str(wav), "-c:a", codec, str(ROOT / ("media_rules." + extension)))
    ffmpeg("-loop", "1", "-framerate", "2", "-i", str(ROOT / "image_understanding_clear.png"),
           "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
           "-threads", "1", "-g", "4", "-bf", "0", "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-t", str(speech_seconds), "-movflags", "+faststart", str(ROOT / "media_rules.mp4"))
    ffmpeg("-loop", "1", "-framerate", "2", "-i", str(ROOT / "image_understanding_truncated.png"),
           "-t", "4", "-an", "-c:v", "libx264", "-threads", "1", "-g", "4", "-bf", "0",
           "-pix_fmt", "yuv420p", str(ROOT / "media_uncertain.mp4"))
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=160x120:r=10:d=2",
           "-f", "lavfi", "-i", "color=c=green:s=160x120:r=10:d=2",
           "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=10:d=2",
           "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]",
           "-c:v", "libx264", "-threads", "1", "-g", "30", "-keyint_min", "30",
           "-sc_threshold", "0", "-bf", "2", str(ROOT / "media_timeline.mp4"))
    ffmpeg("-i", str(ROOT / "media_timeline.mp4"), "-c", "copy", "-output_ts_offset", "5",
           str(ROOT / "media_offset.mp4"))
    for extension in ("mov", "mkv"):
        ffmpeg("-i", str(ROOT / "media_timeline.mp4"), "-c", "copy",
               str(ROOT / ("media_timeline." + extension)))
    (ROOT / "media_corrupt.mp4").write_bytes(b"not a valid media file\n")
    files = sorted(path for path in ROOT.glob("media_*")
                   if path.suffix in {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".mp4", ".mov", ".mkv"})
    manifest = {
        "source": "本仓库固定构造素材；未使用被测 ASR 或视觉模型产生真值。",
        "builder": Path(__file__).name,
        "license": "测试用途原创媒体，音频由 Windows Microsoft Huihui Desktop 合成，非真实讲师录音；未分发语音引擎或字体。",
        "script": SCRIPT, "question": QUESTION,
        "video_sources": ["image_understanding_clear.png", "image_understanding_truncated.png"],
        "timeline": "0–2 秒红色；2–4 秒绿色；4–6 秒蓝色。每 3 秒关键帧，含 B 帧；offset 文件相同内容但容器起点为 5 秒。",
        "expected_branches": ["金额超过1万元 → 负责人审批", "其他情况 → 财务审批"],
        "samples": [{"filename": p.name, "bytes": p.stat().st_size,
                     "sha256": sha256(p.read_bytes()).hexdigest()} for p in files],
    }
    (ROOT / "media_constructed.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)
                                               + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
