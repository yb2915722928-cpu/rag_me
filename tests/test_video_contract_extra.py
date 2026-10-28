from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from tests.test_audio_video import media, media_server, SAMPLES


MANIFEST = json.loads((SAMPLES / "video_extra_constructed.json").read_text(encoding="utf-8"))


class VideoContractExtraTests(unittest.TestCase):
    def test_fixed_sample_versions(self):
        for sample in MANIFEST["samples"]:
            with self.subTest(sample=sample["filename"]):
                data = (SAMPLES / sample["filename"]).read_bytes()
                self.assertEqual(len(data), sample["bytes"])
                self.assertEqual(sha256(data).hexdigest(), sample["sha256"])

    def test_mkv_source_duration_excludes_fractional_container_origin(self):
        path = SAMPLES / "video_extra_offset.mkv"
        with media_server() as (config, requests):
            result = media.convert_file(path, task="video", config=config,
                                        options=media.ProcessingOptions(video_segment_seconds=2))
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source.duration_seconds, 6)
        self.assertEqual([(s.start_seconds, s.end_seconds) for s in result.segments],
                         [(0, 3), (3, 6)])
        self.assertEqual(len(requests), 2)

    def test_unremuxable_video_reports_failure_without_submitting_or_reencoding(self):
        path = SAMPLES / "video_extra_huffyuv.mkv"
        with media_server() as (config, requests):
            result = media.convert_file(path, task="video", config=config)
        self.assertFalse(result.success)
        self.assertEqual((result.error.code, result.error.stage), ("media_tool_error", "prepare"))
        self.assertIn("MP4 without re-encoding", result.error.message)
        self.assertEqual(result.source.sha256, sha256(path.read_bytes()).hexdigest())
        self.assertIsNone(result.text)
        self.assertEqual(result.segments, [])
        self.assertEqual(requests, [])

    def test_later_video_failure_retains_original_source_and_actual_failed_range(self):
        path = SAMPLES / "video_extra_delayed.mp4"
        with media_server(fail_at=2) as (config, requests):
            result = media.convert_file(path, task="video", source="course-video", question="画面是什么颜色？",
                                        media_id="course", media_version="v3", config=config,
                                        options=media.ProcessingOptions(video_segment_seconds=2))
        self.assertEqual(len(requests), 2)
        self.assertFalse(result.success)
        self.assertEqual((result.error.code, result.error.stage, result.error.start_seconds),
                         ("service_error", "video", 3.25))
        self.assertEqual((result.source.location, result.source.media_id, result.source.media_version),
                         ("course-video", "course", "v3"))
        self.assertEqual(result.source.sha256, sha256(path.read_bytes()).hexdigest())
        self.assertEqual(result.question, "画面是什么颜色？")
        self.assertIsNone(result.text)
        self.assertEqual(result.segments, [])

    def test_delayed_video_maps_only_visible_ranges_to_original_playback(self):
        path = SAMPLES / "video_extra_delayed.mp4"
        with media_server() as (config, requests):
            first = media.convert_file(path, source="delayed", task="video", config=config,
                                       options=media.ProcessingOptions(video_segment_seconds=2))
            second = media.convert_bytes(path.read_bytes(), source="delayed", format="mp4",
                                         task="video", config=config,
                                         options=media.ProcessingOptions(video_segment_seconds=2))
        self.assertTrue(first.success, first.error)
        self.assertEqual(asdict(first), asdict(second))
        self.assertEqual(first.source.duration_seconds, 6)
        self.assertEqual([(s.start_seconds, s.end_seconds) for s in first.segments],
                         [(1.25, 3.25), (3.25, 5.25)])
        self.assertEqual(len(requests), 4)
        with TemporaryDirectory() as directory:
            for index, request in enumerate(requests[:2]):
                clip = Path(directory) / "clip.mp4"
                clip.write_bytes(request["media_bytes"])
                frames = subprocess.check_output([
                    "ffmpeg", "-v", "error", "-i", str(clip), "-map", "0:v:0",
                    "-vf", "scale=1:1", "-fps_mode", "passthrough",
                    "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
                self.assertEqual(len(frames), 40 * 3)
                channel = 0 if index == 0 else 2
                for offset in range(0, len(frames), 3):
                    pixel = frames[offset:offset + 3]
                    self.assertGreater(pixel[channel], 2 * max(pixel[(channel + 1) % 3],
                                                               pixel[(channel + 2) % 3]))


if __name__ == "__main__":
    unittest.main()
