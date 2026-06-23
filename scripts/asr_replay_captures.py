from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import requests


def iter_capture_jsons(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.json")))
        elif path.is_file() and path.suffix.lower() == ".json":
            files.append(path)
    return files


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
            files={"file": (wav_path.name, wav_file, "audio/wav")},
            data={
                "providers": json.dumps(providers, ensure_ascii=False),
                "hotwords": json.dumps(hotwords, ensure_ascii=False),
                "reference_text": reference_text,
            },
            timeout=timeout,
        )
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay saved ASR capture samples against benchmark providers."
    )
    parser.add_argument(
        "captures",
        nargs="*",
        type=Path,
        default=[Path("reports/asr_captures")],
        help="Capture JSON files or directories. Defaults to reports/asr_captures.",
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:18080")
    parser.add_argument("--providers", default="sherpa_onnx_asr")
    parser.add_argument("--hotwords", default="")
    parser.add_argument("--output", type=Path, default=Path("reports/asr_captures/replay_results.csv"))
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    providers = [item.strip() for item in args.providers.split(",") if item.strip()]
    hotwords = [item.strip() for item in args.hotwords.split(",") if item.strip()]
    if not providers:
        raise ValueError("At least one provider is required.")

    rows: list[dict[str, Any]] = []
    for json_path in iter_capture_jsons(args.captures):
        capture = json.loads(json_path.read_text(encoding="utf-8"))
        wav_path = Path(capture["audio"]["path"])
        if not wav_path.is_absolute():
            wav_path = Path.cwd() / wav_path
        if not wav_path.is_file():
            print(f"skip missing wav: {wav_path}")
            continue

        reference = capture.get("transcript", "")
        print(f"replay {json_path} providers={','.join(providers)}")
        result = post_benchmark(
            args.backend_url,
            wav_path,
            providers,
            hotwords,
            reference,
            args.timeout,
        )
        for item in result.get("results", []):
            rows.append(
                {
                    "capture": str(json_path),
                    "wav": str(wav_path),
                    "source_provider": capture.get("provider", ""),
                    "provider": item.get("provider", ""),
                    "reference": reference,
                    "hypothesis": item.get("text", ""),
                    "duration_ms": result.get("audio", {}).get("duration_ms", ""),
                    "elapsed_ms": item.get("elapsed_ms", ""),
                    "rtf": item.get("rtf", ""),
                    "cer": item.get("cer", ""),
                    "wer": item.get("wer", ""),
                    "error": item.get("error", ""),
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "capture",
        "wav",
        "source_provider",
        "provider",
        "reference",
        "hypothesis",
        "duration_ms",
        "elapsed_ms",
        "rtf",
        "cer",
        "wer",
        "error",
    ]
    with args.output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {args.output} rows={len(rows)}")


if __name__ == "__main__":
    main()
