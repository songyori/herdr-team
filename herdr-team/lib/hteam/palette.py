"""팔레트 카탈로그(설계 11.10, 13단계): 플러그인의 `lib/hteam/data/`(palettes.json·fonts-ko.json·overused.json)를 읽고 검사한다.

배정(`hteam palette deal`)·내용 검사(lint, 11.13)·획일도 측정(15.5)이 같이 읽는다. 읽기만 한다. 카탈로그를 읽지 못하거나
스키마가 틀리면 HteamError("catalog_invalid", exit 1). NaN·무한대 수는 받지 않는다.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from . import color
from .errors import FAIL, HteamError

DATA = Path(__file__).with_name("data")
BUCKET = 30  # hue 칸 너비(도). 칸 k 는 [30k, 30k+30)
EXCLUDED = (240, 300)  # 뽑지 않는 hue(파랑·남색·보라): 칸 8·9
ALLOWED = tuple(k for k in range(360 // BUCKET) if not EXCLUDED[0] <= k * BUCKET < EXCLUDED[1])
CHROMATIC_C = 0.03  # 강조 C 가 이보다 작으면 무채색이라 칸에 넣지 않는다(획일도 측정의 유효 강조와 같다)
FONT_CLASSES = ("돋움", "부리", "표시", "손글씨")
BODY_CLASSES = ("돋움", "부리")  # 본문 글꼴로 배정하는 계열
HUE_TOLERANCE = 0.5  # 팔레트의 hue 와 accent 의 OKLCH h 가 이보다 멀면 깨진 카탈로그다(들여오기는 h 를 소수 첫째 자리로 적는다)
_HEX6 = re.compile(r"#[0-9a-f]{6}")


def _invalid(why: str) -> HteamError:
    return HteamError("catalog_invalid", f"카탈로그가 깨졌다: {why}", FAIL,
                      "플러그인을 다시 설치한다. 그래도 같으면 저장소의 scripts/import-palettes.py --check 로 확인한다")


def _no_constant(name: str):
    raise ValueError(f"JSON 에 {name} 이 있다")


def _read(name: str):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"), parse_constant=_no_constant)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise _invalid(f"{name} 를 읽지 못했다: {exc}") from None


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _real(value) -> bool:
    """유한한 수인가(참·거짓은 아니다). float 로 바꿀 수 없을 만큼 큰 JSON 정수(10**309)도 아니다(OverflowError)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def bucket(hue: float) -> int:
    """hue(도)가 드는 칸(0–11)."""
    return int((hue % 360) // BUCKET) % (360 // BUCKET)


def _palette_problem(p) -> str | None:
    if not isinstance(p, dict):
        return "객체가 아니다"
    for key in ("id", "source", "license", "accent", "mood"):
        if not _text(p.get(key)):
            return f"{key} 가 빈 글이다"
    if color.parse(p["accent"]) is None:
        return f"accent 를 색으로 읽지 못했다: {p['accent']!r}"
    for key in ("bg", "ink"):
        if p.get(key) is not None and (not isinstance(p[key], str) or color.parse(p[key]) is None):
            return f"{key} 는 null 이나 색이다"
    if not _real(p.get("hue")) or not 0 <= p["hue"] < 360:
        return "hue 는 0 이상 360 미만의 수다"
    lch = color.parse(p["accent"])
    if lch[1] >= color.ACHROMATIC_C and color.hue_distance(lch[2], p["hue"]) > HUE_TOLERANCE:
        return f"hue {p['hue']} 가 accent 의 OKLCH h {lch[2]:.1f} 와 다르다(칸이 틀린다)"
    return None


def chromatic(p: dict) -> bool:
    """강조가 무채색이 아닌가(C ≥ CHROMATIC_C)."""
    return color.parse(p["accent"])[1] >= CHROMATIC_C


def load_palettes() -> list[dict]:
    """palettes.json 의 팔레트 목록. 항목의 hue 가 accent 의 OKLCH h 와 HUE_TOLERANCE 안이어야 하고(유채색일 때), 무채색이 아닌
    팔레트가 2개보다 적어도 catalog_invalid."""
    data = _read("palettes.json")
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list) or not isinstance(data.get("palettes"), list):
        raise _invalid("palettes.json 은 sources·palettes 목록을 가진 객체다")
    seen: set[str] = set()
    for i, p in enumerate(data["palettes"]):
        why = _palette_problem(p)
        if why is None and p["id"] in seen:
            why = f"id {p['id']} 가 겹친다"
        if why:
            raise _invalid(f"palettes.json 의 palettes[{i}]: {why}")
        seen.add(p["id"])
    if sum(1 for p in data["palettes"] if chromatic(p)) < 2:
        raise _invalid("palettes.json 에 무채색이 아닌 팔레트가 2개보다 적다")
    return data["palettes"]


