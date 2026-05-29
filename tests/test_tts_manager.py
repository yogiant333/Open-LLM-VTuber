import asyncio
import json

import src.open_llm_vtuber.conversations.tts_manager as tts_manager_module
from src.open_llm_vtuber.conversations.tts_manager import TTSTaskManager


def test_wait_until_idle_waits_for_ordered_payload_sender(monkeypatch):
    asyncio.run(_run_wait_until_idle_waits_for_ordered_payload_sender(monkeypatch))


async def _run_wait_until_idle_waits_for_ordered_payload_sender(monkeypatch):
    release_second_send = asyncio.Event()
    sent: list[int | str] = []

    async def fake_send_audio_payload(payload, username="User"):
        if payload["id"] == 1:
            await release_second_send.wait()
        sent.append(payload["id"])

    async def fake_websocket_send(raw_payload: str):
        sent.append(f"ws:{json.loads(raw_payload)['id']}")

    monkeypatch.setattr(
        tts_manager_module, "send_audio_payload", fake_send_audio_payload
    )

    manager = TTSTaskManager(username="User")
    manager._sender_task = asyncio.create_task(
        manager._process_payload_queue(fake_websocket_send)
    )

    await manager._payload_queue.put(({"id": 1}, 1))
    await manager._payload_queue.put(({"id": 0}, 0))

    waiter = asyncio.create_task(manager.wait_until_idle())
    await asyncio.sleep(0)

    assert not waiter.done()
    release_second_send.set()
    await asyncio.wait_for(waiter, timeout=1)

    assert sent == [0, "ws:0", 1, "ws:1"]

    manager._sender_task.cancel()
    await asyncio.gather(manager._sender_task, return_exceptions=True)
