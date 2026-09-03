from __future__ import annotations

import asyncio
from collections import defaultdict
import logging
import os
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("uvicorn.error")
_DEFAULT_WS_SEND_TIMEOUT_SECONDS = float(os.getenv("ISOFTDEVAGENTS_WS_SEND_TIMEOUT_SECONDS") or "0.3")


def _payload_type(payload: dict[str, Any]) -> str:
    value = payload.get("type")
    if isinstance(value, str) and value.strip():
        return value
    return "unknown"


class WebSocketManager:
    def __init__(self, *, send_timeout_seconds: float = _DEFAULT_WS_SEND_TIMEOUT_SECONDS) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._send_timeout_seconds = max(0.1, float(send_timeout_seconds))

    async def connect(self, project_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[project_id].add(websocket)
            connection_count = len(self._connections[project_id])
        logger.info(
            "WebSocket connected: project_id=%s connection_id=%s active_connections=%s",
            project_id,
            hex(id(websocket)),
            connection_count,
        )

    async def disconnect(self, project_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(project_id)
            if not connections:
                return
            connections.discard(websocket)
            connection_count = len(connections)
            if not connections:
                self._connections.pop(project_id, None)
        logger.info(
            "WebSocket disconnected: project_id=%s connection_id=%s active_connections=%s",
            project_id,
            hex(id(websocket)),
            connection_count,
        )

    async def broadcast(self, project_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections.get(project_id, set()))
        logger.debug(
            "WebSocket broadcast: project_id=%s payload_type=%s target_connections=%s",
            project_id,
            _payload_type(payload),
            len(connections),
        )

        stale: list[WebSocket] = []
        results = await asyncio.gather(
            *[
                self._send_payload_with_timeout(project_id, websocket, payload)
                for websocket in connections
            ],
            return_exceptions=False,
        )
        stale.extend([websocket for websocket in results if websocket is not None])

        for websocket in stale:
            await self.disconnect(project_id, websocket)
        if stale:
            logger.warning(
                "WebSocket broadcast removed stale connections: project_id=%s stale_count=%s",
                project_id,
                len(stale),
            )

    async def _send_payload_with_timeout(
        self,
        project_id: str,
        websocket: WebSocket,
        payload: dict[str, Any],
    ) -> WebSocket | None:
        """
        接口注释：
        给单个 websocket 发送一次消息，并在超时或发送失败时返回这个连接，交给上层清理。

        设计注释：
        之前 broadcast 是顺序 await 每个连接的 send_json。
        只要某一个浏览器标签页、代理连接或前端调试窗口卡住，
        整个广播链就会被拖慢，连普通 HTTP API 也会跟着排队。
        这里改成“每个连接单独限时 + 并发发送”，避免一个慢连接拖死全局。
        """

        try:
            await asyncio.wait_for(
                websocket.send_json(payload),
                timeout=self._send_timeout_seconds,
            )
            return None
        except Exception:
            logger.warning(
                "WebSocket send failed or timed out: project_id=%s connection_id=%s payload_type=%s timeout=%.2fs",
                project_id,
                hex(id(websocket)),
                _payload_type(payload),
                self._send_timeout_seconds,
                exc_info=True,
            )
            return websocket


ws_manager = WebSocketManager()
