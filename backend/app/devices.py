"""기기 레지스트리 — IoT 시리얼 기반 기기 관리(STS Device 모델 대응).

STS와의 차이: STS는 업로드 TXT를 기기에 연결했지만, IoT 트랙은 **기기 시리얼**로 케이웨더
API에서 실시간 값을 조회한다. 데모 기기(mock)와 실기기(kweather, 시리얼)를 한 레지스트리로 관리.

영속화: 서버리스 데모에서는 인메모리(시드=config). 영구 등록은 sts 서버 이식 시 DB(예정).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from . import mock
from .config import settings


@dataclass
class DeviceInfo:
    serial: str
    name: str
    kind: str            # indoor | outdoor
    location: str | None  # 설치 위치/사업장
    source: str          # demo | kweather


_REGISTRY: dict[str, DeviceInfo] = {}


def _seed() -> None:
    _REGISTRY.clear()
    # 데모 기기(mock 스테이션)
    for st in mock.STATIONS:
        _REGISTRY[st["sn"]] = DeviceInfo(
            serial=st["sn"], name=st["name"], kind=st["kind"], location=st["name"], source="demo")
    # 실기기(케이웨더 시리얼) — config KW_IOT_SERIALS(csv)
    for raw in (settings.KW_IOT_SERIALS or "").split(","):
        s = raw.strip()
        if s and s not in _REGISTRY:
            _REGISTRY[s] = DeviceInfo(serial=s, name=s, kind="outdoor", location=None, source="kweather")


_seed()


def all_devices() -> list[DeviceInfo]:
    return list(_REGISTRY.values())


def get(serial: str) -> DeviceInfo | None:
    return _REGISTRY.get(serial)


def add(serial: str, name: str | None, kind: str, location: str | None) -> DeviceInfo:
    serial = serial.strip()
    if not serial:
        raise ValueError("시리얼 번호가 필요합니다.")
    dev = DeviceInfo(serial=serial, name=(name or serial).strip(),
                     kind=("indoor" if kind == "indoor" else "outdoor"),
                     location=(location or None), source="kweather")
    _REGISTRY[serial] = dev
    return dev


def remove(serial: str) -> bool:
    dev = _REGISTRY.get(serial)
    if dev is None or dev.source == "demo":   # 데모 기기는 삭제 불가
        return False
    del _REGISTRY[serial]
    return True


def as_dict(dev: DeviceInfo) -> dict:
    return asdict(dev)
