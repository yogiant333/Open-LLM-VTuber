import asyncio
import json
import re
import time
import uuid
from datetime import datetime
from typing import Any, List, Optional, Dict
from loguru import logger

from ..agent.output_types import DisplayText, Actions
from ..live2d_model import Live2dModel
from ..tts.tts_interface import TTSInterface
from ..utils.stream_audio import prepare_audio_payload
from ..ue_avatar_protocol import send_audio_payload
from .types import WebSocketSend


class TTSTaskManager:
    """Manages TTS tasks and ensures ordered delivery to frontend while allowing parallel TTS generation"""

    def __init__(
        self, username: str = "User", timing_context: Optional[Dict[str, Any]] = None
    ) -> None:
        self.task_list: List[asyncio.Task] = []
        self.username = username
        self.timing_context = timing_context
        self._lock = asyncio.Lock()
        # Queue to store ordered payloads
        self._payload_queue: asyncio.Queue[Dict] = asyncio.Queue()
        # Task to handle sending payloads in order
        self._sender_task: Optional[asyncio.Task] = None
        # Counter for maintaining order
        self._sequence_counter = 0
        self._next_sequence_to_send = 0

    async def speak(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        websocket_send: WebSocketSend,
    ) -> None:
        """
        Queue a TTS task while maintaining order of delivery.

        Args:
            tts_text: Text to synthesize
            display_text: Text to display in UI
            actions: Live2D model actions
            live2d_model: Live2D model instance
            tts_engine: TTS engine instance
            websocket_send: WebSocket send function
        """
        if len(re.sub(r'[\s.,!?，。！？\'"』」）】\s]+', "", tts_text)) == 0:
            logger.debug("Empty TTS text, sending silent display payload")
            # Get current sequence number for silent payload
            current_sequence = self._sequence_counter
            self._sequence_counter += 1

            # Start sender task if not running
            if not self._sender_task or self._sender_task.done():
                self._sender_task = asyncio.create_task(
                    self._process_payload_queue(websocket_send)
                )

            await self._send_silent_payload(display_text, actions, current_sequence)
            return

        logger.debug(
            f"🏃Queuing TTS task for: '''{tts_text}''' (by {display_text.name})"
        )
        self._log_once("first_tts_task_queued_logged", "first_tts_task_queued")

        # Get current sequence number
        current_sequence = self._sequence_counter
        self._sequence_counter += 1

        # Start sender task if not running
        if not self._sender_task or self._sender_task.done():
            self._sender_task = asyncio.create_task(
                self._process_payload_queue(websocket_send)
            )

        # Create and queue the TTS task
        task = asyncio.create_task(
            self._process_tts(
                tts_text=tts_text,
                display_text=display_text,
                actions=actions,
                live2d_model=live2d_model,
                tts_engine=tts_engine,
                sequence_number=current_sequence,
            )
        )
        self.task_list.append(task)

    async def _process_payload_queue(self, websocket_send: WebSocketSend) -> None:
        """
        Process and send payloads in correct order.
        Runs continuously until all payloads are processed.
        """
        buffered_payloads: Dict[int, Dict] = {}

        while True:
            try:
                # Get payload from queue
                payload, sequence_number = await self._payload_queue.get()
                buffered_payloads[sequence_number] = payload

                # Send payloads in order
                while self._next_sequence_to_send in buffered_payloads:
                    next_payload = buffered_payloads.pop(self._next_sequence_to_send)
                    if next_payload.get("audio"):
                        next_payload["server_perf"] = self._server_perf_payload()
                    await send_audio_payload(next_payload, username=self.username)
                    await websocket_send(json.dumps(next_payload))
                    if next_payload.get("audio"):
                        self._log_once("first_audio_sent_logged", "first_audio_sent")
                    self._next_sequence_to_send += 1

                self._payload_queue.task_done()

            except asyncio.CancelledError:
                break

    async def wait_until_idle(self) -> None:
        """Wait until generated TTS payloads have been sent in sequence."""
        if self.task_list:
            await asyncio.gather(*self.task_list)
        await self._payload_queue.join()

    async def _send_silent_payload(
        self,
        display_text: DisplayText,
        actions: Optional[Actions],
        sequence_number: int,
    ) -> None:
        """Queue a silent audio payload"""
        audio_payload = prepare_audio_payload(
            audio_path=None,
            display_text=display_text,
            actions=actions,
        )
        await self._payload_queue.put((audio_payload, sequence_number))

    async def _process_tts(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        sequence_number: int,
    ) -> None:
        """Process TTS generation and queue the result for ordered delivery"""
        audio_file_path = None
        try:
            audio_file_path = await self._generate_audio(tts_engine, tts_text)
            self._log_once(
                "first_tts_audio_generated_logged", "first_tts_audio_generated"
            )
            payload = prepare_audio_payload(
                audio_path=audio_file_path,
                display_text=display_text,
                actions=actions,
            )
            # Queue the payload with its sequence number
            await self._payload_queue.put((payload, sequence_number))

        except Exception as e:
            logger.error(f"Error preparing audio payload: {e}")
            # Queue silent payload for error case
            payload = prepare_audio_payload(
                audio_path=None,
                display_text=display_text,
                actions=actions,
            )
            await self._payload_queue.put((payload, sequence_number))

        finally:
            if audio_file_path:
                tts_engine.remove_file(audio_file_path)
                logger.debug("Audio cache file cleaned.")

    async def _generate_audio(self, tts_engine: TTSInterface, text: str) -> str:
        """Generate audio file from text"""
        logger.debug(f"🏃Generating audio for '''{text}'''...")
        return await tts_engine.async_generate_audio(
            text=text,
            file_name_no_ext=f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}",
        )

    def clear(self) -> None:
        """Clear all pending tasks and reset state"""
        for task in self.task_list:
            task.add_done_callback(self._consume_task_result)
            if not task.done():
                task.cancel()
        self.task_list.clear()
        if self._sender_task:
            self._sender_task.add_done_callback(self._consume_task_result)
            self._sender_task.cancel()
        self._sequence_counter = 0
        self._next_sequence_to_send = 0
        # Create a new queue to clear any pending items
        self._payload_queue = asyncio.Queue()

    @staticmethod
    def _consume_task_result(task: asyncio.Task) -> None:
        try:
            task.exception()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug(f"Discarded cancelled TTS task result: {exc}")

    def _log_once(self, flag_name: str, event: str) -> None:
        if not self.timing_context or self.timing_context.get(flag_name):
            return

        self.timing_context[flag_name] = True
        turn_started_ns = self.timing_context.get("turn_started_ns")
        if not turn_started_ns:
            return

        elapsed_ms = (time.perf_counter_ns() - turn_started_ns) / 1_000_000
        logger.info(
            "PERF conversation turn_id={} event={} elapsed_ms={:.3f}",
            self.timing_context.get("turn_id", ""),
            event,
            elapsed_ms,
        )

    def _server_perf_payload(self) -> Optional[Dict[str, Any]]:
        if not self.timing_context:
            return None

        turn_started_ns = self.timing_context.get("turn_started_ns")
        if not turn_started_ns:
            return None

        return {
            "turn_id": self.timing_context.get("turn_id", ""),
            "elapsed_ms": round(
                (time.perf_counter_ns() - turn_started_ns) / 1_000_000, 3
            ),
        }
