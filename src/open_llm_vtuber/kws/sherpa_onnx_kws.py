from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

from ..config_manager.kws import KWSConfig


@dataclass
class KeywordDetection:
    keyword: str
    confidence: Optional[float] = None


class SherpaOnnxKWS:
    """Thin wrapper around sherpa-onnx KeywordSpotter."""

    def __init__(self, config: KWSConfig):
        if not config.enabled:
            raise ValueError("KWS config is disabled.")

        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa-onnx is required when KWS is enabled.") from exc

        self.config = config
        kws_config = config.sherpa_onnx_kws
        self._validate_paths(
            {
                "encoder": kws_config.encoder,
                "decoder": kws_config.decoder,
                "joiner": kws_config.joiner,
                "tokens": kws_config.tokens,
                "keywords_file": kws_config.keywords_file,
            }
        )
        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=kws_config.tokens,
            encoder=kws_config.encoder,
            decoder=kws_config.decoder,
            joiner=kws_config.joiner,
            keywords_file=kws_config.keywords_file,
            num_threads=kws_config.num_threads,
            sample_rate=config.sample_rate,
            keywords_score=kws_config.keywords_score,
            keywords_threshold=kws_config.keywords_threshold,
            provider=kws_config.provider,
        )
        logger.info(
            "Sherpa-Onnx KWS initialized: sample_rate={} keywords_file={}",
            config.sample_rate,
            kws_config.keywords_file,
        )

    def create_stream(self):
        return self._spotter.create_stream()

    def reset_stream(self, stream) -> None:
        self._spotter.reset_stream(stream)

    def accept_waveform(self, stream, samples: np.ndarray) -> Optional[KeywordDetection]:
        if samples.size == 0:
            return None

        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)

        stream.accept_waveform(self.config.sample_rate, samples)
        while self._spotter.is_ready(stream):
            self._spotter.decode_stream(stream)

        keyword = self._spotter.get_result(stream)
        if keyword:
            return KeywordDetection(keyword=keyword)
        return None

    @staticmethod
    def _validate_paths(paths: dict[str, str]) -> None:
        missing = [name for name, value in paths.items() if not value or not Path(value).is_file()]
        if missing:
            detail = ", ".join(f"{name}={paths[name]!r}" for name in missing)
            raise FileNotFoundError(f"Missing KWS model files: {detail}")
