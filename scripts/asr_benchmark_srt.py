from __future__ import annotations

import argparse
import csv
import json
import unicodedata
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


DEFAULT_AUDIO = Path("doc/黑神话/1.mp3")
DEFAULT_SRT = Path("doc/黑神话/1.srt")
DEFAULT_OUTPUT_DIR = Path("reports/asr_benchmark")


@dataclass(frozen=True)
class SubtitleSegment:
    index: int
    start_ms: int
    end_ms: int
    text: str

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def parse_srt_timestamp(value: str) -> int:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1000
        + int(millis)
    )


def parse_srt(path: Path) -> list[SubtitleSegment]:
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = [block.strip() for block in content.replace("\r\n", "\n").split("\n\n")]
    segments: list[SubtitleSegment] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        try:
            index = int(lines[0])
            start_raw, end_raw = [part.strip() for part in lines[1].split("-->")]
            text = " ".join(lines[2:]).strip()
            segments.append(
                SubtitleSegment(
                    index=index,
                    start_ms=parse_srt_timestamp(start_raw),
                    end_ms=parse_srt_timestamp(end_raw),
                    text=text,
                )
            )
        except ValueError:
            continue
    return segments


def merge_segments(
    segments: list[SubtitleSegment],
    max_gap_ms: int,
    min_duration_ms: int,
    max_duration_ms: int,
) -> list[SubtitleSegment]:
    merged: list[SubtitleSegment] = []
    current: SubtitleSegment | None = None

    for segment in segments:
        if not segment.text:
            continue
        if current is None:
            current = segment
            continue

        gap_ms = segment.start_ms - current.end_ms
        next_duration = segment.end_ms - current.start_ms
        should_merge = (
            gap_ms <= max_gap_ms
            and (current.duration_ms < min_duration_ms or next_duration <= max_duration_ms)
        )
        if should_merge:
            current = SubtitleSegment(
                index=current.index,
                start_ms=current.start_ms,
                end_ms=segment.end_ms,
                text=f"{current.text}{segment.text}",
            )
        else:
            merged.append(current)
            current = segment

    if current is not None:
        merged.append(current)
    return merged


def normalize_text(text: str) -> str:
    normalized = []
    for char in (text or "").lower():
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            normalized.append(char)
    return "".join(normalized)


def levenshtein(left: list[str], right: list[str]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_item in enumerate(left, 1):
        current = [i]
        for j, right_item in enumerate(right, 1):
            cost = 0 if left_item == right_item else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


def char_error_stats(reference: str, hypothesis: str) -> tuple[int, int]:
    reference_chars = list(normalize_text(reference))
    hypothesis_chars = list(normalize_text(hypothesis))
    return levenshtein(reference_chars, hypothesis_chars), len(reference_chars)


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required but was not found in PATH")


def extract_segment(audio_path: Path, segment: SubtitleSegment, output_path: Path) -> None:
    start_sec = max(0, segment.start_ms - 120) / 1000
    duration_sec = (segment.duration_ms + 240) / 1000
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        str(audio_path),
        "-t",
        f"{duration_sec:.3f}",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(output_path),
    ]
    subprocess.run(command, check=True)


def post_benchmark(
    backend_url: str,
    wav_path: Path,
    providers: list[str],
    hotwords: list[str],
    reference_text: str,
    timeout: int,
) -> dict[str, Any]:
    endpoint = f"{backend_url.rstrip('/')}/api/asr-benchmark/transcribe"
    with wav_path.open("rb") as wav_file:
        response = requests.post(
            endpoint,
            files={"file": ("segment.wav", wav_file, "audio/wav")},
            data={
                "providers": json.dumps(providers, ensure_ascii=False),
                "hotwords": json.dumps(hotwords, ensure_ascii=False),
                "reference_text": reference_text,
            },
            timeout=timeout,
        )
    response.raise_for_status()
    return response.json()


