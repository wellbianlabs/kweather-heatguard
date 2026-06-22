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
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
    # 서버리스(Vercel)에서는 RUN_COLLECTOR=false → 워커 미기동, /api/live 는 stateless 합성 사용.
    task = asyncio.create_task(collector.run()) if settings.RUN_COLLECTOR else None
    try:
        yield
    finally:
        if task is not None:
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
async def live() -> dict:
    # 워커가 누적한 실시간 스냅샷이 있으면 그대로, 없으면(서버리스 콜드/무워커)
    # stateless 합성으로 폴백 — 동일 대시보드가 sts(WS)·Vercel(폴링) 양쪽에서 동작.
    snap = store.snapshot()
    if snap["stations"]:
        return mock.attach_external(snap, mock.now_kst())
    if settings.USE_MOCK or not settings.KW_IOT_API_KEY:
        return mock.snapshot_at(mock.now_kst())
    # 실계정·무워커: last-all 1회 조회로 현재값만(히스토리 없음)
    from .kw_iot import fetch_last_all
    readings = await fetch_last_all()
    for r in readings:
        store.ingest(r)
    return mock.attach_external(store.snapshot(), mock.now_kst())


# ── 분석/리포트 API (STS 대시보드·리포트 기능 계승, 데모는 mock 시계열 기반) ──
from datetime import date as _date  # noqa: E402

from . import analytics, devices as dev_registry, kw_iot, mock  # noqa: E402


def _parse_date(s: str | None) -> _date:
    if s:
        try:
            return _date.fromisoformat(s)
        except Exception:  # noqa: BLE001
            pass
    return mock.now_kst().date()


def _points_for(sn: str | None, on: _date, today: bool) -> list[dict]:
    """선택 기기·일자의 시계열. sn 없으면 전체 기기 합산(KPI용)."""
    sns = [sn] if sn else [s["sn"] for s in mock.STATIONS]
    pts: list[dict] = []
    now = mock.now_kst()
    for s in sns:
        pts += (mock.today_series(s, now) if today else mock.day_series(s, on))
    return pts


