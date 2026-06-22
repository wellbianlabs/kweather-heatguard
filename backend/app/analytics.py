"""분석 엔진 — STS analytics.py 계승(경량판, pandas/DB 없이 포인트 리스트로 동작).

KPI·노출시간·일일 보고서·시간별 집계·안전조치 가이드를 산출. 도메인 규칙(노출시간 산정,
법정 휴식 의무, 권고 문구)은 STS와 동일하게 보존.
"""
from __future__ import annotations

from datetime import datetime

from .config import settings
from .heat import LEVELS, classify, thresholds


def fmt_minutes(minutes: int | None) -> str:
    if not minutes or minutes <= 0:
        return "0분"
    h, m = divmod(int(minutes), 60)
    return f"{h}시간 {m}분" if h > 0 else f"{m}분"


def _level_out(code: str) -> dict:
    lv = LEVELS[code]
    return {"code": lv.code, "label": lv.label, "color": lv.color, "rank": lv.rank}


# 안전조치 권고 — 고용노동부 「2026 폭염 대비 노동자 건강보호 대책」(2026.5.13.) 반영(STS 계승).
GUIDANCE = {
    "danger": [
        "(작업 중지) 폭염중대경보(체감 38℃ 이상) 기준 — 긴급조치 작업을 제외한 옥외작업 원칙적 중지",
        "(휴식) 체감온도 33℃ 이상 작업 시 2시간마다 20분 이상 휴식 부여(법적 의무), 작업 전 건강상태 확인",
        "(응급대응) 온열질환 의심 증상 발생 시 즉시 작업 중단, 시원한 장소 이송 및 119 신고체계 가동",
        "(점검) 냉방장치·그늘 휴게시설 가동 상태, 시원한 물·개인 보냉장구 비치 여부 즉시 점검",
    ],
    "warning": [
        "(작업 중지) 폭염경보(체감 35℃ 이상) 기준 — 무더위 시간대(14~17시) 옥외작업 중지, 작업시간 조기·야간 전환",
        "(휴식) 체감온도 33℃ 이상 작업 시 2시간마다 20분 이상 휴식 부여(법적 의무)",
        "(관리감독) 관리감독자 순회점검 강화 및 2인 1조 작업 운영",
    ],
    "caution": [
        "(작업 조정) 폭염주의보(체감 33℃ 이상) 기준 — 작업시간대 조정 또는 옥외작업 단축",
        "(휴식) 체감온도 33℃ 이상 작업 시 2시간마다 20분 이상 휴식 부여(법적 의무) 및 충분한 음용수 섭취 지도",
        "(건강관리) 온열질환 민감군(고령자·기저질환자) 작업배치 조정 및 건강상태 수시 확인",
    ],
    "attention": [
        "(예방수칙) 폭염안전 5대 기본수칙(시원한 물·냉방장치·휴식·보냉장구·119 신고) 이행체계 점검",
        "(안내) 폭염 대비 근로자 행동요령 게시 및 전파, 음용수·그늘 휴게장소 사전 확보",
    ],
    "safe": [
        "(통상관리) 폭염 위험단계 미해당 — 통상적인 안전보건 관리체계 유지",
        "(대비) 폭염 발생 대비 음용수·냉방·휴게시설 등 예방 인프라 사전 점검 권고",
    ],
}


def _f(points: list[dict], key: str) -> list[float]:
    return [p[key] for p in points if p.get(key) is not None]


def kpi_from_points(points: list[dict], step_min: int = 10) -> dict:
    if not points:
        return {
            "record_count": 0, "max_feels_like": None, "max_feels_like_time": None,
            "max_temperature": None, "avg_humidity": None, "avg_feels_like": None,
            "danger_minutes": 0, "danger_minutes_label": "0분",
            "current_level": _level_out("safe"), "thresholds": thresholds(),
        }
    feels = _f(points, "feels_like")
    mx = max(feels)
    mx_pt = max(points, key=lambda p: p.get("feels_like", -999))
    temps = _f(points, "temperature")
    humis = _f(points, "humidity")
    danger_min = sum(1 for v in feels if v >= settings.HEAT_DANGER) * step_min
    return {
        "record_count": len(points),
        "max_feels_like": round(mx, 1),
        "max_feels_like_time": _hhmm(mx_pt.get("at")),
        "max_temperature": round(max(temps), 1) if temps else None,
        "avg_humidity": round(sum(humis) / len(humis), 1) if humis else None,
        "avg_feels_like": round(sum(feels) / len(feels), 1),
        "danger_minutes": danger_min,
        "danger_minutes_label": fmt_minutes(danger_min),
        "current_level": _level_out(classify(mx).code),
        "thresholds": thresholds(),
    }


