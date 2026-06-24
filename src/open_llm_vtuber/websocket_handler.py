from typing import Dict, List, Optional, Callable, TypedDict
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import json
from enum import Enum
import numpy as np
from loguru import logger

from .service_context import ServiceContext
from .chat_group import (
    ChatGroupManager,
    handle_group_operation,
    handle_client_disconnect,
    broadcast_to_group,
)
from .message_handler import message_handler
from .ue_avatar_server import ue_avatar_server
from .ue_avatar_protocol import (
    send_kws_state,
    send_user_speech_state,
    send_wakeup_status,
)
from .kws.audio_session import AudioSession, AudioSessionState
from .utils.stream_audio import prepare_audio_payload
from .chat_history_manager import (
    create_new_history,
    get_history,
    delete_history,
    get_history_list,
)
from .config_manager.kws import KWSConfig
from .config_manager.utils import scan_config_alts_directory, scan_bg_directory
from .conversations.conversation_handler import (
    handle_conversation_trigger,
    handle_group_interrupt,
    handle_individual_interrupt,
)

PCM_FLOAT_FLOOR = 1e-7


class MessageType(Enum):
    """Enum for WebSocket message types"""

    GROUP = ["add-client-to-group", "remove-client-from-group"]
    HISTORY = [
        "fetch-history-list",
        "fetch-and-set-history",
        "create-new-history",
        "delete-history",
    ]
    CONVERSATION = ["mic-audio-end", "text-input", "ai-speak-signal"]
    CONFIG = ["fetch-configs", "switch-config"]
    CONTROL = ["interrupt-signal", "audio-play-start"]
    DATA = ["mic-audio-data"]


class WSMessage(TypedDict, total=False):
    """Type definition for WebSocket messages"""

    type: str
    action: Optional[str]
    text: Optional[str]
    audio: Optional[List[float]]
    images: Optional[List[str]]
    history_uid: Optional[str]
    file: Optional[str]
    display_text: Optional[dict]


