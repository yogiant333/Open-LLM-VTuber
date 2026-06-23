import numpy as np
from loguru import logger

from .asr_interface import ASRInterface


class VoiceRecognition(ASRInterface):
    def __init__(
        self,
        backend: str = "transformers",
        model_name: str = "Qwen/Qwen3-ASR-1.7B",
        device_map: str = "cuda:0",
        dtype: str = "bfloat16",
        language: str | None = "Chinese",
        context: str = (
            "请严格逐字转写音频中的原话，不要润色、不要改写、不要补全、不要总结。"
            "像“喂喂喂”“嗯”“啊”“能听见吗”这类口语和重复词也必须按听到的内容保留。"
        ),
        max_new_tokens: int = 256,
        max_inference_batch_size: int = 1,
        attn_implementation: str | None = None,
        vllm_gpu_memory_utilization: float = 0.9,
        vllm_tensor_parallel_size: int = 1,
        vllm_max_model_len: int | None = None,
        vllm_enforce_eager: bool = False,
        hotwords: list[str] | None = None,
    ) -> None:
        try:
            from qwen_asr import Qwen3ASRModel
        except ImportError as exc:
            raise ImportError(
                "Qwen3-ASR requires the qwen-asr package. Install it in the "
                "Windows backend environment with `pip install -U qwen-asr`."
            ) from exc

        normalized_device = (device_map or "").lower()
        if not normalized_device.startswith("cuda"):
            raise ValueError(
                f"Qwen3-ASR must use a CUDA device, got device_map={device_map!r}."
            )

        normalized_backend = (backend or "transformers").lower()
        if normalized_backend not in {"transformers", "vllm"}:
            raise ValueError("Qwen3-ASR backend must be 'transformers' or 'vllm'.")

        logger.info(
            f"Initializing Qwen3-ASR: backend={normalized_backend}, "
            f"model={model_name}, device_map={device_map}, dtype={dtype}"
        )

        if normalized_backend == "vllm":
            vllm_kwargs = {
                "dtype": dtype,
                "gpu_memory_utilization": vllm_gpu_memory_utilization,
                "tensor_parallel_size": vllm_tensor_parallel_size,
                "enforce_eager": vllm_enforce_eager,
                "max_inference_batch_size": max_inference_batch_size,
                "max_new_tokens": max_new_tokens,
            }
            if vllm_max_model_len:
                vllm_kwargs["max_model_len"] = vllm_max_model_len
            self.model = Qwen3ASRModel.LLM(model=model_name, **vllm_kwargs)
        else:
            import torch

            if not torch.cuda.is_available():
                raise RuntimeError(
                    "Qwen3-ASR is configured for GPU-only use, but CUDA is not available."
                )

            dtype_map = {
                "bfloat16": torch.bfloat16,
                "float16": torch.float16,
            }
            if dtype not in dtype_map:
                raise ValueError("Qwen3-ASR dtype must be 'bfloat16' or 'float16'.")

            model_kwargs = {
                "dtype": dtype_map[dtype],
                "device_map": device_map,
                "max_inference_batch_size": max_inference_batch_size,
                "max_new_tokens": max_new_tokens,
            }
            if attn_implementation:
                model_kwargs["attn_implementation"] = attn_implementation
            self.model = Qwen3ASRModel.from_pretrained(model_name, **model_kwargs)

        self.backend = normalized_backend
        self.language = language or None
        self.context = self._merge_context_with_hotwords(context or "", hotwords)

        logger.info("Qwen3-ASR model loaded.")

    @staticmethod
    def _merge_context_with_hotwords(context: str, hotwords: list[str] | None) -> str:
        words = [word.strip() for word in hotwords or [] if word and word.strip()]
        if not words:
            return context

        hotwords_context = (
            "以下是本场景常见专有名词和热词，识别时请优先按这些词转写，"
            "不要替换成同音或近音词："
            + "、".join(words)
            + "。"
        )
        if context:
            return f"{context}\n{hotwords_context}"
        return hotwords_context

    def transcribe_np(self, audio: np.ndarray) -> str:
        logger.info("Transcribing audio (Qwen3-ASR)...")

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        audio = np.clip(audio, -1, 1)

        results = self.model.transcribe(
            audio=(audio, self.SAMPLE_RATE),
            context=self.context,
            language=self.language,
        )

        if not results:
            return ""

        text = getattr(results[0], "text", "")
        return text.strip()
