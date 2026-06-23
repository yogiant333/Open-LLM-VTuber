from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import soundfile as sf
import yaml

from src.open_llm_vtuber.asr.asr_factory import ASRFactory


def convert_to_wav(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
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
            str(output_path),
        ],
        check=True,
    )


def load_asr_config(config_path: Path) -> dict:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config["character_config"]["asr_config"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare configured ASR providers on one audio file.")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--providers", default="sherpa_onnx_asr,qwen3_asr")
    parser.add_argument("--chunk-sec", type=float, default=25.0)
    parser.add_argument("--config", type=Path, default=Path("conf.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/asr_benchmark"))
    parser.add_argument("--prefix", default="")
    args = parser.parse_args()

    if not args.audio.is_file():
        raise FileNotFoundError(args.audio)

    prefix = args.prefix or args.audio.stem
    wav_path = args.output_dir / f"{prefix}_16k.wav"
    json_path = args.output_dir / f"{prefix}_compare.json"
    txt_path = args.output_dir / f"{prefix}_compare.txt"

    convert_to_wav(args.audio, wav_path)
    audio, sample_rate = sf.read(str(wav_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    duration_sec = len(audio) / sample_rate
    chunk_samples = int(args.chunk_sec * sample_rate)
    chunks = []
    for start in range(0, len(audio), chunk_samples):
        end = min(len(audio), start + chunk_samples)
        if (end - start) / sample_rate >= 1.0:
            chunks.append((start / sample_rate, end / sample_rate, audio[start:end]))

    asr_config = load_asr_config(args.config)
    hotwords = asr_config.get("hotwords") or []
    providers = [item.strip() for item in args.providers.split(",") if item.strip()]

    print(f"audio duration={duration_sec:.2f}s sample_rate={sample_rate} chunks={len(chunks)}")

    engines = {}
    init_times = {}
    for provider in providers:
        kwargs = dict(asr_config[provider])
        kwargs["hotwords"] = hotwords
        print(f"initializing {provider}...")
        started = time.perf_counter()
        engines[provider] = ASRFactory.get_asr_system(provider, **kwargs)
        init_times[provider] = time.perf_counter() - started
        print(f"initialized {provider} in {init_times[provider]:.2f}s")

    report = {
        "audio": {
            "source": str(args.audio),
            "wav": str(wav_path),
            "duration_sec": duration_sec,
            "sample_rate": sample_rate,
            "chunk_sec": args.chunk_sec,
        },
        "init_times_sec": init_times,
        "chunks": [],
        "summary": {},
    }

    for index, (start_sec, end_sec, samples) in enumerate(chunks, 1):
        row = {
            "index": index,
            "start_sec": round(start_sec, 3),
            "end_sec": round(end_sec, 3),
            "duration_sec": round(end_sec - start_sec, 3),
            "results": {},
        }
        print(f"chunk {index}/{len(chunks)} {start_sec:.1f}-{end_sec:.1f}s")
        for provider in providers:
            started = time.perf_counter()
            try:
                text = engines[provider].transcribe_np(samples)
                error = None
            except Exception as exc:
                text = ""
                error = repr(exc)
            elapsed_sec = time.perf_counter() - started
            row["results"][provider] = {
                "text": text,
                "elapsed_sec": elapsed_sec,
                "rtf": elapsed_sec / (end_sec - start_sec),
                "error": error,
            }
            print(
                f"  {provider}: {elapsed_sec:.2f}s "
                f"rtf={elapsed_sec / (end_sec - start_sec):.3f} "
                f"text={text[:120]} error={error}"
            )
        report["chunks"].append(row)

    for provider in providers:
        total_elapsed = sum(
            chunk["results"][provider]["elapsed_sec"] for chunk in report["chunks"]
        )
        full_text = "".join(
            chunk["results"][provider]["text"] for chunk in report["chunks"]
        )
        report["summary"][provider] = {
            "init_sec": init_times[provider],
            "total_elapsed_sec": total_elapsed,
            "rtf_excluding_init": total_elapsed / duration_sec,
            "text": full_text,
        }

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"audio={wav_path}",
        f"duration={duration_sec:.2f}s sample_rate={sample_rate} chunks={len(chunks)}",
    ]
    for provider in providers:
        summary = report["summary"][provider]
        lines.extend(
            [
                "",
                (
                    f"[{provider}] init={summary['init_sec']:.2f}s "
                    f"transcribe={summary['total_elapsed_sec']:.2f}s "
                    f"rtf={summary['rtf_excluding_init']:.3f}"
                ),
                summary["text"],
            ]
        )
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"JSON {json_path}")
    print(f"TXT {txt_path}")


if __name__ == "__main__":
    main()