class WebSocketHandler:
    """Handles WebSocket connections and message routing"""

    def __init__(self, default_context_cache: ServiceContext):
        """Initialize the WebSocket handler with default context"""
        self.client_connections: Dict[str, WebSocket] = {}
        self.client_contexts: Dict[str, ServiceContext] = {}
        self.chat_group_manager = ChatGroupManager()
        self.current_conversation_tasks: Dict[str, Optional[asyncio.Task]] = {}
        self.default_context_cache = default_context_cache
        self.received_data_buffers: Dict[str, np.ndarray] = {}
        self.user_speech_active: Dict[str, bool] = {}
        self.audio_sessions: Dict[str, AudioSession] = {}
        self.kws_timeout_tasks: Dict[str, asyncio.Task] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        ue_avatar_server.set_status_listener(self._publish_ue_avatar_status)

        # Message handlers mapping
        self._message_handlers = self._init_message_handlers()

    def _init_message_handlers(self) -> Dict[str, Callable]:
        """Initialize message type to handler mapping"""
        return {
            "add-client-to-group": self._handle_group_operation,
            "remove-client-from-group": self._handle_group_operation,
            "request-group-info": self._handle_group_info,
            "fetch-history-list": self._handle_history_list_request,
            "fetch-and-set-history": self._handle_fetch_history,
            "create-new-history": self._handle_create_history,
            "delete-history": self._handle_delete_history,
            "interrupt-signal": self._handle_interrupt,
            "mic-audio-data": self._handle_audio_data,
            "mic-audio-end": self._handle_conversation_trigger,
            "raw-audio-data": self._handle_raw_audio_data,
            "text-input": self._handle_conversation_trigger,
            "ai-speak-signal": self._handle_conversation_trigger,
            "fetch-configs": self._handle_fetch_configs,
            "switch-config": self._handle_config_switch,
            "fetch-backgrounds": self._handle_fetch_backgrounds,
            "audio-play-start": self._handle_audio_play_start,
            "frontend-playback-complete": self._handle_frontend_playback_complete,
            "kws-config-request": self._handle_kws_config_request,
            "kws-config-update": self._handle_kws_config_update,
            "request-init-config": self._handle_init_config_request,
            "heartbeat": self._handle_heartbeat,
        }

    async def handle_new_connection(
        self, websocket: WebSocket, client_uid: str
    ) -> None:
        """
        Handle new WebSocket connection setup

        Args:
            websocket: The WebSocket connection
            client_uid: Unique identifier for the client

        Raises:
            Exception: If initialization fails
        """
        try:
            self._event_loop = asyncio.get_running_loop()
            await self._replace_existing_connection(client_uid)
            session_service_context = await self._init_service_context(
                websocket.send_text, client_uid
            )

            await self._store_client_data(
                websocket, client_uid, session_service_context
            )

            await self._send_initial_messages(
                websocket, client_uid, session_service_context
            )

            logger.info(f"Connection established for client {client_uid}")

        except Exception as e:
            logger.error(
                f"Failed to initialize connection for client {client_uid}: {e}"
            )
            await self._cleanup_failed_connection(client_uid)
            raise

    async def _replace_existing_connection(self, client_uid: str) -> None:
        """Close and remove a stale connection before reusing an explicit client UID."""
        old_websocket = self.client_connections.get(client_uid)
        if not old_websocket:
            return

        logger.info(f"Replacing existing connection for client {client_uid}")
        try:
            await old_websocket.close(code=1000, reason="client_uid reconnected")
        except Exception as exc:
            logger.debug(f"Failed closing stale websocket for {client_uid}: {exc}")

        await self._cleanup_failed_connection(client_uid)

    async def _store_client_data(
        self,
        websocket: WebSocket,
        client_uid: str,
        session_service_context: ServiceContext,
    ):
        """Store client data and initialize group status"""
        self.client_connections[client_uid] = websocket
        self.client_contexts[client_uid] = session_service_context
        self.received_data_buffers[client_uid] = np.array([])
        self.user_speech_active[client_uid] = False

        self.chat_group_manager.client_group_map[client_uid] = ""
        await self.send_group_update(websocket, client_uid)

    async def _send_initial_messages(
        self,
        websocket: WebSocket,
        client_uid: str,
        session_service_context: ServiceContext,
    ):
        """Send initial connection messages to the client"""
        await websocket.send_text(
            json.dumps({"type": "full-text", "text": "Connection established"})
        )

        await websocket.send_text(
            json.dumps(
                {
                    "type": "set-model-and-conf",
                    "model_info": session_service_context.live2d_model.model_info,
                    "conf_name": session_service_context.character_config.conf_name,
                    "conf_uid": session_service_context.character_config.conf_uid,
                    "client_uid": client_uid,
                    "kws_config": self._public_kws_config(session_service_context),
                }
            )
        )

        # Send initial group status
        await self.send_group_update(websocket, client_uid)

        await websocket.send_text(json.dumps(ue_avatar_server.status_payload()))

        # Start microphone
        await websocket.send_text(json.dumps({"type": "control", "text": "start-mic"}))

    def _publish_ue_avatar_status(self, payload: dict) -> None:
        loop = self._event_loop
        if not loop or loop.is_closed():
            return

        asyncio.run_coroutine_threadsafe(
            self.broadcast_ue_avatar_status(payload),
            loop,
        )

    async def broadcast_ue_avatar_status(self, payload: dict) -> None:
        for uid, websocket in list(self.client_connections.items()):
            try:
                await websocket.send_text(json.dumps(payload))
            except Exception as exc:
                logger.warning(f"Failed to send UE avatar status to {uid}: {exc}")

    @staticmethod
    def _is_fast_audio_message(data: dict) -> bool:
        return data.get("type") in {"raw-audio-data", "mic-audio-data"}

    @staticmethod
    def _public_kws_config(context: ServiceContext) -> dict:
        kws_config = getattr(context.character_config, "kws_config", None)
        if not kws_config:
            return {"enabled": False}
        sherpa_config = kws_config.sherpa_onnx_kws
        return {
            "enabled": bool(kws_config.enabled and context.kws_engine and context.vad_engine),
            "requested_enabled": kws_config.enabled,
            "model_ready": bool(context.kws_engine),
            "vad_ready": bool(context.vad_engine),
            "wake_words": kws_config.wake_words,
            "sample_rate": kws_config.sample_rate,
            "channels": kws_config.channels,
            "audio_format": kws_config.audio_format,
            "frame_ms": kws_config.frame_ms,
            "pre_roll_ms": kws_config.pre_roll_ms,
            "cooldown_seconds": kws_config.cooldown_seconds,
            "listen_timeout_seconds": kws_config.listen_timeout_seconds,
            "active_timeout_seconds": kws_config.active_timeout_seconds,
            "keywords_score": sherpa_config.keywords_score,
            "keywords_threshold": sherpa_config.keywords_threshold,
        }

    @staticmethod
    def _build_runtime_kws_config(current_config: KWSConfig, data: dict) -> KWSConfig:
        allowed_top_level = {
            "enabled",
            "wake_words",
            "sample_rate",
            "frame_ms",
            "pre_roll_ms",
            "cooldown_seconds",
            "listen_timeout_seconds",
            "active_timeout_seconds",
        }
        allowed_sherpa = {"keywords_score", "keywords_threshold"}

        updates = {key: data[key] for key in allowed_top_level if key in data}
        sherpa_updates = {key: data[key] for key in allowed_sherpa if key in data}
        nested_sherpa = data.get("sherpa_onnx_kws")
        if isinstance(nested_sherpa, dict):
            sherpa_updates.update(
                {key: nested_sherpa[key] for key in allowed_sherpa if key in nested_sherpa}
            )

        config_data = current_config.model_dump(by_alias=True)
        config_data.update(updates)
        config_data["sherpa_onnx_kws"].update(sherpa_updates)
        new_config = KWSConfig.model_validate(config_data)

        if new_config.channels != 1:
            raise ValueError("KWS only supports mono audio: channels must be 1")
        if new_config.sample_rate != 16000:
            raise ValueError("KWS sample_rate must be 16000")
        if new_config.audio_format != "pcm_f32le":
            raise ValueError("KWS audio_format must be pcm_f32le")
        if new_config.frame_ms not in {20, 32, 40, 60, 80, 100}:
            raise ValueError("KWS frame_ms must be one of 20, 32, 40, 60, 80, 100")
        if new_config.pre_roll_ms < 0 or new_config.pre_roll_ms > 3000:
            raise ValueError("KWS pre_roll_ms must be between 0 and 3000")
        if new_config.cooldown_seconds < 0 or new_config.cooldown_seconds > 30:
            raise ValueError("KWS cooldown_seconds must be between 0 and 30")
        if new_config.listen_timeout_seconds <= 0 or new_config.listen_timeout_seconds > 60:
            raise ValueError("KWS listen_timeout_seconds must be between 0 and 60")
        if new_config.active_timeout_seconds <= 0 or new_config.active_timeout_seconds > 600:
            raise ValueError("KWS active_timeout_seconds must be between 0 and 600")
        if new_config.sherpa_onnx_kws.keywords_score <= 0:
            raise ValueError("KWS keywords_score must be greater than 0")
        if new_config.sherpa_onnx_kws.keywords_threshold < 0:
            raise ValueError("KWS keywords_threshold must be non-negative")
        return new_config

    async def _broadcast_kws_config_state(self) -> None:
        for uid, websocket in list(self.client_connections.items()):
            context = self.client_contexts.get(uid)
            if not context:
                continue
            try:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "kws-config-state",
                            "success": True,
                            "kws_config": self._public_kws_config(context),
                        }
                    )
                )
            except Exception as exc:
                logger.warning(f"Failed to send KWS config state to {uid}: {exc}")

    def _sync_runtime_kws_config(self, new_config: KWSConfig) -> None:
        self.default_context_cache.init_kws(new_config)
        shared_kws_engine = self.default_context_cache.kws_engine

        for uid, context in list(self.client_contexts.items()):
            context.character_config.kws_config = new_config
            context.kws_engine = shared_kws_engine
            if new_config.enabled and context.kws_engine and context.vad_engine:
                self._ensure_audio_session(uid, context)
            else:
                self.audio_sessions.pop(uid, None)
                self._cancel_kws_timeout_task(uid)

    def _ensure_audio_session(
        self, client_uid: str, context: ServiceContext
    ) -> None:
        kws_config = getattr(context.character_config, "kws_config", None)
        if not kws_config or not kws_config.enabled:
            return
        if not context.kws_engine:
            logger.warning("KWS is enabled but no KWS engine is initialized.")
            return
        if not context.vad_engine:
            logger.warning("KWS is enabled but VAD is disabled; audio session skipped.")
            return

        self.audio_sessions[client_uid] = AudioSession(
            client_uid=client_uid,
            config=kws_config,
            kws_engine=context.kws_engine,
            vad_engine=context.vad_engine,
        )

    def _cancel_kws_timeout_task(self, client_uid: str) -> None:
        task = self.kws_timeout_tasks.pop(client_uid, None)
        if task and not task.done():
            task.cancel()

    def _schedule_kws_timeout_after_response(
        self,
        websocket: WebSocket,
        client_uid: str,
        audio_session: AudioSession,
    ) -> None:
        self._cancel_kws_timeout_task(client_uid)
        timeout_seconds = float(
            getattr(
                audio_session.config,
                "active_timeout_seconds",
                audio_session.config.listen_timeout_seconds,
            )
        )

        async def expire_awake_window() -> None:
            try:
                await asyncio.sleep(max(0.0, timeout_seconds))
                if self.client_connections.get(client_uid) is not websocket:
                    return
                if self.audio_sessions.get(client_uid) is not audio_session:
                    return
                if audio_session.state != AudioSessionState.LISTENING:
                    return

                audio_session.mark_idle()
                await websocket.send_text(
                    json.dumps({"type": "control", "text": "wakeup-timeout"})
                )
                await send_kws_state(
                    False,
                    username=client_uid,
                    reason="post-response-timeout",
                    source="client-ws",
                )
                logger.info(
                    "KWS post-response awake window timed out: client_uid={} seconds={}",
                    client_uid,
                    timeout_seconds,
                )
            except asyncio.CancelledError:
                return
            finally:
                if self.kws_timeout_tasks.get(client_uid) is asyncio.current_task():
                    self.kws_timeout_tasks.pop(client_uid, None)

        self.kws_timeout_tasks[client_uid] = asyncio.create_task(expire_awake_window())

    async def _init_service_context(
        self, send_text: Callable, client_uid: str
    ) -> ServiceContext:
        """Initialize service context for a new session by cloning the default context"""
        session_service_context = ServiceContext()
        await session_service_context.load_cache(
            config=self.default_context_cache.config.model_copy(deep=True),
            system_config=self.default_context_cache.system_config.model_copy(
                deep=True
            ),
            character_config=self.default_context_cache.character_config.model_copy(
                deep=True
            ),
            live2d_model=self.default_context_cache.live2d_model,
            asr_engine=self.default_context_cache.asr_engine,
            tts_engine=self.default_context_cache.tts_engine,
            vad_engine=self.default_context_cache.vad_engine,
            kws_engine=self.default_context_cache.kws_engine,
            agent_engine=None,
            translate_engine=self.default_context_cache.translate_engine,
            mcp_server_registery=self.default_context_cache.mcp_server_registery,
            tool_adapter=self.default_context_cache.tool_adapter,
            send_text=send_text,
            client_uid=client_uid,
        )
        self._ensure_audio_session(client_uid, session_service_context)
        return session_service_context

    async def handle_websocket_communication(
        self, websocket: WebSocket, client_uid: str
    ) -> None:
        """
        Handle ongoing WebSocket communication

        Args:
            websocket: The WebSocket connection
            client_uid: Unique identifier for the client
        """
        try:
            while True:
                try:
                    data = await websocket.receive_json()
                    if not self._is_fast_audio_message(data):
                        message_handler.handle_message(client_uid, data)
                    await self._route_message(websocket, client_uid, data)
                except WebSocketDisconnect:
                    raise
                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                    continue
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": str(e)})
                    )
                    continue

        except WebSocketDisconnect:
            logger.info(f"Client {client_uid} disconnected")
            raise
        except Exception as e:
            logger.error(f"Fatal error in WebSocket communication: {e}")
            raise

    async def _route_message(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """
        Route incoming message to appropriate handler

        Args:
            websocket: The WebSocket connection
            client_uid: Client identifier
            data: Message data
        """
        msg_type = data.get("type")
        if not msg_type:
            logger.warning("Message received without type")
            return

        handler = self._message_handlers.get(msg_type)
        if handler:
            await handler(websocket, client_uid, data)
        else:
            if msg_type != "frontend-playback-complete":
                logger.warning(f"Unknown message type: {msg_type}")

    async def _handle_kws_config_request(
        self, websocket: WebSocket, client_uid: str, data: dict
    ) -> None:
        context = self.client_contexts[client_uid]
        await websocket.send_text(
            json.dumps(
                {
                    "type": "kws-config-state",
                    "success": True,
                    "kws_config": self._public_kws_config(context),
                }
            )
        )

    async def _handle_kws_config_update(
        self, websocket: WebSocket, client_uid: str, data: dict
    ) -> None:
        current_config = self.default_context_cache.character_config.kws_config
        try:
            new_config = self._build_runtime_kws_config(current_config, data)
            self._sync_runtime_kws_config(new_config)
        except Exception as exc:
            logger.warning(f"KWS runtime config update failed: {exc}")
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "kws-config-state",
                        "success": False,
                        "message": str(exc),
                        "kws_config": self._public_kws_config(
                            self.client_contexts[client_uid]
                        ),
                    }
                )
            )
            return

        logger.info(
            "KWS runtime config updated by {}: enabled={} frame_ms={} threshold={}",
            client_uid,
            new_config.enabled,
            new_config.frame_ms,
            new_config.sherpa_onnx_kws.keywords_threshold,
        )
        await self._broadcast_kws_config_state()

    async def _handle_group_operation(
        self, websocket: WebSocket, client_uid: str, data: dict
    ) -> None:
        """Handle group-related operations"""
        operation = data.get("type")
        target_uid = data.get(
            "invitee_uid" if operation == "add-client-to-group" else "target_uid"
        )

        await handle_group_operation(
            operation=operation,
            client_uid=client_uid,
            target_uid=target_uid,
            chat_group_manager=self.chat_group_manager,
            client_connections=self.client_connections,
            send_group_update=self.send_group_update,
        )

    async def handle_disconnect(
        self, client_uid: str, websocket: Optional[WebSocket] = None
    ) -> None:
        """Handle client disconnection"""
        if websocket is not None and self.client_connections.get(client_uid) is not websocket:
            logger.debug(f"Ignoring stale disconnect for client {client_uid}")
            return

        group = self.chat_group_manager.get_client_group(client_uid)
        if group:
            await handle_group_interrupt(
                group_id=group.group_id,
                heard_response="",
                current_conversation_tasks=self.current_conversation_tasks,
                chat_group_manager=self.chat_group_manager,
                client_contexts=self.client_contexts,
                broadcast_to_group=self.broadcast_to_group,
            )

        await handle_client_disconnect(
            client_uid=client_uid,
            chat_group_manager=self.chat_group_manager,
            client_connections=self.client_connections,
            send_group_update=self.send_group_update,
        )

        context = self.client_contexts.get(client_uid)

        # Clean up other client data
        self.client_connections.pop(client_uid, None)
        self.client_contexts.pop(client_uid, None)
        self.received_data_buffers.pop(client_uid, None)
        self.user_speech_active.pop(client_uid, None)
        self.audio_sessions.pop(client_uid, None)
        self._cancel_kws_timeout_task(client_uid)
        if client_uid in self.current_conversation_tasks:
            task = self.current_conversation_tasks[client_uid]
            if task and not task.done():
                task.cancel()
            self.current_conversation_tasks.pop(client_uid, None)

        # Call context close to clean up resources (e.g., MCPClient)
        if context:
            await context.close()

        logger.info(f"Client {client_uid} disconnected")
        message_handler.cleanup_client(client_uid)

    async def _cleanup_failed_connection(self, client_uid: str) -> None:
        """Clean up failed connection data"""
        self.client_connections.pop(client_uid, None)
        self.client_contexts.pop(client_uid, None)
        self.received_data_buffers.pop(client_uid, None)
        self.user_speech_active.pop(client_uid, None)
        self.audio_sessions.pop(client_uid, None)
        self._cancel_kws_timeout_task(client_uid)
        self.chat_group_manager.client_group_map.pop(client_uid, None)

        if client_uid in self.current_conversation_tasks:
            task = self.current_conversation_tasks[client_uid]
            if task and not task.done():
                task.cancel()
            self.current_conversation_tasks.pop(client_uid, None)

        message_handler.cleanup_client(client_uid)

    async def broadcast_to_group(
        self, group_members: list[str], message: dict, exclude_uid: str = None
    ) -> None:
        """Broadcasts a message to group members"""
        await broadcast_to_group(
            group_members=group_members,
            message=message,
            client_connections=self.client_connections,
            exclude_uid=exclude_uid,
        )

    async def send_group_update(self, websocket: WebSocket, client_uid: str):
        """Sends group information to a client"""
        group = self.chat_group_manager.get_client_group(client_uid)
        if group:
            current_members = self.chat_group_manager.get_group_members(client_uid)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "group-update",
                        "members": current_members,
                        "is_owner": group.owner_uid == client_uid,
                    }
                )
            )
        else:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "group-update",
                        "members": [],
                        "is_owner": False,
                    }
                )
            )

    async def _handle_interrupt(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle conversation interruption"""
        heard_response = data.get("text", "")
        context = self.client_contexts[client_uid]
        group = self.chat_group_manager.get_client_group(client_uid)

        if group and len(group.members) > 1:
            await handle_group_interrupt(
                group_id=group.group_id,
                heard_response=heard_response,
                current_conversation_tasks=self.current_conversation_tasks,
                chat_group_manager=self.chat_group_manager,
                client_contexts=self.client_contexts,
                broadcast_to_group=self.broadcast_to_group,
            )
        else:
            await handle_individual_interrupt(
                client_uid=client_uid,
                current_conversation_tasks=self.current_conversation_tasks,
                context=context,
                heard_response=heard_response,
            )

    async def _handle_history_list_request(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle request for chat history list"""
        context = self.client_contexts[client_uid]
        histories = get_history_list(context.character_config.conf_uid)
        await websocket.send_text(
            json.dumps({"type": "history-list", "histories": histories})
        )

    async def _handle_fetch_history(
        self, websocket: WebSocket, client_uid: str, data: dict
    ):
        """Handle fetching and setting specific chat history"""
        history_uid = data.get("history_uid")
        if not history_uid:
            return

        context = self.client_contexts[client_uid]
        # Update history_uid in service context
        context.history_uid = history_uid
        context.agent_engine.set_memory_from_history(
            conf_uid=context.character_config.conf_uid,
            history_uid=history_uid,
        )

        messages = [
            msg
            for msg in get_history(
                context.character_config.conf_uid,
                history_uid,
            )
            if msg["role"] != "system"
        ]
        await websocket.send_text(
            json.dumps({"type": "history-data", "messages": messages})
        )

    async def _handle_create_history(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle creation of new chat history"""
        context = self.client_contexts[client_uid]
        history_uid = create_new_history(context.character_config.conf_uid)
        if history_uid:
            context.history_uid = history_uid
            context.agent_engine.set_memory_from_history(
                conf_uid=context.character_config.conf_uid,
                history_uid=history_uid,
            )
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "new-history-created",
                        "history_uid": history_uid,
                    }
                )
            )

    async def _handle_delete_history(
        self, websocket: WebSocket, client_uid: str, data: dict
    ):
        """Handle deletion of chat history"""
        history_uid = data.get("history_uid")
        if not history_uid:
            return

        context = self.client_contexts[client_uid]
        success = delete_history(
            context.character_config.conf_uid,
            history_uid,
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "history-deleted",
                    "success": success,
                    "history_uid": history_uid,
                }
            )
        )
        if history_uid == context.history_uid:
            context.history_uid = None

    async def _handle_audio_data(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle incoming audio data"""
        audio_data = data.get("audio", [])
        if audio_data:
            self.received_data_buffers[client_uid] = np.append(
                self.received_data_buffers[client_uid],
                np.array(audio_data, dtype=np.float32),
            )

    async def _handle_raw_audio_data(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle incoming raw audio data for VAD processing"""
        context = self.client_contexts[client_uid]
        chunk = data.get("audio", [])
        audio_session = self.audio_sessions.get(client_uid)
        if chunk and audio_session:
            await self._handle_kws_audio_frame(websocket, client_uid, data, audio_session)
            return

        if chunk:
            for audio_bytes in context.vad_engine.detect_speech(chunk):
                if audio_bytes == b"<|PAUSE|>":
                    await self._send_user_speech_state(
                        websocket,
                        client_uid,
                        True,
                        "speech-start",
                    )
                    await websocket.send_text(
                        json.dumps({"type": "control", "text": "interrupt"})
                    )
                elif audio_bytes == b"<|RESUME|>":
                    await self._send_user_speech_state(
                        websocket,
                        client_uid,
                        False,
                        "speech-end",
                    )
                elif len(audio_bytes) > 1024:
                    # Detected audio activity (voice)
                    audio = (
                        np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
                        / 32768.0
                    )
                    if not self._is_valid_utterance_audio(audio, client_uid, "vad"):
                        await self._send_user_speech_state(
                            websocket,
                            client_uid,
                            False,
                            "speech-rejected",
                        )
                        continue
                    self.received_data_buffers[client_uid] = np.append(
                        self.received_data_buffers[client_uid],
                        audio,
                    )
                    await websocket.send_text(
                        json.dumps({"type": "control", "text": "mic-audio-end"})
                    )

    async def _handle_kws_audio_frame(
        self,
        websocket: WebSocket,
        client_uid: str,
        data: WSMessage,
        audio_session: AudioSession,
    ) -> None:
        samples = np.array(data.get("audio", []), dtype=np.float32)
        for event in audio_session.accept_frame(samples):
            if event.type == "wakeup":
                self._cancel_kws_timeout_task(client_uid)
                payload = {
                    "type": "ue-wakeup",
                    "username": client_uid,
                    "keyword": event.keyword,
                    "confidence": event.confidence,
                    "source": "client-ws",
                }
                await websocket.send_text(json.dumps(payload))
                await websocket.send_text(
                    json.dumps({"type": "control", "text": "wakeup-detected"})
                )
                await send_wakeup_status(
                    event.keyword or "",
                    username=client_uid,
                    source="client-ws",
                )
                await send_kws_state(
                    True,
                    username=client_uid,
                    reason="wakeup-detected",
                    keyword=event.keyword or "",
                    source="client-ws",
                )
            elif event.type == "speech-start":
                self._cancel_kws_timeout_task(client_uid)
                await self._send_user_speech_state(
                    websocket,
                    client_uid,
                    True,
                    "speech-start",
                )
                await websocket.send_text(
                    json.dumps({"type": "control", "text": "interrupt"})
                )
                task = self.current_conversation_tasks.get(client_uid)
                if task and not task.done():
                    logger.info(
                        "KWS speech-start interrupts active conversation: client_uid={}",
                        client_uid,
                    )
                    await self._handle_interrupt(
                        websocket,
                        client_uid,
                        {"type": "interrupt-signal"},
                    )
            elif event.type == "speech-end":
                await self._send_user_speech_state(
                    websocket,
                    client_uid,
                    False,
                    "speech-end",
                )
            elif event.type == "utterance" and event.audio is not None:
                self._cancel_kws_timeout_task(client_uid)
                if not self._is_valid_utterance_audio(event.audio, client_uid, "kws"):
                    await self._send_user_speech_state(
                        websocket,
                        client_uid,
                        False,
                        "speech-rejected",
                    )
                    continue
                audio_session.mark_processing()
                self.received_data_buffers[client_uid] = event.audio
                await self._handle_conversation_trigger(
                    websocket,
                    client_uid,
                    {
                        "type": "mic-audio-end",
                        "metadata": {
                            "wakeup": True,
                            "wake_words": self.client_contexts[
                                client_uid
                            ].character_config.kws_config.wake_words,
                        },
                    },
                )
            elif event.type == "timeout":
                await websocket.send_text(
                    json.dumps({"type": "control", "text": "wakeup-timeout"})
                )
                await send_kws_state(
                    False,
                    username=client_uid,
                    reason="timeout",
                    source="client-ws",
                )

    def _is_valid_utterance_audio(
        self, audio: np.ndarray, client_uid: str, source: str
    ) -> bool:
        if audio.size == 0:
            return False

        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(np.square(audio))))
        peak_dbfs = 20.0 * np.log10(max(peak, PCM_FLOAT_FLOOR))
        rms_dbfs = 20.0 * np.log10(max(rms, PCM_FLOAT_FLOOR))
        utterance_filter = (
            self.client_contexts[client_uid]
            .character_config.vad_config.utterance_filter
        )
        if not utterance_filter.enabled:
            return True

        accepted = (
            rms_dbfs >= utterance_filter.min_rms_dbfs
            and peak_dbfs >= utterance_filter.min_peak_dbfs
        )
        if not accepted:
            logger.info(
                "Rejected low-energy utterance: client_uid={} source={} rms_dbfs={:.1f} peak_dbfs={:.1f} thresholds=({:.1f}, {:.1f})",
                client_uid,
                source,
                rms_dbfs,
                peak_dbfs,
                utterance_filter.min_rms_dbfs,
                utterance_filter.min_peak_dbfs,
            )
        return accepted

    async def _send_user_speech_state(
        self,
        websocket: WebSocket,
        client_uid: str,
        active: bool,
        phase: str,
    ) -> None:
        """Notify clients when backend VAD has confirmed speech start/end."""
        if self.user_speech_active.get(client_uid) == active:
            return

        self.user_speech_active[client_uid] = active
        await websocket.send_text(
            json.dumps(
                {
                    "type": "user-speech-state",
                    "active": active,
                    "phase": phase,
                }
            )
        )
        await send_user_speech_state(
            active,
            username=client_uid,
            phase=phase,
            source="client-ws",
        )

    async def _handle_conversation_trigger(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle triggers that start a conversation"""
        await handle_conversation_trigger(
            msg_type=data.get("type", ""),
            data=data,
            client_uid=client_uid,
            context=self.client_contexts[client_uid],
            websocket=websocket,
            client_contexts=self.client_contexts,
            client_connections=self.client_connections,
            chat_group_manager=self.chat_group_manager,
            received_data_buffers=self.received_data_buffers,
            current_conversation_tasks=self.current_conversation_tasks,
            broadcast_to_group=self.broadcast_to_group,
        )
        audio_session = self.audio_sessions.get(client_uid)
        task = self.current_conversation_tasks.get(client_uid)
        if audio_session and task:
            task.add_done_callback(
                lambda _task, session=audio_session: session.mark_awake_after_response()
            )

    async def _handle_fetch_configs(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle fetching available configurations"""
        context = self.client_contexts[client_uid]
        config_files = scan_config_alts_directory(context.system_config.config_alts_dir)
        await websocket.send_text(
            json.dumps({"type": "config-files", "configs": config_files})
        )

    async def _handle_config_switch(
        self, websocket: WebSocket, client_uid: str, data: dict
    ):
        """Handle switching to a different configuration"""
        config_file_name = data.get("file")
        if config_file_name:
            context = self.client_contexts[client_uid]
            await context.handle_config_switch(websocket, config_file_name)

    async def _handle_fetch_backgrounds(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle fetching available background images"""
        bg_files = scan_bg_directory()
        await websocket.send_text(
            json.dumps({"type": "background-files", "files": bg_files})
        )

    async def _handle_audio_play_start(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """
        Handle audio playback start notification
        """
        audio_session = self.audio_sessions.get(client_uid)
        if audio_session:
            audio_session.mark_speaking()

        group_members = self.chat_group_manager.get_group_members(client_uid)
        if len(group_members) > 1:
            display_text = data.get("display_text")
            if display_text:
                silent_payload = prepare_audio_payload(
                    audio_path=None,
                    display_text=display_text,
                    actions=None,
                    forwarded=True,
                )
                await self.broadcast_to_group(
                    group_members, silent_payload, exclude_uid=client_uid
                )

    async def _handle_frontend_playback_complete(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        audio_session = self.audio_sessions.get(client_uid)
        if audio_session:
            audio_session.mark_awake_after_response()
            self._schedule_kws_timeout_after_response(
                websocket,
                client_uid,
                audio_session,
            )

    async def _handle_group_info(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle group info request"""
        await self.send_group_update(websocket, client_uid)

    async def _handle_init_config_request(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle request for initialization configuration"""
        context = self.client_contexts.get(client_uid)
        if not context:
            context = self.default_context_cache

        await websocket.send_text(
            json.dumps(
                {
                    "type": "set-model-and-conf",
                    "model_info": context.live2d_model.model_info,
                    "conf_name": context.character_config.conf_name,
                    "conf_uid": context.character_config.conf_uid,
                    "client_uid": client_uid,
                }
            )
        )

    async def _handle_heartbeat(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle heartbeat messages from clients"""
        try:
            await websocket.send_json({"type": "heartbeat-ack"})
        except Exception as e:
            logger.error(f"Error sending heartbeat acknowledgment: {e}")
