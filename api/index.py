"""Vercel Python 서버리스 진입점 — HeatGuard 웹 데모.

repo 루트를 Vercel 프로젝트 루트로 배포. 모든 요청은 vercel.json rewrite 로 이 함수에
전달되고 FastAPI 가 라우팅한다(API + 대시보드 정적 서빙).

서버리스는 백그라운드 워커·WebSocket·인메모리 상태를 유지할 수 없으므로 강제로:
- RUN_COLLECTOR=false (폴링 워커 미기동)
- USE_MOCK=true       (요청마다 시간기반 stateless 합성)
대시보드는 WS 연결 실패 시 자동으로 /api/live 폴링으로 전환된다.
"""
import os
import sys

# backend/ 를 import 경로에 추가 (app 패키지 접근)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

os.environ.setdefault("RUN_COLLECTOR", "false")
os.environ.setdefault("USE_MOCK", "true")

from app.main import app  # noqa: E402

# Vercel Python 런타임이 ASGI 앱(`app`)을 그대로 구동한다.
