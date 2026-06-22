"""체감온도 산식 — STS weather.kma_feels_like 계승.

senseTemp가 응답에 있으면 그대로 쓰고, 없으면 온도/습도로 기상청 공식 여름 체감온도를 산출.
"""
from __future__ import annotations

import math


def kma_feels_like(ta: float | None, rh: float | None) -> float | None:
    """기상청 공식 여름철 체감온도 (습구온도 Tw: Stull 식 기반)."""
    if ta is None or rh is None:
        return None
    tw = (
        ta * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(ta + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * (rh ** 1.5) * math.atan(0.023101 * rh)
        - 4.686035
    )
    feels = -0.2442 + 0.55399 * tw + 0.45535 * ta - 0.0022 * tw * tw + 0.00278 * tw * ta + 3.0
    return round(feels, 1)