def _font_problem(f) -> str | None:
    if not isinstance(f, dict):
        return "객체가 아니다"
    for key in ("id", "name", "license", "license_url", "source_url", "weights"):
        if not _text(f.get(key)):
            return f"{key} 가 빈 글이다"
    if f.get("class") not in FONT_CLASSES:
        return f"class 는 {'·'.join(FONT_CLASSES)} 가운데 하나다"
    if not all(isinstance(f.get(key), bool) for key in ("variable", "deal", "verified")):
        return "variable·deal·verified 는 참·거짓이다"
    if "reserved_name" not in f or not (f["reserved_name"] is None or _text(f["reserved_name"])):
        return "reserved_name 은 null 이나 글이다(OFL 의 예약 이름)"
    if f["deal"] and not (f["verified"] and f["license"].startswith("OFL") and f["class"] in BODY_CLASSES):
        return "배정 대상(deal: true)은 라이선스 원문을 확인한(verified) OFL 본문 글꼴(돋움·부리)이다"
    return None


def load_fonts() -> list[dict]:
    """fonts-ko.json 의 글꼴 목록. 항목마다 verified·reserved_name 이 있고, 배정 대상(deal: true)은 확인한 OFL 본문 글꼴이고
    과용 글꼴(overused.json, font_key 로 견준다)이 아니며 3개 이상이다. 아니면 catalog_invalid."""
    data = _read("fonts-ko.json")
    if not isinstance(data, list):
        raise _invalid("fonts-ko.json 은 목록이다")
    seen: set[str] = set()
    for i, f in enumerate(data):
        why = _font_problem(f)
        if why is None and f["id"] in seen:
            why = f"id {f['id']} 가 겹친다"
        if why:
            raise _invalid(f"fonts-ko.json[{i}]: {why}")
        seen.add(f["id"])
    over = load_overused()
    overused = {font_key(n) for n in over["fonts_ko"] + over["fonts_latin"]}
    for i, f in enumerate(data):
        if f["deal"] and font_key(f["name"]) in overused:
            raise _invalid(f"fonts-ko.json[{i}]: 배정 대상(deal: true) {f['name']} 이 과용 글꼴이다(overused.json)")
    if sum(1 for f in data if f["deal"]) < 3:
        raise _invalid("fonts-ko.json 에 배정 대상(deal: true) 글꼴이 3개보다 적다")
    return data


def load_overused() -> dict:
    """overused.json: colors([{hex, name}]), tailwind_ramp([hex]), fonts_ko·fonts_latin([이름]). hex 는 소문자 6자리다."""
    data = _read("overused.json")
    ok = (isinstance(data, dict) and isinstance(data.get("colors"), list)
          and all(isinstance(c, dict) and isinstance(c.get("hex"), str) and _HEX6.fullmatch(c["hex"]) and _text(c.get("name"))
                  for c in data["colors"])
          and isinstance(data.get("tailwind_ramp"), list)
          and all(isinstance(h, str) and _HEX6.fullmatch(h) for h in data["tailwind_ramp"])
          and all(isinstance(data.get(k), list) and data[k] and all(_text(x) for x in data[k])
                  for k in ("fonts_ko", "fonts_latin")))
    if not ok:
        raise _invalid("overused.json 은 colors·tailwind_ramp·fonts_ko·fonts_latin 을 가진 객체다")
    return data


def font_key(name: str) -> str:
    """글꼴 이름 비교 열쇠(설계 11.10): 소문자, 공백·따옴표 없음, 끝의 variable·vf 를 뗀다."""
    return re.sub(r"(variable|vf)$", "", re.sub(r"[\s\"'`]", "", name).lower())


def hangul_font(stack: list[str], latin: set[str]) -> str | None:
    """글꼴 스택에서 한글을 그리는 글꼴: 라틴 과용 글꼴(latin, font_key 집합)이 아닌 첫 글꼴. 없으면 None(시스템 글꼴)."""
    return next((name for name in stack if font_key(name) and font_key(name) not in latin), None)
