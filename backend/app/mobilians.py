"""KG모빌리언스 정기결제(자동결제) 어댑터 — 골격.

실제 연동(빌링키 발급/정기 청구/해시 규칙/엔드포인트)은 **정기결제 연동규격서**와
전용 인증키 수령 후 아래 TODO 자리에 구현한다. 키는 settings(=Vercel env)에서만 읽고,
빌링키는 crypto로 암호화해 DB(tenants.billing_key)에 저장한다.

안전: 카드정보 입력·청구는 모빌리언스 결제창/빌링(PCI)이 처리. 본 모듈은 요청 생성·
결과 검증·정기 청구 호출만 담당하며 카드 원문(PAN)을 절대 저장/처리하지 않는다.
"""
from __future__ import annotations

from .config import settings

PROVIDER = "mobilians"


def configured() -> bool:
    return bool(settings.MOBILIANS_MID and settings.MOBILIANS_KEY)


def checkout_params(tenant_id: int, plan_code: str, amount: int) -> dict:
    """결제창 호출용 파라미터 생성.

    TODO(규격서): 모빌리언스 정기결제 결제창 파라미터(MID, 주문번호, 금액, 상품명,
    리턴/노티 URL, 해시 signature) 구성. 현재는 미구성 상태를 알린다.
    """
    if not configured():
        return {"ready": False, "reason": "정기결제 자격증명(MOBILIANS_MID/KEY) 미설정"}
    raise NotImplementedError("정기결제 연동규격서 수령 후 결제창 파라미터 구현 필요")


def verify_callback(payload: dict) -> bool:
    """결제창/웹훅 콜백 무결성 검증(해시·MID 일치 등).

    TODO(규격서): 모빌리언스 해시 규칙으로 위변조 검증. 미구현 시 False.
    """
    return False


def charge(billing_key: str, amount: int, order_id: str) -> dict:
    """저장된 빌링키로 정기 청구.

    TODO(규격서): 모빌리언스 정기결제 승인 API 호출(빌링키+금액+주문번호+해시).
    PG_TEST_MODE면 실청구 금지.
    """
    if settings.PG_TEST_MODE:
        return {"ok": False, "test_mode": True, "message": "테스트 모드 — 실청구 차단"}
    raise NotImplementedError("정기결제 승인 API 구현 필요(규격서)")
