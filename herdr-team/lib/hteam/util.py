"""시각, 원자적 쓰기, JSON 파일, flock, 환경 변수 조정값, 템플릿 채우기."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .errors import FAIL, HteamError


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
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:  # 디스크가 차는 등 쓰다 실패하면 임시 파일을 남기지 않는다
        tmp.unlink(missing_ok=True)
        raise


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def bad_side_file(path: Path, why: str) -> HteamError:
    # 힌트의 경로는 state 폴더 기준이다(answers/ 아래 답 파일도 그 하위 경로까지 적는다)
    rel = next((path.relative_to(up).as_posix() for up in path.parents
                if up.name == "state" and up.parent.name == ".herdr-team"), path.name)
    return HteamError("bad_side_file", f"{path.name} 을 읽지 못했다: {why}", FAIL,
                      f"`.herdr-team/state/{rel}` 을 직접 고치거나 치운 뒤 다시 한다(덮어쓰지 않았다)")


def read_json_strict(path: Path, default):
    """없으면 default. 있는데 읽지 못하거나 JSON 이 아니면 bad_side_file(exit 1).

    read_json 과 달리 손상을 없는 것으로 보지 않는다. 읽은 값을 고쳐 다시 쓰는 기록이 손상 때문에 빈 기록으로 덮어써져
    지워지지 않게 한다. 모양(dict 인지 등)은 부르는 쪽이 보고 틀리면 bad_side_file 을 낸다."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:  # 디렉터리·권한·UTF-8 아님
        raise bad_side_file(path, str(exc)) from None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise bad_side_file(path, f"JSON 이 아니다: {exc}") from None


_SURROGATE = re.compile(r"[\ud800-\udfff]")


def dumps(obj, indent: int | None = None) -> str:
    """JSON 글(ensure_ascii=False). UTF-8 이 아닌 파일명을 os.fsdecode 로 푼 짝 없는 서로게이트(\\udcXX)는 `\\udcXX` 로
    이스케이프한다: 결과는 늘 올바른 UTF-8 이고 json.loads 가 같은 글자로 되읽는다(손실 없음)."""
    return _SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", json.dumps(obj, ensure_ascii=False, indent=indent))


def show(text: str) -> str:
    """사람이 읽는 글(리뷰 파일·프롬프트·커밋 본문)에 넣을 경로. UTF-8 이 아닌 바이트는 `\\xff` 꼴로, 줄바꿈은 `\\n` 으로
    보인다(이름의 줄바꿈이 목록 한 줄을 둘로 나누지 않게). 저장·JSON 값은 그대로 둔다(dumps)."""
    try:
        shown = os.fsencode(text).decode("utf-8", "backslashreplace")
    except UnicodeEncodeError:  # surrogateescape 로 만들 수 없는 서로게이트
        shown = text.encode("utf-8", "backslashreplace").decode("utf-8")
    return shown.replace("\n", "\\n")


def write_json(path: Path, obj) -> None:
    write_atomic(path, dumps(obj, indent=2) + "\n")


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
    """테스트 전용: HTEAM_TEST_DIE_AT 이 point 면 그 자리에서 프로세스를 죽인다(실행자 사망 재현).

    HTEAM_TEST_PAUSE_AT 이 point 면 `<HTEAM_TEST_PAUSE_FILE>.reached` 를 만들고 HTEAM_TEST_PAUSE_FILE 이 생길 때까지
    (최대 60초) 멈춘다(겹친 호출 재현)."""
    if os.environ.get("HTEAM_TEST_DIE_AT") == point:
        os._exit(137)
    if os.environ.get("HTEAM_TEST_PAUSE_AT") == point:
        gate = Path(os.environ["HTEAM_TEST_PAUSE_FILE"])
        gate.with_name(gate.name + ".reached").touch()
        deadline = time.monotonic() + 60
        while not gate.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
