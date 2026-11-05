"""시각, 원자적 쓰기, JSON 파일, flock, 환경 변수 조정값, 템플릿 채우기."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def now() -> str:
    """UTC `%Y-%m-%dT%H:%M:%SZ`. 같은 길이라 문자열 비교가 시각 비교다."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_seconds(stamp: str | None) -> float | None:
    """now() 형식 시각에서 지금까지 흐른 초. 읽지 못하면 None."""
    if not stamp:
        return None
    try:
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - then).total_seconds()


def write_atomic(path: Path, text: str) -> None:
    """임시 파일에 쓴 뒤 os.replace 한다. 읽는 쪽은 잠금 없이도 완전한 파일만 본다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj) -> None:
    write_atomic(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


@contextlib.contextmanager
def flock(path: Path) -> Iterator[None]:
    """path 를 잠금 파일로 LOCK_EX 를 잡는다. 같은 프로세스에서 같은 파일을 두 번 잡으면 교착한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def env_float(name: str, default: float) -> float:
    """테스트가 대기 시간을 줄일 때 쓴다. 값이 이상하면 기본값."""
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


_SLOT = re.compile(r"\{\{(\w+)\}\}")


def fill(text: str, **values: str) -> str:
    """템플릿의 `{{이름}}` 을 채운다. 모르는 이름은 KeyError(템플릿 버그)."""
    return _SLOT.sub(lambda m: str(values[m.group(1)]), text)


def die_at(point: str) -> None:
    """테스트 전용: HTEAM_TEST_DIE_AT 이 point 면 그 자리에서 프로세스를 죽인다(실행자 사망 재현)."""
    if os.environ.get("HTEAM_TEST_DIE_AT") == point:
        os._exit(137)
