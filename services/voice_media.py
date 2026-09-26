"""Local validation and conversion for optional custom-voice recordings."""

import hashlib
import logging
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

logger = logging.getLogger("winged-tycoons.voice-media")

DEFAULT_CONSENT_PATH = Path(r"C:\Users\camil\Downloads\Consent OpenAI.m4a")
DEFAULT_SAMPLE_PATH = Path(r"C:\Users\camil\Downloads\Open AI sample.m4a")
MAX_SAMPLE_BYTES = 10 * 1024 * 1024
MAX_SAMPLE_DURATION_SECONDS = 30.0
MIN_SAMPLE_DURATION_SECONDS = 5.0
TARGET_SAMPLE_RATE = 24_000


def resolve_voice_recording_paths() -> dict[str, Path]:
    return {
        "consent": Path(os.getenv("VOICE_CONSENT_PATH", str(DEFAULT_CONSENT_PATH))).expanduser(),
        "sample": Path(os.getenv("VOICE_SAMPLE_PATH", str(DEFAULT_SAMPLE_PATH))).expanduser(),
    }


def _conversion_path(kind: str, source: Path, stat: os.stat_result) -> Path:
    identity = f"{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
    suffix = hashlib.sha256(identity).hexdigest()[:16]
    cache_dir = Path(os.getenv("VOICE_MEDIA_CACHE_DIR", str(Path(tempfile.gettempdir()) / "winged-tycoons" / "voice-media")))
    return cache_dir / f"{kind}-{suffix}.wav"


def _read_wav_metadata(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        frame_count = wav_file.getnframes()
    if channels != 1 or sample_rate != TARGET_SAMPLE_RATE or sample_width != 2:
        raise ValueError("Converted audio is not mono PCM16 at 24kHz.")
    return {
        "converted_path": str(path),
        "channels": channels,
        "sample_rate": sample_rate,
        "sample_width_bytes": sample_width,
        "duration_seconds": round(frame_count / sample_rate, 3),
    }


def _convert_to_pcm16(
    source: Path,
    destination: Path,
    max_duration_seconds: float | None = None,
) -> dict[str, Any]:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError("Install imageio-ffmpeg to enable local M4A conversion.") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
    ]
    if max_duration_seconds is not None:
        command.extend(["-t", str(max_duration_seconds)])
    command.append(str(destination))
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    if completed.returncode != 0:
        destination.unlink(missing_ok=True)
        message = completed.stderr.strip()[-500:] or "FFmpeg could not decode the audio file."
        raise ValueError(message)
    try:
        return _read_wav_metadata(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _prepare_recording(kind: str, source: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"configured_path": str(source), "status": "missing"}
    if not source.is_file():
        result["message"] = "Recording file was not found; voice sessions will use the built-in voice."
        return result

    stat = source.stat()
    result["size_bytes"] = stat.st_size
    if source.suffix.lower() not in {".m4a", ".mp4", ".wav", ".mp3", ".aac", ".ogg", ".flac", ".webm"}:
        result.update(status="invalid", message="Unsupported recording format.")
        return result
    if kind == "sample" and stat.st_size > MAX_SAMPLE_BYTES:
        result.update(status="invalid", message="Voice sample exceeds the 10 MiB upload limit.")
        return result

    destination = _conversion_path(kind, source, stat)
    try:
        metadata = _read_wav_metadata(destination) if destination.is_file() else _convert_to_pcm16(source, destination)
        duration = metadata["duration_seconds"]
        if kind == "sample" and duration > MAX_SAMPLE_DURATION_SECONDS:
            destination.unlink(missing_ok=True)
            metadata = _convert_to_pcm16(source, destination, MAX_SAMPLE_DURATION_SECONDS)
            metadata["source_duration_seconds"] = duration
            metadata["trimmed_to_limit"] = True
            duration = metadata["duration_seconds"]
        result.update(status="ready", **metadata)
        if kind == "sample" and not MIN_SAMPLE_DURATION_SECONDS <= duration <= MAX_SAMPLE_DURATION_SECONDS:
            result.update(
                status="invalid",
                message="Voice sample must contain 5 to 30 seconds of audio for custom-voice registration.",
            )
        return result
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        result.update(status="invalid", message=str(exc)[:500])
        return result


def initialize_voice_media() -> dict[str, Any]:
    """Convert configured local recordings when present; never call external APIs."""
    paths = resolve_voice_recording_paths()
    results = {kind: _prepare_recording(kind, path) for kind, path in paths.items()}
    for kind, result in results.items():
        logger.info(
            "voice_recording_initialized kind=%s status=%s duration_seconds=%s",
            kind,
            result["status"],
            result.get("duration_seconds"),
        )
    return results