def _downsample(points: list[dict], interval: int) -> list[dict]:
    """interval(분) 버킷 평균 — STS time_series 다운샘플 대응."""
    if interval <= 10:
        return points
    buckets: dict[str, list[dict]] = {}
    for p in points:
        try:
            t = datetime.fromisoformat(p["at"])
        except Exception:  # noqa: BLE001
            continue
        b = t.replace(minute=(t.minute // interval) * interval, second=0, microsecond=0)
        buckets.setdefault(b.isoformat(), []).append(p)
    out = []
    for key in sorted(buckets):
        g = buckets[key]
        gf = [x["feels_like"] for x in g if x.get("feels_like") is not None]
        gt = [x["temperature"] for x in g if x.get("temperature") is not None]
        out.append({
            "at": key,
            "feels_like": round(sum(gf) / len(gf), 1) if gf else None,
            "temperature": round(sum(gt) / len(gt), 1) if gt else None,
        })
    return out


def _demo_latest_by_serial() -> dict:
    snap = mock.snapshot_at(mock.now_kst())
    out = {}
    for st in snap.get("stations", []):
        lt = st.get("latest") or {}
        out[st["sn"]] = {"feels_like": lt.get("feels_like"), "level": lt.get("level"),
                         "level_label": lt.get("level_label"), "at": lt.get("measured_at")}
    return out


@app.get("/api/devices")
def devices() -> dict:
    """등록 기기 목록(데모+케이웨더 시리얼). 데모 기기는 현재값 동봉(외부호출 없음)."""
    demo = _demo_latest_by_serial()
    items = []
    for d in dev_registry.all_devices():
        row = {"device_sn": d.serial, "location_name": d.name, "name": d.name,
               "kind": d.kind, "location": d.location, "source": d.source}
        if d.source == "demo":
            row["latest"] = demo.get(d.serial)
        items.append(row)
    return {"devices": items, "kweather_configured": kw_iot.has_credentials(),
            "kweather_account": settings.KW_IOT_USER_ID or None}


@app.post("/api/devices")
def add_device(payload: dict = Body(...)) -> dict:
    serial = (payload.get("serial") or payload.get("device_sn") or "").strip()
    if not serial:
        raise HTTPException(400, "시리얼 번호가 필요합니다.")
    d = dev_registry.add(serial, payload.get("name"), payload.get("kind", "outdoor"), payload.get("location"))
    return {"ok": True, "device": dev_registry.as_dict(d)}


@app.delete("/api/devices/{serial}")
def delete_device(serial: str) -> dict:
    if not dev_registry.remove(serial):
        raise HTTPException(400, "삭제할 수 없는 기기입니다(데모 기기이거나 미등록).")
    return {"ok": True}


@app.get("/api/kweather/status")
async def kweather_status() -> dict:
    """케이웨더 IoT API 연결 점검 + 등록 시리얼별 연동 상태(기기 관리 페이지용)."""
    pr = await kw_iot.probe()
    seen_map = {s["serial"]: s for s in pr.get("seen", [])}
    now = mock.now_kst()
    devices_status = []
    for d in dev_registry.all_devices():
        if d.source != "kweather":
            continue
        hit = seen_map.get(d.serial)
        if hit is None:
            st = "not_found" if pr.get("reachable") else ("unconfigured" if not pr.get("configured") else "unreachable")
            devices_status.append({"serial": d.serial, "name": d.name, "status": st})
        else:
            # 신선도 판단(응답 date YYYYMMDDHHMM)
            stale = True
            raw = str(hit.get("date") or "")
            try:
                mt = datetime.strptime(raw[:12], "%Y%m%d%H%M")
                stale = (now - mt).total_seconds() > 3600
            except Exception:  # noqa: BLE001
                pass
            devices_status.append({"serial": d.serial, "name": d.name, "status": "online",
                                   "feels_like": hit.get("feels_like"), "temperature": hit.get("temperature"),
                                   "humidity": hit.get("humidity"), "date": hit.get("date"), "stale": stale})
    return {**pr, "devices": devices_status,
            "registered": [d.serial for d in dev_registry.all_devices() if d.source == "kweather"]}


@app.get("/api/dates")
def dates() -> dict:
    today = mock.now_kst().date()
    return {"dates": mock.available_dates(today, 14), "max_date": today.isoformat()}


@app.get("/api/kpi")
def kpi(sn: str | None = None, date: str | None = None) -> dict:
    on = _parse_date(date)
    is_today = on == mock.now_kst().date()
    pts = _points_for(sn, on, is_today)
    return {"device_sn": sn, "date": on.isoformat(), **analytics.kpi_from_points(pts)}


@app.get("/api/timeseries")
def timeseries(sn: str, date: str | None = None, interval: int = 10) -> dict:
    on = _parse_date(date)
    is_today = on == mock.now_kst().date()
    pts = _downsample(_points_for(sn, on, is_today), interval)
    # 외부(기상청) 체감 라인 — 같은 시각 기준 병합(내부 vs 외부 비교)
    ext = {p["at"]: p for p in _downsample(
        [{"at": e["at"], "feels_like": e["feels"], "temperature": e["temperature"]} for e in mock.external_series(on)],
        interval)}
    max_delta = None
    for p in pts:
        e = ext.get(p["at"])
        ef = e["feels_like"] if e else None
        p["external_feels"] = ef
        if p.get("feels_like") is not None and ef is not None:
            d = round(p["feels_like"] - ef, 1)
            p["delta"] = d
            if max_delta is None or d > max_delta:
                max_delta = d
    return {"device_sn": sn, "date": on.isoformat(), "interval_minutes": interval,
            "points": pts, "max_delta": max_delta,
            "enclosed_alert": max_delta is not None and max_delta >= settings.ENCLOSED_DELTA_ALERT,
            "enclosed_threshold": settings.ENCLOSED_DELTA_ALERT}


@app.get("/api/weekly")
def weekly(sn: str | None = None) -> dict:
    target = sn or mock.STATIONS[0]["sn"]
    return {"device_sn": target, "days": mock.recent_days(target, mock.now_kst().date(), 7)}


@app.get("/api/report/daily")
def report_daily(sn: str, date: str | None = None) -> dict:
    on = _parse_date(date)
    st = mock.station_by_sn(sn)
    is_today = on == mock.now_kst().date()
    pts = mock.today_series(sn, mock.now_kst()) if is_today else mock.day_series(sn, on)
    data = analytics.daily_from_points(pts)

    # 내·외부(기상청) 체감온도 비교 — 시간별 외부 체감 산출 후 내부와 대조
    ext_by_hour: dict[int, list[float]] = {}
    for e in mock.external_series(on):
        h = datetime.fromisoformat(e["at"]).hour
        if e["feels"] is not None:
            ext_by_hour.setdefault(h, []).append(e["feels"])
    compare = []
    max_delta = None
    for hr in data["hours"]:
        ev = ext_by_hour.get(hr["hour"])
        ef = round(sum(ev) / len(ev), 1) if ev else None
        d = round(hr["feels"] - ef, 1) if (hr["feels"] is not None and ef is not None) else None
        if d is not None and (max_delta is None or d > max_delta):
            max_delta = d
        compare.append({"hour": hr["hour"], "indoor_feels": hr["feels"], "external_feels": ef,
                        "delta": d, "color": hr["color"]})
    enclosed = max_delta is not None and max_delta >= settings.ENCLOSED_DELTA_ALERT

    return {
        "device_sn": sn, "date": on.isoformat(),
        "location_name": st["name"] if st else sn,
        "kind": st["kind"] if st else None,
        "generated_at": mock.now_kst().isoformat(),
        "compare": compare, "max_delta": max_delta,
        "enclosed_alert": enclosed, "enclosed_threshold": settings.ENCLOSED_DELTA_ALERT,
        **data,
    }


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "snapshot", "data": mock.attach_external(store.snapshot(), mock.now_kst())})
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
