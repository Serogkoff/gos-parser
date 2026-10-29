"""Loopback HTTP service for local GigaAM transcription.

The service deliberately binds to 127.0.0.1 and accepts browser requests only
from the Monitor origins listed in ``GOS_TRANSCRIBER_ORIGINS``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HOST = "127.0.0.1"
PORT = int(os.getenv("GOS_TRANSCRIBER_PORT", "8765"))
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_CHUNK_BYTES = 5 * 1024 * 1024
ALLOWED_REQUEST_HEADERS = "Content-Type, X-Upload-Offset"
DEFAULT_ORIGINS = {
    "https://ria.tail196372.ts.net",
    "http://127.0.0.1:5000",
    "http://localhost:5000",
}
ALLOWED_ORIGINS = {
    item.strip().rstrip("/")
    for item in os.getenv("GOS_TRANSCRIBER_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",")
    if item.strip()
}


def _duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        rate = max(1, audio.getframerate())
        return audio.getnframes() / rate


class GigaamRecognizer:
    """Lazy, reusable CPU recognizer. Model files remain in the local cache."""

    def __init__(self):
        self._models = {}
        self._vad = None
        self._lock = threading.Lock()

    def _load(self, mode):
        if mode not in self._models:
            import onnx_asr

            if self._vad is None:
                self._vad = onnx_asr.load_vad("silero")
            model_name = (
                "gigaam-v3-e2e-rnnt"
                if mode == "accurate"
                else "gigaam-v3-e2e-ctc"
            )
            base = onnx_asr.load_model(model_name, quantization="int8")
            self._models[mode] = base.with_vad(self._vad)
        return self._models[mode]

    def transcribe(self, path: Path, progress, mode="fast"):
        with self._lock:
            model = self._load(mode)
            duration = max(0.1, _duration_seconds(path))
            segments = []
            for index, result in enumerate(model.recognize(str(path), channel="mean"), start=1):
                text = str(result.text or "").strip()
                if text:
                    segments.append({
                        "start": float(result.start),
                        "end": float(result.end),
                        "text": text,
                    })
                progress(index, min(99, round(float(result.end) / duration * 100)))
            return segments


@dataclass
class Job:
    job_id: str
    path: Path
    filename: str
    size: int
    mode: str = "fast"
    received: int = 0
    status: str = "uploading"
    progress: int = 0
    fragment: int = 0
    text: str = ""
    segments: list[dict] = field(default_factory=list)
    error: str = ""
    updated_at: float = field(default_factory=time.time)

    def public(self):
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "size": self.size,
            "mode": self.mode,
            "received": self.received,
            "status": self.status,
            "progress": self.progress,
            "fragment": self.fragment,
            "text": self.text,
            "segments": self.segments,
            "error": self.error,
        }


class JobStore:
    def __init__(self, root: Path | None = None, recognizer=None):
        self.root = Path(root or Path(tempfile.gettempdir()) / "gos-parser-transcriber")
        self.root.mkdir(parents=True, exist_ok=True)
        self.recognizer = recognizer or GigaamRecognizer()
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def create(self, filename: str, size: int, mode: str = "fast") -> Job:
        if size <= 0 or size > MAX_FILE_BYTES:
            raise ValueError("Недопустимый размер записи")
        safe_name = Path(filename or "recording.wav").name
        if not safe_name.lower().endswith(".wav"):
            raise ValueError("Локальный распознаватель принимает только WAV")
        if mode not in {"fast", "accurate"}:
            raise ValueError("Неизвестный режим распознавания")
        job_id = uuid.uuid4().hex
        job_dir = self.root / job_id
        job_dir.mkdir()
        job = Job(job_id, job_dir / "recording.wav", safe_name, size, mode=mode)
        job.path.touch()
        with self.lock:
            self.jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job:
        with self.lock:
            job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        return job

    def upload(self, job_id: str, offset: int, data: bytes) -> Job:
        job = self.get(job_id)
        if job.status != "uploading":
            raise ValueError("Загрузка уже завершена")
        if offset != job.received:
            raise ValueError(f"Ожидалось смещение {job.received}")
        if not data or len(data) > MAX_CHUNK_BYTES or offset + len(data) > job.size:
            raise ValueError("Недопустимый фрагмент")
        with job.path.open("ab") as output:
            output.write(data)
        job.received += len(data)
        job.progress = round(job.received / job.size * 100)
        job.updated_at = time.time()
        return job

    def start(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status != "uploading" or job.received != job.size:
            raise ValueError("Запись загружена не полностью")
        job.status = "queued"
        job.progress = 0
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job):
        try:
            job.status = "processing"

            def update(fragment, progress):
                job.fragment = fragment
                job.progress = progress
                job.updated_at = time.time()

            job.segments = self.recognizer.transcribe(job.path, update, job.mode)
            job.text = " ".join(
                item["text"].strip() for item in job.segments if item["text"].strip()
            )
            job.progress = 100
            job.status = "complete"
        except Exception as error:
            logging.exception("Local transcription failed")
            job.status = "error"
            job.error = str(error) or type(error).__name__
        finally:
            job.updated_at = time.time()

    def delete(self, job_id: str):
        with self.lock:
            job = self.jobs.pop(job_id, None)
        if job:
            shutil.rmtree(job.path.parent, ignore_errors=True)


STORE = JobStore()


class Handler(BaseHTTPRequestHandler):
    server_version = "GosParserTranscriber/1.0"

    def log_message(self, message, *args):
        logging.info("%s - %s", self.address_string(), message % args)

    @property
    def origin(self):
        return (self.headers.get("Origin") or "").rstrip("/")

    def _allowed(self):
        return self.origin in ALLOWED_ORIGINS

    def _cors(self):
        if self._allowed():
            self.send_header("Access-Control-Allow-Origin", self.origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _reject_origin(self):
        if not self._allowed():
            self._json(403, {"error": "Этот сайт не может обращаться к распознавателю"})
            return True
        return False

    def do_OPTIONS(self):
        if self._reject_origin():
            return
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", ALLOWED_REQUEST_HEADERS)
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        if self._reject_origin():
            return
        parts = urlparse(self.path).path.strip("/").split("/")
        if parts == ["health"]:
            self._json(200, {
                "status": "ok",
                "engine": "GigaAM v3 E2E",
                "modes": ["fast", "accurate"],
            })
            return
        if len(parts) == 2 and parts[0] == "jobs":
            try:
                self._json(200, STORE.get(parts[1]).public())
            except KeyError:
                self._json(404, {"error": "Задание не найдено"})
            return
        self._json(404, {"error": "Не найдено"})

    def do_POST(self):
        if self._reject_origin():
            return
        parts = urlparse(self.path).path.strip("/").split("/")
        try:
            if parts == ["jobs"]:
                length = min(int(self.headers.get("Content-Length", "0")), 8192)
                payload = json.loads(self.rfile.read(length) or b"{}")
                job = STORE.create(
                    str(payload.get("filename", "recording.wav")),
                    int(payload.get("size", 0)),
                    str(payload.get("mode", "fast")),
                )
                self._json(201, job.public())
                return
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "start":
                self._json(202, STORE.start(parts[1]).public())
                return
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self._json(400, {"error": str(error)})
            return
        self._json(404, {"error": "Не найдено"})

    def do_PUT(self):
        if self._reject_origin():
            return
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "jobs" or parts[2] != "upload":
            self._json(404, {"error": "Не найдено"})
            return
        try:
            offset = int(self.headers.get("X-Upload-Offset", "-1"))
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_CHUNK_BYTES:
                raise ValueError("Фрагмент больше 5 МБ")
            self._json(200, STORE.upload(parts[1], offset, self.rfile.read(length)).public())
        except (ValueError, KeyError) as error:
            self._json(400, {"error": str(error)})

    def do_DELETE(self):
        if self._reject_origin():
            return
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "jobs":
            STORE.delete(parts[1])
            self._json(200, {"status": "deleted"})
            return
        self._json(404, {"error": "Не найдено"})


def configure_logging():
    data_dir = Path(os.getenv("LOCALAPPDATA", Path.home())) / "GosParserTranscriber"
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=data_dir / "transcriber.log",
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        encoding="utf-8",
    )


def main():
    configure_logging()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logging.info("Local transcriber started on http://%s:%s", HOST, PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
