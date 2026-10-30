import os
import tempfile
import time
import unittest
import wave
from pathlib import Path

from local_transcriber.server import (
    ALLOWED_REQUEST_HEADERS,
    MAX_CHUNK_BYTES,
    JobStore,
)


class FakeRecognizer:
    def transcribe(self, path, progress, mode="fast", state=lambda *_: None):
        self.path = path
        self.mode = mode
        state("loading_model", 2)
        state("recognizing", 3)
        progress(1, 45)
        progress(2, 90)
        return [
            {"start": 0.0, "end": 1.2, "text": "Первый фрагмент"},
            {"start": 1.5, "end": 3.0, "text": "Второй фрагмент"},
        ]


def wav_bytes():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output:
        path = Path(output.name)
    try:
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(b"\0\0" * 16_000)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


class LocalTranscriberTests(unittest.TestCase):
    def test_background_download_progress_is_disabled_for_pythonw(self):
        self.assertEqual(os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS"), "1")
        self.assertEqual(os.environ.get("TQDM_DISABLE"), "1")

    def test_chunk_offset_header_is_allowed_by_cors(self):
        self.assertIn("Content-Type", ALLOWED_REQUEST_HEADERS)
        self.assertIn("X-Upload-Offset", ALLOWED_REQUEST_HEADERS)

    def test_upload_is_ordered_and_transcription_keeps_timestamps(self):
        content = wav_bytes()
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory), FakeRecognizer())
            job = store.create("meeting.wav", len(content), "fast")
            split = min(len(content), MAX_CHUNK_BYTES)
            store.upload(job.job_id, 0, content[:split])
            if split < len(content):
                store.upload(job.job_id, split, content[split:])
            store.start(job.job_id)
            for _ in range(100):
                if job.status in {"complete", "error"}:
                    break
                time.sleep(0.01)
            self.assertEqual(job.status, "complete")
            self.assertEqual(job.progress, 100)
            self.assertEqual(job.text, "Первый фрагмент Второй фрагмент")
            self.assertEqual(store.recognizer.mode, "fast")
            self.assertEqual(job.stage, "complete")

    def test_rejects_wrong_offset_and_non_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory), FakeRecognizer())
            with self.assertRaisesRegex(ValueError, "только WAV"):
                store.create("recording.mp3", 100)
            with self.assertRaisesRegex(ValueError, "Неизвестный режим"):
                store.create("recording.wav", 100, "turbo")
            job = store.create("recording.wav", 100)
            with self.assertRaisesRegex(ValueError, "смещение 0"):
                store.upload(job.job_id, 10, b"abc")

    def test_delete_removes_temporary_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory), FakeRecognizer())
            job = store.create("recording.wav", 100)
            folder = job.path.parent
            store.delete(job.job_id)
            self.assertFalse(folder.exists())
            with self.assertRaises(KeyError):
                store.get(job.job_id)


if __name__ == "__main__":
    unittest.main()
