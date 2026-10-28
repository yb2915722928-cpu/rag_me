"""只重建 #43 自有 ZIP 样本；复用固定媒体，不调用模型或修改其他样本。"""

from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


SAMPLES = Path(__file__).resolve().parent


def build():
    archives = {
        "zip_media_audio.zip": [("音频/规则." + ext, "media_rules." + ext)
                                for ext in ("wav", "mp3", "m4a", "ogg", "flac")],
        "zip_media_video.zip": [("画面/时间线." + ext, "media_timeline." + ext)
                                for ext in ("mp4", "mov", "mkv")],
        "zip_media_delayed.zip": [("片段/延迟.mp4", "video_extra_delayed.mp4")],
        "zip_media_failures.zip": [("损坏.mp4", "media_corrupt.mp4"),
                                  ("编码限制.mkv", "video_extra_huffyuv.mkv"),
                                  ("正常.mp4", "media_timeline.mp4")],
        "zip_media_silence.zip": [("静音.wav", "media_silence.wav")],
        "zip_media_live_audio.zip": [("培训/规则.wav", "media_rules.wav")],
        "zip_media_live_video.zip": [("培训/规则.mp4", "media_rules.mp4")],
    }
    manifest = {"builder": Path(__file__).name,
                "source": "复用本仓库固定原创媒体；成员字节与既有媒体样本相同，未调用 API。",
                "limitation": "协议响应不证明识别质量；live 使用合成中文语音及审批图示短视频。",
                "archives": []}
    for filename, members in archives.items():
        records = []
        path = SAMPLES / filename
        with ZipFile(path, "w") as container:
            for name, original in members + [("说明.txt", None)]:
                data = ((SAMPLES / original).read_bytes() if original else
                        "其他成员仍可独立读取。".encode("utf-8"))
                info = ZipInfo(name, date_time=(2026, 10, 28, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o600 << 16
                container.writestr(info, data)
                records.append({"member_path": name, "original": original, "bytes": len(data),
                                "sha256": sha256(data).hexdigest()})
        manifest["archives"].append({"filename": filename, "bytes": path.stat().st_size,
                                     "sha256": sha256(path.read_bytes()).hexdigest(),
                                     "members": records})
    (SAMPLES / "zip_media_samples.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    build()
