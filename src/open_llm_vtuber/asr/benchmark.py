import asyncio
import importlib.util
import os
import re
import time
import wave
from pathlib import Path
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import numpy as np
from loguru import logger

from ..config_manager import ASRConfig
from ..service_context import ServiceContext
from .asr_factory import ASRFactory


SUPPORTED_PROVIDERS = (
    "qwen3_asr",
    "qwen3_asr_gguf",
    "faster_whisper",
    "sherpa_onnx_asr",
    "fun_asr",
    "whisper",
    "whisper_cpp",
    "groq_whisper_asr",
    "azure_asr",
)

PROVIDER_PACKAGES = {
    "qwen3_asr": "qwen_asr",
    "qwen3_asr_gguf": None,
    "faster_whisper": "faster_whisper",
    "sherpa_onnx_asr": "sherpa_onnx",
    "fun_asr": "funasr",
    "whisper": "whisper",
    "whisper_cpp": "pywhispercpp",
    "groq_whisper_asr": "groq",
    "azure_asr": "azure.cognitiveservices.speech",
}

GPU_PROVIDERS = {"qwen3_asr", "qwen3_asr_gguf"}


def _to_runtime_path(path: str) -> str:
    if os.name == "nt" or not re.match(r"^[A-Za-z]:[\\/]", path or ""):
        return path

    drive = path[0].lower()
    rest = path[2:].replace("\\", "/").lstrip("/")
    return f"/mnt/{drive}/{rest}"


@dataclass(frozen=True)
class DecodedAudio:
    samples: np.ndarray
    sample_rate: int
    channels: int
    duration_ms: float


def decode_wav_bytes(contents: bytes) -> DecodedAudio:
    if len(contents) < 44:
        raise ValueError("Invalid WAV file: file is too small")

    with wave.open(BytesIO(contents), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        frame_count = wav_file.getnframes()
        pcm = wav_file.readframes(frame_count)

    if sample_width != 2:
        raise ValueError("Only 16-bit PCM WAV is supported")
    if sample_rate != 16000:
        raise ValueError(f"Only 16 kHz WAV is supported, got {sample_rate} Hz")
    if channels < 1:
        raise ValueError("WAV file must contain at least one channel")

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.float32)

    duration_ms = (len(samples) / sample_rate) * 1000 if sample_rate else 0
    if len(samples) == 0:
        raise ValueError("Empty WAV audio data")

    return DecodedAudio(
        samples=samples,
        sample_rate=sample_rate,
        channels=channels,
        duration_ms=duration_ms,
    )


