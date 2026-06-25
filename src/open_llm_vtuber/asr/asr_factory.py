from typing import Type
from .asr_interface import ASRInterface


def _normalize_hotwords(hotwords: list[str] | None) -> list[str]:
    return [word.strip() for word in hotwords or [] if word and word.strip()]


def _merge_prompt_with_hotwords(
    prompt: str | None, hotwords: list[str] | None
) -> str | None:
    words = _normalize_hotwords(hotwords)
    if not words:
        return prompt

    hotwords_prompt = (
        "识别时请优先保留这些专有名词和领域词，不要改写：" + "、".join(words) + "。"
    )
    if prompt:
        return f"{prompt}\n{hotwords_prompt}"
    return hotwords_prompt


def _without_common_options(kwargs: dict) -> dict:
    cleaned = dict(kwargs)
    cleaned.pop("hotwords", None)
    return cleaned


class ASRFactory:
    @staticmethod
    def get_asr_system(system_name: str, **kwargs) -> Type[ASRInterface]:
        if system_name == "faster_whisper":
            from .faster_whisper_asr import VoiceRecognition as FasterWhisperASR

            return FasterWhisperASR(
                model_path=kwargs.get("model_path"),
                download_root=kwargs.get("download_root"),
                language=kwargs.get("language"),
                device=kwargs.get("device"),
                compute_type=kwargs.get("compute_type"),
                prompt=_merge_prompt_with_hotwords(
                    kwargs.get("prompt", None), kwargs.get("hotwords")
                ),
            )
        elif system_name == "whisper_cpp":
            from .whisper_cpp_asr import VoiceRecognition as WhisperCPPASR

            provider_kwargs = _without_common_options(kwargs)
            provider_kwargs["prompt"] = _merge_prompt_with_hotwords(
                provider_kwargs.get("prompt"), kwargs.get("hotwords")
            )
            return WhisperCPPASR(**provider_kwargs)
        elif system_name == "whisper":
            from .openai_whisper_asr import VoiceRecognition as WhisperASR

            provider_kwargs = _without_common_options(kwargs)
            provider_kwargs["prompt"] = _merge_prompt_with_hotwords(
                provider_kwargs.get("prompt"), kwargs.get("hotwords")
            )
            return WhisperASR(**provider_kwargs)
        elif system_name == "fun_asr":
            from .fun_asr import VoiceRecognition as FunASR

            return FunASR(
                model_name=kwargs.get("model_name"),
                vad_model=kwargs.get("vad_model"),
                punc_model=kwargs.get("punc_model"),
                ncpu=kwargs.get("ncpu"),
                hub=kwargs.get("hub"),
                device=kwargs.get("device"),
                language=kwargs.get("language"),
                model_revision=kwargs.get("model_revision", "v2.0.4"),
                use_itn=kwargs.get("use_itn"),
                streaming_enabled=kwargs.get("streaming_enabled", True),
                streaming_model_name=kwargs.get(
                    "streaming_model_name", "paraformer-zh-online"
                ),
                streaming_chunk_size=kwargs.get("streaming_chunk_size"),
                encoder_chunk_look_back=kwargs.get("encoder_chunk_look_back", 4),
                decoder_chunk_look_back=kwargs.get("decoder_chunk_look_back", 1),
                # sample_rate=kwargs.get("sample_rate"),
            )
        elif system_name == "azure_asr":
            from .azure_asr import VoiceRecognition as AzureASR

            return AzureASR(
                subscription_key=kwargs.get("api_key"),
                region=kwargs.get("region"),
                languages=kwargs.get("languages", ["en-US", "zh-CN"]),
            )
        elif system_name == "groq_whisper_asr":
            from .groq_whisper_asr import VoiceRecognition as GroqWhisperASR

            return GroqWhisperASR(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model"),
                lang=kwargs.get("lang"),
            )
        elif system_name == "sherpa_onnx_asr":
            from .sherpa_onnx_asr import VoiceRecognition as SherpaOnnxASR

            return SherpaOnnxASR(**_without_common_options(kwargs))
        elif system_name == "qwen3_asr":
            from .qwen3_asr import VoiceRecognition as Qwen3ASR

            return Qwen3ASR(**kwargs)
        elif system_name == "qwen3_asr_gguf":
            from .qwen3_asr_gguf import VoiceRecognition as Qwen3ASRGGUF

            return Qwen3ASRGGUF(**kwargs)
        elif system_name == "fun_asr_gguf":
            from .fun_asr_gguf import VoiceRecognition as FunASRGGUF

            return FunASRGGUF(**kwargs)
        else:
            raise ValueError(f"Unknown ASR system: {system_name}")
