import os
import json
import base64
import binascii
import time
from pathlib import Path
from typing import Any
from uuid import uuid4
import numpy as np
from datetime import datetime
from fastapi import APIRouter, WebSocket, UploadFile, File, Response, HTTPException, Request
from pydantic import BaseModel, Field
from ruamel.yaml import YAML
from starlette.responses import FileResponse, JSONResponse
from starlette.websockets import WebSocketDisconnect
from loguru import logger
from .config_manager import validate_config
from .service_context import ServiceContext
from .websocket_handler import WebSocketHandler
from .proxy_handler import ProxyHandler
from .ue_avatar_server import ue_avatar_server


CONFIG_PATH = Path("conf.yaml")

TTS_EDITABLE_FIELDS: dict[str, set[str]] = {
    "edge_tts": {"voice", "proxy"},
    "cosyvoice_tts": {
        "client_url",
        "mode_checkbox_group",
        "sft_dropdown",
        "prompt_text",
        "prompt_wav_upload_url",
        "prompt_wav_record_url",
        "instruct_text",
        "seed",
        "api_name",
    },
    "cosyvoice2_tts": {
        "client_url",
        "mode_checkbox_group",
        "sft_dropdown",
        "prompt_text",
        "prompt_wav_upload_url",
        "prompt_wav_record_url",
        "instruct_text",
        "stream",
        "seed",
        "speed",
        "api_name",
    },
    "x_tts": {"api_url", "speaker_wav", "language"},
    "gpt_sovits_tts": {
        "api_url",
        "text_lang",
        "ref_audio_path",
        "prompt_lang",
        "prompt_text",
        "text_split_method",
        "batch_size",
        "media_type",
        "streaming_mode",
    },
    "piper_tts": {
        "model_path",
        "speaker_id",
        "length_scale",
        "noise_scale",
        "noise_w",
        "volume",
        "normalize_audio",
        "use_cuda",
    },
    "sherpa_onnx_tts": {
        "vits_model",
        "vits_lexicon",
        "vits_tokens",
        "vits_data_dir",
        "vits_dict_dir",
        "tts_rule_fsts",
        "max_num_sentences",
        "sid",
        "provider",
        "num_threads",
        "speed",
        "debug",
    },
    "siliconflow_tts": {
        "api_url",
        "default_model",
        "default_voice",
        "sample_rate",
        "response_format",
        "stream",
        "speed",
        "gain",
    },
    "openai_tts": {"model", "voice", "base_url", "file_extension"},
    "spark_tts": {"api_url", "prompt_wav_upload", "api_name", "gender", "pitch", "speed"},
    "minimax_tts": {"model", "voice_id", "pronunciation_dict"},
    "elevenlabs_tts": {
        "voice_id",
        "model_id",
        "output_format",
        "stability",
        "similarity_boost",
        "style",
        "use_speaker_boost",
    },
    "cartesia_tts": {
        "voice_id",
        "model_id",
        "output_format",
        "language",
        "emotion",
        "volume",
        "speed",
    },
}


class RuntimeTTSConfigUpdate(BaseModel):
    tts_model: str
    config: dict[str, Any] = Field(default_factory=dict)


class UeAudioCacheRequest(BaseModel):
    audio: str


class UeAvatarMessageRequest(BaseModel):
    message: dict[str, Any]


def _read_conf_yaml() -> Any:
    yaml = YAML()
    yaml.preserve_quotes = True
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.load(file)


def _write_conf_yaml(config_data: Any) -> None:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    with CONFIG_PATH.open("w", encoding="utf-8") as file:
        yaml.dump(config_data, file)


def _get_tts_config_data(config_data: Any) -> Any:
    try:
        return config_data["character_config"]["tts_config"]
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=500, detail="Invalid TTS configuration file") from exc


