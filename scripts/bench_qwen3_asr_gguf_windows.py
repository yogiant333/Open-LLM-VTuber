from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import soundfile as sf
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.open_llm_vtuber.asr.asr_factory import ASRFactory
from scripts.asr_benchmark_srt import (
    char_error_stats,
    extract_segment,
    merge_segments,
    parse_srt,
)


def convert_to_wav(input_path: Path, output_path: Path, duration_sec: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
    ]
    if duration_sec > 0:
        command.extend(["-t", str(duration_sec)])
    command.append(str(output_path))
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Qwen3-ASR-GGUF in-process on Windows.")
    parser.add_argument("--audio", type=Path, default=Path("doc/黑神话/1.mp3"))
    parser.add_argument("--config", type=Path, default=Path("conf.yaml"))
    parser.add_argument("--duration-sec", type=float, default=30.0)
    parser.add_argument("--srt", type=Path)
    parser.add_argument("--max-segments", type=int, default=0)
    parser.add_argument("--timestamp", action="store_true", help="Enable ForceAligner timestamp output.")
    parser.add_argument(
        "--preset",
        choices=("config", "int4-q4", "fp16-q5"),
        default="config",
        help="Override ASR model file names for common Qwen3-ASR-GGUF precision presets.",
    )
    parser.add_argument("--asr-encoder-frontend", help="Override ASR encoder frontend ONNX file name.")
    parser.add_argument("--asr-encoder-backend", help="Override ASR encoder backend ONNX file name.")
    parser.add_argument("--asr-llm", help="Override ASR decoder GGUF file name.")
    parser.add_argument("--output", type=Path, default=Path("reports/asr_benchmark/qwen3_gguf_windows_direct.json"))
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    asr_config = config["character_config"]["asr_config"]
    kwargs = dict(asr_config["qwen3_asr_gguf"])
    kwargs["hotwords"] = asr_config.get("hotwords") or []
    kwargs["timestamp"] = args.timestamp
    if args.preset == "int4-q4":
        kwargs.update(
            {
                "asr_encoder_frontend": "qwen3_asr_encoder_frontend.int4.onnx",
                "asr_encoder_backend": "qwen3_asr_encoder_backend.int4.onnx",
                "asr_llm": "qwen3_asr_llm.q4_k.gguf",
            }
        )
    elif args.preset == "fp16-q5":
        kwargs.update(
            {
                "asr_encoder_frontend": "qwen3_asr_encoder_frontend.fp16.onnx",
                "asr_encoder_backend": "qwen3_asr_encoder_backend.fp16.onnx",
                "asr_llm": "qwen3_asr_llm.q5_k.gguf",
            }
        )
    if args.asr_encoder_frontend:
        kwargs["asr_encoder_frontend"] = args.asr_encoder_frontend
    if args.asr_encoder_backend:
        kwargs["asr_encoder_backend"] = args.asr_encoder_backend
    if args.asr_llm:
        kwargs["asr_llm"] = args.asr_llm

    init_started = time.perf_counter()
    engine = ASRFactory.get_asr_system("qwen3_asr_gguf", **kwargs)
    init_sec = time.perf_counter() - init_started

    if args.srt:
        rows = []
        segments = merge_segments(
            parse_srt(args.srt),
            max_gap_ms=400,
            min_duration_ms=1400,
            max_duration_ms=8000,
        )
        if args.max_segments > 0:
            segments = segments[: args.max_segments]

        tmp_dir = args.output.parent / f"{args.output.stem}_segments"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        total_elapsed_sec = 0.0
        total_duration_sec = 0.0
        total_edit_distance = 0
        total_reference_chars = 0
        for ordinal, segment in enumerate(segments, 1):
            segment_wav = tmp_dir / f"segment_{segment.index}.wav"
            extract_segment(args.audio, segment, segment_wav)
            audio, sample_rate = sf.read(str(segment_wav), dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            duration_sec = len(audio) / sample_rate
            run_started = time.perf_counter()
            text = engine.transcribe_np(audio)
            elapsed_sec = time.perf_counter() - run_started
            edit_distance, reference_chars = char_error_stats(segment.text, text)
            total_elapsed_sec += elapsed_sec
            total_duration_sec += duration_sec
            total_edit_distance += edit_distance
            total_reference_chars += reference_chars
            row = {
                "segment_index": segment.index,
                "reference": segment.text,
                "hypothesis": text,
                "duration_sec": duration_sec,
                "elapsed_sec": elapsed_sec,
                "rtf": elapsed_sec / duration_sec if duration_sec else None,
                "cer": edit_distance / reference_chars if reference_chars else None,
            }
            rows.append(row)
            print(
                f"[{ordinal}/{len(segments)}] #{segment.index} "
                f"cer={row['cer']} rtf={row['rtf']:.4f} text={text}"
            )

        result = {
            "audio": str(args.audio),
            "srt": str(args.srt),
            "init_sec": init_sec,
            "segments": rows,
            "summary": {
                "segments": len(rows),
                "duration_sec": total_duration_sec,
                "elapsed_sec": total_elapsed_sec,
                "rtf_excluding_init": total_elapsed_sec / total_duration_sec
                if total_duration_sec
                else None,
                "rtf_including_init": (total_elapsed_sec + init_sec) / total_duration_sec
                if total_duration_sec
                else None,
                "cer": total_edit_distance / total_reference_chars
                if total_reference_chars
                else None,
            },
        }
    else:
        wav_path = args.output.with_suffix(".wav")
        convert_to_wav(args.audio, wav_path, args.duration_sec)
        audio, sample_rate = sf.read(str(wav_path), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        duration_sec = len(audio) / sample_rate

        run_started = time.perf_counter()
        text = engine.transcribe_np(audio)
        elapsed_sec = time.perf_counter() - run_started

        result = {
            "audio": str(args.audio),
            "wav": str(wav_path),
            "duration_sec": duration_sec,
            "init_sec": init_sec,
            "elapsed_sec": elapsed_sec,
            "rtf_excluding_init": elapsed_sec / duration_sec if duration_sec else None,
            "rtf_including_init": (elapsed_sec + init_sec) / duration_sec if duration_sec else None,
            "text": text,
        }

    shutdown = getattr(engine, "shutdown", None)
    if callable(shutdown):
        shutdown()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
