"""이미지 생성(설계 12장): `hteam image`. 디자인 워커(Claude)가 자기 pane 에서 부른다.

이미지마다 실행 폴더 하나와 `scripts/codex-run.sh --profile image` 호출 하나(codex exec, Codex 내장 image_gen)다.
래퍼는 timeout + 여유(GRACE) 안에 끝나야 한다(넘기면 끝내고 그 이미지의 실패). 결과는 result.txt 마지막 줄의 일반
파일이다(심볼릭 링크는 따라가지 않고 실패, 읽기는 O_NONBLOCK 으로 열어 fstat 으로 다시 본다). PNG 는 모든 청크의 CRC 를
IEND 까지 보고(IHDR 처음, IDAT 하나 이상, 색 형식 3 은 IDAT 앞 PLTE, 0·4 는 PLTE 없음) IDAT 를 풀어 그 길이가 IHDR 로
계산한 길이와 같고 줄마다 필터 바이트가 0–4 여야 한다. 아니면 `sips` 로 PNG
로 다시 쓴다(못 하면 그 이미지의 실패). --transparent 인데 투명이 빠졌으면 모서리 색을 크로마키로 지운다(8비트 RGB·RGBA
PNG 만). 다 된 바이트를 --out 폴더(검사한 뒤 fd 로 연다) 안 임시 파일에 쓰고 하드 링크로 게시한다: 이미 있는 이름(끊어진
링크 포함)은 덮어쓰지도 따라가지도 않고 `-v2` … 로 간다. 실행 중 폴더·파일 바꿔치기는 위협 모델 밖이다(이미지 codex 는
샌드박스 밖에서 돈다). fd 고정은 실수 방지다. 이미지 하나의 예상 가능한 오류(파일·변환·해독)는 그 이미지의 실패이고
나머지를 계속한다. 중단(Ctrl-C)이면 지금까지의 결과를 `image_interrupted` 로, 실행 중 codex 가 없어지면(래퍼 exit 12)
`codex_missing` 에 지금까지의 결과를 붙여 멈춘다. 거절(turn.failed·error)과 실패는 자동으로 다시 하지 않는다(부른
워커가 정한다).

이 모듈은 codex 를 사전 점검(`codex features list`)과 래퍼(scripts/codex-run.sh, `codex exec` 는 래퍼만 부른다)로만
부르고(사용자 `chrome-devtools` 서버를 끌지는 디스패치와 같은 browser.user_off 가 정한다), PNG 가 아닌 결과를 바꿀 때만 `sips` 를 부른다. hc·horch·git 은 부르지 않는다. 실행 폴더는 저장소 밖(`${XDG_CACHE_HOME:-~/.cache}/herdr-team/images/<프로젝트 폴더 이름>/`)이다(codex 출력이 그대로
담긴다).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import itertools
import stat
import struct
import subprocess
import time
import zlib
from pathlib import Path

from . import browser, config
from .errors import FAIL, MISSING, USAGE, HteamError
from .paths import PLUGIN_ROOT, TEMPLATES, find_project
from .util import fill, write_atomic

WRAPPER = PLUGIN_ROOT / "scripts" / "codex-run.sh"
N_MAX = 8
HEARTBEAT = 300  # 진행 신호 없음 한도(설계 12장). 시간 제한이 이보다 짧으면 그보다 1초 짧게 둔다
PNG_SIG = b"\x89PNG\r\n\x1a\n"
AR_RE = re.compile(r"[1-9]\d{0,3}:[1-9]\d{0,3}")
KEY_TOLERANCE = 40  # 크로마키: 모서리 색과 채널마다 이만큼 안이면 배경으로 본다
GRACE = 30  # 래퍼 상한 = timeout + 이만큼(버전 조회 10초 + 그룹 정리 5초 + 감시 주기의 여유). HTEAM_IMAGE_GRACE 로 바꾼다
STOP_WAIT = 15  # 상한을 넘긴 래퍼에 TERM 을 보낸 뒤 KILL 까지 기다리는 초(래퍼의 trap 이 codex 그룹을 끝낼 시간)
MAX_SIDE = 16384  # PNG 한 변 상한(IHDR). 넘으면 PNG 로 보지 않는다
MAX_PIXELS = 1 << 26  # 픽셀 수 상한(약 6700만). 크로마키는 RGBA 로 풀어 메모리를 쓴다
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # PNG 색 형식 → 채널 수
DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))  # (x0, y0, dx, dy)


def feature_args(args: list[str]) -> list[str]:
    """실행 인자(codex_args 로 거른 것) 가운데 기능·설정에 영향을 주는 것(`-c`·`--config`, `--enable`·`--disable`)만. 사전
    조회(`codex features list`)가 실행과 같은 기능 상태를 읽게 한다(둘 다 이 인자들을 받는다)."""
    out = [x for _, _, v in browser.config_items(args) for x in ("-c", v)]
    k = 0
    while k < len(args):
        a = args[k]
        if a in ("--enable", "--disable") and k + 1 < len(args):
            out += [a, args[k + 1]]
            k += 1
        elif a.startswith(("--enable=", "--disable=")):
            out.append(a)
        k += 1
    return out


def preflight(args: list[str] = ()) -> None:
    """codex 와 image_generation 기능(설계 12장). 없으면 exit 12. args 는 실행에 쓸 Codex 인자다(기능 조회에 반영한다)."""
    if not shutil.which("codex"):
        raise HteamError("codex_missing", "codex 가 PATH 에 없다", MISSING, "hteam doctor 로 점검한다")
    if not os.access(WRAPPER, os.X_OK):
        raise HteamError("wrapper_missing", f"Codex 래퍼가 없거나 실행할 수 없다: {WRAPPER}", MISSING,
                         "플러그인 설치가 깨졌다. herdr-team 을 다시 설치한다")
    try:
        proc = subprocess.run(["codex", "features", "list", *feature_args(list(args))], capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HteamError("codex_failed", f"codex features list 실패: {exc}", FAIL) from None
    row = next((ln.split() for ln in proc.stdout.splitlines() if ln.split()[:1] == ["image_generation"]), None)
    if proc.returncode != 0 or not row or row[-1] != "true":
        raise HteamError("no_image_generation", "Codex 의 image_generation 기능이 꺼져 있다", MISSING,
                         "사용자가 `codex features enable image_generation` 으로 켠다(시험 생성은 하지 않는다)")


def slug(prompt: str) -> str:
    words = re.findall(r"[a-z0-9]+", prompt.lower())[:5]
    return "-".join(words) or "image"


def run_dir(p, name: str, i: int) -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return base / "herdr-team" / "images" / p.root.name / f"{stamp}-{name}-{i}-{os.getpid()}"


def prompt_text(prompt: str, ar: str | None, transparent: bool, refs: list[str]) -> str:
    return fill((TEMPLATES / "image-prompt.md").read_text(encoding="utf-8"), prompt=prompt.strip(),
                ar=f"가로세로 비율은 {ar} 다." if ar else "",
                transparent=("배경은 투명(알파 채널)이어야 한다. 투명하게 만들 수 없으면 배경 전체를 #00FF00 한 색으로만 "
                             "칠한다(나중에 지운다)." if transparent else ""),
                ref=("첨부한 이미지를 참조한다. 요청에서 바꾸라고 한 것만 바꾸고 구도·색·피사체는 그대로 둔다."
                     if refs else ""))


def split_args(args: list[str]) -> tuple[list[str], list[str]]:
    """(이미지 실행에 넘길 인자, `codex exec` 가 받지 않거나 이미지가 직접 정해서 뺀 인자의 보임 글). 뺀 인자는 부른 쪽이
    결과 warnings 에 남긴다. 읽기 전용 `codex --help`·`codex exec --help`(0.166)로 확인했다: `-a/--ask-for-approval`·
    `--search`·`--no-alt-screen` 은 대화형(`codex`)만 받고 exec 에는 없다(주면 exit 2). `-m/--model` 은 이미지가 `--model` 을
    직접 준다(두 번 주면 어느 쪽인지 모른다). 이 밖에 [agents.codex].args 에서 MCP 서버 정의와 우회 플래그를 뺀다(codex_args)."""
    drop: set[int] = set()
    for start, end, value in browser.config_items(args):
        if browser.key_of(value).startswith("mcp_servers."):
            drop.update(range(start, end))
    shown: list[str] = []
    k = 0
    while k < len(args):
        a = args[k]
        name = a.split("=", 1)[0]
        if name in ("--search", "--no-alt-screen"):
            span = 1
        elif name in ("-a", "--ask-for-approval", "-m", "--model"):
            span = 1 if "=" in a or k + 1 >= len(args) else 2
        elif a.startswith(("-a", "-m")) and not a.startswith("--") and len(a) > 2:
            span = 1  # 붙인 형 -aNEVER·-mX
        else:
            k += 1
            continue
        drop.update(range(k, k + span))
        shown.append(" ".join(args[k:k + span]))
        k += span
    kept = [a for k, a in enumerate(args) if k not in drop and a.split("=", 1)[0] not in config.CODEX_BYPASS]
    return kept, shown


def codex_args(args: list[str]) -> list[str]:
    """[agents.codex].args 에서 이미지 실행에 넘기지 않을 것을 뺀다. MCP 서버 정의(`-c`·`--config` 의 `mcp_servers.…`):
    이미지에 브라우저가 필요 없고 서버 시작(npx)을 이미지마다 치르지 않는다. 샌드박스·승인 우회 플래그: 래퍼가 늘
    붙인다(같은 플래그가 두 번이면 codex exec 가 exit 2 로 끝난다). `-c`·`--config` 는 디스패치·doctor 와 같은 파서
    (browser.config_items: 분리형·붙인 형 모두)로 읽고 키의 앞뒤 공백은 browser.key_of 로 뗀다. exec 가 받지 않는 인자는
    split_args 가 함께 뺀다."""
    return split_args(args)[0]


def size_ok(width: int, height: int) -> bool:
    """IHDR 의 크기 상한(각 변 MAX_SIDE, 픽셀 수 MAX_PIXELS). 넘으면 풀기 전에 그 이미지만 실패로 한다(메모리·시간)."""
    return 0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width * height <= MAX_PIXELS


def rows(width: int, height: int, depth: int, ctype: int, interlace: int) -> list[int] | None:
    """IHDR 로 계산한 풀린 IDAT 의 줄 길이들(필터 바이트 하나를 넣은 길이, Adam7 이면 패스 차례로). 맞지 않는 조합이면 None."""
    if depth not in DEPTHS.get(ctype, ()) or interlace not in (0, 1) or not width or not height or not size_ok(width, height):
        return None
    bits = depth * CHANNELS[ctype]

    def lines(w: int, h: int) -> list[int]:
        return [1 + (w * bits + 7) // 8] * h if w > 0 and h > 0 else []
    if not interlace:
        return lines(width, height)
    return [n for x0, y0, dx, dy in ADAM7 for n in lines((width - x0 + dx - 1) // dx, (height - y0 + dy - 1) // dy)]


def png_info(data: bytes) -> tuple[int, int, int, int] | None:
    """(너비, 높이, 비트 깊이, 색 형식). 서명, 첫 청크 IHDR(13바이트), IDAT 하나 이상, IEND 까지 모든 청크의 길이·CRC 가
    맞고, 색 형식 3 은 IDAT 앞에 PLTE(3바이트 × 1–256)가 있고 0·4 에는 PLTE 가 없으며, 이은 IDAT 가 zlib 으로 풀리고 풀린
    길이가 IHDR 로 계산한 길이(rows)와 같고 줄마다 필터 바이트가 0–4 여야 PNG 다. 아니면 None."""
    if data[:8] != PNG_SIG:
        return None
    pos, head, idat, plte = 8, None, [], None
    while pos + 12 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        end = pos + 12 + length
        if end > len(data):
            return None
        body = data[pos + 8:end - 4]
        if struct.unpack(">I", data[end - 4:end])[0] != zlib.crc32(kind + body) & 0xFFFFFFFF:
            return None
        if head is None:
            if kind != b"IHDR" or length != 13:
                return None
            head = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"PLTE":
            if idat or plte is not None:  # IDAT 뒤의 PLTE, 두 번째 PLTE
                return None
            plte = body
        elif kind == b"IEND":
            break
        pos = end
    else:
        return None
    if not idat:
        return None
    width, height, depth, ctype, method, filtering, interlace = head
    if ctype == 3 and (plte is None or not 3 <= len(plte) <= 768 or len(plte) % 3):
        return None
    if ctype in (0, 4) and plte is not None:
        return None
    lines = rows(width, height, depth, ctype, interlace)
    if lines is None or method or filtering:
        return None
    want = sum(lines)
    unzip = zlib.decompressobj()
    try:
        raw = unzip.decompress(b"".join(idat), want + 1)
    except zlib.error:
        return None
    if len(raw) != want or not unzip.eof:
        return None
    at = 0
    for n in lines:  # 줄마다 첫 바이트가 필터 형식(0–4)
        if raw[at] > 4:
            return None
        at += n
    return width, height, depth, ctype


def _chunks(data: bytes):
    """서명 뒤 청크를 차례로. IEND 에서 멈춘다(그 뒤의 덧붙은 바이트는 png_info 와 같이 보지 않는다)."""
    pos = 8
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        yield kind, data[pos + 8:pos + 8 + length]
        if kind == b"IEND":
            return
        pos += 12 + length


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def read_rgba(data: bytes) -> tuple[int, int, bytearray] | None:
    """8비트·인터레이스 없는 RGB·RGBA PNG → (너비, 높이, RGBA 바이트). 다른 형식이면 None."""
    if data[:8] != PNG_SIG:
        return None
    head, idat = None, []
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            head = head or struct.unpack(">IIBBBBB", body[:13])  # 첫 IHDR 만(png_info 와 같다)
        elif kind == b"IDAT":
            idat.append(body)
    if not head:
        return None
    width, height, depth, ctype, _, _, interlace = head
    if depth != 8 or ctype not in (2, 6) or interlace or not size_ok(width, height):
        return None
    bpp = 4 if ctype == 6 else 3
    stride = width * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None
    if len(raw) < height * (stride + 1):
        return None
    prev = bytearray(stride)
    out = bytearray()
    for y in range(height):
        kind = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if kind == 1:
                line[x] = (line[x] + a) & 0xFF
            elif kind == 2:
                line[x] = (line[x] + b) & 0xFF
            elif kind == 3:
                line[x] = (line[x] + (a + b) // 2) & 0xFF
            elif kind == 4:
                line[x] = (line[x] + _paeth(a, b, c)) & 0xFF
        prev = line
        if bpp == 4:
            out += line
        else:
            for x in range(0, stride, 3):
                out += line[x:x + 3] + b"\xff"
    return width, height, out


def write_rgba(width: int, height: int, rgba: bytearray) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes(rgba[y * width * 4:(y + 1) * width * 4]) for y in range(height))
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def transparency(data: bytes) -> tuple[str, bytes]:
    """--transparent 결과를 맞춘다. (방식, 바이트). "native"(이미 투명한 곳이 있다), "chroma"(모서리 색을 지웠다. 바이트가
    바뀐다), "unsupported"(읽을 수 없는 PNG 형식), "no_key"(네 모서리 색이 달라 배경색을 정하지 못했다)."""
    decoded = read_rgba(data)
    if decoded is None:
        return "unsupported", data
    width, height, rgba = decoded
    if any(rgba[i] < 255 for i in range(3, len(rgba), 4)):
        return "native", data
    corners = [rgba[i:i + 3] for i in (0, (width - 1) * 4, (height - 1) * width * 4, (height * width - 1) * 4)]
    key = corners[0]
    if any(max(abs(c[k] - key[k]) for k in range(3)) > KEY_TOLERANCE for c in corners):
        return "no_key", data
    for i in range(0, len(rgba), 4):
        if max(abs(rgba[i + k] - key[k]) for k in range(3)) <= KEY_TOLERANCE:
            rgba[i + 3] = 0
    return "chroma", write_rgba(width, height, rgba)


def _status(folder: Path) -> dict:
    try:
        data = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _tail(path: Path, lines: int = 5) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-lines:])
    except OSError:
        return ""


def _generated(folder: Path) -> tuple[Path | None, str]:
    """result.txt 마지막 줄의 파일(앞뒤 공백·백틱을 뗀 절대 경로)과, 못 쓰면 그 이유. 일반 파일만 받는다(심볼릭 링크는
    따라가지 않는다)."""
    text = _tail(folder / "result.txt", 1).strip().strip("`").strip()
    path = Path(text) if text else None
    if path is None or not path.is_absolute():
        return None, "결과의 마지막 줄에 이미지 경로가 없다"
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return None, f"결과의 마지막 줄 경로에 파일이 없다: {path}"
    if stat.S_ISLNK(mode):
        return None, f"결과 파일이 심볼릭 링크다(따라가지 않는다): {path}"
    if not stat.S_ISREG(mode):
        return None, f"결과 경로가 일반 파일이 아니다: {path}"
    return path, ""


def _read(src: Path) -> bytes:
    """링크를 따라가지 않고, 막히지 않게(O_NONBLOCK: 검사 뒤 FIFO 로 바뀌어도 열기에서 기다리지 않는다) 열고 fstat 으로
    일반 파일인지 다시 본 뒤 읽는다. 아니면 OSError(그 이미지의 실패)."""
    with os.fdopen(os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise OSError(f"결과 파일이 일반 파일이 아니다(열 때 다시 봤다): {src}")
        return fh.read()


def _to_png(data: bytes, folder: Path, suffix: str) -> bytes | None:
    """PNG 가 아닌 결과를 sips 로 PNG 로 바꾼다(실행 폴더 안에서). sips 가 없거나 못 바꾸면 None."""
    if not shutil.which("sips"):
        return None
    src, dst = folder / f"convert-src{suffix or '.bin'}", folder / "convert.png"
    src.write_bytes(data)
    proc = subprocess.run(["sips", "-s", "format", "png", str(src), "--out", str(dst)], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)
    png = dst.read_bytes() if proc.returncode == 0 and dst.is_file() else b""
    return png if png_info(png) is not None else None


def open_out(folder: Path) -> int:
    """검사한 --out 폴더의 fd(마지막 단계가 링크면 OSError). 게시·임시 파일·정리는 이 fd 기준이다: 실행 중 이름이 링크로
    바뀌어도 이 폴더에 쓴다."""
    return os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _publish(data: bytes, dfd: int, stem: str) -> str:
    """data 를 폴더 fd dfd 안 <stem>.png 로 게시하고 그 이름을 낸다. 이름이 있으면(끊어진 링크 포함) -v2, -v3 …
    덮어쓰지도 링크를 따라가지도 않는다: 같은 폴더의 새 임시 파일(O_EXCL|O_NOFOLLOW)에 다 쓴 뒤 하드 링크를 만든다(이름이
    이미 있으면 link 가 FileExistsError 다). dir_fd 를 받지 않는 플랫폼이면 OSError(그 이미지의 실패)."""
    if not all(f in os.supports_dir_fd for f in (os.open, os.link, os.unlink)):
        raise OSError("이 플랫폼은 dir_fd 를 받지 않아 게시할 수 없다")
    for k in itertools.count():
        tmp = f".{stem}.{os.getpid()}.{k}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666, dir_fd=dfd)
            break
        except FileExistsError:
            continue
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        for n in itertools.count(1):
            name = f"{stem}.png" if n == 1 else f"{stem}-v{n}.png"
            try:
                os.link(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
                return name
            except FileExistsError:
                continue
    finally:
        os.unlink(tmp, dir_fd=dfd)


def _grace() -> int:
    try:
        return max(0, int(os.environ.get("HTEAM_IMAGE_GRACE", GRACE)))
    except ValueError:
        return GRACE


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.communicate(timeout=STOP_WAIT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()


def _run(argv: list[str], limit: int) -> tuple[int | None, str, bool]:
    """래퍼를 limit 초 상한으로 돌린다. (exit, stderr, 상한을 넘겼나). 넘기면 TERM(래퍼의 trap 이 codex 그룹을 끝낸다),
    STOP_WAIT 초 뒤에도 살아 있으면 KILL. 중단(KeyboardInterrupt)도 래퍼를 끝낸 뒤 다시 올린다."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
    try:
        _, err = proc.communicate(timeout=limit)
        return proc.returncode, err, False
    except subprocess.TimeoutExpired:
        _stop(proc)
        return proc.returncode, "", True
    except BaseException:
        _stop(proc)
        raise