def _serialize_tts_config(tts_config: Any) -> dict[str, Any]:
    providers = sorted(
        provider
        for provider in TTS_EDITABLE_FIELDS
        if isinstance(tts_config.get(provider), dict)
    )
    selected_model = tts_config.get("tts_model")
    provider_config = tts_config.get(selected_model, {})
    editable_fields = TTS_EDITABLE_FIELDS.get(selected_model, set())
    safe_config = {
        key: value
        for key, value in dict(provider_config).items()
        if key in editable_fields
    }

    return {
        "tts_model": selected_model,
        "providers": providers,
        "config": safe_config,
        "provider_configs": {
            provider: {
                key: value
                for key, value in dict(tts_config.get(provider, {})).items()
                if key in TTS_EDITABLE_FIELDS[provider]
            }
            for provider in providers
        },
    }


def _build_next_tts_config(update: RuntimeTTSConfigUpdate) -> Any:
    config_data = _read_conf_yaml()
    tts_config = _get_tts_config_data(config_data)
    if update.tts_model not in TTS_EDITABLE_FIELDS:
        raise HTTPException(status_code=400, detail=f"Unsupported TTS model: {update.tts_model}")
    if update.tts_model not in tts_config:
        raise HTTPException(status_code=400, detail=f"TTS model is not configured: {update.tts_model}")

    tts_config["tts_model"] = update.tts_model
    editable_fields = TTS_EDITABLE_FIELDS[update.tts_model]
    provider_config = tts_config[update.tts_model]
    for key, value in update.config.items():
        if key in editable_fields:
            provider_config[key] = value

    validated_config = validate_config(config_data)
    return config_data, validated_config


UE_AUDIO_CACHE_DIR = Path("cache") / "ue_audio"
UE_AUDIO_CACHE_MAX_AGE_SECONDS = 60 * 60


def _purge_old_ue_audio_files() -> None:
    if not UE_AUDIO_CACHE_DIR.exists():
        return

    expires_before = time.time() - UE_AUDIO_CACHE_MAX_AGE_SECONDS
    for audio_file in UE_AUDIO_CACHE_DIR.glob("*.wav"):
        try:
            if audio_file.stat().st_mtime < expires_before:
                audio_file.unlink()
        except OSError:
            logger.debug(f"Failed to purge UE audio cache file: {audio_file}")


def _decode_audio_base64(audio: str) -> bytes:
    normalized = audio.split(",", 1)[1] if "," in audio else audio
    try:
        return base64.b64decode(normalized, validate=True)
    except binascii.Error as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 audio payload") from exc


def init_client_ws_route(default_context_cache: ServiceContext) -> APIRouter:
    """
    Create and return API routes for handling the `/client-ws` WebSocket connections.

    Args:
        default_context_cache: Default service context cache for new sessions.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()
    ws_handler = WebSocketHandler(default_context_cache)

    @router.websocket("/client-ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for client connections"""
        await websocket.accept()
        client_uid = str(uuid4())

        try:
            await ws_handler.handle_new_connection(websocket, client_uid)
            await ws_handler.handle_websocket_communication(websocket, client_uid)
        except WebSocketDisconnect:
            await ws_handler.handle_disconnect(client_uid)
        except Exception as e:
            logger.error(f"Error in WebSocket connection: {e}")
            await ws_handler.handle_disconnect(client_uid)
            raise

    return router


def init_proxy_route(server_url: str) -> APIRouter:
    """
    Create and return API routes for handling proxy connections.

    Args:
        server_url: The WebSocket URL of the actual server

    Returns:
        APIRouter: Configured router with proxy WebSocket endpoint
    """
    router = APIRouter()
    proxy_handler = ProxyHandler(server_url)

    @router.websocket("/proxy-ws")
    async def proxy_endpoint(websocket: WebSocket):
        """WebSocket endpoint for proxy connections"""
        try:
            await proxy_handler.handle_client_connection(websocket)
        except Exception as e:
            logger.error(f"Error in proxy connection: {e}")
            raise

    return router


