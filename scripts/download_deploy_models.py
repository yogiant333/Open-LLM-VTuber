"""Download local model assets for the Windows backend deployment.

Default behavior matches the current Windows profile:

- Qwen3-ASR-GGUF ASR: 1.7B fp16/q5_k from CapsWriter-Offline
- Qwen3-ASR-GGUF aligner: 0.6B int4/q4_k from Qwen3-ASR-GGUF
- Qwen3-ASR-GGUF Windows runtime DLLs from Qwen3-ASR-GGUF v0.1

The script is idempotent and keeps downloaded archives outside git-tracked model
paths. Model weights and DLLs are local deployment assets; do not commit them.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


QWEN_GGUF_ASR_Q5_URL = (
    "https://github.com/HaujetZhao/CapsWriter-Offline/releases/download/models/"
    "Qwen3-ASR-1.7B-q5_k.zip"
)
QWEN_GGUF_ALIGNER_URL = (
    "https://github.com/HaujetZhao/Qwen3-ASR-GGUF/releases/download/models/"
    "Qwen3-ForceAligner-0.6B-gguf.zip"
)
QWEN_GGUF_RUNTIME_URL = (
    "https://github.com/HaujetZhao/Qwen3-ASR-GGUF/releases/download/v0.1/"
    "Qwen3-ASR-Transcribe-20260223.zip"
)

QWEN_ASR_REQUIRED_FILES = [
    "qwen3_asr_encoder_frontend.fp16.onnx",
    "qwen3_asr_encoder_backend.fp16.onnx",
    "qwen3_asr_llm.q5_k.gguf",
]
QWEN_ALIGNER_REQUIRED_FILES = [
    "qwen3_aligner_encoder_frontend.int4.onnx",
    "qwen3_aligner_encoder_backend.int4.onnx",
    "qwen3_aligner_llm.q4_k.gguf",
]
QWEN_RUNTIME_REQUIRED_FILES = [
    "llama.dll",
    "ggml-vulkan.dll",
    "ggml-base.dll",
    "libomp140.x86_64.dll",
]

SHERPA_ASR_MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
SHERPA_ASR_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{SHERPA_ASR_MODEL_NAME}.tar.bz2"
)
SHERPA_KWS_MODEL_NAME = "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
SHERPA_KWS_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
    f"{SHERPA_KWS_MODEL_NAME}.tar.bz2"
)
SHERPA_KWS_REQUIRED_FILES = [
    "encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
    "decoder-epoch-13-avg-2-chunk-16-left-64.onnx",
    "joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
    "tokens.txt",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download model assets for the Windows backend deployment."
    )
    parser.add_argument(
        "--qwen-dir",
        default="Qwen3-ASR-GGUF",
        help="Qwen3-ASR-GGUF submodule directory. Default: Qwen3-ASR-GGUF",
    )
    parser.add_argument(
        "--download-dir",
        default="downloads/deploy-models",
        help="Archive cache directory. Default: downloads/deploy-models",
    )
    parser.add_argument(
        "--skip-qwen",
        action="store_true",
        help="Skip all Qwen3-ASR-GGUF downloads.",
    )
    parser.add_argument(
        "--skip-qwen-asr",
        action="store_true",
        help="Skip Qwen3-ASR-GGUF ASR model download.",
    )
    parser.add_argument(
        "--skip-qwen-aligner",
        action="store_true",
        help="Skip Qwen3-ASR-GGUF aligner model download.",
    )
    parser.add_argument(
        "--skip-qwen-runtime",
        action="store_true",
        help="Skip Qwen3-ASR-GGUF Windows runtime DLL download.",
    )
    parser.add_argument(
        "--include-sherpa",
        action="store_true",
        help="Also download legacy sherpa-onnx ASR/KWS models.",
    )
    parser.add_argument(
        "--models-dir",
        default="models",
        help="Directory for legacy sherpa-onnx models. Default: models",
    )
    parser.add_argument(
        "--wake-word",
        action="append",
        dest="wake_words",
        default=[],
        help="Wake word for legacy sherpa-onnx KWS keywords.txt. May be repeated.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Download/extract even if required target files already exist.",
    )
    args = parser.parse_args()

    download_dir = Path(args.download_dir).resolve()
    download_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_qwen:
        ensure_qwen_assets(
            qwen_dir=Path(args.qwen_dir).resolve(),
            download_dir=download_dir,
            skip_asr=args.skip_qwen_asr,
            skip_aligner=args.skip_qwen_aligner,
            skip_runtime=args.skip_qwen_runtime,
            force=args.force,
        )

    if args.include_sherpa:
        ensure_sherpa_assets(
            models_dir=Path(args.models_dir).resolve(),
            wake_words=args.wake_words or ["小智小智"],
            force=args.force,
        )

    print("Model download complete.")
    return 0


def ensure_qwen_assets(
    qwen_dir: Path,
    download_dir: Path,
    skip_asr: bool,
    skip_aligner: bool,
    skip_runtime: bool,
    force: bool,
) -> None:
    if not qwen_dir.is_dir():
        raise FileNotFoundError(
            f"Missing Qwen3-ASR-GGUF submodule: {qwen_dir}. "
            "Run `git submodule update --init --recursive` first."
        )
    configure_qwen_submodule_excludes(qwen_dir)

    model_dir = qwen_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)

    if not skip_asr:
        if force or not required_paths_exist(model_dir, QWEN_ASR_REQUIRED_FILES):
            archive = download_archive(QWEN_GGUF_ASR_Q5_URL, download_dir)
            with tempfile.TemporaryDirectory(prefix="qwen-asr-", dir=download_dir) as tmp:
                tmp_dir = Path(tmp)
                extract_zip(archive, tmp_dir)
                source_root = tmp_dir / "Qwen3-ASR-1.7B"
                copy_required_file(
                    source_root / "qwen3_asr_encoder_frontend.onnx",
                    model_dir / "qwen3_asr_encoder_frontend.fp16.onnx",
                )
                copy_required_file(
                    source_root / "qwen3_asr_encoder_backend.onnx",
                    model_dir / "qwen3_asr_encoder_backend.fp16.onnx",
                )
                copy_required_file(
                    source_root / "qwen3_asr_llm.gguf",
                    model_dir / "qwen3_asr_llm.q5_k.gguf",
                )
        verify_required(model_dir, QWEN_ASR_REQUIRED_FILES, "Qwen3-ASR-GGUF ASR")
        print(f"Qwen3-ASR-GGUF ASR ready: {model_dir}")

    if not skip_aligner:
        if force or not required_paths_exist(model_dir, QWEN_ALIGNER_REQUIRED_FILES):
            archive = download_archive(QWEN_GGUF_ALIGNER_URL, download_dir)
            extract_zip(archive, model_dir)
        verify_required(
            model_dir, QWEN_ALIGNER_REQUIRED_FILES, "Qwen3-ASR-GGUF aligner"
        )
        print(f"Qwen3-ASR-GGUF aligner ready: {model_dir}")

    if not skip_runtime:
        runtime_dir = qwen_dir / "qwen_asr_gguf" / "inference" / "bin"
        if force or not required_paths_exist(runtime_dir, QWEN_RUNTIME_REQUIRED_FILES):
            archive = download_archive(QWEN_GGUF_RUNTIME_URL, download_dir)
            with tempfile.TemporaryDirectory(prefix="qwen-runtime-", dir=download_dir) as tmp:
                tmp_dir = Path(tmp)
                extract_zip(archive, tmp_dir)
                source_dir = (
                    tmp_dir
                    / "Qwen3-ASR-Transcribe"
                    / "qwen_asr_gguf"
                    / "inference"
                    / "bin"
                )
                copy_tree_contents(source_dir, runtime_dir)
        verify_required(
            runtime_dir, QWEN_RUNTIME_REQUIRED_FILES, "Qwen3-ASR-GGUF runtime"
        )
        print(f"Qwen3-ASR-GGUF Windows runtime ready: {runtime_dir}")


def ensure_sherpa_assets(models_dir: Path, wake_words: list[str], force: bool) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    asr_dir = ensure_tar_bz2_extracted(
        url=SHERPA_ASR_MODEL_URL,
        output_dir=models_dir,
        expected_dir_name=SHERPA_ASR_MODEL_NAME,
        required_files=["model.int8.onnx", "tokens.txt"],
        force=force,
    )
    kws_dir = ensure_tar_bz2_extracted(
        url=SHERPA_KWS_MODEL_URL,
        output_dir=models_dir,
        expected_dir_name=SHERPA_KWS_MODEL_NAME,
        required_files=SHERPA_KWS_REQUIRED_FILES,
        force=force,
    )
    keywords_path = write_kws_keywords(kws_dir, wake_words)
    print(f"Legacy sherpa ASR ready: {asr_dir}")
    print(f"Legacy sherpa KWS ready: {kws_dir}")
    print(f"Legacy sherpa KWS keywords ready: {keywords_path}")


def ensure_tar_bz2_extracted(
    url: str,
    output_dir: Path,
    expected_dir_name: str,
    required_files: list[str],
    force: bool,
) -> Path:
    target_dir = output_dir / expected_dir_name
    if not force and required_paths_exist(target_dir, required_files):
        return target_dir

    archive = download_archive(url, output_dir)
    with tarfile.open(archive, "r:bz2") as tar:
        safe_extract_tar(tar, output_dir)
    verify_required(target_dir, required_files, expected_dir_name)
    return target_dir


def download_archive(url: str, download_dir: Path) -> Path:
    file_name = url.rsplit("/", 1)[-1]
    final_path = download_dir / file_name
    if final_path.is_file():
        print(f"Using cached archive: {final_path}")
        return final_path

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{file_name}.", suffix=".download", dir=download_dir
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
                    print(
                        f"\r  {copied / 1024 / 1024:.1f} MiB / "
                        f"{total / 1024 / 1024:.1f} MiB ({percent:.0f}%)",
                        end="",
                    )
            if total:
                print()
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    tmp_path.replace(final_path)
    return final_path


def extract_zip(archive_path: Path, output_dir: Path) -> None:
    print(f"Extracting: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        safe_extract_zip(archive, output_dir)


def safe_extract_zip(archive: zipfile.ZipFile, output_dir: Path) -> None:
    output_root = output_dir.resolve()
    for member in archive.infolist():
        member_path = (output_root / member.filename).resolve()
        if output_root != member_path and output_root not in member_path.parents:
            raise RuntimeError(f"Unsafe archive member path: {member.filename}")
    archive.extractall(output_root)


def safe_extract_tar(tar: tarfile.TarFile, output_dir: Path) -> None:
    output_root = output_dir.resolve()
    for member in tar.getmembers():
        member_path = (output_root / member.name).resolve()
        if output_root != member_path and output_root not in member_path.parents:
            raise RuntimeError(f"Unsafe archive member path: {member.name}")
    tar.extractall(output_root)


def copy_required_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Archive did not contain expected file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree_contents(source_dir: Path, destination_dir: Path) -> None:
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Archive did not contain expected directory: {source_dir}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    for source in source_dir.iterdir():
        destination = destination_dir / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)


def required_paths_exist(target_dir: Path, required_files: list[str]) -> bool:
    return target_dir.is_dir() and not missing_required_files(target_dir, required_files)


def missing_required_files(target_dir: Path, required_files: list[str]) -> list[Path]:
    return [target_dir / name for name in required_files if not (target_dir / name).is_file()]


def verify_required(target_dir: Path, required_files: list[str], label: str) -> None:
    missing = missing_required_files(target_dir, required_files)
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"{label} is incomplete. Missing: {missing_text}")


def configure_qwen_submodule_excludes(qwen_dir: Path) -> None:
    git_dir = get_submodule_git_dir(qwen_dir)
    exclude_path = git_dir / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""
    lines = existing.splitlines()
    for pattern in ("/model/", "/logs/", "/qwen_asr_gguf/inference/bin/", "__pycache__/"):
        if pattern not in lines:
            lines.append(pattern)
    exclude_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def get_submodule_git_dir(qwen_dir: Path) -> Path:
    dot_git = qwen_dir / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        content = dot_git.read_text(encoding="utf-8").strip()
        prefix = "gitdir:"
        if not content.lower().startswith(prefix):
            raise RuntimeError(f"Unexpected submodule .git file content: {dot_git}")
        raw_path = content[len(prefix) :].strip()
        git_dir = Path(raw_path)
        if not git_dir.is_absolute():
            git_dir = (qwen_dir / git_dir).resolve()
        return git_dir
    raise FileNotFoundError(f"Cannot locate submodule git directory: {qwen_dir}")


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

    encoded_lines = text2token(
        wake_words,
        tokens=str(tokens_path),
        tokens_type="ppinyin",
        output_ids=False,
    )
    lines = [
        f"{' '.join(str(token) for token in tokens)} @{wake_word}"
        for tokens, wake_word in zip(encoded_lines, wake_words)
    ]
    keywords_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return keywords_path


if __name__ == "__main__":
    raise SystemExit(main())
