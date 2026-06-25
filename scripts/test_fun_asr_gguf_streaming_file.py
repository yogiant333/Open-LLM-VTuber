from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from open_llm_vtuber.asr.fun_asr_gguf import VoiceRecognition  # noqa: E402


def load_mono_16k(path: Path) -> np.ndarray:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate != 16000:
        gcd = np.gcd(sample_rate, 16000)
        audio = resample_poly(audio, 16000 // gcd, sample_rate // gcd).astype(
            np.float32
        )
    return np.clip(audio, -1.0, 1.0).astype(np.float32)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run HaujetZhao/Fun-ASR-GGUF streaming recognition on a local WAV file."
    )
    parser.add_argument("wav", type=Path)
    parser.add_argument("--working-dir", default="Fun-ASR-GGUF")
    parser.add_argument("--model-dir", default="Fun-ASR-GGUF/model/model")
    parser.add_argument("--chunk-ms", type=int, default=600)
    parser.add_argument("--onnx-provider", default="DML")
    parser.add_argument("--partial-mode", choices=["ctc", "full"], default="ctc")
    parser.add_argument("--language", default="中文")
    args = parser.parse_args()

    audio = load_mono_16k(args.wav)
    engine = VoiceRecognition(
        working_dir=args.working_dir,
        model_dir=args.model_dir,
        language=args.language,
        onnx_provider=args.onnx_provider,
        streaming_enabled=True,
        streaming_partial_mode=args.partial_mode,
    )

    session_id = "file-smoke-test"
    chunk_samples = max(1, int(16000 * args.chunk_ms / 1000))
    try:
        for offset in range(0, len(audio), chunk_samples):
            chunk = audio[offset : offset + chunk_samples]
            is_final = offset + chunk_samples >= len(audio)
            results = await engine.async_streaming_transcribe_np(
                session_id,
                chunk,
                is_final=is_final,
            )
            for result in results:
                label = "final" if result.is_final else "partial"
                print(f"[{label}] {result.text}", flush=True)
    finally:
        engine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