def _levenshtein(left: list[str], right: list[str]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for i, left_item in enumerate(left, 1):
        current = [i]
        for j, right_item in enumerate(right, 1):
            cost = 0 if left_item == right_item else 1
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def _normalize_text(text: str) -> str:
    return "".join((text or "").split()).lower()


def cer(reference: str, hypothesis: str) -> float | None:
    normalized_reference = _normalize_text(reference)
    normalized_hypothesis = _normalize_text(hypothesis)
    if not normalized_reference:
        return None
    return _levenshtein(
        list(normalized_reference), list(normalized_hypothesis)
    ) / len(normalized_reference)


def wer(reference: str, hypothesis: str) -> float | None:
    reference_words = (reference or "").strip().split()
    hypothesis_words = (hypothesis or "").strip().split()
    if not reference_words:
        return None
    return _levenshtein(reference_words, hypothesis_words) / len(reference_words)


def hotword_hits(text: str, hotwords: list[str]) -> list[str]:
    normalized_text = _normalize_text(text)
    hits = []
    for word in hotwords:
        normalized_word = _normalize_text(word)
        if normalized_word and normalized_word in normalized_text:
            hits.append(word)
    return hits


class ASRBenchmarkManager:
    def __init__(self, default_context: ServiceContext) -> None:
        self.default_context = default_context
        self._engine_cache: dict[str, Any] = {}
        self._cache_lock = asyncio.Lock()
        self._gpu_lock = asyncio.Lock()

    def provider_status(self) -> dict[str, Any]:
        asr_config = self._asr_config()
        providers = []
        for provider in SUPPORTED_PROVIDERS:
            provider_config = getattr(asr_config, provider, None)
            package_name = PROVIDER_PACKAGES.get(provider)
            package_available = (
                importlib.util.find_spec(package_name) is not None
                if package_name
                else True
            )
            configured = provider_config is not None
            available = configured and package_available
            reason = ""
            if not configured:
                reason = "not configured"
            elif not package_available:
                reason = f"missing package: {package_name}"
            elif provider == "qwen3_asr_gguf":
                executable = getattr(provider_config, "executable", "")
                if not Path(_to_runtime_path(executable)).is_file():
                    available = False
                    reason = f"missing executable: {executable}"

            providers.append(
                {
                    "name": provider,
                    "enabled": provider == asr_config.asr_model,
                    "available": available,
                    "reason": reason,
                    "supports_hotwords": provider
                    in {
                        "qwen3_asr",
                        "qwen3_asr_gguf",
                        "faster_whisper",
                        "whisper",
                        "whisper_cpp",
                        "sherpa_onnx_asr",
                    },
                    "mode": self._hotword_mode(provider),
                }
            )

        return {
            "current_asr": asr_config.asr_model,
            "hotwords": asr_config.hotwords,
            "providers": providers,
        }

    async def transcribe_many(
        self,
        provider_names: list[str],
        audio: DecodedAudio,
        hotwords: list[str],
        reference_text: str = "",
    ) -> dict[str, Any]:
        selected = [name for name in provider_names if name in SUPPORTED_PROVIDERS]
        if not selected:
            raise ValueError("No supported ASR providers selected")

        tasks = [
            self.transcribe_one(provider, audio, hotwords, reference_text)
            for provider in selected
        ]
        results = await asyncio.gather(*tasks)
        return {
            "audio": {
                "duration_ms": round(audio.duration_ms, 3),
                "sample_rate": audio.sample_rate,
                "channels": audio.channels,
            },
            "results": results,
        }

    async def transcribe_one(
        self,
        provider: str,
        audio: DecodedAudio,
        hotwords: list[str],
        reference_text: str = "",
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            if provider in GPU_PROVIDERS:
                async with self._gpu_lock:
                    text = await self._transcribe(provider, audio, hotwords)
            else:
                text = await self._transcribe(provider, audio, hotwords)

            elapsed_ms = (time.perf_counter() - started) * 1000
            return {
                "provider": provider,
                "text": text,
                "elapsed_ms": round(elapsed_ms, 3),
                "rtf": round(elapsed_ms / audio.duration_ms, 4)
                if audio.duration_ms
                else None,
                "hotword_hits": hotword_hits(text, hotwords),
                "cer": cer(reference_text, text),
                "wer": wer(reference_text, text),
                "error": None,
            }
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.error(f"ASR benchmark failed for {provider}: {exc}", exc_info=True)
            return {
                "provider": provider,
                "text": "",
                "elapsed_ms": round(elapsed_ms, 3),
                "rtf": round(elapsed_ms / audio.duration_ms, 4)
                if audio.duration_ms
                else None,
                "hotword_hits": [],
                "cer": None,
                "wer": None,
                "error": str(exc),
            }

    async def _transcribe(
        self, provider: str, audio: DecodedAudio, hotwords: list[str]
    ) -> str:
        engine = await self._get_engine(provider, hotwords)
        return await engine.async_transcribe_np(audio.samples)

    async def _get_engine(self, provider: str, hotwords: list[str]) -> Any:
        asr_config = self._asr_config()
        if provider == asr_config.asr_model and self.default_context.asr_engine:
            return self.default_context.asr_engine

        async with self._cache_lock:
            if provider in self._engine_cache:
                return self._engine_cache[provider]

            provider_config = getattr(asr_config, provider, None)
            if provider_config is None:
                raise ValueError(f"ASR provider is not configured: {provider}")

            kwargs = provider_config.model_dump()
            kwargs["hotwords"] = hotwords or asr_config.hotwords
            engine = ASRFactory.get_asr_system(provider, **kwargs)
            self._engine_cache[provider] = engine
            return engine

    def _asr_config(self) -> ASRConfig:
        if not self.default_context.character_config:
            raise RuntimeError("Service context is not initialized")
        return self.default_context.character_config.asr_config

    @staticmethod
    def _hotword_mode(provider: str) -> str:
        if provider in {"qwen3_asr", "qwen3_asr_gguf"}:
            return "context"
        if provider in {"faster_whisper", "whisper", "whisper_cpp"}:
            return "prompt"
        if provider == "sherpa_onnx_asr":
            return "native_file"
        return "none"
