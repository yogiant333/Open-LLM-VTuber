from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
from loguru import logger

from ..config_manager.kws import KWSConfig
from ..vad.vad_interface import VADInterface
from .sherpa_onnx_kws import SherpaOnnxKWS


class AudioSessionState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


@dataclass
class AudioSessionEvent:
    type: str
    keyword: Optional[str] = None
    confidence: Optional[float] = None
    audio: Optional[np.ndarray] = None


class AudioSession:
    """Per-client KWS/VAD gate over one continuous audio stream."""

    def __init__(
        self,
        client_uid: str,
        config: KWSConfig,
        kws_engine: SherpaOnnxKWS,
        vad_engine: VADInterface,
    ):
        self.client_uid = client_uid
        self.config = config
        self.kws_engine = kws_engine
        self.vad_engine = vad_engine
        self.state = AudioSessionState.IDLE
        self._kws_stream = kws_engine.create_stream()
        self._ring_buffer: deque[np.ndarray] = deque()
        self._ring_samples = 0
        self._max_ring_samples = int(config.sample_rate * max(config.pre_roll_ms, 0) / 1000)
        self._last_wakeup_at = 0.0
        self._listening_started_at = 0.0
        self._last_user_activity_at = 0.0
        self._user_speech_active = False

    def accept_frame(self, samples: np.ndarray) -> list[AudioSessionEvent]:
        frame = self._normalize_samples(samples)
        if frame.size == 0:
            return []

        self._append_ring(frame)

        if self.state == AudioSessionState.IDLE:
            return self._process_idle(frame)

        if self.state == AudioSessionState.LISTENING:
            return self._process_listening(frame)

        if self.state in {AudioSessionState.PROCESSING, AudioSessionState.SPEAKING}:
            return self._process_speaking(frame)

        return []

    def mark_processing(self) -> None:
        self.state = AudioSessionState.PROCESSING
        self._user_speech_active = False

    def mark_speaking(self) -> None:
        self.state = AudioSessionState.SPEAKING
        self._user_speech_active = False

    def mark_awake(self) -> None:
        self.state = AudioSessionState.LISTENING
        self._last_user_activity_at = time.monotonic()
        self._user_speech_active = False

    def mark_awake_after_response(self) -> None:
        if self.state == AudioSessionState.IDLE:
            logger.info(
                "Ignoring stale KWS awake transition after timeout: client_uid={}",
                self.client_uid,
            )
            return
        self.mark_awake()

    def mark_idle(self) -> None:
        self.state = AudioSessionState.IDLE
        self._user_speech_active = False
        self._reset_kws_stream()

    def _process_idle(self, frame: np.ndarray) -> list[AudioSessionEvent]:
        detection = self.kws_engine.accept_waveform(self._kws_stream, frame)
        if not detection:
            return []

        now = time.monotonic()
        if now - self._last_wakeup_at < self.config.cooldown_seconds:
            self._reset_kws_stream()
            return []

        self._last_wakeup_at = now
        self._listening_started_at = now
        self._last_user_activity_at = now
        self._user_speech_active = False
        self.state = AudioSessionState.LISTENING
        self._reset_kws_stream()
        logger.info(
            "KWS wakeup detected: client_uid={} keyword={}",
            self.client_uid,
            detection.keyword,
        )

        events = [
            AudioSessionEvent(
                type="wakeup",
                keyword=detection.keyword,
                confidence=detection.confidence,
            )
        ]
        events.extend(self._process_listening(self._ring_audio()))
        return events

    def _process_listening(self, frame: np.ndarray) -> list[AudioSessionEvent]:
        now = time.monotonic()
        events: list[AudioSessionEvent] = []
        for audio_bytes in self.vad_engine.detect_speech(frame.tolist()):
            if audio_bytes == b"<|PAUSE|>":
                self._user_speech_active = True
                self._last_user_activity_at = now
                events.append(AudioSessionEvent(type="speech-start"))
            elif audio_bytes == b"<|RESUME|>":
                self._user_speech_active = False
                self._last_user_activity_at = now
                events.append(AudioSessionEvent(type="speech-end"))
            elif len(audio_bytes) > 1024:
                self._user_speech_active = False
                self._last_user_activity_at = now
                audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                events.append(AudioSessionEvent(type="utterance", audio=audio))

        if self._user_speech_active:
            # 10 秒窗口只限制“是否开始讲话”。用户已经开始说长句时不能因为句子超过 10 秒而失效。
            self._last_user_activity_at = now
            return events

        active_timeout = getattr(
            self.config,
            "active_timeout_seconds",
            self.config.listen_timeout_seconds,
        )
        if now - self._last_user_activity_at > active_timeout:
            logger.info("KWS active listening timed out: client_uid={}", self.client_uid)
            self.mark_idle()
            events.append(AudioSessionEvent(type="timeout"))
        return events

    def _process_speaking(self, frame: np.ndarray) -> list[AudioSessionEvent]:
        events: list[AudioSessionEvent] = []
        for audio_bytes in self.vad_engine.detect_speech(frame.tolist()):
            if audio_bytes == b"<|PAUSE|>":
                self._user_speech_active = True
                events.append(AudioSessionEvent(type="speech-start"))
            elif audio_bytes == b"<|RESUME|>":
                self._user_speech_active = False
                events.append(AudioSessionEvent(type="speech-end"))
            elif len(audio_bytes) > 1024:
                self._user_speech_active = False
                audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                events.append(AudioSessionEvent(type="utterance", audio=audio))
        return events

    def _append_ring(self, frame: np.ndarray) -> None:
        if self._max_ring_samples <= 0:
            return

        self._ring_buffer.append(frame.copy())
        self._ring_samples += frame.size
        while self._ring_samples > self._max_ring_samples and self._ring_buffer:
            removed = self._ring_buffer.popleft()
            self._ring_samples -= removed.size

    def _ring_audio(self) -> np.ndarray:
        if not self._ring_buffer:
            return np.array([], dtype=np.float32)
        return np.concatenate(list(self._ring_buffer)).astype(np.float32)

    def _reset_kws_stream(self) -> None:
        self.kws_engine.reset_stream(self._kws_stream)

    @staticmethod
    def _normalize_samples(samples: np.ndarray) -> np.ndarray:
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)
        if samples.size and np.max(np.abs(samples)) > 2.0:
            samples = samples / 32768.0
        return np.clip(samples, -1.0, 1.0)
