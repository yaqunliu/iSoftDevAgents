import asyncio
import time
import unittest

from app.ws.manager import WebSocketManager


class _FastWebSocket:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.payloads.append(payload)


class _SlowWebSocket:
    def __init__(self, *, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.payloads: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        await asyncio.sleep(self.delay_seconds)
        self.payloads.append(payload)


class WebSocketManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_does_not_wait_forever_for_a_slow_connection(self) -> None:
        manager = WebSocketManager(send_timeout_seconds=0.02)
        project_id = "project-1"
        fast_socket = _FastWebSocket()
        slow_socket = _SlowWebSocket(delay_seconds=0.2)

        manager._connections[project_id].add(fast_socket)  # type: ignore[arg-type]
        manager._connections[project_id].add(slow_socket)  # type: ignore[arg-type]

        started_at = time.perf_counter()
        await manager.broadcast(project_id, {"type": "agent_progress", "data": {"taskId": "task-1"}})
        elapsed_seconds = time.perf_counter() - started_at

        self.assertLess(elapsed_seconds, 0.12)
        self.assertEqual(len(fast_socket.payloads), 1)
        self.assertEqual(fast_socket.payloads[0]["type"], "agent_progress")
        self.assertNotIn(slow_socket, manager._connections.get(project_id, set()))


if __name__ == "__main__":
    unittest.main()
