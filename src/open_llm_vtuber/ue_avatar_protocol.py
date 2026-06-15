import base64
import binascii
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger

from .ue_avatar_server import ue_avatar_server


UE_AUDIO_CACHE_DIR = Path("cache") / "ue_audio"
UE_AUDIO_CACHE_MAX_AGE_SECONDS = 60 * 60
UE_PUBLIC_BASE_URL = os.getenv("OPEN_LLM_VTUBER_PUBLIC_URL", "http://127.0.0.1:18080")

_session_states: dict[str, dict[str, Any]] = {}


def _state_for(username: str) -> dict[str, Any]:
    return _session_states.setdefault(
        username,
        {
            "conversation_id": "",
            "audio_message_no": 0,
            "has_active_audio": False,
            "has_active_text": False,
        },
    )


async def send_question(text: str, username: str = "User") -> None:
    if not text.strip():
        return

    await ue_avatar_server.send(
        {
            "Topic": "human",
            "Data": {
                "Key": "question",
                "Value": text,
            },
            "Username": username,
        }
    )


async def send_log(text: str, username: str = "User") -> None:
    await ue_avatar_server.send(
        {
            "Topic": "human",
            "Data": {
                "Key": "log",
                "Value": text,
            },
            "Username": username,
        }
    )


async def send_suggestions(
    suggestions: list[str],
    username: str = "User",
    context: str = "follow_up",
) -> None:
    cleaned = [item.strip() for item in suggestions if item and item.strip()]
    if not cleaned:
        return

    await ue_avatar_server.send(
        {
            "Topic": "human",
            "Data": {
                "Key": "suggestions",
                "Value": cleaned[:3],
                "Context": context,
            },
            "Username": username,
        }
    )

async def send_text(text: str, is_end: bool = False, username: str = "User") -> None:
    normalized = text.strip()
    if not normalized and not is_end:
        return

    state = _state_for(username)
    await ue_avatar_server.send(
        {
            "Topic": "human",
            "Data": {
                "Key": "text",
                "Value": normalized,
                "IsFirst": 0 if state["has_active_text"] else 1,
                "IsEnd": 1 if is_end else 0,
            },
            "Username": username,
        }
    )
    state["has_active_text"] = not is_end


async def send_audio_payload(payload: dict[str, Any], username: str = "User") -> None:
    display_text = payload.get("display_text") or {}
    text = display_text.get("text", "") if isinstance(display_text, dict) else ""
    await send_text(text, username=username)

    audio_base64 = payload.get("audio")
    if not audio_base64:
        return

    state = _state_for(username)
    if not state["has_active_audio"]:
        state["conversation_id"] = _create_conversation_id()
        state["audio_message_no"] = 0
        state["has_active_audio"] = True

    audio_path, audio_url = _cache_audio_base64(audio_base64)
    volumes = payload.get("volumes") or []
    slice_length = payload.get("slice_length") or 20
    duration = len(volumes) * slice_length / 1000
    server_perf = payload.get("server_perf") or {}

    await ue_avatar_server.send(
        {
            "Topic": "human",
            "Data": {
                "Key": "audio",
                "Value": _to_windows_path(audio_path),
                "HttpValue": audio_url,
                "Text": text,
                "Time": duration,
                "Type": 2,
                "IsFirst": 1 if state["audio_message_no"] == 0 else 0,
                "IsEnd": 0,
                "CONV_ID": state["conversation_id"],
                "CONV_MSG_NO": state["audio_message_no"],
                "Sentiment": 0,
                "Action": payload.get("actions"),
                "Images": [],
                "Lips": [],
                "ServerTurnId": server_perf.get("turn_id", ""),
                "ServerElapsedMs": server_perf.get("elapsed_ms"),
            },
            "Username": username,
            "robot": f"{UE_PUBLIC_BASE_URL}/robot/Speaking.jpg",
        }
    )
    state["audio_message_no"] += 1


async def send_audio_end(username: str = "User") -> None:
    state = _state_for(username)
    if state["has_active_text"]:
        await send_text("", is_end=True, username=username)

    if not state["has_active_audio"]:
        return

    await ue_avatar_server.send(
        {
            "Topic": "human",
            "Data": {
                "Key": "audio",
                "Value": "",
                "HttpValue": "",
                "Text": "",
                "Time": 0,
                "Type": 2,
                "IsFirst": 0,
                "IsEnd": 1,
                "CONV_ID": state["conversation_id"],
                "CONV_MSG_NO": state["audio_message_no"],
                "Sentiment": 0,
                "Images": [],
                "Lips": [],
            },
            "Username": username,
            "robot": f"{UE_PUBLIC_BASE_URL}/robot/Speaking.jpg",
        }
    )
    state["conversation_id"] = ""
    state["audio_message_no"] = 0
    state["has_active_audio"] = False
    state["has_active_text"] = False


def _cache_audio_base64(audio: str) -> tuple[Path, str]:
    normalized = audio.split(",", 1)[1] if "," in audio else audio
    try:
        audio_bytes = base64.b64decode(normalized, validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid base64 audio payload") from exc

    _purge_old_audio_files()
    UE_AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}.wav"
    audio_path = UE_AUDIO_CACHE_DIR / file_name
    audio_path.write_bytes(audio_bytes)
    audio_url = f"{UE_PUBLIC_BASE_URL}/api/runtime/ue-audio-cache/{file_name}"
    logger.info(
        "UE avatar audio cached: "
        f"value={_to_windows_path(audio_path)} http_value={audio_url} "
        f"bytes={len(audio_bytes)}"
    )
    return audio_path, audio_url


def _to_windows_path(path: Path) -> str:
    resolved = path.resolve()
    parts = resolved.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "mnt" and len(parts[2]) == 1:
        drive = parts[2].upper()
        return f"{drive}:\\" + "\\".join(parts[3:])
    return str(resolved)


def _purge_old_audio_files() -> None:
    if not UE_AUDIO_CACHE_DIR.exists():
        return

    expires_before = time.time() - UE_AUDIO_CACHE_MAX_AGE_SECONDS
    for audio_file in UE_AUDIO_CACHE_DIR.glob("*.wav"):
        try:
            if audio_file.stat().st_mtime < expires_before:
                audio_file.unlink()
        except OSError:
            logger.debug(f"Failed to purge UE audio cache file: {audio_file}")


def _create_conversation_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{uuid4().hex[:8]}"
