import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import numpy as np
from loguru import logger

from .asr_interface import ASRInterface


class VoiceRecognition(ASRInterface):
    def __init__(
        self,
        working_dir: str = "Qwen3-ASR-GGUF",
        model_dir: str = "Qwen3-ASR-GGUF/model",
        language: str | None = "Chinese",
        context: str | None = (
            "请严格逐字转写音频中的原话，不要润色、不要改写、不要补全、不要总结。"
            "像“喂喂喂”“嗯”“啊”“能听见吗”这类口语和重复词也必须按听到的内容保留。"
        ),
        use_dml: bool = True,
        use_vulkan: bool = True,
        timestamp: bool = False,
        asr_encoder_frontend: str = "qwen3_asr_encoder_frontend.int4.onnx",
        asr_encoder_backend: str = "qwen3_asr_encoder_backend.int4.onnx",
        asr_llm: str = "qwen3_asr_llm.q4_k.gguf",
        aligner_encoder_frontend: str = "qwen3_aligner_encoder_frontend.int4.onnx",
        aligner_encoder_backend: str = "qwen3_aligner_encoder_backend.int4.onnx",
        aligner_llm: str = "qwen3_aligner_llm.q4_k.gguf",
        n_ctx: int = 2048,
        chunk_size: float = 40.0,
        memory_num: int = 1,
        temperature: float = 0.4,
        hotwords: list[str] | None = None,
    ) -> None:
        self.working_dir = str(Path(working_dir).resolve())
        self.model_dir = str(Path(model_dir).resolve())
        self.language = language or None
        self.context = self._merge_context_with_hotwords(context or "", hotwords)
        self.use_dml = use_dml
        self.use_vulkan = use_vulkan
        self.timestamp = timestamp
        self.asr_encoder_frontend = asr_encoder_frontend
        self.asr_encoder_backend = asr_encoder_backend
        self.asr_llm = asr_llm
        self.aligner_encoder_frontend = aligner_encoder_frontend
        self.aligner_encoder_backend = aligner_encoder_backend
        self.aligner_llm = aligner_llm
        self.n_ctx = n_ctx
        self.chunk_size = chunk_size
        self.memory_num = memory_num
        self.temperature = temperature
        self.engine = None
        self._dll_dirs = []

        working_dir_path = Path(self.working_dir)
        if not working_dir_path.is_dir():
            raise FileNotFoundError(f"Qwen3-ASR-GGUF submodule not found: {self.working_dir}")

        model_dir_path = Path(self.model_dir)
        if not model_dir_path.is_dir():
            raise FileNotFoundError(f"Qwen3-ASR-GGUF model_dir not found: {self.model_dir}")
        self._check_model_files(model_dir_path)

        self._init_python_engine()

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

    def _check_model_files(self, model_dir: Path) -> None:
        required_files = [
            self.asr_encoder_frontend,
            self.asr_encoder_backend,
            self.asr_llm,
        ]
        if self.timestamp:
            required_files.extend(
                [
                    self.aligner_encoder_frontend,
                    self.aligner_encoder_backend,
                    self.aligner_llm,
                ]
            )
        missing = [name for name in required_files if not (model_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(
                "Qwen3-ASR-GGUF model files are missing from "
                f"{model_dir}: {', '.join(missing)}"
            )

    def transcribe_np(self, audio: np.ndarray) -> str:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        audio = np.clip(audio, -1, 1)
        return self._transcribe_python(audio)

    def shutdown(self) -> None:
        if self.engine is not None:
            self.engine.shutdown()
            self.engine = None
        for dll_dir in self._dll_dirs:
            dll_dir.close()
        self._dll_dirs.clear()

    def _init_python_engine(self) -> None:
        if self.use_vulkan:
            os.environ["GGML_VULKAN"] = "1"
        else:
            os.environ.pop("GGML_VULKAN", None)

        tool_root_path = Path(self.working_dir)
        tool_root = str(tool_root_path)
        if tool_root not in sys.path:
            sys.path.insert(0, tool_root)

        if os.name == "nt":
            bin_path = tool_root_path / "qwen_asr_gguf" / "inference" / "bin"
            if bin_path.is_dir():
                self._dll_dirs.append(os.add_dll_directory(str(bin_path)))

        try:
            from qwen_asr_gguf.inference import (
                ASREngineConfig,
                AlignerConfig,
                QwenASREngine,
            )
        except ImportError as exc:
            raise ImportError(
                "Qwen3-ASR-GGUF python runtime requires the Qwen3-ASR-GGUF "
                "submodule and its Python dependencies in the current .venv."
            ) from exc

        config = ASREngineConfig(
            model_dir=self.model_dir,
            encoder_frontend_fn=self.asr_encoder_frontend,
            encoder_backend_fn=self.asr_encoder_backend,
            llm_fn=self.asr_llm,
            onnx_provider="DML" if self.use_dml else "CPU",
            llm_use_gpu=self.use_vulkan,
            n_ctx=self.n_ctx,
            chunk_size=self.chunk_size,
            memory_num=self.memory_num,
            verbose=False,
            enable_aligner=self.timestamp,
            align_config=AlignerConfig(
                model_dir=self.model_dir,
                encoder_frontend_fn=self.aligner_encoder_frontend,
                encoder_backend_fn=self.aligner_encoder_backend,
                llm_fn=self.aligner_llm,
                onnx_provider="DML" if self.use_dml else "CPU",
                llm_use_gpu=self.use_vulkan,
                n_ctx=self.n_ctx,
            ),
        )
        logger.info("Initializing Qwen3-ASR-GGUF python runtime...")
        self.engine = QwenASREngine(config=config)

    def _transcribe_python(self, audio: np.ndarray) -> str:
        logger.info("Transcribing audio (Qwen3-ASR-GGUF python runtime)...")
        with redirect_stdout(StringIO()):
            result = self.engine.asr(
                audio=audio,
                context=self.context,
                language=self.language,
                temperature=self.temperature,
            )
        return (result.text or "").strip()
