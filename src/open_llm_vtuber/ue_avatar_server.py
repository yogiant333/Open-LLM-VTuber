import asyncio
import json
import os
import threading
from typing import Any

import websockets
from loguru import logger
from websockets.legacy.server import Serve, WebSocketServerProtocol, serve


class UeAvatarServer:
    """Fay-compatible WebSocket server for UE digital human clients."""

    def __init__(self, host: str | None = None, port: int | None = None):
        self.host = host or os.getenv("OPEN_LLM_VTUBER_UE_WS_HOST", "127.0.0.1")
        self.port = port or int(os.getenv("OPEN_LLM_VTUBER_UE_WS_PORT", "10002"))
        self._clients: dict[WebSocketServerProtocol, dict[str, Any]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: Serve | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._lock = threading.Lock()
        self._send_lock: asyncio.Lock | None = None
        self._status_listener = None

    def set_status_listener(self, listener) -> None:
        self._status_listener = listener

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            self._started.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="ue-avatar-ws",
                daemon=True,
            )
            self._thread.start()

        self._started.wait(timeout=3)

    def stop(self) -> None:
        loop = self._loop
        server = self._server
        if not loop:
            return

        async def shutdown() -> None:
            for websocket in list(self._clients):
                await websocket.close()
            self._clients.clear()

            if server:
                server.close()
                await server.wait_closed()
            loop.stop()

        asyncio.run_coroutine_threadsafe(shutdown(), loop)

    def client_count(self, username: str | None = None) -> int:
        if username is None:
            return len(self._clients)
        return sum(
            1
            for client in self._clients.values()
            if client.get("username", "User") == username
        )

    def client_snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "username": metadata.get("username", "User"),
                "output": metadata.get("output", True),
                "remote_address": self._format_remote_address(websocket),
            }
            for websocket, metadata in self._clients.items()
        ]

    def status_payload(self) -> dict[str, Any]:
        return {
            "type": "ue-avatar-status",
            "connected_clients": self.client_count(),
            "clients": self.client_snapshot(),
        }

    async def send(self, message: dict[str, Any]) -> int:
        loop = self._loop
        if loop and loop.is_running():
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is not loop:
                future = asyncio.run_coroutine_threadsafe(
                    self._send_on_server_loop(message), loop
                )
                return await asyncio.wrap_future(future)

        return await self._send_on_server_loop(message)

    async def _send_on_server_loop(self, message: dict[str, Any]) -> int:
        if self._send_lock:
            async with self._send_lock:
                return await self._send_on_server_loop_unlocked(message)

        return await self._send_on_server_loop_unlocked(message)

    async def _send_on_server_loop_unlocked(self, message: dict[str, Any]) -> int:
        text = json.dumps(message, ensure_ascii=False)
        username = message.get("Username")

        targets = []
        for websocket, metadata in list(self._clients.items()):
            if username is not None and metadata.get("username", "User") != username:
                continue
            if not self._is_output_enabled(metadata.get("output", True)):
                continue
            targets.append(websocket)

        sent = 0
        for websocket in targets:
            try:
                await websocket.send(text)
                sent += 1
            except websockets.exceptions.ConnectionClosed:
                await self._remove_client(websocket)
            except Exception as exc:
                logger.warning(f"Failed to send UE avatar message: {exc}")

        data = message.get("Data", {})
        audio_detail = ""
        if data.get("Key") == "audio":
            audio_detail = (
                f" value={data.get('Value', '')} "
                f"http_value={data.get('HttpValue', '')}"
            )
        logger.info(
            "UE avatar message dispatched: "
            f"topic={message.get('Topic')} key={data.get('Key')} "
            f"username={username or '*'} sent={sent} targets={len(targets)} "
            f"connected={self.client_count(username)}{audio_detail}"
        )
        return sent

    async def _handler(self, websocket: WebSocketServerProtocol, path: str) -> None:
        self._clients[websocket] = {
            "username": "User",
            "output": True,
            "path": path,
        }
        logger.info(f"UE avatar WebSocket connected: {websocket.remote_address}")
        self._emit_status()

        try:
            async for message in websocket:
                self._update_client_metadata(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self._remove_client(websocket)

    async def _remove_client(self, websocket: WebSocketServerProtocol) -> None:
        if websocket in self._clients:
            self._clients.pop(websocket, None)
            logger.info(f"UE avatar WebSocket disconnected: {websocket.remote_address}")
            self._emit_status()

    def _update_client_metadata(
        self,
        websocket: WebSocketServerProtocol,
        message: str | bytes,
    ) -> None:
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except UnicodeDecodeError:
                return

        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return

        metadata = self._clients.get(websocket)
        if metadata is None:
            return

        username = payload.get("Username")
        output = payload.get("Output")
        if username is not None:
            metadata["username"] = username
        if output is not None:
            metadata["output"] = output
        if username is not None or output is not None:
            logger.info(
                "UE avatar client metadata updated: "
                f"remote={self._format_remote_address(websocket)} "
                f"username={metadata.get('username')} output={metadata.get('output')}"
            )
            self._emit_status()

    def _emit_status(self) -> None:
        if not self._status_listener:
            return

        try:
            self._status_listener(self.status_payload())
        except Exception as exc:
            logger.warning(f"Failed to publish UE avatar status: {exc}")

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._send_lock = asyncio.Lock()

        try:
            self._server = loop.run_until_complete(
                serve(
                    self._handler,
                    self.host,
                    self.port,
                    ping_interval=10,
                    ping_timeout=5,
                )
            )
            logger.info(f"UE avatar WebSocket server listening on {self.host}:{self.port}")
            self._started.set()
            loop.run_forever()
        except OSError as exc:
            logger.error(
                f"Failed to start UE avatar WebSocket server on "
                f"{self.host}:{self.port}: {exc}"
            )
            self._started.set()
        finally:
            self._server = None
            self._send_lock = None
            if not loop.is_closed():
                loop.close()
            self._loop = None

    @staticmethod
    def _is_output_enabled(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() == "true"
        if isinstance(value, (int, float)):
            return value != 0
        return True

    @staticmethod
    def _format_remote_address(websocket: WebSocketServerProtocol) -> str:
        remote_address = websocket.remote_address
        if isinstance(remote_address, tuple):
            return ":".join(str(part) for part in remote_address)
        return str(remote_address)


ue_avatar_server = UeAvatarServer()