def _hhmm(at: str | None) -> str | None:
    if not at:
        return None
    try:
        return datetime.fromisoformat(at).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return None


def daily_from_points(points: list[dict], step_min: int = 10) -> dict:
    if not points:
        return {
            "max_feels_like": None, "max_feels_like_time": None, "max_temperature": None,
            "avg_humidity": None,
            "minutes_over_31": 0, "minutes_over_33": 0, "minutes_over_35": 0, "minutes_over_38": 0,
            "exposure": [], "work_hot_minutes": 0, "legal_rest_count": 0, "legal_rest_minutes": 0,
            "hours": [], "peak_level": _level_out("safe"), "guidance": GUIDANCE["safe"],
        }
    feels = _f(points, "feels_like")
    mx = max(feels)
    mx_pt = max(points, key=lambda p: p.get("feels_like", -999))
    temps = _f(points, "temperature")
    humis = _f(points, "humidity")

    def minutes_over(thr: float) -> int:
        return sum(1 for v in feels if v >= thr) * step_min

    over = {
        "attention": minutes_over(settings.HEAT_ATTENTION),
        "caution": minutes_over(settings.HEAT_CAUTION),
        "warning": minutes_over(settings.HEAT_WARNING),
        "danger": minutes_over(settings.HEAT_DANGER),
    }
    exposure = [
        {"code": c, "label": LEVELS[c].label, "color": LEVELS[c].color,
         "threshold": thresholds()[c], "minutes": over[c], "label_time": fmt_minutes(over[c])}
        for c in ("attention", "caution", "warning", "danger")
    ]

    # 법정 휴식 의무 — 근무시간(09~18) 중 체감 33℃↑ 작업에 '2시간마다 20분 이상'(산안규칙).
    work_hot = 0
    for p in points:
        h = _hour(p.get("at"))
        if h is not None and 9 <= h < 18 and (p.get("feels_like") or -999) >= settings.HEAT_CAUTION:
            work_hot += step_min
    legal_rest_count = work_hot // 120
    legal_rest_minutes = legal_rest_count * 20

    # 시간별 평균(체감/온도) → 단계 색
    buckets: dict[int, list[dict]] = {}
    for p in points:
        h = _hour(p.get("at"))
        if h is not None:
            buckets.setdefault(h, []).append(p)
    hours = []
    for h in sorted(buckets):
        g = buckets[h]
        gf = _f(g, "feels_like")
        gt = _f(g, "temperature")
        f = round(sum(gf) / len(gf), 1) if gf else None
        t = round(sum(gt) / len(gt), 1) if gt else None
        lv = classify(f)
        hours.append({"hour": h, "feels": f, "temperature": t, "level": lv.code, "color": lv.color})

    peak = classify(mx)
    return {
        "max_feels_like": round(mx, 1), "max_feels_like_time": _hhmm(mx_pt.get("at")),
        "max_temperature": round(max(temps), 1) if temps else None,
        "avg_humidity": round(sum(humis) / len(humis), 1) if humis else None,
        "minutes_over_31": over["attention"], "minutes_over_33": over["caution"],
        "minutes_over_35": over["warning"], "minutes_over_38": over["danger"],
        "exposure": exposure,
        "work_hot_minutes": work_hot, "work_hot_label": fmt_minutes(work_hot),
        "legal_rest_count": legal_rest_count, "legal_rest_minutes": legal_rest_minutes,
        "hours": hours,
        "peak_level": _level_out(peak.code), "guidance": GUIDANCE[peak.code],
    }


def _hour(at: str | None) -> int | None:
    if not at:
        return None
    try:
        return datetime.fromisoformat(at).hour
    except Exception:  # noqa: BLE001
        return None
