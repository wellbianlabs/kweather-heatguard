"""수집 워커 — 케이웨더 IoT last-all 주기 폴링 → 저장 → 경보평가 → WS 브로드캐스트.

asyncio 백그라운드 태스크. main 의 lifespan 에서 기동/종료.
"""
from __future__ import annotations

import asyncio
import logging

from . import alerts, mock
from .config import settings
from .kw_iot import fetch_last_all
from .store import store
from .ws import manager

log = logging.getLogger("heatguard.collector")


async def _poll_once() -> None:
    readings = await fetch_last_all()
    fired: list[dict] = []
    for reading in readings:
        res = store.ingest(reading)
        station, prev, current = res["station"], res["prev"], res["current"]
        if alerts.should_alert(station, prev, current):
            alert = alerts.build_alert(station, current)
            store.add_alert(alert)
            fired.append(alert)
            await alerts.dispatch(alert)
    # 라이브 대시보드로 최신 스냅샷 푸시(외부 기상청 체감 비교 부착)
    snap = mock.attach_external(store.snapshot(), mock.now_kst())
    await manager.broadcast({"type": "snapshot", "data": snap})
    for alert in fired:
        await manager.broadcast({"type": "alert", "data": alert})


async def run() -> None:
    mode = "MOCK" if (settings.USE_MOCK or not settings.KW_IOT_API_KEY) else "KW-IoT"
    log.info("수집 워커 시작 — 모드=%s, 주기=%ss", mode, settings.POLL_INTERVAL_SEC)
    while True:
        try:
            await _poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("폴링 오류: %s", e)
        await asyncio.sleep(settings.POLL_INTERVAL_SEC)
