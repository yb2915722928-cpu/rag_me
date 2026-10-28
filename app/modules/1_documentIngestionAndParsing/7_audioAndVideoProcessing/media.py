import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess

from .models import ProcessingOptions


AUDIO_FORMATS = {"wav", "mp3", "m4a", "ogg", "flac"}
VIDEO_FORMATS = {"mp4", "mov", "mkv"}
CONTAINERS = {
    "wav": {"wav"}, "mp3": {"mp3"}, "m4a": {"mov", "mp4", "m4a"},
    "ogg": {"ogg"}, "flac": {"flac"}, "mp4": {"mov", "mp4"},
    "mov": {"mov", "mp4"}, "mkv": {"matroska"},
}


class MediaError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    audio_stream: int | None
    video_stream: int | None


@dataclass(frozen=True)
class Clip:
    path: Path
    kind: str
    start: float
    end: float


def probe(path: Path, format: str, options: ProcessingOptions) -> MediaInfo:
    payload = _run([options.ffprobe, "-v", "error", "-show_format", "-show_streams",
                    "-of", "json", str(path)], options.media_timeout)
    try:
        data = json.loads(payload)
        container = data["format"]
        streams = data["streams"]
        actual = set(container["format_name"].split(","))
        if not CONTAINERS[format] & actual:
            raise MediaError("format_mismatch", "Declared format differs from the media container")
        audio = next((s for s in streams if s["codec_type"] == "audio"), None)
        video = next((s for s in streams if s["codec_type"] == "video"
                      and not s.get("disposition", {}).get("attached_pic")), None)
        selected = [s for s in (audio, video) if s is not None]
        origin = float(container.get("start_time", 0))
        if selected and all("duration" in s for s in selected):
            duration = max(float(s.get("start_time", origin)) + float(s["duration"])
                           - origin for s in selected)
        else:
            duration = float(container["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return MediaInfo(duration, None if audio is None else int(audio["index"]),
                         None if video is None else int(video["index"]))
    except (KeyError, TypeError, ValueError, StopIteration):
        raise MediaError("media_probe_error", "Media has no readable finite duration or streams") from None


def prepare(path: Path, directory: Path, kind: str, info: MediaInfo,
            options: ProcessingOptions) -> list[Clip]:
    """切点受关键帧影响；禁用负 DTS 平移，以免 B 帧使清单时间偏离原片。"""
    audio = kind == "audio"
    index = info.audio_stream if audio else info.video_stream
    seconds = options.audio_segment_seconds if audio else options.video_segment_seconds
    extension = "wav" if audio else "mp4"
    listing = directory / f"{kind}.csv"
    output = directory / f"{kind}-%06d.{extension}"
    codec = (["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"] if audio
             else ["-an", "-c:v", "copy"])
    _run([options.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
          "-copyts", "-start_at_zero", "-i", str(path), "-map", f"0:{index}",
          "-t", str(info.duration), *codec,
          "-avoid_negative_ts", "disabled",
          "-f", "segment", "-segment_format", extension, "-segment_time", str(seconds),
          "-segment_list", str(listing), "-segment_list_type", "csv",
          "-reset_timestamps", "1", str(output)], options.media_timeout)
    try:
        clips = []
        with listing.open(encoding="utf-8", newline="") as handle:
            for name, start, end in csv.reader(handle):
                start, end = max(0.0, float(start)), min(info.duration, float(end))
                clip_path = directory / Path(name).name
                if (not math.isfinite(start) or not math.isfinite(end) or end <= start
                        or not clip_path.is_file() or clip_path.stat().st_size == 0):
                    raise ValueError
                clips.append(Clip(clip_path, kind, start, end))
        if not clips:
            raise ValueError
        return clips
    except (OSError, ValueError):
        raise MediaError("media_prepare_error", "Could not read actual media segment boundaries") from None


def _run(command: list[str], timeout: float) -> str:
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout, check=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise MediaError("missing_media_tool", "FFmpeg/FFprobe executable was not found") from None
    except subprocess.TimeoutExpired:
        raise MediaError("media_timeout", "Media preparation exceeded its time limit") from None
    except OSError:
        raise MediaError("media_tool_error", "Could not start FFmpeg/FFprobe") from None
    if completed.returncode != 0:
        raise MediaError("media_tool_error", "Media tool failed; check input codecs and file integrity. "
                         "Video must be remuxable to MP4 without re-encoding.")
    return completed.stdout.decode("utf-8", errors="replace")
