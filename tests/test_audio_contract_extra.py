from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

from tests.test_audio_video import MANIFEST, SAMPLES, media, media_server


EXTRA = json.loads((SAMPLES / "audio_extra_samples.json").read_text(encoding="utf-8"))


class AudioContractExtraTests(unittest.TestCase):
    def test_invalid_source_file_and_bytes_return_serializable_failure(self):
        path = SAMPLES / "media_rules.wav"
        with media_server() as (config, requests):
            for source in (Path("recording.wav"), 123):
                with self.subTest(source=source):
                    file_result = media.convert_file(path, source=source, task="transcribe", config=config)
                    byte_result = media.convert_bytes(path.read_bytes(), source=source, format="wav",
                                                       task="transcribe", config=config)
                    for result in (file_result, byte_result):
                        json.dumps(asdict(result))
                        self.assertFalse(result.success)
                        self.assertEqual(result.error.code, "invalid_options")
                        self.assertIsNone(result.source.location)
                        self.assertIsNone(result.text)
                        self.assertEqual(result.segments, [])
                    self.assertEqual(asdict(file_result), asdict(byte_result))
            self.assertEqual(requests, [])

    def test_first_audio_track_is_uploaded_even_when_second_track_is_default(self):
        sample = EXTRA["samples"][0]
        path = SAMPLES / sample["filename"]
        self.assertEqual(path.stat().st_size, sample["bytes"])
        self.assertEqual(sha256(path.read_bytes()).hexdigest(), sample["sha256"])
        with media_server(asr={"text": "首个音轨"}) as (config, requests):
            result = media.convert_file(path, task="transcribe", config=config)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.source.location, str(path))
        self.assertEqual(result.source.audio_stream_index, 0)
        self.assertEqual(result.source.duration_seconds, 3.75)
        self.assertEqual(len(requests), 1)
        with wave.open(BytesIO(requests[0]["media_bytes"])) as handle:
            self.assertEqual(handle.getnframes(), 60000)
            frames = handle.readframes(handle.getnframes())
        self.assert_first_track_tones(frames)

    def test_offset_audio_file_and_bytes_keep_actual_ranges_and_complete_waveform(self):
        path = SAMPLES / "audio_extra_tracks_offset.m4a"
        options = media.ProcessingOptions(audio_segment_seconds=1.25)
        with media_server(asr={"text": "固定音轨"}) as (config, requests):
            file_result = media.convert_file(path, task="transcribe", source="recording:v1",
                                             config=config, options=options)
            file_requests = list(requests)
            requests.clear()
            byte_result = media.convert_bytes(path.read_bytes(), format="m4a", source="recording:v1",
                                               task="transcribe", config=config, options=options)
        self.assertTrue(file_result.success, file_result.error)
        self.assertEqual(asdict(file_result), asdict(byte_result))
        self.assertEqual(file_result.segments[0].start_seconds, 0)
        self.assertEqual(file_result.segments[-1].end_seconds, 3.75)
        self.assertEqual([r["media_bytes"] for r in file_requests],
                         [r["media_bytes"] for r in requests])
        self.assertGreater(len(file_result.segments), 1)
        frames = []
        previous_end = 0
        for segment, request in zip(file_result.segments, requests, strict=True):
            with wave.open(BytesIO(request["media_bytes"])) as handle:
                duration = handle.getnframes() / handle.getframerate()
                frames.append(handle.readframes(handle.getnframes()))
            self.assertEqual(segment.start_seconds, previous_end)
            self.assertAlmostEqual(segment.end_seconds - segment.start_seconds, duration, delta=1 / 16000)
            self.assertEqual((segment.time_precision, segment.speaker), ("segment", None))
            previous_end = segment.end_seconds
        pcm = b"".join(frames)
        self.assertEqual(len(pcm), 120000)
        self.assert_first_track_tones(pcm)

    def test_temporary_media_is_removed_on_success_and_each_failure_stage(self):
        path = SAMPLES / "audio_extra_tracks_offset.m4a"
        for format, options, fail_at, code, stage in (
            ("m4a", media.ProcessingOptions(audio_segment_seconds=1.25), None, None, None),
            ("wav", media.ProcessingOptions(), None, "format_mismatch", "probe"),
            ("m4a", media.ProcessingOptions(ffmpeg="missing-rag-ffmpeg"), None,
             "missing_media_tool", "prepare"),
            ("m4a", media.ProcessingOptions(audio_segment_seconds=1.25), 2,
             "service_error", "audio"),
        ):
            with self.subTest(code=code):
                with TemporaryDirectory(prefix="audio-extra-test-") as directory:
                    results = []
                    for entry in ("file", "bytes"):
                        with media_server(fail_at=fail_at) as (config, _), patch("tempfile.tempdir", directory):
                            kwargs = dict(format=format, source="recording:cleanup", task="transcribe",
                                          media_id="course", media_version="v2", config=config, options=options)
                            result = (media.convert_file(path, **kwargs) if entry == "file" else
                                      media.convert_bytes(path.read_bytes(), **kwargs))
                            results.append(result)
                            self.assertEqual(list(Path(directory).iterdir()), [])
                self.assertEqual(asdict(results[0]), asdict(results[1]))
                for result in results:
                    self.assertEqual(result.source.sha256, EXTRA["samples"][0]["sha256"])
                    self.assertEqual((result.source.location, result.source.media_id, result.source.media_version),
                                     ("recording:cleanup", "course", "v2"))
                    if code is None:
                        self.assertTrue(result.success, result.error)
                    else:
                        self.assertFalse(result.success)
                        self.assertEqual((result.error.code, result.error.stage), (code, stage))
                        self.assertIsNone(result.text)
                        self.assertEqual(result.segments, [])

    def test_same_source_name_keeps_distinct_original_bytes_without_inventing_business_version(self):
        samples = [EXTRA["samples"][0], next(s for s in MANIFEST["samples"]
                                           if s["filename"] == "media_rules.m4a")]
        identities = []
        with media_server(asr={"text": "固定响应"}) as (config, _):
            for sample in samples:
                with self.subTest(sample=sample["filename"]):
                    path = SAMPLES / sample["filename"]
                    kwargs = dict(format="m4a", source="same-recording-v2.m4a", task="transcribe", config=config)
                    file_result = media.convert_file(path, **kwargs)
                    byte_result = media.convert_bytes(path.read_bytes(), **kwargs)
                    self.assertTrue(file_result.success, file_result.error)
                    self.assertEqual(asdict(file_result), asdict(byte_result))
                    self.assertEqual(file_result.source.location, "same-recording-v2.m4a")
                    self.assertEqual(file_result.source.sha256, sample["sha256"])
                    self.assertIsNone(file_result.source.media_id)
                    self.assertIsNone(file_result.source.media_version)
                    identities.append(file_result.source.sha256)
        self.assertNotEqual(*identities)

    def test_compressed_audio_bytes_match_empty_file_result_and_original_version(self):
        with media_server(asr={"text": ""}) as (config, _):
            for format in ("mp3", "m4a", "ogg", "flac"):
                with self.subTest(format=format):
                    filename = "media_rules." + format
                    path = SAMPLES / filename
                    kwargs = dict(format=format, source="recording:empty", task="transcribe", config=config)
                    file_result = media.convert_file(path, **kwargs)
                    byte_result = media.convert_bytes(path.read_bytes(), **kwargs)
                    self.assertTrue(byte_result.success, byte_result.error)
                    self.assertEqual(asdict(file_result), asdict(byte_result))
                    self.assertEqual(byte_result.source.sha256,
                                     next(s["sha256"] for s in MANIFEST["samples"] if s["filename"] == filename))
                    self.assertEqual((byte_result.status, byte_result.text), ("no_text", ""))
                    self.assertTrue(byte_result.requires_review)
                    self.assertTrue(byte_result.warnings)
                    self.assertIsNone(byte_result.error)

    def test_runtime_audio_configuration_and_explicit_override_stay_independent_of_visual_model(self):
        path = SAMPLES / "audio_extra_tracks_offset.m4a"
        with media_server() as (config, _):
            environment = {"STEP_API_KEY": "test-key", "STEP_BASE_URL": config.base_url,
                           "STEP_ASR_MODEL": "stepaudio-2.5-asr", "STEP_MODEL": "visual-only-model"}
            with patch.dict(os.environ, environment):
                result = media.convert_file(path, task="transcribe")
            self.assertTrue(result.success, result.error)
            self.assertEqual(result.segments[0].requested_model, "stepaudio-2.5-asr")
            environment.update(STEP_API_KEY="wrong-runtime-key", STEP_BASE_URL=config.base_url + "/wrong",
                               STEP_ASR_MODEL="wrong-runtime-asr")
            with patch.dict(os.environ, environment):
                result = media.convert_bytes(path.read_bytes(), format="m4a", source="recording:override",
                                               task="transcribe", config=replace(config, video_model=None))
            self.assertTrue(result.success, result.error)
            self.assertEqual(result.segments[0].requested_model, "stepaudio-2.5-asr")

    def assert_first_track_tones(self, frames):
        """用构造时已知的频率核验上传音轨，避免只信结果中的音轨编号。"""
        values = struct.unpack(f"<{len(frames) // 2}h", frames)
        for start, expected_hz in ((0.4, 300), (1.7, 600), (2.9, 900)):
            window = values[round(start * 16000):round((start + 0.2) * 16000)]
            crossings = sum(left <= 0 < right for left, right in zip(window, window[1:]))
            self.assertAlmostEqual(crossings / 0.2, expected_hz, delta=5)


if __name__ == "__main__":
    unittest.main()
