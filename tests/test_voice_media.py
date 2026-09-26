import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from services.voice_media import _prepare_recording, resolve_voice_recording_paths


class VoiceMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_audio_fixture(self, path: Path, duration_seconds: int):
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(8000)
            wav_file.writeframes(b"\x00\x00" * 8000 * duration_seconds)

    def test_sample_is_converted_to_pcm16_24khz_and_trimmed_without_mutating_source(self):
        source = self.root / "customer-sample.m4a"
        self._write_audio_fixture(source, 33)
        original_bytes = source.read_bytes()
        with patch.dict(os.environ, {"VOICE_MEDIA_CACHE_DIR": str(self.root / "cache")}):
            result = _prepare_recording("sample", source)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["sample_rate"], 24000)
        self.assertEqual(result["sample_width_bytes"], 2)
        self.assertEqual(result["channels"], 1)
        self.assertEqual(result["duration_seconds"], 30.0)
        self.assertEqual(result["source_duration_seconds"], 33.0)
        self.assertTrue(result["trimmed_to_limit"])
        self.assertEqual(source.read_bytes(), original_bytes)

    def test_missing_recordings_are_reported_without_raising(self):
        result = _prepare_recording("consent", self.root / "missing.m4a")

        self.assertEqual(result["status"], "missing")
        self.assertIn("built-in voice", result["message"])

    def test_recording_paths_can_be_overridden_by_environment(self):
        with patch.dict(os.environ, {
            "VOICE_CONSENT_PATH": str(self.root / "consent.m4a"),
            "VOICE_SAMPLE_PATH": str(self.root / "sample.m4a"),
        }):
            result = resolve_voice_recording_paths()

        self.assertEqual(result["consent"], self.root / "consent.m4a")
        self.assertEqual(result["sample"], self.root / "sample.m4a")


if __name__ == "__main__":
    unittest.main()