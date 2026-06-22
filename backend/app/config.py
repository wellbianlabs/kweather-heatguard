"""HeatGuard 실시간 폭염대응 — 설정.

STS(과거 기록 분석)에서 검증된 위험단계 임계값/IoT 연동 설정을 그대로 계승하되,
실시간 수집/경보/푸시에 필요한 항목을 추가한다. 값은 환경변수(.env)로 주입.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── 위험단계 임계값(체감온도 ℃) — STS와 동일 도메인 규칙 ──
    HEAT_ATTENTION: float = 31.0   # 관심
    HEAT_CAUTION: float = 33.0     # 주의 (33℃↑ 2시간마다 20분 휴식 법적의무 기준)
    HEAT_WARNING: float = 35.0     # 경고
    HEAT_DANGER: float = 38.0      # 위험 (폭염중대경보)

    # 내부(측정) 체감이 외부(기상청)보다 이 값 이상 높으면 '밀폐형 폭염 사업장' 경보(STS 계승)
    ENCLOSED_DELTA_ALERT: float = 5.0

    # ── 케이웨더 IoT Open API (last-all 폴링) ──
    KW_IOT_BASE_URL: str = "https://gateway.kweather.co.kr:8443/iot/groups/v2"
    KW_IOT_API_KEY: str = ""               # IoT api_key (없으면 mock 모드)
    KW_IOT_USER_ID: str = ""               # 계정 id (idType=USER), 예: test1@kweather.co.kr

    # ── 실시간 수집 ──
    POLL_INTERVAL_SEC: int = 30            # last-all 폴링 주기
    USE_MOCK: bool = False                 # true면 합성 데이터(키 없이 PoC 구동)
    RUN_COLLECTOR: bool = True             # 백그라운드 폴링 워커 기동(서버리스=false)

    # ── 경보(MVP: Slack/Webhook 1채널) ──
    SLACK_WEBHOOK_URL: str = ""            # 비면 경보를 콘솔/WS 피드로만 송출
    ALERT_DEBOUNCE_SEC: int = 600          # 동일 기기·단계 재경보 억제(중복 방지)

    # ── 저장 ──
    DATABASE_URL: str = ""                 # 비면 메모리 전용(PoC). 추후 TimescaleDB.
    HISTORY_POINTS: int = 240              # 기기별 메모리 링버퍼 길이(≈ 2시간/30초)


settings = Settings()