def init_webtool_routes(default_context_cache: ServiceContext) -> APIRouter:
    """
    Create and return API routes for handling web tool interactions.

    Args:
        default_context_cache: Default service context cache for new sessions.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()

    @router.get("/web-tool")
    async def web_tool_redirect():
        """Redirect /web-tool to /web_tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    @router.get("/web_tool")
    async def web_tool_redirect_alt():
        """Redirect /web_tool to /web_tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    @router.get("/live2d-models/info")
    async def get_live2d_folder_info():
        """Get information about available Live2D models"""
        live2d_dir = "live2d-models"
        if not os.path.exists(live2d_dir):
            return JSONResponse(
                {"error": "Live2D models directory not found"}, status_code=404
            )

        valid_characters = []
        supported_extensions = [".png", ".jpg", ".jpeg"]

        for entry in os.scandir(live2d_dir):
            if entry.is_dir():
                folder_name = entry.name.replace("\\", "/")
                model3_candidates = [
                    os.path.join(live2d_dir, folder_name, f"{folder_name}.model3.json"),
                    os.path.join(live2d_dir, folder_name, "runtime", f"{folder_name}.model3.json"),
                ]
                model3_file = next(
                    (candidate for candidate in model3_candidates if os.path.isfile(candidate)),
                    "",
                )

                if model3_file:
                    # Find avatar file if it exists
                    avatar_file = None
                    avatar_candidates = []
                    for root in ("", "runtime"):
                        for ext in supported_extensions:
                            avatar_candidates.append(
                                os.path.join(live2d_dir, folder_name, root, f"{folder_name}{ext}")
                            )

                    for avatar_path in avatar_candidates:
                        if os.path.isfile(avatar_path):
                            avatar_file = avatar_path.replace("\\", "/")
                            break

                    valid_characters.append(
                        {
                            "name": folder_name,
                            "avatar": avatar_file,
                            "model_path": model3_file,
                        }
                    )
        return JSONResponse(
            {
                "type": "live2d-models/info",
                "count": len(valid_characters),
                "characters": valid_characters,
            }
        )

    @router.get("/api/runtime/tts-config")
    async def get_runtime_tts_config():
        """Get the editable runtime TTS configuration for the main frontend."""
        config_data = _read_conf_yaml()
        return JSONResponse(_serialize_tts_config(_get_tts_config_data(config_data)))

    @router.put("/api/runtime/tts-config")
    async def update_runtime_tts_config(update: RuntimeTTSConfigUpdate):
        """Update the selected TTS provider and safe provider fields."""
        try:
            config_data, validated_config = _build_next_tts_config(update)
            default_context_cache.init_tts(validated_config.character_config.tts_config)
            default_context_cache.config = validated_config
            default_context_cache.system_config = validated_config.system_config
            default_context_cache.character_config = validated_config.character_config
            _write_conf_yaml(config_data)
            logger.info(f"Runtime TTS configuration updated: {update.tts_model}")
            return JSONResponse(_serialize_tts_config(_get_tts_config_data(config_data)))
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update runtime TTS configuration: {e}", exc_info=True)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to update TTS configuration: {e}",
            ) from e

    @router.post("/api/runtime/ue-audio-cache")
    async def cache_ue_audio(payload: UeAudioCacheRequest, request: Request):
        """Cache browser-received WAV audio so UE can fetch it via HttpValue."""
        audio_bytes = _decode_audio_base64(payload.audio)
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Audio payload is empty")

        _purge_old_ue_audio_files()
        UE_AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}.wav"
        audio_path = UE_AUDIO_CACHE_DIR / file_name
        audio_path.write_bytes(audio_bytes)

        audio_url = str(request.url_for("get_ue_audio_cache", file_name=file_name))
        return JSONResponse(
            {
                "url": audio_url,
                "path": str(audio_path),
            }
        )

    @router.get("/api/runtime/ue-audio-cache/{file_name}", name="get_ue_audio_cache")
    async def get_ue_audio_cache(file_name: str):
        """Serve cached UE audio files generated from frontend audio payloads."""
        if "/" in file_name or "\\" in file_name or not file_name.endswith(".wav"):
            raise HTTPException(status_code=400, detail="Invalid audio file name")

        audio_path = UE_AUDIO_CACHE_DIR / file_name
        if not audio_path.is_file():
            raise HTTPException(status_code=404, detail="Audio file not found")

        return FileResponse(audio_path, media_type="audio/wav", filename=file_name)

    @router.post("/api/runtime/ue-avatar-message")
    async def send_ue_avatar_message(payload: UeAvatarMessageRequest):
        """Send a Fay-compatible digital human message to connected UE clients."""
        sent = await ue_avatar_server.send(payload.message)
        username = payload.message.get("Username")
        return JSONResponse(
            {
                "sent": sent,
                "connected_clients": ue_avatar_server.client_count(username),
            }
        )

    @router.get("/api/runtime/ue-avatar-status")
    async def get_ue_avatar_status():
        """Return currently connected Fay-compatible UE digital human clients."""
        return JSONResponse(
            {
                "connected_clients": ue_avatar_server.client_count(),
                "clients": ue_avatar_server.client_snapshot(),
            }
        )

    @router.post("/asr")
    async def transcribe_audio(file: UploadFile = File(...)):
        """
        Endpoint for transcribing audio using the ASR engine
        """
        logger.info(f"Received audio file for transcription: {file.filename}")

        try:
            contents = await file.read()

            # Validate minimum file size
            if len(contents) < 44:  # Minimum WAV header size
                raise ValueError("Invalid WAV file: File too small")

            # Decode the WAV header and get actual audio data
            wav_header_size = 44  # Standard WAV header size
            audio_data = contents[wav_header_size:]

            # Validate audio data size
            if len(audio_data) % 2 != 0:
                raise ValueError("Invalid audio data: Buffer size must be even")

            # Convert to 16-bit PCM samples to float32
            try:
                audio_array = (
                    np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )
            except ValueError as e:
                raise ValueError(
                    f"Audio format error: {str(e)}. Please ensure the file is 16-bit PCM WAV format."
                )

            # Validate audio data
            if len(audio_array) == 0:
                raise ValueError("Empty audio data")

            text = await default_context_cache.asr_engine.async_transcribe_np(
                audio_array
            )
            logger.info(f"Transcription result: {text}")
            return {"text": text}

        except ValueError as e:
            logger.error(f"Audio format error: {e}")
            return Response(
                content=json.dumps({"error": str(e)}),
                status_code=400,
                media_type="application/json",
            )
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            return Response(
                content=json.dumps(
                    {"error": "Internal server error during transcription"}
                ),
                status_code=500,
                media_type="application/json",
            )

    @router.websocket("/tts-ws")
    async def tts_endpoint(websocket: WebSocket):
        """WebSocket endpoint for TTS generation"""
        await websocket.accept()
        logger.info("TTS WebSocket connection established")

        try:
            while True:
                data = await websocket.receive_json()
                text = data.get("text")
                if not text:
                    continue

                logger.info(f"Received text for TTS: {text}")

                # Split text into sentences
                sentences = [s.strip() for s in text.split(".") if s.strip()]

                try:
                    # Generate and send audio for each sentence
                    for sentence in sentences:
                        sentence = sentence + "."  # Add back the period
                        file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid4())[:8]}"
                        audio_path = (
                            await default_context_cache.tts_engine.async_generate_audio(
                                text=sentence, file_name_no_ext=file_name
                            )
                        )
                        logger.info(
                            f"Generated audio for sentence: {sentence} at: {audio_path}"
                        )

                        await websocket.send_json(
                            {
                                "status": "partial",
                                "audioPath": audio_path,
                                "text": sentence,
                            }
                        )

                    # Send completion signal
                    await websocket.send_json({"status": "complete"})

                except Exception as e:
                    logger.error(f"Error generating TTS: {e}")
                    await websocket.send_json({"status": "error", "message": str(e)})

        except WebSocketDisconnect:
            logger.info("TTS WebSocket client disconnected")
        except Exception as e:
            logger.error(f"Error in TTS WebSocket connection: {e}")
            await websocket.close()

    return router
