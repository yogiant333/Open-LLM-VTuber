from typing import Union, List, Dict, Any, Optional
import asyncio
import json
import time
from loguru import logger
import numpy as np

from .conversation_utils import (
    create_batch_input,
    process_agent_output,
    send_conversation_start_signals,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    send_ui_suggestions,
    EMOJI_LIST,
)
from .types import WebSocketSend
from .tts_manager import TTSTaskManager
from ..chat_history_manager import store_message
from ..service_context import ServiceContext

# Import necessary types from agent outputs
from ..agent.output_types import SentenceOutput, AudioOutput
from ..ue_avatar_protocol import send_question


async def process_single_conversation(
    context: ServiceContext,
    websocket_send: WebSocketSend,
    client_uid: str,
    user_input: Union[str, List[str], np.ndarray],
    images: Optional[List[Dict[str, Any]]] = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Process a single-user conversation turn

    Args:
        context: Service context containing all configurations and engines
        websocket_send: WebSocket send function
        client_uid: Client unique identifier
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation
        metadata: Optional metadata for special processing flags

    Returns:
        str: Complete response text
    """
    turn_started_ns = time.perf_counter_ns()
    timing_context: Dict[str, Any] = {
        "turn_started_ns": turn_started_ns,
        "turn_id": f"{client_uid}-{turn_started_ns}",
        "first_agent_output_logged": False,
        "first_audio_sent_logged": False,
        "first_tts_task_queued_logged": False,
        "first_tts_audio_generated_logged": False,
    }
    # Create TTSTaskManager for this conversation
    tts_manager = TTSTaskManager(username=client_uid, timing_context=timing_context)
    full_response = ""  # Initialize full_response here

    try:
        # Send initial signals
        await send_conversation_start_signals(websocket_send, username=client_uid)
        logger.info(f"New Conversation Chain {session_emoji} started!")

        # Process user input
        if isinstance(user_input, list):
            input_text = [text.strip() for text in user_input if text.strip()]
            for text in input_text:
                await send_question(text, username=client_uid)
                await websocket_send(
                    json.dumps(
                        {
                            "type": "user-input-transcription",
                            "text": text,
                        }
                    )
                )
        else:
            input_text = await process_user_input(
                user_input,
                context.asr_engine,
                websocket_send,
                username=client_uid,
                metadata=metadata,
                asr_model=context.character_config.asr_config.asr_model,
            )
        input_ready_ms = (time.perf_counter_ns() - turn_started_ns) / 1_000_000
        logger.info(
            "PERF conversation turn_id={} event=input_ready input_type={} elapsed_ms={:.3f}",
            timing_context["turn_id"],
            "audio" if isinstance(user_input, np.ndarray) else "text",
            input_ready_ms,
        )

        # Create batch input
        batch_input = create_batch_input(
            input_text=input_text,
            images=images,
            from_name=context.character_config.human_name,
            metadata=metadata,
        )

        # Store user message (check if we should skip storing to history)
        skip_history = metadata and metadata.get("skip_history", False)
        if context.history_uid and not skip_history:
            input_history_items = input_text if isinstance(input_text, list) else [input_text]
            for input_history_text in input_history_items:
                store_message(
                    conf_uid=context.character_config.conf_uid,
                    history_uid=context.history_uid,
                    role="human",
                    content=input_history_text,
                    name=context.character_config.human_name,
                )

        if skip_history:
            logger.debug("Skipping storing user input to history (proactive speak)")

        logger.info(f"User input: {input_text}")
        if images:
            logger.info(f"With {len(images)} images")

        try:
            # agent.chat yields Union[SentenceOutput, Dict[str, Any]]
            agent_output_stream = context.agent_engine.chat(batch_input)

            async for output_item in agent_output_stream:
                if (
                    isinstance(output_item, dict)
                    and output_item.get("type") == "tool_call_status"
                ):
                    # Handle tool status event: send WebSocket message
                    output_item["name"] = context.character_config.character_name
                    logger.debug(f"Sending tool status update: {output_item}")

                    await websocket_send(json.dumps(output_item))

                elif isinstance(output_item, (SentenceOutput, AudioOutput)):
                    if not timing_context["first_agent_output_logged"]:
                        timing_context["first_agent_output_logged"] = True
                        first_agent_output_ms = (
                            time.perf_counter_ns() - turn_started_ns
                        ) / 1_000_000
                        logger.info(
                            "PERF conversation turn_id={} event=first_agent_output output_type={} elapsed_ms={:.3f}",
                            timing_context["turn_id"],
                            type(output_item).__name__,
                            first_agent_output_ms,
                        )
                    # Handle SentenceOutput or AudioOutput
                    response_part = await process_agent_output(
                        output=output_item,
                        character_config=context.character_config,
                        live2d_model=context.live2d_model,
                        tts_engine=context.tts_engine,
                        websocket_send=websocket_send,  # Pass websocket_send for audio/tts messages
                        tts_manager=tts_manager,
                        translate_engine=context.translate_engine,
                        username=client_uid,
                    )
                    # Ensure response_part is treated as a string before concatenation
                    response_part_str = (
                        str(response_part) if response_part is not None else ""
                    )
                    full_response += response_part_str  # Accumulate text response
                else:
                    logger.warning(
                        f"Received unexpected item type from agent chat stream: {type(output_item)}"
                    )
                    logger.debug(f"Unexpected item content: {output_item}")

        except Exception as e:
            logger.exception(
                f"Error processing agent response stream: {e}"
            )  # Log with stack trace
            await websocket_send(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"Error processing agent response: {str(e)}",
                    }
                )
            )
            # full_response will contain partial response before error
        # --- End processing agent response ---

        # Wait for any pending TTS tasks
        if tts_manager.task_list:
            await tts_manager.wait_until_idle()
            await websocket_send(json.dumps({"type": "backend-synth-complete"}))

        await finalize_conversation_turn(
            tts_manager=tts_manager,
            websocket_send=websocket_send,
            client_uid=client_uid,
        )

        if full_response:
            await send_ui_suggestions(
                context=context,
                username=client_uid,
                user_text="\n".join(input_text) if isinstance(input_text, list) else input_text,
                assistant_text=full_response,
                suggestion_context="follow_up",
            )

        if context.history_uid and full_response:  # Check full_response before storing
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="ai",
                content=full_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
            )
            logger.info(f"AI response: {full_response}")

        return full_response  # Return accumulated full_response

    except asyncio.CancelledError:
        logger.info(f"🤡👍 Conversation {session_emoji} cancelled because interrupted.")
        raise
    except Exception as e:
        logger.error(f"Error in conversation chain: {e}")
        await websocket_send(
            json.dumps({"type": "error", "message": f"Conversation error: {str(e)}"})
        )
        raise
    finally:
        cleanup_conversation(tts_manager, session_emoji)
