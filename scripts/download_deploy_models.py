"""Download deployment models used by the Windows backend-only profile.

This script is intentionally idempotent. It downloads and extracts the ASR and
KWS models referenced by the default deployment config, then generates the KWS
keywords file for the configured wake words.
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


ASR_MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
ASR_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{ASR_MODEL_NAME}.tar.bz2"
)

KWS_MODEL_NAME = "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
KWS_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
    f"{KWS_MODEL_NAME}.tar.bz2"
)

KWS_REQUIRED_FILES = [
    "encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
    "decoder-epoch-13-avg-2-chunk-16-left-64.onnx",
    "joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
    "tokens.txt",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download ASR/KWS models for Windows backend-only deployment."
    )
    parser.add_argument(
        "--models-dir",
        default="models",
        help="Directory used to store extracted model folders. Default: models",
    )
    parser.add_argument(
        "--wake-word",
        action="append",
        dest="wake_words",
        default=[],
        help="Wake word to write into KWS keywords.txt. May be repeated.",
    )
    parser.add_argument(
        "--skip-asr",
        action="store_true",
        help="Do not download the SenseVoice ASR model.",
    )
    parser.add_argument(
        "--skip-kws",
        action="store_true",
        help="Do not download the sherpa-onnx KWS model or generate keywords.txt.",
    )
    parser.add_argument(
        "--skip-vad",
        action="store_true",
        help="Do not verify the Silero VAD package model files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Download/extract even if the target model directory already exists.",
    )
    args = parser.parse_args()

    models_dir = Path(args.models_dir).resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    wake_words = args.wake_words or ["小智小智"]

    if not args.skip_asr:
        asr_dir = ensure_archive_extracted(
            url=ASR_MODEL_URL,
            output_dir=models_dir,
            expected_dir_name=ASR_MODEL_NAME,
            required_files=["model.int8.onnx", "tokens.txt"],
            force=args.force,
        )
        print(f"ASR model ready: {asr_dir}")

    if not args.skip_kws:
        kws_dir = ensure_archive_extracted(
            url=KWS_MODEL_URL,
            output_dir=models_dir,
            expected_dir_name=KWS_MODEL_NAME,
            required_files=KWS_REQUIRED_FILES,
            force=args.force,
        )
        keywords_path = write_kws_keywords(kws_dir, wake_words)
        print(f"KWS model ready: {kws_dir}")
        print(f"KWS keywords ready: {keywords_path}")

    if not args.skip_vad:
        vad_files = ensure_silero_vad_files()
        print("Silero VAD model files ready:")
        for path in vad_files:
            print(f"  {path}")

    return 0


def ensure_archive_extracted(
    url: str,
    output_dir: Path,
    expected_dir_name: str,
    required_files: list[str],
    force: bool = False,
) -> Path:
    target_dir = output_dir / expected_dir_name
    if not force and required_paths_exist(target_dir, required_files):
        print(f"Already present: {target_dir}")
        return target_dir

    local_archive = output_dir / f"{expected_dir_name}.tar.bz2"
    if local_archive.is_file():
        archive_path = local_archive
        print(f"Using existing archive: {archive_path}")
    else:
        archive_path = download_to_temp(url, output_dir)

    extract_tar_bz2(archive_path, output_dir)
    if archive_path != local_archive:
        archive_path.unlink(missing_ok=True)

    missing = missing_required_files(target_dir, required_files)
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Model extraction incomplete. Missing: {missing_text}")

    return target_dir


def required_paths_exist(target_dir: Path, required_files: list[str]) -> bool:
    return target_dir.is_dir() and not missing_required_files(target_dir, required_files)


def missing_required_files(target_dir: Path, required_files: list[str]) -> list[Path]:
    return [target_dir / name for name in required_files if not (target_dir / name).is_file()]


def download_to_temp(url: str, output_dir: Path) -> Path:
    file_name = url.rsplit("/", 1)[-1]
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{file_name}.", suffix=".download", dir=output_dir
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    print(f"Downloading: {url}")
    try:
        with urllib.request.urlopen(url) as response, tmp_path.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            copied = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                copied += len(chunk)
                if total:
                    percent = copied * 100 / total
                    print(f"\r  {copied / 1024 / 1024:.1f} MiB / {total / 1024 / 1024:.1f} MiB ({percent:.0f}%)", end="")
            if total:
                print()
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    final_path = output_dir / file_name
    tmp_path.replace(final_path)
    return final_path


def extract_tar_bz2(archive_path: Path, output_dir: Path) -> None:
    print(f"Extracting: {archive_path}")
    with tarfile.open(archive_path, "r:bz2") as tar:
        safe_extract(tar, output_dir)


def safe_extract(tar: tarfile.TarFile, output_dir: Path) -> None:
    output_root = output_dir.resolve()
    for member in tar.getmembers():
        member_path = (output_root / member.name).resolve()
        if output_root != member_path and output_root not in member_path.parents:
            raise RuntimeError(f"Unsafe archive member path: {member.name}")
    tar.extractall(output_root)


def write_kws_keywords(kws_dir: Path, wake_words: list[str]) -> Path:
    tokens_path = kws_dir / "tokens.txt"
    raw_path = kws_dir / "keywords_raw.txt"
    keywords_path = kws_dir / "keywords.txt"

    raw_lines = [f"{word} @{word}" for word in wake_words]
    raw_path.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")

    try:
        from sherpa_onnx.utils import text2token
    except ImportError as exc:
        raise RuntimeError(
            "sherpa-onnx is required to generate KWS keywords. Run `uv sync` first."
        ) from exc

    try:
        encoded_lines = text2token(
            wake_words,
            tokens=str(tokens_path),
            tokens_type="ppinyin",
            output_ids=False,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Generating Chinese KWS keywords requires `sentencepiece` and `pypinyin`. "
            "Install them with `uv pip install sentencepiece pypinyin`."
        ) from exc

    lines = [
        f"{' '.join(str(token) for token in tokens)} @{wake_word}"
        for tokens, wake_word in zip(encoded_lines, wake_words)
    ]
    keywords_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return keywords_path


def ensure_silero_vad_files() -> list[Path]:
    try:
        import silero_vad
    except ImportError as exc:
        raise RuntimeError(
            "silero-vad is required for VAD. Run `uv sync` before this script."
        ) from exc

    package_dir = Path(silero_vad.__file__).resolve().parent
    data_dir = package_dir / "data"
    required = [
        data_dir / "silero_vad.jit",
        data_dir / "silero_vad.onnx",
        data_dir / "silero_vad_16k.safetensors",
    ]
    missing = [path for path in required if not path.is_file()]
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Missing Silero VAD model files: {missing_text}")

    try:
        from silero_vad import load_silero_vad

        load_silero_vad()
    except Exception as exc:
        raise RuntimeError("Silero VAD package is installed but failed to load.") from exc

    return required


if __name__ == "__main__":
    raise SystemExit(main())
