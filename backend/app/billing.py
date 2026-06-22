"""구독 요금제 카탈로그 — 프리미엄 SaaS(월간/연간). 가격은 운영자 조정 가능(KRW).

실제 결제는 PSP(토스페이먼츠/Stripe) 연동 자리. 현재는 가입 시 플랜만 저장(데모 결제).
"""
from __future__ import annotations

PREMIUM_FEATURES = [
    "실시간 IoT 위험감지 · 무제한 기기",
    "단계별 자동 경보(Slack/Webhook·알림톡)",
    "기상청 외부 체감온도 비교·밀폐형 경보",
    "일일/기간 안전관리 리포트·PDF",
    "법정 휴식 의무 자동 진단",
    "회사별 격리·계정 관리",
]

PLANS = {
    "monthly": {
        "code": "monthly", "name": "월간 구독", "price": 49000, "period": "월",
        "cycle_days": 30, "billed": "매월 자동 결제", "tagline": "부담 없이 시작",
    },
    "annual": {
        "code": "annual", "name": "연간 구독", "price": 490000, "period": "년",
        "cycle_days": 365, "billed": "연 1회 결제", "monthly_equiv": 40833,
        "save_label": "2개월 무료 · 약 17% 절약", "tagline": "가장 인기", "recommended": True,
    },
}


def catalog() -> dict:
    return {"plans": list(PLANS.values()), "features": PREMIUM_FEATURES, "currency": "KRW"}


def get_plan(code: str | None) -> dict | None:
    return PLANS.get(code or "")