def fetch_default_hotwords(backend_url: str, timeout: int) -> list[str]:
    endpoint = f"{backend_url.rstrip('/')}/api/asr-benchmark/providers"
    response = requests.get(endpoint, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return [word for word in data.get("hotwords", []) if isinstance(word, str)]


def write_reports(rows: list[dict[str, Any]], output_dir: Path, prefix: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{prefix}.json"
    csv_path = output_dir / f"{prefix}.csv"
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fieldnames = [
        "segment_index",
        "provider",
        "reference",
        "hypothesis",
        "duration_ms",
        "elapsed_ms",
        "rtf",
        "cer",
        "hotword_hits",
        "error",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark ASR with an MP3/SRT pair.")
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO)
    parser.add_argument("--srt", type=Path, default=DEFAULT_SRT)
    parser.add_argument("--backend-url", default="http://127.0.0.1:18080")
    parser.add_argument("--providers", default="qwen3_asr")
    parser.add_argument("--hotwords", default="")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prefix", default="black-myth-1")
    parser.add_argument("--start", type=int, default=0, help="0-based merged segment offset")
    parser.add_argument("--max-segments", type=int, default=20)
    parser.add_argument("--merge-gap-ms", type=int, default=400)
    parser.add_argument("--min-duration-ms", type=int, default=1400)
    parser.add_argument("--max-duration-ms", type=int, default=8000)
    parser.add_argument("--timeout", type=int, default=180)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ensure_ffmpeg()
    if not args.audio.is_file():
        raise FileNotFoundError(args.audio)
    if not args.srt.is_file():
        raise FileNotFoundError(args.srt)

    providers = [item.strip() for item in args.providers.split(",") if item.strip()]
    hotwords = [item.strip() for item in args.hotwords.split(",") if item.strip()]
    if not hotwords:
        hotwords = fetch_default_hotwords(args.backend_url, args.timeout)

    segments = merge_segments(
        parse_srt(args.srt),
        max_gap_ms=args.merge_gap_ms,
        min_duration_ms=args.min_duration_ms,
        max_duration_ms=args.max_duration_ms,
    )
    selected = segments[args.start :]
    if args.max_segments > 0:
        selected = selected[: args.max_segments]
    if not selected:
        raise RuntimeError("No subtitle segments selected")

    rows: list[dict[str, Any]] = []
    total_edit_distance: dict[str, int] = {}
    total_reference_chars: dict[str, int] = {}
    total_elapsed_ms: dict[str, float] = {}
    total_audio_ms: dict[str, float] = {}

    run_started = time.strftime("%Y%m%d_%H%M%S")
    with tempfile.TemporaryDirectory(prefix="asr_benchmark_") as temp_dir:
        temp_path = Path(temp_dir)
        for ordinal, segment in enumerate(selected, 1):
            wav_path = temp_path / f"segment_{segment.index}.wav"
            extract_segment(args.audio, segment, wav_path)
            print(
                f"[{ordinal}/{len(selected)}] #{segment.index} "
                f"{segment.duration_ms}ms ref={segment.text}"
            )
            response = post_benchmark(
                args.backend_url,
                wav_path,
                providers,
                hotwords,
                segment.text,
                args.timeout,
            )
            audio_info = response.get("audio", {})
            for result in response.get("results", []):
                provider = result.get("provider", "")
                hypothesis = result.get("text", "")
                edit_distance, reference_chars = char_error_stats(
                    segment.text, hypothesis
                )
                total_edit_distance[provider] = (
                    total_edit_distance.get(provider, 0) + edit_distance
                )
                total_reference_chars[provider] = (
                    total_reference_chars.get(provider, 0) + reference_chars
                )
                total_elapsed_ms[provider] = total_elapsed_ms.get(provider, 0.0) + float(
                    result.get("elapsed_ms") or 0
                )
                total_audio_ms[provider] = total_audio_ms.get(provider, 0.0) + float(
                    audio_info.get("duration_ms") or 0
                )
                row = {
                    "segment_index": segment.index,
                    "provider": provider,
                    "reference": segment.text,
                    "hypothesis": hypothesis,
                    "duration_ms": audio_info.get("duration_ms"),
                    "elapsed_ms": result.get("elapsed_ms"),
                    "rtf": result.get("rtf"),
                    "cer": edit_distance / reference_chars
                    if reference_chars
                    else None,
                    "hotword_hits": "、".join(result.get("hotword_hits") or []),
                    "error": result.get("error"),
                }
                rows.append(row)
                print(
                    f"  {provider}: cer={row['cer']} rtf={row['rtf']} "
                    f"text={hypothesis} error={row['error']}"
                )

    print("\nSummary")
    for provider in providers:
        reference_chars = total_reference_chars.get(provider, 0)
        aggregate_cer = (
            total_edit_distance.get(provider, 0) / reference_chars
            if reference_chars
            else None
        )
        aggregate_rtf = (
            total_elapsed_ms.get(provider, 0.0) / total_audio_ms.get(provider, 0.0)
            if total_audio_ms.get(provider, 0.0)
            else None
        )
        cer_text = f"{aggregate_cer:.4f}" if aggregate_cer is not None else "n/a"
        rtf_text = f"{aggregate_rtf:.4f}" if aggregate_rtf is not None else "n/a"
        print(
            f"{provider}: segments={sum(1 for row in rows if row['provider'] == provider)} "
            f"CER={cer_text} RTF={rtf_text}"
        )

    write_reports(rows, args.output_dir, f"{args.prefix}_{run_started}")


if __name__ == "__main__":
    main()
