# HeatGuard — IoT 기반 실시간 폭염대응 솔루션

케이웨더 STS(과거 기록 분석)를 토대로 한 **별도 신규 트랙**. 실시간 IoT 센서 스트림 →
즉시 위험감지 → 자동 알림·작업중지 권고까지 수행한다.

> STS(`KWEATHER_STS`)는 *과거 측정기록 분석 전용*. 이 저장소는 정반대로 **실시간**을 지향한다.
> 도메인 규칙(위험단계·체감온도 공식·폭염정책)은 STS에서 그대로 계승했다.

## 현재 상태 (PoC)
**수집 → 저장 → WebSocket 라이브 대시보드** 수직 슬라이스가 동작한다.

- **수집:** 케이웨더 IoT Open API `last-all` 폴링(`app/kw_iot.py`). 키가 없으면 **mock 모드**로
  가상 기기 4대가 위험단계 임계를 넘나들며 시연 — 키 없이 바로 구동.
- **저장:** 인메모리(기기별 최신값 + 링버퍼 + 경보상태, `app/store.py`). *추후 TimescaleDB+Redis.*
- **경보:** 위험단계 **상향 교차 감지 → 디바운스 → Slack/Webhook**(`app/alerts.py`). 채널 미설정 시
  WS 피드/로그로만 송출.
- **푸시:** FastAPI WebSocket `/ws/live`로 스냅샷·경보 브로드캐스트(`app/ws.py`, `app/collector.py`).
- **대시보드:** 빌드 불필요 자립형 HTML(`web/index.html`) — 라이브 게이지·스파크라인·임계선·경보 피드.

## 실행
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt
copy .env.example .env                            # mock 모드 기본
uvicorn app.main:app --reload --port 8100
```
브라우저 → http://localhost:8100  (대시보드)
- `GET /api/health` · `GET /api/live` · `GET /api/thresholds` · `WS /ws/live`

실 케이웨더 IoT 연동: `.env`에 `KW_IOT_API_KEY`/`KW_IOT_USER_ID` 채우고 `USE_MOCK=false`.

## 계승한 STS 도메인 규칙
- 위험단계(체감℃): 관심 31 / 주의 33 / 경고 35 / 위험 38. 색 동일.
- 체감온도 = 기상청 공식(Stull 습구). senseTemp 있으면 우선.
- 경보 권고: 체감 33℃↑ 2시간마다 20분 휴식(법적의무), 경고 14~17시 옥외중지, 위험 중대경보.

## 로드맵 (HANDOFF §10)
1. ✅ 수집→저장→WS 라이브 대시보드 (PoC)
2. ⬜ TimescaleDB 하이퍼테이블 + Redis 최신값/pub-sub (sts 서버 공용)
3. ⬜ 경보 엔진 고도화: 에스컬레이션·근무시간 정책·이력 영속화
4. ⬜ Slack/Webhook 실채널 연동 + (후속) 카카오 알림톡/SMS
5. ⬜ 라이브 대시보드 React/Mantine 이관(STS 디자인시스템 재활용) + 정기요약은 STS `report.py`
