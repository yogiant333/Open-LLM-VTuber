import numpy as np
import pytest

from src.open_llm_vtuber.config_manager.kws import KWSConfig
from src.open_llm_vtuber.kws.audio_session import AudioSession, AudioSessionState
from src.open_llm_vtuber.websocket_handler import WebSocketHandler


class FakeKWS:
    def __init__(self):
        self.calls = 0

    def create_stream(self):
        return object()

    def reset_stream(self, stream):
        pass

    def accept_waveform(self, stream, samples):
        self.calls += 1
        if self.calls == 1:
            return type("Detection", (), {"keyword": "小智小智", "confidence": None})()
        return None


class FakeVAD:
    def detect_speech(self, audio_data):
        yield b"<|PAUSE|>"
        audio = (np.ones(1600, dtype=np.float32) * 0.1 * 32767).astype(np.int16)
        yield audio.tobytes()


class OneShotVAD:
    def __init__(self):
        self.calls = 0

    def detect_speech(self, audio_data):
        self.calls += 1
        if self.calls == 1:
            audio = (np.ones(1600, dtype=np.float32) * 0.1 * 32767).astype(np.int16)
            yield audio.tobytes()


class AlwaysUtteranceVAD:
    def detect_speech(self, audio_data):
        audio = (np.ones(1600, dtype=np.float32) * 0.1 * 32767).astype(np.int16)
        yield audio.tobytes()


def test_audio_session_wakeup_feeds_same_stream_to_vad():
    session = AudioSession(
        client_uid="client",
        config=KWSConfig(enabled=True, wake_words=["小智小智"]),
        kws_engine=FakeKWS(),
        vad_engine=FakeVAD(),
    )

    events = session.accept_frame(np.zeros(640, dtype=np.float32))

    assert [event.type for event in events] == ["wakeup", "speech-start", "utterance"]
    assert events[-1].audio.dtype == np.float32
    assert np.max(np.abs(events[-1].audio)) <= 1.0


def test_audio_session_stays_awake_for_followup_without_wake_word():
    kws = FakeKWS()
    vad = AlwaysUtteranceVAD()
    session = AudioSession(
        client_uid="client",
        config=KWSConfig(
            enabled=True,
            wake_words=["小智小智"],
            active_timeout_seconds=120,
        ),
        kws_engine=kws,
        vad_engine=vad,
    )

    session.accept_frame(np.zeros(640, dtype=np.float32))
    session.mark_processing()
    session.mark_awake()

    events = session.accept_frame(np.zeros(640, dtype=np.float32))

    assert kws.calls == 1
    assert [event.type for event in events] == ["utterance"]


def test_audio_session_returns_to_idle_after_active_timeout(monkeypatch):
    now = 1000.0
    monkeypatch.setattr("src.open_llm_vtuber.kws.audio_session.time.monotonic", lambda: now)
    session = AudioSession(
        client_uid="client",
        config=KWSConfig(
            enabled=True,
            wake_words=["小智小智"],
            active_timeout_seconds=120,
        ),
        kws_engine=FakeKWS(),
        vad_engine=OneShotVAD(),
    )

    session.accept_frame(np.zeros(640, dtype=np.float32))
    now = 1121.0

    events = session.accept_frame(np.zeros(640, dtype=np.float32))

    assert [event.type for event in events] == ["timeout"]
    assert session.state == AudioSessionState.IDLE


def test_runtime_kws_config_update_keeps_server_model_paths():
    base_config = KWSConfig.model_validate(
        {
            "enabled": False,
            "sherpa_onnx_kws": {
                "encoder": "./models/kws/encoder.onnx",
                "decoder": "./models/kws/decoder.onnx",
                "joiner": "./models/kws/joiner.onnx",
                "tokens": "./models/kws/tokens.txt",
                "keywords_file": "./models/kws/keywords.txt",
            },
        }
    )

    updated = WebSocketHandler._build_runtime_kws_config(
        base_config,
        {
            "enabled": True,
            "wake_words": ["小智小智"],
            "frame_ms": 40,
            "active_timeout_seconds": 120,
            "keywords_threshold": 0.3,
            "sherpa_onnx_kws": {"encoder": "./evil.onnx"},
        },
    )

    assert updated.enabled is True
    assert updated.wake_words == ["小智小智"]
    assert updated.active_timeout_seconds == 120
    assert updated.sherpa_onnx_kws.keywords_threshold == 0.3
    assert updated.sherpa_onnx_kws.encoder == "./models/kws/encoder.onnx"


def test_runtime_kws_config_rejects_unsupported_audio_format():
    with pytest.raises(ValueError, match="sample_rate must be 16000"):
        WebSocketHandler._build_runtime_kws_config(
            KWSConfig(),
            {"enabled": True, "sample_rate": 48000},
        )
