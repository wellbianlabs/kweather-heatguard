"""폭염 위험 단계 판정 — STS heat.py 계승(체감온도 A-TEMP 기준).

위험단계/색/임계는 STS와 동일하게 유지한다(도메인 규칙 보존). 임계값은 config로 조정 가능.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class HeatLevel:
    code: str       # safe | attention | caution | warning | danger
    label: str      # 한글 표기
    color: str      # 헥스 컬러 (대시보드 공통)
    rank: int       # 정렬/비교용 (높을수록 위험)


LEVELS = {
    "safe": HeatLevel("safe", "안전", "#16a34a", 0),
    "attention": HeatLevel("attention", "관심", "#84cc16", 1),
    "caution": HeatLevel("caution", "주의", "#facc15", 2),
    "warning": HeatLevel("warning", "경고", "#f97316", 3),
    "danger": HeatLevel("danger", "위험", "#dc2626", 4),
}


def classify(feels_like: float | None) -> HeatLevel:
    """체감온도 -> 위험 단계."""
    if feels_like is None:
        return LEVELS["safe"]
    t = float(feels_like)
    if t >= settings.HEAT_DANGER:
        return LEVELS["danger"]
    if t >= settings.HEAT_WARNING:
        return LEVELS["warning"]
    if t >= settings.HEAT_CAUTION:
        return LEVELS["caution"]
    if t >= settings.HEAT_ATTENTION:
        return LEVELS["attention"]
    return LEVELS["safe"]


def thresholds() -> dict[str, float]:
    return {
        "attention": settings.HEAT_ATTENTION,
        "caution": settings.HEAT_CAUTION,
        "warning": settings.HEAT_WARNING,
        "danger": settings.HEAT_DANGER,
    }
