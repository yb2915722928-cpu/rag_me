import hashlib
import json
import unittest
from pathlib import Path


SAMPLES = Path(__file__).resolve().parents[1] / "testFile"


class PublicSampleIntegrityTests(unittest.TestCase):
    def test_public_samples_match_the_recorded_downloads(self):
        records = json.loads((SAMPLES / "sources.json").read_text(encoding="utf-8"))
        for record in records["samples"]:
            with self.subTest(filename=record["filename"]):
                payload = (SAMPLES / record["filename"]).read_bytes()
                self.assertEqual(len(payload), record["bytes"])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), record["sha256"])


if __name__ == "__main__":
    unittest.main()
