"""팔레트 카탈로그(설계 11.10, 13단계): 플러그인의 `lib/hteam/data/`(palettes.json·fonts-ko.json·overused.json)를 읽고 검사한다.

배정(`hteam palette deal`)·내용 검사(lint, 11.13)·획일도 측정(15.5)이 같이 읽는다. 읽기만 한다. 카탈로그를 읽지 못하거나
스키마가 틀리면 HteamError("catalog_invalid", exit 1). NaN·무한대 수는 받지 않는다.
"""
from __future__ import annotations

import functools
import hashlib
import itertools
import json
import math
import re
from pathlib import Path

from . import color
from .errors import FAIL, USAGE, HteamError

DATA = Path(__file__).with_name("data")
BUCKET = 30  # hue 칸 너비(도). 칸 k 는 [30k, 30k+30)
EXCLUDED = (240, 300)  # 뽑지 않는 hue(파랑·남색·보라): 칸 8·9
ALLOWED = tuple(k for k in range(360 // BUCKET) if not EXCLUDED[0] <= k * BUCKET < EXCLUDED[1])
CHROMATIC_C = 0.03  # 강조 C 가 이보다 작으면 무채색이라 칸에 넣지 않는다(획일도 측정의 유효 강조와 같다)
FONT_CLASSES = ("돋움", "부리", "표시", "손글씨")
BODY_CLASSES = ("돋움", "부리")  # 본문 글꼴로 배정하는 계열
HUE_TOLERANCE = 0.5  # 팔레트의 hue 와 accent 의 OKLCH h 가 이보다 멀면 깨진 카탈로그다(들여오기는 h 를 소수 첫째 자리로 적는다)
_HEX6 = re.compile(r"#[0-9a-f]{6}")
_TASK = re.compile(r"T-\d{3,}")


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


# --- 배정(hteam palette deal, 설계 11.10) ---

MIN_GAP = 3  # A·B·C 칸 사이 원형 거리(칸 가운데 사이 90°)
POSTURES = ("절제", "몰입", "전면", "흠뻑")
SLOTS = "ABC"
FIT_ROUNDS = 500  # 집합 가중치의 반복 비례 맞춤 상한
FIT_TOL = 1e-12  # 칸마다 확률이 목표와 이만큼 안이면 멈춘다


class Draw:
    """시드 글에서 정수를 차례로 뽑는다: SHA-256(<시드 글>:<차례 번호>) 앞 8바이트, 거부 표집(치우침 없음).
    random 모듈을 쓰지 않는다(Python 판마다 결과가 달라질 수 있다)."""

    def __init__(self, seed: str):
        self.seed = seed
        self.count = 0

    def below(self, n: int) -> int:
        """0 이상 n 미만의 정수 하나."""
        if n <= 0:
            raise ValueError("n 은 1 이상이다")
        limit = (1 << 64) - (1 << 64) % n
        while True:
            digest = hashlib.sha256(f"{self.seed}:{self.count}".encode("utf-8")).digest()
            self.count += 1
            value = int.from_bytes(digest[:8], "big")
            if value < limit:
                return value % n

    def pick(self, items: list):
        return items[self.below(len(items))]

    def fraction(self) -> float:
        """0 이상 1 미만의 수 하나(다이제스트 앞 8바이트의 위 53비트)."""
        digest = hashlib.sha256(f"{self.seed}:{self.count}".encode("utf-8")).digest()
        self.count += 1
        return (int.from_bytes(digest[:8], "big") >> 11) / (1 << 53)


def gap(a: int, b: int) -> int:
    """두 칸의 원형 거리(0–6)."""
    d = abs(a - b) % 12
    return min(d, 12 - d)


def _apart(ks) -> bool:
    return all(gap(a, b) >= MIN_GAP for a, b in itertools.combinations(ks, 2))


def bucket_sets() -> list[tuple[int, int, int]]:
    """허용 칸에서 서로 MIN_GAP 이상 떨어진 칸 셋의 집합(오름차순 튜플, 사전 차례). 20개다."""
    return [s for s in itertools.combinations(ALLOWED, 3) if _apart(s)]


def marginals(weights: list[float]) -> dict[int, float]:
    """집합 가중치에서 칸마다 뽑힐 확률(math.fsum: 정확히 반올림한 합이라 Python 판마다 같다)."""
    return {k: math.fsum(w for w, s in zip(weights, bucket_sets()) if k in s) for k in ALLOWED}


@functools.lru_cache(maxsize=None)
def set_weights() -> tuple[float, ...]:
    """bucket_sets 차례의 가중치(합 1). 칸마다 뽑힐 확률이 3/len(ALLOWED)(0.3)가 되게 반복 비례 맞춤으로 정한다: 칸마다
    차례로 그 칸이 든 집합은 목표/지금, 들지 않은 집합은 (1−목표)/(1−지금)을 곱하고, 한 바퀴마다 합을 1로 맞춘다. 칸마다
    확률이 목표와 FIT_TOL 안이거나 FIT_ROUNDS 바퀴면 멈춘다. 합은 모두 math.fsum 이다(내장 sum 은 Python 3.12 에서 합하는 방법이
    바뀌어 가중치가 판마다 달라진다). 곱셈·나눗셈은 IEEE 754 그대로라 결정적이다. 집합을 고르게 뽑으면 빈칸 옆 칸이 치우친다
    (설계 11.10)."""
    sets = bucket_sets()
    target = 3 / len(ALLOWED)
    weights = [1 / len(sets)] * len(sets)
    for _ in range(FIT_ROUNDS):
        for k in ALLOWED:
            now = math.fsum(w for w, s in zip(weights, sets) if k in s)
            weights = [w * (target / now if k in s else (1 - target) / (1 - now)) for w, s in zip(weights, sets)]
        total = math.fsum(weights)
        weights = [w / total for w in weights]
        if max(abs(m - target) for m in marginals(weights).values()) < FIT_TOL:
            break
    return tuple(weights)


@functools.lru_cache(maxsize=None)
def cumulative() -> tuple[float, ...]:
    """set_weights 의 누적 경계. i 번째는 앞 i+1 개 가중치의 math.fsum 이다(Python 판마다 같다)."""
    weights = set_weights()
    return tuple(math.fsum(weights[:i + 1]) for i in range(len(weights)))


def brand_pairs(first: int) -> list[tuple[int, int]]:
    """A 를 칸 first 로 고정할 때(240–300° 칸이어도 된다) B·C 가 될 허용 칸 쌍(오름차순, 사전 차례)."""
    return [(b, c) for b, c in itertools.combinations(ALLOWED, 2) if _apart((first, b, c))]


def pick_buckets(draw: Draw, first: int | None = None) -> tuple[int, int, int]:
    """A·B·C 칸. first 가 없으면 set_weights 로 집합 하나(53비트 수를 누적 경계 cumulative() 와 차례로 견준다)를 고른 뒤 여섯
    차례 가운데 하나를 고르게 고른다. first 가 있으면 A = first, B·C 는 brand_pairs 가운데 하나를 고르게 고르고 차례를 고르게
    정한다."""
    if first is None:
        u = draw.fraction()
        sets = bucket_sets()
        chosen = next((s for s, edge in zip(sets, cumulative()) if u < edge), sets[-1])  # 경계가 1 보다 작으면 마지막 집합
        return draw.pick(list(itertools.permutations(chosen)))
    b, c = draw.pick(brand_pairs(first))
    return (first, b, c) if draw.below(2) == 0 else (first, c, b)


def _show(p: dict, near: bool) -> dict:
    out = {k: p.get(k) for k in ("id", "source", "license", "accent", "bg", "ink", "mood")}
    if near:
        out["near"] = True
    return out


def _candidates(k: int, palettes: list[dict], draw: Draw) -> list[dict]:
    """칸 k 의 팔레트 후보 2개(서로 다른 것). 칸 안의 것을 고르게 뽑고, 모자라면 칸 가운데 hue 에서 가까운 차례로(같으면 id
    차례) 다른 칸의 것을 near 로 채운다."""
    inside = [p for p in palettes if bucket(p["hue"]) == k]
    chosen = []
    while inside and len(chosen) < 2:
        chosen.append(_show(inside.pop(draw.below(len(inside))), False))
    center = k * BUCKET + BUCKET / 2
    outside = sorted((p for p in palettes if bucket(p["hue"]) != k),
                     key=lambda p: (color.hue_distance(p["hue"], center), p["id"]))
    for p in outside[:2 - len(chosen)]:
        chosen.append(_show(p, True))
    return chosen


def deal(seed: str, brand_hue: float | None = None, turn: int = 0) -> dict:
    """배정(설계 11.10 의 출력 JSON 과 같은 dict). 같은 seed·brand_hue 면 늘 같다. 뽑는 차례: 칸(pick_buckets) → 자세 →
    칸마다 팔레트 후보(A·B·C) → 본문 글꼴 셋. brand_hue 를 주면 A 는 그 hue 의 칸이고 팔레트 후보를 두지 않는다."""
    palettes = [p for p in load_palettes() if chromatic(p)]
    fonts = [f for f in load_fonts() if f["deal"]]
    draw = Draw(seed)
    first = None if brand_hue is None else bucket(brand_hue)
    ks = pick_buckets(draw, first)
    postures = list(POSTURES)
    chosen_postures = [postures.pop(draw.below(len(postures))) for _ in SLOTS]
    picks = [[] if first is not None and i == 0 else _candidates(k, palettes, draw) for i, k in enumerate(ks)]
    chosen_fonts = [fonts.pop(draw.below(len(fonts))) for _ in SLOTS]
    slots = [{"slot": name, "hue": [k * BUCKET, k * BUCKET + BUCKET], "posture": posture, "palettes": pick,
              "body_font": {"id": f["id"], "name": f["name"], "class": f["class"], "license": f["license"],
                            "url": f["source_url"]}}
             for name, k, posture, pick, f in zip(SLOTS, ks, chosen_postures, picks, chosen_fonts)]
    return {"seed": seed, "turn": turn, "brand_hue": brand_hue, "excluded_hue": list(EXCLUDED), "slots": slots}


def _cmd_deal(args) -> dict:
    if not _TASK.fullmatch(args.task):
        raise HteamError("usage", f"태스크 ID 는 T- 와 숫자 3자리 이상이다: {args.task!r}", USAGE)
    if args.turn < 0:
        raise HteamError("usage", f"--turn 은 0 이상이다: {args.turn}", USAGE)
    brand = args.brand_hue
    if brand is not None and not (math.isfinite(brand) and 0 <= brand < 360):
        raise HteamError("usage", f"--brand-hue 는 0 이상 360 미만의 수다: {brand}", USAGE)
    if args.seed is not None:
        if not args.seed.strip():
            raise HteamError("usage", "--seed 가 빈 글이다", USAGE)
        seed = args.seed
    else:
        from .paths import find_project  # --seed 를 주면 프로젝트 밖에서도 된다(시험·획일도 측정)
        seed = f"{find_project(args.root).root.name}:{args.task}:{args.turn}"
    return deal(seed, brand, args.turn)


def _hue_arg(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise HteamError("usage", f"--brand-hue 는 수다: {text!r}", USAGE) from None


def register(sub) -> None:
    palette = sub.add_parser("palette")
    psub = palette.add_subparsers(dest="palette_cmd", required=True, parser_class=palette.__class__)
    d = psub.add_parser("deal")
    d.add_argument("--task", required=True)
    d.add_argument("--turn", type=int, default=0)
    d.add_argument("--seed")
    d.add_argument("--brand-hue", type=_hue_arg)
    d.set_defaults(func=_cmd_deal)
