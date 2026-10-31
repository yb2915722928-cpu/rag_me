from dataclasses import asdict, replace
import os
import unittest
from unittest.mock import patch

from tests.test_audio_video import SAMPLES, media, media_server, video_reply
from tests.test_image_ocr import envelope, images, step_server


class StepFunConsumerContractTests(unittest.TestCase):
    def test_public_configs_keep_distinct_defaults_and_reject_each_others_type(self):
        self.assertIsNot(images.StepFunConfig, media.StepFunConfig)
        self.assertEqual(asdict(images.StepFunConfig()), {
            "api_key": None, "base_url": None, "model": None, "timeout": 90,
        })
        self.assertEqual(asdict(media.StepFunConfig()), {
            "api_key": None, "base_url": None, "asr_model": None,
            "video_model": None, "timeout": 180,
        })
        for parser, filename, task, config in (
            (images, "image_ocr_rules.png", "ocr", media.StepFunConfig()),
            (media, "media_rules.wav", "transcribe", images.StepFunConfig()),
        ):
            with self.subTest(task=task):
                result = parser.convert_file(SAMPLES / filename, task=task, config=config)
                self.assertEqual((result.status, result.text), ("failed", None))
                self.assertEqual((result.error.code, result.error.message),
                                 ("invalid_config", "config must be StepFunConfig"))

    def test_shared_config_checks_preserve_error_wording_and_validation_order(self):
        cases = (
            ({"api_key": ""}, "missing_config", "Set STEP_API_KEY or StepFunConfig.api_key",
             "Set STEP_API_KEY or StepFunConfig.api_key"),
            ({"base_url": ""}, "missing_config", "Set STEP_BASE_URL or StepFunConfig.base_url",
             "Set STEP_BASE_URL or StepFunConfig.base_url"),
            ({"base_url": "https://user:secret@example.org/v1?token=secret"}, "invalid_config",
             "STEP_BASE_URL must be an HTTP(S) API base URL", "Invalid STEP_BASE_URL or STEP_API_KEY"),
            ({"api_key": "密钥"}, "invalid_config", "Invalid STEP_API_KEY",
             "Invalid STEP_BASE_URL or STEP_API_KEY"),
            ({"timeout": True}, "invalid_config", "timeout must be a finite positive number of seconds",
             "timeout must be finite and positive"),
            ({"base_url": "invalid", "timeout": 0}, "invalid_config",
             "STEP_BASE_URL must be an HTTP(S) API base URL", "Invalid STEP_BASE_URL or STEP_API_KEY"),
        )
        configs = (
            (images, "image_ocr_rules.png", "ocr", images.StepFunConfig(
                api_key="private-key", base_url="http://127.0.0.1:1/v1", model="vision")),
            (media, "media_rules.wav", "transcribe", media.StepFunConfig(
                api_key="private-key", base_url="http://127.0.0.1:1/v1", asr_model="asr")),
        )
        environment = {name: value for name, value in os.environ.items() if not name.startswith("STEP_")}
        with patch.dict(os.environ, environment, clear=True):
            for changes, code, image_message, media_message in cases:
                for (parser, filename, task, config), message in zip(
                        configs, (image_message, media_message), strict=True):
                    with self.subTest(task=task, changes=changes):
                        result = parser.convert_file(SAMPLES / filename, task=task,
                                                     config=replace(config, **changes))
                        self.assertEqual((result.error.code, result.error.message), (code, message))
                        self.assertIsNone(result.text)
                        self.assertIsNotNone(result.source.sha256)
                        if task == "transcribe":
                            self.assertEqual((result.error.stage, result.segments), ("config", []))

    def test_image_and_video_keep_their_envelope_failure_diagnostics(self):
        invalid_model = envelope()
        invalid_model["model"] = " "
        truncated = envelope()
        truncated["choices"][0]["finish_reason"] = "length"
        refused = envelope()
        refused["choices"][0]["message"]["refusal"] = "private-key"
        for reply, image_message in (
            ([], "StepFun response must be an object"),
            (invalid_model, "Invalid response model identifier"),
            ({"choices": []}, "StepFun response requires one completion"),
            (truncated, "StepFun completion was not normally finished"),
            (refused, "StepFun response has no usable content or was refused"),
        ):
            with self.subTest(reply=reply), step_server(reply) as config:
                image = images.convert_file(SAMPLES / "image_ocr_rules.png", task="ocr", config=config)
                self.assertEqual((image.error.code, image.error.message), ("protocol_error", image_message))
                self.assertIsNone(image.text)
            with self.subTest(video=reply), media_server(video=reply) as (config, requests):
                video = media.convert_file(SAMPLES / "media_timeline.mp4", task="video", config=config)
                self.assertEqual((video.error.code, video.error.message), (
                    "protocol_error", "Video response is incomplete or has invalid fields"))
                self.assertEqual((video.error.stage, video.error.start_seconds), ("video", 0))
                self.assertEqual((video.text, video.segments), (None, []))
                self.assertEqual(len(requests), 1)

    def test_no_text_remains_an_ocr_result_and_is_rejected_for_video(self):
        with step_server(envelope("", "no_text")) as config:
            image = images.convert_file(SAMPLES / "image_ocr_blank.png", task="ocr", config=config)
        self.assertEqual((image.status, image.text), ("no_text", ""))
        self.assertTrue(image.requires_review)
        with media_server(video=video_reply("", "no_text")) as (config, _):
            video = media.convert_file(SAMPLES / "media_timeline.mp4", task="video", config=config)
        self.assertEqual((video.status, video.text, video.segments), ("failed", None, []))
        self.assertEqual(video.error.code, "protocol_error")


if __name__ == "__main__":
    unittest.main()
