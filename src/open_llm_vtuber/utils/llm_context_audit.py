from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


_WRITE_LOCK = threading.Lock()
_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|authorization|password|passwd|bearer)",
    re.IGNORECASE,
)


def audit_enabled() -> bool:
    return os.getenv("LLM_CONTEXT_AUDIT_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def write_llm_context_audit(event: str, payload: dict[str, Any]) -> None:
    if not audit_enabled():
        return

    audit_dir = Path(os.getenv("LLM_CONTEXT_AUDIT_DIR", "logs/llm_context"))
    audit_path = audit_dir / f"{datetime.now().strftime('%Y%m%d')}.jsonl"
    record = {
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "event": event,
        **sanitize_for_audit(payload),
    }

    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with _WRITE_LOCK:
            with audit_path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
    except Exception as exc:
        logger.warning("Failed to write LLM context audit log: {}", exc)


def sanitize_for_audit(value: Any, key: str = "") -> Any:
    if key and _SECRET_KEY_PATTERN.search(key):
        return "[REDACTED]"

    if isinstance(value, dict):
        return {str(k): sanitize_for_audit(v, str(k)) for k, v in value.items()}

    if isinstance(value, list):
        return [sanitize_for_audit(item, key) for item in value]

    if isinstance(value, tuple):
        return [sanitize_for_audit(item, key) for item in value]

    if isinstance(value, str):
        return _sanitize_string(value)

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return str(value)


def _sanitize_string(value: str) -> str:
    if value.startswith("data:image"):
        header = value.split(",", 1)[0]
        return f"{header},[REDACTED_IMAGE_DATA length={len(value)}]"

    if len(value) > 200_000:
        return f"{value[:200_000]}...[TRUNCATED length={len(value)}]"

    return value