def one(p, cfg, prompt: str, *, i: int, out: Path, dfd: int, ar, transparent: bool, refs: list[str], timeout: int,
        extra: list[str] = ()) -> dict:
    """이미지 하나: 실행 폴더, 프롬프트 파일, 래퍼 한 번(상한 timeout + 여유), 결과 검사·게시(out 의 fd dfd 기준).
    extra 는 [agents.codex].args 뒤에 붙일 Codex 인자다(browser.user_off)."""
    name = slug(prompt)
    folder = run_dir(p, name, i)
    folder.mkdir(parents=True, exist_ok=True)
    write_atomic(folder / "prompt.txt", prompt_text(prompt, ar, transparent, refs))
    model, effort = cfg.image_choice()
    argv = [str(WRAPPER), "--profile", "image", "--cwd", str(p.root), "--prompt-file", str(folder / "prompt.txt"),
            "--run-dir", str(folder), "--timeout", str(timeout), "--heartbeat", str(min(HEARTBEAT, timeout - 1))]
    argv += [f"--codex-arg={a}" for a in codex_args(cfg.args("codex")) + list(extra)]  # MCP 정의·우회 플래그는 뺀다
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    for ref in refs:
        argv += ["--image", ref]
    limit = timeout + _grace()
    code, err, hung = _run(argv, limit)
    status = _status(folder)
    item = {"i": i, "run_dir": str(folder), "exit": code, "terminal_event": status.get("terminal_event"),
            "path": None, "warnings": []}
    if hung:
        return {**item, "status": "failed", "reason": f"래퍼가 {limit}초(timeout + 여유) 안에 끝나지 않아 멈췄다",
                "progress": _tail(folder / "progress.log")}
    if code == 12:
        raise HteamError("codex_missing", "codex 가 PATH 에 없다", MISSING, "hteam doctor 로 점검한다")
    if code == 2:
        return {**item, "status": "failed", "reason": f"래퍼 인자 오류: {err.strip()[-300:]}"}
    event = item["terminal_event"]
    if event in ("turn.failed", "error"):
        return {**item, "status": "refused",
                "reason": "Codex 가 거절했거나 턴이 실패했다(자동으로 다시 하지 않는다)",
                "result": _tail(folder / "result.txt", 20), "progress": _tail(folder / "progress.log")}
    src, why = _generated(folder)
    if src is None:
        if event != "turn.completed":
            why = f"codex 가 끝나지 않았다(exit {code}: 10 시간 초과, 11 진행 신호 없음, 130 중단, 1 비정상 종료)"
        return {**item, "status": "failed", "reason": why, "result": _tail(folder / "result.txt", 20),
                "progress": _tail(folder / "progress.log")}
    if event != "turn.completed":
        item["warnings"].append(f"종단 이벤트가 {event or '없음'} 인데 이미지 파일이 있다(exit {code}). 직접 열어 확인한다")
    data = _read(src)
    if png_info(data) is None:
        png = _to_png(data, folder, src.suffix)
        if png is None:
            return {**item, "status": "failed", "source": str(src),
                    "reason": f"결과가 PNG 가 아니고 PNG 로 바꾸지 못했다({src.suffix or '확장자 없음'}"
                              f"{'' if shutil.which('sips') else ', sips 없음'})"}
        data = png
        item["warnings"].append(f"PNG 가 아니라 sips 로 바꿨다({src.suffix or '확장자 없음'})")
    if transparent:
        item["transparent"], data = transparency(data)
        if item["transparent"] in ("unsupported", "no_key"):
            item["warnings"].append("투명 배경을 만들지 못했다(--transparent). 직접 열어 확인한다")
    width, height, _, ctype = png_info(data)
    dst = out / _publish(data, dfd, f"{name}-{i}")
    return {**item, "status": "ok", "path": str(dst), "source": str(src), "width": width, "height": height,
            "alpha": ctype in (4, 6)}


