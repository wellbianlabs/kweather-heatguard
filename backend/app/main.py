"""HeatGuard 실시간 폭염대응 — FastAPI 진입점(멀티테넌트 인증).

- 인증: 이메일/비번 회원가입·로그인, 토큰=테넌트 api_key(X-API-Key). 데모계정 'demo-key'(읽기전용).
- 계정별 기기 관리: 데모=데모 기기(mock), 실계정=등록 시리얼(케이웨더 API 조회).
- 분석/리포트: STS 대시보드·리포트 기능 계승(데모는 mock 시계열, 실계정은 실데이터 한정).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date as _date
from datetime import datetime
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import analytics, auth, collector, crypto, devices as dev_db, kw_iot, mock, sites as site_db
from .config import settings
from .database import SessionLocal, db_enabled
from .deps import block_demo, get_db, get_tenant
from .heat import LEVELS, classify, thresholds
from .models import Device, Tenant
from .store import store
from .ws import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("heatguard.main")

_DEMO_DEVICES = [
    ("HG-OUT-001", "A현장 옥외작업장", "outdoor"),
    ("HG-OUT-002", "B현장 자재야적장", "outdoor"),
    ("HG-IN-001", "용해로 작업동(밀폐)", "indoor"),
    ("HG-IN-002", "사무동 휴게실", "indoor"),
]


def _ensure_demo() -> None:
    """데모 테넌트/기기 보장(시드 누락 대비, idempotent)."""
    if not db_enabled():
        return
    try:
        with SessionLocal() as db:
            t = db.scalar(select(Tenant).where(Tenant.api_key == "demo-key"))
            if t is None:
                t = Tenant(email="demo@heatguard.local", api_key="demo-key", name="데모 사업장", is_demo=True)
                db.add(t)
                db.commit()
                db.refresh(t)
            if not db.scalar(select(Device).where(Device.tenant_id == t.id)):
                for sn, name, kind in _DEMO_DEVICES:
                    db.add(Device(tenant_id=t.id, serial=sn, name=name, kind=kind, location=name, source="demo"))
                db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("데모 시드 보장 실패(무시): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_demo()
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


app = FastAPI(title="HeatGuard 실시간 폭염대응", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(auth.router)


# ── 공개 엔드포인트(인증 불필요) ──
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mode": "mock" if (settings.USE_MOCK or not settings.KW_IOT_API_KEY) else "kw-iot",
            "db": db_enabled(), "kweather_configured": kw_iot.has_credentials()}


@app.get("/api/thresholds")
def get_thresholds() -> dict:
    return {"thresholds": thresholds(),
            "levels": [{"code": l.code, "label": l.label, "color": l.color, "rank": l.rank}
                       for l in sorted(LEVELS.values(), key=lambda x: x.rank)]}


@app.get("/api/dates")
def dates() -> dict:
    today = mock.now_kst().date()
    return {"dates": mock.available_dates(today, 14), "max_date": today.isoformat()}


# ── 헬퍼 ──
def _parse_date(s: str | None) -> _date:
    if s:
        try:
            return _date.fromisoformat(s)
        except Exception:  # noqa: BLE001
            pass
    return mock.now_kst().date()


def _points_for(serials: list[str], sn: str | None, on: _date, today: bool) -> list[dict]:
    sns = [sn] if sn else list(serials)
    now = mock.now_kst()
    pts: list[dict] = []
    for s in sns:
        pts += (mock.today_series(s, now) if today else mock.day_series(s, on))
    return pts


def _downsample(points: list[dict], interval: int) -> list[dict]:
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
        out.append({"at": key, "feels_like": round(sum(gf) / len(gf), 1) if gf else None,
                    "temperature": round(sum(gt) / len(gt), 1) if gt else None})
    return out


def _demo_latest_by_serial() -> dict:
    snap = mock.snapshot_at(mock.now_kst())
    return {st["sn"]: {"feels_like": (st.get("latest") or {}).get("feels_like"),
                       "level": (st.get("latest") or {}).get("level"),
                       "level_label": (st.get("latest") or {}).get("level_label")}
            for st in snap.get("stations", [])}


async def _real_live(db: Session, tenant: Tenant) -> dict:
    """실계정 라이브 — 등록 시리얼을 케이웨더 API로 조회해 스냅샷 구성(히스토리 없음)."""
    devs = {d.serial: d for d in dev_db.list_for(db, tenant)}
    now = mock.now_kst()
    try:
        readings = {r["sn"]: r for r in await kw_iot.fetch_real_readings(crypto.decrypt(tenant.kw_api_key), tenant.kw_user_id)}
    except Exception:  # noqa: BLE001
        readings = {}
    stations, alerts = [], []
    for serial, d in devs.items():
        r = readings.get(serial)
        if not r:
            continue
        lvl = classify(r["feels_like"])
        at = r["measured_at"].isoformat() if hasattr(r["measured_at"], "isoformat") else None
        latest = {"sn": serial, "name": d.name, "kind": d.kind, "measured_at": at,
                  "temperature": r["temperature"], "humidity": r["humidity"], "feels_like": r["feels_like"],
                  "level": lvl.code, "level_label": lvl.label, "level_color": lvl.color}
        stations.append({"sn": serial, "name": d.name, "kind": d.kind, "latest": latest, "history": []})
        if lvl.rank >= LEVELS["caution"].rank:
            from .alerts import ACTION
            alerts.append({"at": now.isoformat(), "sn": serial, "name": d.name, "kind": d.kind,
                           "level": lvl.code, "level_label": lvl.label, "level_color": lvl.color,
                           "feels_like": r["feels_like"], "action": ACTION.get(lvl.code, "")})
    alerts.sort(key=lambda a: a["feels_like"] or 0, reverse=True)
    snap = {"stations": stations, "alerts": alerts, "ts": now.isoformat()}
    return mock.attach_external(snap, now)


# ── 인증 필요 엔드포인트 ──
@app.get("/api/live")
async def live(tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    if tenant.is_demo:
        return mock.snapshot_at(mock.now_kst())
    return await _real_live(db, tenant)


@app.get("/api/devices")
def devices(tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    demo_latest = _demo_latest_by_serial() if tenant.is_demo else {}
    items = []
    for d in dev_db.list_for(db, tenant):
        row = dev_db.as_dict(d)
        if d.source == "demo":
            row["latest"] = demo_latest.get(d.serial)
        items.append(row)
    return {"devices": items, "is_demo": tenant.is_demo,
            "kweather_configured": kw_iot.has_credentials(),
            "kweather_account": settings.KW_IOT_USER_ID or None}


@app.post("/api/devices")
def add_device(payload: dict = Body(...), tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    block_demo(tenant)
    serial = (payload.get("serial") or payload.get("device_sn") or "").strip()
    if not serial:
        raise HTTPException(400, "시리얼 번호가 필요합니다.")
    d = dev_db.add(db, tenant, serial, payload.get("name"), payload.get("kind", "outdoor"),
                   payload.get("location"), payload.get("site_id"), payload.get("device_type"))
    return {"ok": True, "device": dev_db.as_dict(d)}


@app.patch("/api/devices/{serial}/site")
def assign_device_site(serial: str, payload: dict = Body(...),
                       tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    block_demo(tenant)
    if not dev_db.assign_site(db, tenant, serial, payload.get("site_id")):
        raise HTTPException(404, "기기를 찾을 수 없습니다.")
    return {"ok": True}


@app.get("/api/devices/page")
def devices_page(page: int = 1, page_size: int = 50, site_id: int | None = None, region: str | None = None,
                 kind: str | None = None, model: str | None = None, q: str | None = None,
                 unassigned: bool = False, tenant: Tenant = Depends(get_tenant),
                 db: Session = Depends(get_db)) -> dict:
    """대규모 기기 목록(서버측 필터·페이지네이션). 데모 기기는 현재값 동봉."""
    res = dev_db.query(db, tenant, page=page, page_size=page_size, site_id=site_id, region=region,
                       kind=kind, model=model, q=q, unassigned=unassigned)
    if tenant.is_demo:
        latest = _demo_latest_by_serial()
        for d in res["devices"]:
            d["latest"] = latest.get(d["device_sn"])
    return res


@app.get("/api/devices/summary")
def devices_summary(tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    return dev_db.summary(db, tenant)


@app.post("/api/devices/bulk")
def devices_bulk(payload: dict = Body(...), tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    """선택 기기 일괄 작업 — assign(사업장 이동) / delete(삭제)."""
    block_demo(tenant)
    action = payload.get("action")
    serials = payload.get("serials") or []
    n = 0
    if action == "assign":
        sid = payload.get("site_id")
        for s in serials:
            if dev_db.assign_site(db, tenant, s, int(sid) if sid else None):
                n += 1
    elif action == "delete":
        for s in serials:
            if dev_db.remove(db, tenant, s):
                n += 1
    else:
        raise HTTPException(400, "지원하지 않는 작업입니다.")
    return {"ok": True, "affected": n}


# ── 사업장(Site) ──
@app.get("/api/sites")
def list_sites(tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    counts = site_db.device_counts(db, tenant)
    return {"sites": [site_db.as_dict(s, counts.get(s.id, 0)) for s in site_db.list_for(db, tenant)],
            "regions": site_db.regions(db, tenant)}


@app.post("/api/sites")
def add_site(payload: dict = Body(...), tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    block_demo(tenant)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "사업장 이름이 필요합니다.")
    s = site_db.add(db, tenant, name, payload.get("address"), payload.get("region"))
    return {"ok": True, "site": site_db.as_dict(s, 0)}


@app.delete("/api/sites/{site_id}")
def delete_site(site_id: int, tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    block_demo(tenant)
    if not site_db.remove(db, tenant, site_id):
        raise HTTPException(404, "사업장을 찾을 수 없습니다.")
    return {"ok": True}


# ── AIR365 가져오기 ──
@app.get("/api/air365/devices")
async def air365_devices(tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    """케이웨더 AIR365 계정에 등록된 IoT 기기 목록(가져오기 후보). 이미 등록된 기기는 imported=true."""
    owned = set(dev_db.serials_for(db, tenant))
    acct = (tenant.kw_user_id or settings.KW_IOT_USER_ID) or None
    try:
        readings = await kw_iot.fetch_real_readings(crypto.decrypt(tenant.kw_api_key), tenant.kw_user_id)
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "account": acct, "error": str(e), "devices": []}
    items = [{
        "serial": r["sn"], "name": r["name"], "kind": r["kind"], "model": r.get("model"),
        "device_type": r.get("device_type"),
        "metrics": r.get("metrics", []), "feels_like": r["feels_like"], "temperature": r["temperature"],
        "humidity": r["humidity"], "date": r.get("raw_date"), "imported": r["sn"] in owned,
    } for r in readings]
    return {"reachable": True, "account": acct, "devices": items}


@app.post("/api/air365/import")
async def air365_import(payload: dict = Body(...), tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    """선택한 AIR365 시리얼을 지정 사업장으로 가져오기(등록)."""
    block_demo(tenant)
    serials = payload.get("serials") or []
    site_id = payload.get("site_id")
    if not serials:
        raise HTTPException(400, "가져올 기기를 선택하세요.")
    if site_id is not None and site_db.get(db, tenant, site_id) is None:
        raise HTTPException(400, "유효하지 않은 사업장입니다.")
    try:
        by = {r["sn"]: r for r in await kw_iot.fetch_real_readings(crypto.decrypt(tenant.kw_api_key), tenant.kw_user_id)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AIR365 조회 실패: {e}")
    imported = []
    for sn in serials:
        r = by.get(sn)
        if not r:
            continue
        d = dev_db.add(db, tenant, sn, r.get("name"), r["kind"], None, site_id,
                       r.get("device_type"), source="air365", model=r.get("model"))
        imported.append(d.serial)
    return {"ok": True, "imported": imported, "count": len(imported)}


@app.delete("/api/devices/{serial}")
def delete_device(serial: str, tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    block_demo(tenant)
    if not dev_db.remove(db, tenant, serial):
        raise HTTPException(400, "삭제할 수 없는 기기입니다(데모 기기이거나 미등록).")
    return {"ok": True}


@app.get("/api/kweather/status")
async def kweather_status(tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    kw_devs = [d for d in dev_db.list_for(db, tenant) if d.source in ("kweather", "air365")]
    pr = await kw_iot.probe(crypto.decrypt(tenant.kw_api_key), tenant.kw_user_id)
    seen_map = {s["serial"]: s for s in pr.get("seen", [])}
    now = mock.now_kst()
    devices_status = []
    for d in kw_devs:
        hit = seen_map.get(d.serial)
        if hit is None:
            st = "not_found" if pr.get("reachable") else ("unconfigured" if not pr.get("configured") else "unreachable")
            devices_status.append({"serial": d.serial, "name": d.name, "status": st})
        else:
            stale = True
            try:
                mt = datetime.strptime(str(hit.get("date") or "")[:12], "%Y%m%d%H%M")
                stale = (now - mt).total_seconds() > 3600
            except Exception:  # noqa: BLE001
                pass
            devices_status.append({"serial": d.serial, "name": d.name, "status": "online",
                                   "feels_like": hit.get("feels_like"), "temperature": hit.get("temperature"),
                                   "humidity": hit.get("humidity"), "date": hit.get("date"), "stale": stale})
    return {**pr, "devices": devices_status, "registered": [d.serial for d in kw_devs]}


# ── AIR365 연동 설정(계정별 자격증명) ──
def _mask(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    return ("•" * max(0, len(v) - 4) + v[-4:]) if len(v) > 4 else "••••"


@app.get("/api/integrations/air365")
def air365_settings(tenant: Tenant = Depends(get_tenant)) -> dict:
    """현재 연동 상태(키는 마스킹). 계정 자체 키 없으면 플랫폼 폴백 여부 안내."""
    has_own = bool((tenant.kw_api_key or "").strip() and (tenant.kw_user_id or "").strip())
    return {"connected": has_own, "user_id": tenant.kw_user_id,
            "api_key_masked": _mask(crypto.decrypt(tenant.kw_api_key)),
            "platform_fallback": (not has_own) and kw_iot.has_credentials(),
            "base_url": settings.KW_IOT_BASE_URL}


@app.post("/api/integrations/air365")
async def air365_connect(payload: dict = Body(...), tenant: Tenant = Depends(get_tenant),
                         db: Session = Depends(get_db)) -> dict:
    """AIR365 계정 ID + API 키 저장. test=true 면 저장 전 연결만 점검."""
    block_demo(tenant)
    user_id = (payload.get("user_id") or "").strip()
    api_key = (payload.get("api_key") or "").strip()
    if not user_id or not api_key:
        raise HTTPException(400, "AIR365 계정 ID와 API 키를 모두 입력하세요.")
    pr = await kw_iot.probe(api_key, user_id)
    if not pr.get("reachable"):
        raise HTTPException(400, f"연결 실패: {pr.get('error') or 'API 키/계정 ID를 확인하세요.'}")
    if payload.get("test"):
        return {"ok": True, "reachable": True, "seen": len(pr.get("seen", [])), "saved": False}
    tenant.kw_user_id = user_id
    tenant.kw_api_key = crypto.encrypt(api_key)
    db.commit()
    return {"ok": True, "reachable": True, "seen": len(pr.get("seen", [])), "saved": True}


@app.delete("/api/integrations/air365")
def air365_disconnect(tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    block_demo(tenant)
    tenant.kw_user_id = None
    tenant.kw_api_key = None
    db.commit()
    return {"ok": True}


@app.get("/api/kpi")
def kpi(sn: str | None = None, date: str | None = None,
        tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    serials = dev_db.serials_for(db, tenant)
    on = _parse_date(date)
    is_today = on == mock.now_kst().date()
    pts = _points_for(serials, sn, on, is_today)
    return {"device_sn": sn, "date": on.isoformat(), **analytics.kpi_from_points(pts)}


@app.get("/api/timeseries")
def timeseries(sn: str, date: str | None = None, interval: int = 10,
               tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    on = _parse_date(date)
    is_today = on == mock.now_kst().date()
    pts = _downsample(_points_for(dev_db.serials_for(db, tenant), sn, on, is_today), interval)
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
    return {"device_sn": sn, "date": on.isoformat(), "interval_minutes": interval, "points": pts,
            "max_delta": max_delta, "enclosed_alert": max_delta is not None and max_delta >= settings.ENCLOSED_DELTA_ALERT,
            "enclosed_threshold": settings.ENCLOSED_DELTA_ALERT}


@app.get("/api/weekly")
def weekly(sn: str | None = None, tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    serials = dev_db.serials_for(db, tenant)
    target = sn or (serials[0] if serials else None)
    if not target:
        return {"device_sn": None, "days": []}
    return {"device_sn": target, "days": mock.recent_days(target, mock.now_kst().date(), 7)}


@app.get("/api/report/daily")
def report_daily(sn: str, date: str | None = None,
                 tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)) -> dict:
    on = _parse_date(date)
    dev = dev_db.get(db, tenant, sn)
    is_today = on == mock.now_kst().date()
    pts = mock.today_series(sn, mock.now_kst()) if is_today else mock.day_series(sn, on)
    data = analytics.daily_from_points(pts)
    ext_by_hour: dict[int, list[float]] = {}
    for e in mock.external_series(on):
        h = datetime.fromisoformat(e["at"]).hour
        if e["feels"] is not None:
            ext_by_hour.setdefault(h, []).append(e["feels"])
    compare, max_delta = [], None
    for hr in data["hours"]:
        ev = ext_by_hour.get(hr["hour"])
        ef = round(sum(ev) / len(ev), 1) if ev else None
        d = round(hr["feels"] - ef, 1) if (hr["feels"] is not None and ef is not None) else None
        if d is not None and (max_delta is None or d > max_delta):
            max_delta = d
        compare.append({"hour": hr["hour"], "indoor_feels": hr["feels"], "external_feels": ef,
                        "delta": d, "color": hr["color"]})
    return {"device_sn": sn, "date": on.isoformat(),
            "location_name": dev.name if dev else (mock.station_by_sn(sn) or {}).get("name", sn),
            "kind": dev.kind if dev else (mock.station_by_sn(sn) or {}).get("kind"),
            "generated_at": mock.now_kst().isoformat(),
            "compare": compare, "max_delta": max_delta,
            "enclosed_alert": max_delta is not None and max_delta >= settings.ENCLOSED_DELTA_ALERT,
            "enclosed_threshold": settings.ENCLOSED_DELTA_ALERT, **data}


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "snapshot", "data": mock.attach_external(store.snapshot(), mock.now_kst())})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception:  # noqa: BLE001
        await manager.disconnect(ws)


# ── 프론트 정적 서빙 ──
_root = Path(__file__).resolve().parent.parent.parent
for _cand in (_root / "frontend" / "dist", _root / "web"):
    if _cand.is_dir():
        app.mount("/", StaticFiles(directory=str(_cand), html=True), name="spa")
        break
