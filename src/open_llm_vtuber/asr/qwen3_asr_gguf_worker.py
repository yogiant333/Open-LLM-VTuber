from __future__ import annotations

import base64
import json
import sys
import traceback
from contextlib import redirect_stdout

import numpy as np

from .qwen3_asr_gguf import _InProcessVoiceRecognition


def _write_response(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _decode_audio(message: dict) -> np.ndarray:
    if message.get("dtype") != "float32":
        raise ValueError(f"Unsupported audio dtype: {message.get('dtype')!r}")
    raw = base64.b64decode(message.get("audio") or "", validate=True)
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    expected_shape = message.get("shape")
    if isinstance(expected_shape, list) and expected_shape:
        expected_size = int(expected_shape[0])
        if audio.size != expected_size:
            raise ValueError(f"Audio size mismatch: expected={expected_size} got={audio.size}")
    return audio


def main() -> int:
    engine: _InProcessVoiceRecognition | None = None
    for line in sys.stdin:
        message = {}
        try:
            message = json.loads(line)
            message_type = message.get("type")

            if message_type == "init":
                with redirect_stdout(sys.stderr):
                    engine = _InProcessVoiceRecognition(**(message.get("config") or {}))
                _write_response({"ok": True, "type": "init"})
                continue

            if message_type == "shutdown":
                if engine is not None:
                    engine.shutdown()
                _write_response({"ok": True, "type": "shutdown"})
                return 0

            if message_type == "transcribe":
                if engine is None:
                    raise RuntimeError("Worker is not initialized")
                audio = _decode_audio(message)
                text = engine.transcribe_np(audio)
                _write_response(
                    {
                        "ok": True,
                        "type": "transcribe",
                        "id": message.get("id"),
                        "text": text,
                    }
                )
                continue

            raise ValueError(f"Unknown worker message type: {message_type!r}")
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            _write_response(
                {
                    "ok": False,
                    "type": message.get("type") if isinstance(message, dict) else None,
                    "id": message.get("id") if isinstance(message, dict) else None,
                    "error": str(exc),
                }
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
