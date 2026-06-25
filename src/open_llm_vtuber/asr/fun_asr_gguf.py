import asyncio
import inspect
import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Literal

import numpy as np
from loguru import logger

from .asr_interface import ASRInterface, StreamingASRResult


class VoiceRecognition(ASRInterface):
    def __init__(
        self,
        working_dir: str = "Fun-ASR-GGUF",
        runtime_dir: str = "Fun-ASR-GGUF/model",
        model_dir: str = "Fun-ASR-GGUF/model/model",
        encoder_onnx: str = "Fun-ASR-Nano-Encoder-Adaptor.fp32.onnx",
        ctc_onnx: str = "Fun-ASR-Nano-CTC.int8.onnx",
        decoder_gguf: str = "Fun-ASR-Nano-Decoder.q8_0.gguf",
        tokens: str = "tokens.txt",
        hotwords_path: str | None = "Fun-ASR-GGUF/hot.txt",
        hotwords: list[str] | None = None,
        language: str | None = "中文",
        context: str | None = (
            "请严格逐字转写音频中的原话，不要润色、不要改写、不要补全、不要总结。"
            "像“喂喂喂”“嗯”“啊”“能听见吗”这类口语和重复词也必须按听到的内容保留。"
        ),
        enable_ctc: bool = True,
        onnx_provider: Literal["CPU", "CUDA", "DML", "TensorRT"] | str = "DML",
        llm_use_gpu: bool = True,
        vulkan_force_fp32: bool = False,
        n_predict: int = 512,
        n_threads: int | None = None,
        n_threads_batch: int | None = None,
        n_ubatch: int = 512,
        similar_threshold: float = 0.6,
        max_hotwords: int = 10,
        ctc_topk: int = 20,
        dml_pad_to: int = 30,
        temperature: float = 0.4,
        top_p: float = 1.0,
        top_k: int = 50,
        streaming_enabled: bool = True,
        streaming_partial_mode: Literal["ctc", "full", "none"] = "ctc",
        streaming_min_audio_ms: int = 800,
        streaming_update_ms: int = 600,
        verbose: bool = False,
    ) -> None:
        self.working_dir = str(Path(working_dir).resolve())
        self.runtime_dir = str(Path(runtime_dir).resolve())
        self.model_dir = str(Path(model_dir).resolve())
        self.encoder_onnx = encoder_onnx
        self.ctc_onnx = ctc_onnx
        self.decoder_gguf = decoder_gguf
        self.tokens = tokens
        self.language = language or None
        self.context = context or None
        self.enable_ctc = enable_ctc
        self.onnx_provider = onnx_provider.upper()
        self.llm_use_gpu = llm_use_gpu
        self.vulkan_force_fp32 = vulkan_force_fp32
        self.n_predict = n_predict
        self.n_threads = n_threads
        self.n_threads_batch = n_threads_batch
        self.n_ubatch = n_ubatch
        self.similar_threshold = similar_threshold
        self.max_hotwords = max_hotwords
        self.ctc_topk = ctc_topk
        self.dml_pad_to = dml_pad_to
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.streaming_enabled = streaming_enabled
        self.streaming_partial_mode = streaming_partial_mode
        self.streaming_min_samples = int(
            self.SAMPLE_RATE * streaming_min_audio_ms / 1000
        )
        self.streaming_update_samples = int(
            self.SAMPLE_RATE * streaming_update_ms / 1000
        )
        self.verbose = verbose
        self.hotwords = self._load_hotwords(hotwords_path, hotwords)
        self.engine = None
        self._runtime_api = "modern"
        self._transcribe_lock = asyncio.Lock()
        self._streaming_audio_by_session: dict[str, np.ndarray] = {}
        self._streaming_text_by_session: dict[str, str] = {}
        self._streaming_processed_samples_by_session: dict[str, int] = {}

        working_dir_path = Path(self.working_dir)
        if not working_dir_path.is_dir():
            raise FileNotFoundError(
                f"Fun-ASR-GGUF submodule not found: {self.working_dir}"
            )

        runtime_dir_path = Path(self.runtime_dir)
        if not runtime_dir_path.is_dir():
            raise FileNotFoundError(
                f"Fun-ASR-GGUF runtime_dir not found: {self.runtime_dir}"
            )

        model_dir_path = Path(self.model_dir)
        if not model_dir_path.is_dir():
            raise FileNotFoundError(
                f"Fun-ASR-GGUF model_dir not found: {self.model_dir}"
            )
        self._check_model_files(model_dir_path)
        self._init_python_engine()

    @property
    def supports_streaming(self) -> bool:
        return bool(self.streaming_enabled)

    def reset_streaming_session(self, session_id: str) -> None:
        self._streaming_audio_by_session.pop(session_id, None)
        self._streaming_text_by_session.pop(session_id, None)
        self._streaming_processed_samples_by_session.pop(session_id, None)

    def transcribe_np(self, audio: np.ndarray) -> str:
        audio = self._normalize_audio(audio)
        return self._decode_np(audio)

    async def async_transcribe_np(self, audio: np.ndarray) -> str:
        audio = self._normalize_audio(audio)
        async with self._transcribe_lock:
            return await asyncio.to_thread(self._decode_np, audio)

    async def async_streaming_transcribe_np(
        self,
        session_id: str,
        audio: np.ndarray,
        *,
        is_final: bool = False,
    ) -> list[StreamingASRResult]:
        if not self.streaming_enabled:
            return []

        audio = self._normalize_audio(audio)
        async with self._transcribe_lock:
            return await asyncio.to_thread(
                self._streaming_transcribe_np_sync,
                session_id,
                audio,
                is_final,
            )

    def shutdown(self) -> None:
        if self.engine is not None:
            self.engine.cleanup()
            self.engine = None

    def _streaming_transcribe_np_sync(
        self,
        session_id: str,
        audio: np.ndarray,
        is_final: bool,
    ) -> list[StreamingASRResult]:
        previous_audio = self._streaming_audio_by_session.get(session_id)
        next_audio = (
            audio if previous_audio is None else np.concatenate([previous_audio, audio])
        )
        self._streaming_audio_by_session[session_id] = next_audio

        if next_audio.size < self.streaming_min_samples and not is_final:
            return []

        if is_final:
            text = self._decode_np(next_audio)
            if not text:
                text = self._streaming_text_by_session.get(session_id, "")
            self.reset_streaming_session(session_id)
            return [StreamingASRResult(text=text, is_final=True)] if text else []

        if self.streaming_partial_mode == "none":
            return []

        processed = self._streaming_processed_samples_by_session.get(session_id, 0)
        if next_audio.size - processed < self.streaming_update_samples:
            return []

        text = self._partial_decode_np(next_audio)
        self._streaming_processed_samples_by_session[session_id] = next_audio.size
        previous_text = self._streaming_text_by_session.get(session_id, "")
        if not text or text == previous_text:
            return []
        self._streaming_text_by_session[session_id] = text
        return [StreamingASRResult(text=text, is_final=False)]

    def _partial_decode_np(self, audio: np.ndarray) -> str:
        if self.streaming_partial_mode == "full":
            return self._decode_np(audio)
        try:
            with redirect_stdout(StringIO()):
                if self._runtime_api == "legacy":
                    from fun_asr_gguf.nano_onnx import encode_audio

                    _, enc_output = encode_audio(audio, self.engine.models.encoder_sess)
                    ctc_results, _ = (
                        self.engine.orchestrator.decoder.ctc_decoder.decode(
                            enc_output,
                            self.enable_ctc,
                            self.max_hotwords,
                        )
                    )
                else:
                    (_, enc_output) = self.engine.models.encoder.encode(audio)
                    ctc_results, _, _ = self.engine.models.ctc_decoder.decode(
                        enc_output,
                        self.enable_ctc,
                        self.max_hotwords,
                        top_k=self.ctc_topk,
                    )
            return "".join(item.text for item in ctc_results).strip()
        except Exception as exc:
            logger.warning(f"Fun-ASR-GGUF CTC streaming partial failed: {exc}")
            return ""

    def _decode_np(self, audio: np.ndarray) -> str:
        if audio.size < 1600:
            return ""
        stream = self.engine.create_stream()
        stream.accept_waveform(self.SAMPLE_RATE, audio)
        with redirect_stdout(StringIO()):
            if self._runtime_api == "legacy":
                result = self.engine.decode_stream(
                    stream,
                    language=self.language,
                    context=self.context,
                    verbose=self.verbose,
                )
            else:
                result = self.engine.decode_stream(
                    stream,
                    language=self.language,
                    context=self.context,
                    verbose=self.verbose,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    top_k=self.top_k,
                )
        return (result.text or "").strip()

    def _init_python_engine(self) -> None:
        if self.vulkan_force_fp32:
            os.environ["GGML_VK_DISABLE_F16"] = "1"

        runtime_root = str(Path(self.runtime_dir))
        if runtime_root not in sys.path:
            sys.path.insert(0, runtime_root)

        tool_root = str(Path(self.working_dir))
        if tool_root not in sys.path:
            sys.path.insert(1, tool_root)

        try:
            import fun_asr_gguf
        except ImportError as exc:
            raise ImportError(
                "Fun-ASR-GGUF python runtime requires the Fun-ASR-GGUF submodule, "
                "its llama.cpp dynamic libraries, and its Python dependencies."
            ) from exc

        model_dir = Path(self.model_dir)
        encoder_onnx_path = str(model_dir / self.encoder_onnx)
        ctc_onnx_path = str(model_dir / self.ctc_onnx)
        decoder_gguf_path = str(model_dir / self.decoder_gguf)
        tokens_path = str(model_dir / self.tokens)
        hotwords_path = self._effective_hotwords_path()
        logger.info(
            "Initializing Fun-ASR-GGUF runtime "
            f"(provider={self.onnx_provider}, streaming={self.streaming_enabled})..."
        )
        engine_signature = inspect.signature(fun_asr_gguf.FunASREngine)
        if "config" in engine_signature.parameters:
            config = fun_asr_gguf.ASREngineConfig(
                encoder_onnx_path=encoder_onnx_path,
                ctc_onnx_path=ctc_onnx_path,
                decoder_gguf_path=decoder_gguf_path,
                tokens_path=tokens_path,
                hotwords=self.hotwords,
                enable_ctc=self.enable_ctc,
                n_predict=self.n_predict,
                n_threads=self.n_threads,
                n_threads_batch=self.n_threads_batch,
                n_ubatch=self.n_ubatch,
                similar_threshold=self.similar_threshold,
                max_hotwords=self.max_hotwords,
                sample_rate=self.SAMPLE_RATE,
                onnx_provider=self.onnx_provider,
                ctc_topk=self.ctc_topk,
                dml_pad_to=self.dml_pad_to,
                llm_use_gpu=self.llm_use_gpu,
                vulkan_force_fp32=self.vulkan_force_fp32,
                verbose=self.verbose,
            )
            self.engine = fun_asr_gguf.FunASREngine(config)
            self._runtime_api = "modern"
            return

        self.engine = fun_asr_gguf.FunASREngine(
            encoder_onnx_path=encoder_onnx_path,
            ctc_onnx_path=ctc_onnx_path,
            decoder_gguf_path=decoder_gguf_path,
            tokens_path=tokens_path,
            hotwords_path=hotwords_path,
            enable_ctc=self.enable_ctc,
            n_predict=self.n_predict,
            n_threads=self.n_threads,
            similar_threshold=self.similar_threshold,
            max_hotwords=self.max_hotwords,
        )
        if not self.engine.initialize(verbose=self.verbose):
            raise RuntimeError("Failed to initialize Fun-ASR-GGUF runtime")
        self._runtime_api = "legacy"

    def _check_model_files(self, model_dir: Path) -> None:
        required_files = [
            self.encoder_onnx,
            self.ctc_onnx,
            self.decoder_gguf,
            self.tokens,
        ]
        missing = [name for name in required_files if not (model_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(
                "Fun-ASR-GGUF model files are missing from "
                f"{model_dir}: {', '.join(missing)}"
            )

        candidate_bin_dirs = [
            Path(self.runtime_dir) / "fun_asr_gguf" / "bin",
            Path(self.working_dir) / "fun_asr_gguf" / "inference" / "bin",
        ]
        bin_dir = next((path for path in candidate_bin_dirs if path.is_dir()), None)
        if bin_dir is None:
            raise FileNotFoundError(
                "Fun-ASR-GGUF llama.cpp dynamic library directory is missing: "
                f"{candidate_bin_dirs}. Put llama.cpp DLL/.so/.dylib files there before enabling it."
            )
        if os.name == "nt":
            library_names = ["ggml.dll", "ggml-base.dll", "llama.dll"]
        elif sys.platform == "darwin":
            library_names = ["libggml.dylib", "libggml-base.dylib", "libllama.dylib"]
        else:
            library_names = ["libggml.so", "libggml-base.so", "libllama.so"]
        missing_libraries = [
            name for name in library_names if not (bin_dir / name).is_file()
        ]
        if missing_libraries:
            raise FileNotFoundError(
                "Fun-ASR-GGUF llama.cpp dynamic libraries are missing from "
                f"{bin_dir}: {', '.join(missing_libraries)}"
            )

    def _load_hotwords(
        self,
        hotwords_path: str | None,
        hotwords: list[str] | None,
    ) -> list[str]:
        words = [word.strip() for word in hotwords or [] if word and word.strip()]
        if hotwords_path:
            path = Path(hotwords_path)
            if path.is_file():
                words.extend(
                    line.strip()
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.strip().startswith("#")
                )
        return list(dict.fromkeys(words))

    def _effective_hotwords_path(self) -> str | None:
        if not self.hotwords:
            return None

        path = Path(self.runtime_dir) / "hot-runtime.txt"
        path.write_text("\n".join(self.hotwords), encoding="utf-8")
        return str(path)

    @staticmethod
    def _normalize_audio(audio: np.ndarray) -> np.ndarray:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        return np.clip(audio, -1, 1)
