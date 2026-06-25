import io
import re
import asyncio
import torch
import numpy as np
import soundfile as sf
from funasr import AutoModel
from .asr_interface import ASRInterface, StreamingASRResult
from typing import Optional

# Model alias to actual ModelScope ID mapping table
MODEL_ALIAS_TO_FULL_ID_MAP = {
    "paraformer-zh": "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "paraformer-zh-spk": "iic/speech_paraformer-large-vad-punc-spk_asr_nat-zh-cn",
    "paraformer-zh-online": "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
    "paraformer-zh-streaming": "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
    "paraformer-en": "iic/speech_paraformer-large-vad-punc_asr_nat-en-16k-common-vocab10020",
    "conformer-en": "iic/speech_conformer_asr-en-16k-vocab4199-pytorch",
    "ct-punc": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
    "fsmn-vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "fa-zh": "iic/speech_timestamp_prediction-v1-16k-offline",
    "SenseVoiceSmall": "SenseVoiceSmall",
    "iic/SenseVoiceSmall": "SenseVoiceSmall",
}


# paraformer-zh is a multi-functional asr model
# use vad, punc, spk or not as you need


class VoiceRecognition(ASRInterface):
    def __init__(
        self,
        model_name: str = "iic/SenseVoiceSmall",
        language: str = "auto",
        vad_model: str = "fsmn-vad",
        punc_model: str = "ct-punc",
        ncpu: int = None,
        hub: str = None,
        device: str = "cpu",
        disable_update: bool = True,
        model_revision: str | None = "v2.0.4",
        sample_rate: int = 16000,
        use_itn: bool = False,
        streaming_enabled: bool = True,
        streaming_model_name: str = "paraformer-zh-online",
        streaming_chunk_size: list[int] | None = None,
        encoder_chunk_look_back: int = 4,
        decoder_chunk_look_back: int = 1,
    ) -> None:
        # Resolve model paths
        final_model_input = self._get_final_model_input(model_name)
        final_vad_input = self._get_final_model_input(vad_model) if vad_model else None
        final_punc_input = (
            self._get_final_model_input(punc_model) if punc_model else None
        )

        model_kwargs = {
            "model": final_model_input,
            "vad_model": final_vad_input,
            "ncpu": ncpu,
            "hub": hub,
            "device": device,
            "disable_update": disable_update,
            "model_revision": model_revision,
            "punc_model": final_punc_input,
            # "spk_model": "cam++",
        }
        self.model = AutoModel(
            **{key: value for key, value in model_kwargs.items() if value is not None}
        )
        self.SAMPLE_RATE = sample_rate
        self.use_itn = use_itn
        self.language = language
        self.streaming_enabled = streaming_enabled
        self.streaming_chunk_size = streaming_chunk_size or [0, 10, 5]
        self.encoder_chunk_look_back = encoder_chunk_look_back
        self.decoder_chunk_look_back = decoder_chunk_look_back
        self._streaming_cache_by_session: dict[str, dict] = {}
        self._streaming_text_by_session: dict[str, str] = {}
        self._streaming_lock = asyncio.Lock()
        self.streaming_model = None
        if streaming_enabled:
            final_streaming_model_input = self._get_final_model_input(
                streaming_model_name
            )
            if final_streaming_model_input == final_model_input:
                self.streaming_model = self.model
            else:
                streaming_model_kwargs = {
                    "model": final_streaming_model_input,
                    "ncpu": ncpu,
                    "hub": hub,
                    "device": device,
                    "disable_update": disable_update,
                    "model_revision": model_revision,
                }
                self.streaming_model = AutoModel(
                    **{
                        key: value
                        for key, value in streaming_model_kwargs.items()
                        if value is not None
                    }
                )

    @property
    def supports_streaming(self) -> bool:
        return bool(self.streaming_model)

    def reset_streaming_session(self, session_id: str) -> None:
        self._streaming_cache_by_session.pop(session_id, None)
        self._streaming_text_by_session.pop(session_id, None)

    async def async_streaming_transcribe_np(
        self,
        session_id: str,
        audio: np.ndarray,
        *,
        is_final: bool = False,
    ) -> list[StreamingASRResult]:
        if not self.streaming_model or audio.size == 0:
            return []

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        async with self._streaming_lock:
            return await asyncio.to_thread(
                self._streaming_transcribe_np_sync,
                session_id,
                audio,
                is_final,
            )

    def _streaming_transcribe_np_sync(
        self,
        session_id: str,
        audio: np.ndarray,
        is_final: bool,
    ) -> list[StreamingASRResult]:
        cache = self._streaming_cache_by_session.setdefault(session_id, {})
        res = self.streaming_model.generate(
            input=audio,
            cache=cache,
            is_final=is_final,
            chunk_size=self.streaming_chunk_size,
            encoder_chunk_look_back=self.encoder_chunk_look_back,
            decoder_chunk_look_back=self.decoder_chunk_look_back,
        )
        text = self._clean_text(res[0].get("text", "") if res else "")
        previous_text = self._streaming_text_by_session.get(session_id, "")
        next_text = previous_text
        if text:
            next_text = (
                text if text.startswith(previous_text) else f"{previous_text}{text}"
            )
            self._streaming_text_by_session[session_id] = next_text
        if is_final:
            self.reset_streaming_session(session_id)
            return [StreamingASRResult(text=next_text, is_final=True)]
        if not text or next_text == previous_text:
            return []
        return [StreamingASRResult(text=next_text, is_final=False)]

    def _get_final_model_input(self, alias_or_id: Optional[str]) -> Optional[str]:
        """
        Process model input function:
        1. Check mapping table to get canonical ModelScope ID.
        2. Return the canonical ID and let FunASR/ModelScope resolve cache paths.
        """
        if not alias_or_id:
            return None

        return MODEL_ALIAS_TO_FULL_ID_MAP.get(alias_or_id, alias_or_id)

    def transcribe_np(self, audio: np.ndarray) -> str:
        audio_tensor = torch.tensor(audio, dtype=torch.float32)

        res = self.model.generate(
            input=audio_tensor,
            batch_size_s=300,
            use_itn=self.use_itn,
            language=self.language,
        )

        full_text = res[0]["text"]

        # SenseVoiceSmall may spits out some tags
        # like this: '<|zh|><|NEUTRAL|><|Speech|><|woitn|>欢迎大家来体验达摩院推出的语音识别模型'
        # we should remove those tags from the result

        return self._clean_text(full_text)

    @staticmethod
    def _clean_text(text: str) -> str:
        # remove SenseVoice-style tags
        text = re.sub(r"<\|.*?\|>", "", text)
        # the tags can also look like '< | en | > < | EMO _ UNKNOWN | > < | S pe ech | > < | wo itn | > '
        text = re.sub(r"< \|.*?\| >", "", text)
        return text.strip()

    def _numpy_to_wav_in_memory(self, numpy_array: np.ndarray, sample_rate):
        memory_file = io.BytesIO()
        sf.write(memory_file, numpy_array, sample_rate, format="WAV")
        memory_file.seek(0)

        return memory_file
