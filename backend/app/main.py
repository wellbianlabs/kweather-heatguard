"""HeatGuard 실시간 폭염대응 — FastAPI 진입점.

- lifespan: 수집 워커(collector) 백그라운드 기동/종료
- WS /ws/live: 라이브 대시보드 푸시(접속 즉시 현재 스냅샷 1회 전송)
- REST: /api/live(스냅샷), /api/thresholds, /api/health
- 빌드된 프론트(frontend/dist) 존재 시 정적 서빙(단일 서버 배포)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import collector
from .config import settings
from .heat import LEVELS, thresholds
from .store import store
from .ws import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(collector.run())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="HeatGuard 실시간 폭염대응", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "mode": "mock" if (settings.USE_MOCK or not settings.KW_IOT_API_KEY) else "kw-iot",
        "poll_interval_sec": settings.POLL_INTERVAL_SEC,
        "stations": len(store.stations),
        "ws_clients": len(manager.active),
    }


@app.get("/api/thresholds")
def get_thresholds() -> dict:
    return {
        "thresholds": thresholds(),
        "levels": [
            {"code": l.code, "label": l.label, "color": l.color, "rank": l.rank}
            for l in sorted(LEVELS.values(), key=lambda x: x.rank)
        ],
    }


@app.get("/api/live")
def live() -> dict:
    return store.snapshot()


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "snapshot", "data": store.snapshot()})
        while True:
            await ws.receive_text()   # 클라이언트 keepalive/ping 수신(무시)
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception:  # noqa: BLE001
        await manager.disconnect(ws)


# ── 프론트 정적 서빙 ──
# 우선순위: 빌드된 React(frontend/dist) > 손수 작성한 PoC 대시보드(web/)
_root = Path(__file__).resolve().parent.parent.parent
for _cand in (_root / "frontend" / "dist", _root / "web"):
    if _cand.is_dir():
        app.mount("/", StaticFiles(directory=str(_cand), html=True), name="spa")
        break
