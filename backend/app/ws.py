"""WebSocket 연결 관리 — 라이브 대시보드로 스냅샷/경보 푸시(브로드캐스트)."""
from __future__ import annotations

import asyncio

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            targets = list(self.active)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self.active.discard(ws)


manager = ConnectionManager()