def out_folder(p, out: str) -> Path:
    """--out 의 절대 경로. 링크를 따라 다른 곳에 쓰지 않도록, 프로젝트 안이면 루트 아래 모든 단계, 밖이면 마지막
    폴더가 심볼릭 링크일 때 사용 오류다."""
    folder = Path(os.path.normpath(Path.cwd() / out))
    try:
        parts = folder.relative_to(p.root).parts
        steps = [p.root.joinpath(*parts[:k]) for k in range(1, len(parts) + 1)]
    except ValueError:
        steps = [folder]
    for step in steps:
        if step.is_symlink():
            raise HteamError("usage", f"--out 경로에 심볼릭 링크가 있다(따라가지 않는다): {step}", USAGE,
                             "링크가 아닌 실제 폴더를 준다")
    return folder


def _summary(items: list[dict], folder: Path, warnings: list[str] = ()) -> dict:
    return {"images": items, "count": sum(x["status"] == "ok" for x in items), "out": str(folder),
            "warnings": list(warnings),
            "hint": "Read 로 이미지를 직접 열어 보고 채택한 파일만 커밋한다. 거절·실패는 자동으로 다시 하지 않았다"}


def image(p, prompt: str, *, n: int, out: str, ar: str | None, transparent: bool, refs: list[str],
          timeout: int) -> dict:
    if not prompt.strip():
        raise HteamError("usage", "프롬프트가 비었다", USAGE)
    if not 1 <= n <= N_MAX:
        raise HteamError("usage", f"--n 은 1–{N_MAX} 다", USAGE)
    if ar is not None and not AR_RE.fullmatch(ar):
        raise HteamError("usage", f"--ar 은 w:h 다(예: 16:9): {ar}", USAGE)
    if timeout < 2:
        raise HteamError("usage", "--timeout 은 2초 이상이다", USAGE)
    missing = [r for r in refs if not Path(r).is_file()]
    if missing:
        raise HteamError("usage", f"--ref 파일이 없다: {', '.join(missing)}", USAGE)
    folder = out_folder(p, out)
    cfg = config.load(p)
    args, dropped = split_args(cfg.args("codex"))
    preflight(args)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        dfd = open_out(folder)
    except OSError as exc:
        raise HteamError("usage", f"--out 폴더를 만들거나 열 수 없다: {exc}", USAGE) from None
    try:
        extra, warning = browser.user_off(p.root, args)  # 사용자 chrome-devtools 를 이미지 실행에서만 끈다(조회 실패·프로필이면 경고만)
        notes = [warning] if warning else []
        if dropped:
            notes.append("이미지 실행(codex exec)이 받지 않거나 이미지가 직접 정하는 인자를 뺐다: " + ", ".join(dropped))
        refs = [str(Path(r).resolve()) for r in refs]
        items: list[dict] = []
        for i in range(1, n + 1):
            try:
                items.append(one(p, cfg, prompt, i=i, out=folder, dfd=dfd, ar=ar, transparent=transparent, refs=refs,
                                 timeout=timeout, extra=extra))
            except KeyboardInterrupt:
                raise HteamError("image_interrupted", f"중단했다(이미지 {n}개 가운데 {i - 1}개까지 끝냈다)", FAIL,
                                 "images 에 끝낸 것까지 있다. 남은 것은 다시 부른다",
                                 data=_summary(items, folder, notes)) from None
            except HteamError as exc:  # 실행 중 codex 가 없어졌다 등: 그 오류 그대로 멈추되 지금까지의 결과를 붙인다
                exc.data = {**exc.data, **_summary(items, folder, notes)}
                raise
            except (OSError, subprocess.SubprocessError, ValueError, zlib.error, struct.error, MemoryError,
                    OverflowError) as exc:
                items.append({"i": i, "status": "failed", "path": None, "warnings": [],
                              "reason": f"이미지 처리 중 오류: {type(exc).__name__}: {exc}"})
    finally:
        os.close(dfd)
    result = _summary(items, folder, notes)
    if result["count"] < n:
        raise HteamError("image_failed", f"이미지 {n}개 가운데 {n - result['count']}개를 만들지 못했다", FAIL,
                         "items 의 reason·progress 를 본다. 거절이면 프롬프트를 바꾼다. 시간 초과·멈춤은 한 번 다시 해 볼 수 있다",
                         data=result)
    return result


def _cmd(args) -> dict:
    p = find_project(args.root)
    return image(p, " ".join(args.prompt), n=args.n, out=args.out, ar=args.ar, transparent=args.transparent,
                 refs=list(args.ref or []), timeout=args.timeout)


def register(sub) -> None:
    s = sub.add_parser("image")
    s.add_argument("--n", type=int, default=1, help=f"1–{N_MAX}(기본 1)")
    s.add_argument("--out", default="generated", help="저장 폴더(기본 ./generated/)")
    s.add_argument("--ar", help="가로세로 비율 w:h")
    s.add_argument("--transparent", action="store_true")
    s.add_argument("--ref", action="append", metavar="FILE", help="참조 이미지(여러 번)")
    s.add_argument("--timeout", type=int, default=900, help="이미지 하나의 시간 제한 초(기본 900)")
    s.add_argument("prompt", nargs="+")
    s.set_defaults(func=_cmd)
