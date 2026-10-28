from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
import json
import struct
import unittest
import wave

from tests.test_audio_video import SAMPLES, media, media_server, video_reply


MANIFEST = json.loads((SAMPLES / "media_review_samples.json").read_text(encoding="utf-8"))


class MediaReviewRegressionTests(unittest.TestCase):
    def test_delayed_audio_range_matches_uploaded_wav_and_original_playback(self):
        self.assert_delayed_audio_contract(media.ProcessingOptions())

    def test_one_second_audio_slices_keep_delayed_origin_and_complete_waveform(self):
        self.assert_delayed_audio_contract(media.ProcessingOptions(audio_segment_seconds=1))

    def assert_delayed_audio_contract(self, options):
        for sample in MANIFEST["samples"]:
            path = SAMPLES / sample["filename"]
            data = path.read_bytes()
            self.assertEqual(len(data), sample["bytes"])
            self.assertEqual(sha256(data).hexdigest(), sample["sha256"])
            results, uploads = [], []
            for entry in ("file", "bytes"):
                with self.subTest(sample=sample["filename"], entry=entry):
                    with media_server(asr={"text": "固定音轨响应"},
                                      video=video_reply("固定画面响应")) as (config, requests):
                        kwargs = dict(task="both", source="review:delayed-audio", config=config, options=options)
                        result = (media.convert_file(path, **kwargs) if entry == "file" else
                                  media.convert_bytes(data, format="mp4", **kwargs))
                    self.assertTrue(result.success, result.error)
                    results.append(asdict(result))
                    self.assertEqual(result.source.audio_stream_index, 1)
                    self.assertEqual(result.source.duration_seconds, 6)
                    self.assertEqual(result.source.sha256, sample["sha256"])
                    self.assertEqual(result.source.location, "review:delayed-audio")
                    self.assertTrue(result.requires_review)
                    self.assertEqual([(s.start_seconds, s.end_seconds) for s in result.segments if s.kind == "video"],
                                     [(0, 6)])
                    audio = [s for s in result.segments if s.kind == "audio"]
                    self.assertEqual((audio[0].start_seconds, audio[-1].end_seconds), (1.25, 3.25))
                    if options.audio_segment_seconds == 30:
                        self.assertEqual(len(audio), 1)
                    else:
                        self.assertGreater(len(audio), 1)
                    self.assertEqual([s.kind for s in result.segments], ["video"] + ["audio"] * len(audio))
                    self.assertEqual([r["path"] for r in requests],
                                     ["/v1/chat/completions"] + ["/v1/audio/transcriptions"] * len(audio))
                    self.assertLess(result.text.index("固定画面响应"), result.text.index("固定音轨响应"))
                    previous_end, frames = 1.25, []
                    for segment, request in zip(audio, requests[1:], strict=True):
                        with wave.open(BytesIO(request["media_bytes"])) as handle:
                            self.assertEqual((handle.getnchannels(), handle.getsampwidth(), handle.getframerate()),
                                             (1, 2, 16000))
                            duration = handle.getnframes() / handle.getframerate()
                            frames.append(handle.readframes(handle.getnframes()))
                        self.assertEqual(segment.start_seconds, previous_end)
                        self.assertAlmostEqual(segment.end_seconds - segment.start_seconds, duration, delta=1 / 16000)
                        self.assertEqual((segment.speaker, segment.time_precision), (None, "segment"))
                        previous_end = segment.end_seconds
                    pcm = b"".join(frames)
                    self.assertEqual(len(pcm), 64000)
                    values = struct.unpack(f"<{len(pcm) // 2}h", pcm)
                    for start, frequency in ((0.3, 300), (1.3, 600)):
                        window = values[round(start * 16000):round((start + 0.2) * 16000)]
                        crossings = sum(left <= 0 < right for left, right in zip(window, window[1:]))
                        self.assertAlmostEqual(crossings / 0.2, frequency, delta=5)
                    uploads.append(pcm)
            self.assertEqual(results[0], results[1])
            self.assertEqual(uploads[0], uploads[1])


if __name__ == "__main__":
    unittest.main()
