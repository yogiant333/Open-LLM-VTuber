from __future__ import annotations

import json
import math
import os
import re
import time
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from loguru import logger


DEFAULT_CAPTURE_DIR = Path("reports/asr_captures")


def asr_capture_enabled() -> bool:
    value = os.getenv("ASR_CAPTURE_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def provider_name_from_engine(asr_engine: Any) -> str:
    module = getattr(asr_engine.__class__, "__module__", "")
    if ".asr." in module:
        return module.rsplit(".asr.", 1)[-1].removesuffix("_asr") + "_asr"
    return asr_engine.__class__.__name__


def save_asr_capture(
    *,
    audio: np.ndarray,
    transcript: str,
    provider: str,
    source: str,
    elapsed_ms: float,
    sample_rate: int = 16000,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not asr_capture_enabled():
        return None

    capture_dir = Path(os.getenv("ASR_CAPTURE_DIR", str(DEFAULT_CAPTURE_DIR)))
    day_dir = capture_dir / time.strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    safe_source = _safe_part(source)
    safe_provider = _safe_part(provider)
    stem = f"{time.strftime('%H%M%S')}_{safe_source}_{safe_provider}_{uuid4().hex[:8]}"
    wav_path = day_dir / f"{stem}.wav"
    json_path = day_dir / f"{stem}.json"

    audio_f32 = _as_float32_mono(audio)
    pcm = (np.clip(audio_f32, -1.0, 1.0) * 32767).astype(np.int16)

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())

    duration_ms = len(audio_f32) / sample_rate * 1000 if sample_rate else 0.0
    meta = {
        "schema_version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": source,
        "provider": provider,
        "transcript": transcript,
        "elapsed_ms": round(elapsed_ms, 3),
        "rtf": round(elapsed_ms / duration_ms, 4) if duration_ms else None,
        "audio": {
            "path": str(wav_path),
            "sample_rate": sample_rate,
            "channels": 1,
            "sample_width": 2,
            "duration_ms": round(duration_ms, 3),
            "samples": int(len(audio_f32)),
            "peak_dbfs": _peak_dbfs(audio_f32),
            "rms_dbfs": _rms_dbfs(audio_f32),
        },
        "metadata": metadata or {},
    }
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ASR capture saved: {}", json_path)
    return meta


def _as_float32_mono(audio: np.ndarray) -> np.ndarray:
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype(np.float32)
    return np.clip(audio, -1.0, 1.0)


def _rms_dbfs(audio: np.ndarray) -> float | None:
    if audio.size == 0:
        return None
    rms = float(np.sqrt(np.mean(np.square(audio))))
    return round(20 * math.log10(max(rms, 1e-12)), 3)


def _peak_dbfs(audio: np.ndarray) -> float | None:
    if audio.size == 0:
        return None
    peak = float(np.max(np.abs(audio)))
    return round(20 * math.log10(max(peak, 1e-12)), 3)


def _safe_part(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())
    return safe.strip("-")[:60] or "unknown"
