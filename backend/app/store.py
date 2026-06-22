"""실시간 상태 저장소 — PoC는 인메모리(기기별 최신값 + 링버퍼 + 경보 상태).

추후 TimescaleDB(이력) + Redis(최신값/pub-sub)로 교체. 인터페이스를 좁게 유지해
저장 백엔드 전환 시 collector/ws 변경을 최소화한다.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

from .config import settings
from .heat import classify


class Station:
    def __init__(self, sn: str, name: str | None, kind: str):
        self.sn = sn
        self.name = name or sn
        self.kind = kind
        self.history: deque[dict] = deque(maxlen=settings.HISTORY_POINTS)
        self.latest: dict | None = None
        self.level_code: str = "safe"            # 현재 위험단계
        self.last_alert_at: dict[str, datetime] = {}  # 단계코드 -> 마지막 경보시각(디바운스)

    def update(self, reading: dict) -> dict:
        lvl = classify(reading.get("feels_like"))
        point = {
            "at": reading["measured_at"].isoformat() if reading.get("measured_at") else None,
            "feels_like": reading.get("feels_like"),
            "temperature": reading.get("temperature"),
            "humidity": reading.get("humidity"),
            "level": lvl.code,
        }
        self.history.append(point)
        self.latest = {**reading,
                       "measured_at": point["at"],
                       "level": lvl.code, "level_label": lvl.label, "level_color": lvl.color}
        prev = self.level_code
        self.level_code = lvl.code
        return {"prev": prev, "current": lvl.code}

    def snapshot(self) -> dict:
        return {
            "sn": self.sn, "name": self.name, "kind": self.kind,
            "latest": self.latest,
            "history": list(self.history),
        }


class Store:
    def __init__(self):
        self.stations: dict[str, Station] = {}
        self.alerts: deque[dict] = deque(maxlen=100)  # 최근 경보 피드

    def ingest(self, reading: dict) -> dict:
        sn = reading["sn"]
        st = self.stations.get(sn)
        if st is None:
            st = Station(sn, reading.get("name"), reading.get("kind", "outdoor"))
            self.stations[sn] = st
        transition = st.update(reading)
        return {"station": st, **transition}

    def add_alert(self, alert: dict) -> None:
        self.alerts.appendleft(alert)

    def snapshot(self) -> dict:
        return {
            "stations": [s.snapshot() for s in self.stations.values()],
            "alerts": list(self.alerts),
            "ts": datetime.now().isoformat(),
        }


store = Store()
