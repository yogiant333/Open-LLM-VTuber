from pydantic import Field
from typing import ClassVar, Dict, List, Literal

from .i18n import Description, I18nMixin


class SherpaOnnxKWSConfig(I18nMixin):
    """Configuration for sherpa-onnx keyword spotting."""

    encoder: str = Field("", alias="encoder")
    decoder: str = Field("", alias="decoder")
    joiner: str = Field("", alias="joiner")
    tokens: str = Field("", alias="tokens")
    keywords_file: str = Field("", alias="keywords_file")
    keywords_score: float = Field(1.0, alias="keywords_score")
    keywords_threshold: float = Field(0.25, alias="keywords_threshold")
    num_threads: int = Field(1, alias="num_threads")
    provider: str = Field("cpu", alias="provider")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "encoder": Description(en="Path to KWS encoder model", zh="KWS encoder 模型路径"),
        "decoder": Description(en="Path to KWS decoder model", zh="KWS decoder 模型路径"),
        "joiner": Description(en="Path to KWS joiner model", zh="KWS joiner 模型路径"),
        "tokens": Description(en="Path to KWS tokens.txt", zh="KWS tokens.txt 路径"),
        "keywords_file": Description(en="Path to tokenized keywords file", zh="token 化唤醒词文件路径"),
    }


class KWSConfig(I18nMixin):
    """Keyword spotting gate configuration."""

    enabled: bool = Field(False, alias="enabled")
    provider: Literal["sherpa_onnx_kws"] = Field("sherpa_onnx_kws", alias="provider")
    wake_words: List[str] = Field(default_factory=list, alias="wake_words")
    sample_rate: int = Field(16000, alias="sample_rate")
    channels: int = Field(1, alias="channels")
    audio_format: Literal["pcm_f32le", "pcm_s16le"] = Field(
        "pcm_f32le", alias="audio_format"
    )
    frame_ms: int = Field(40, alias="frame_ms")
    pre_roll_ms: int = Field(600, alias="pre_roll_ms")
    cooldown_seconds: float = Field(2.0, alias="cooldown_seconds")
    listen_timeout_seconds: float = Field(10.0, alias="listen_timeout_seconds")
    active_timeout_seconds: float = Field(10.0, alias="active_timeout_seconds")
    sherpa_onnx_kws: SherpaOnnxKWSConfig = Field(
        default_factory=SherpaOnnxKWSConfig,
        alias="sherpa_onnx_kws",
    )

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "enabled": Description(en="Enable keyword spotting gate", zh="启用唤醒词门控"),
        "wake_words": Description(en="Business wake words", zh="业务唤醒词"),
        "sample_rate": Description(en="Audio sample rate", zh="音频采样率"),
        "frame_ms": Description(en="Audio frame duration in milliseconds", zh="音频帧长度"),
        "active_timeout_seconds": Description(
            en="Seconds to keep listening after avatar playback completes without another user utterance",
            zh="数字人播放完成后无用户语音时保持连续对话的秒数",
        ),
    }
