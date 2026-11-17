"""색 글을 OKLCH 로 바꾼다(설계 11.10, 13단계). 표준 라이브러리만 쓴다. sRGB → 선형 → OKLab 은 Björn Ottosson 의 행렬이다.
lint(11.13)·deal 시험·획일도 측정(15.5)이 같이 쓴다. HSL 기준 lint.hue_family(그라디언트 검사)는 바꾸지 않는다."""
from __future__ import annotations

import colorsys
import math
import re

LCH = tuple[float, float, float]  # (L 0–1, C, h 0–360). C 가 ACHROMATIC_C 보다 작으면 h 는 0.0
ACHROMATIC_C = 1e-4
_HEX = re.compile(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_FUNC = re.compile(r"(rgba?|hsla?|oklch)\(\s*([^()]*)\)", re.I)


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _hue(c: float, h: float) -> float:
    return h % 360 if c >= ACHROMATIC_C else 0.0


def from_srgb(r: float, g: float, b: float) -> LCH:
    """sRGB(각 0–1, 범위 밖은 자른다)의 OKLCH."""
    r, g, b = (_linear(min(max(x, 0.0), 1.0)) for x in (r, g, b))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    lightness = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    chroma = math.hypot(a, bb)
    return (lightness, chroma, _hue(chroma, math.degrees(math.atan2(bb, a))))


def from_hex(text: str) -> LCH | None:
    """`#rgb`·`#rgba`·`#rrggbb`·`#rrggbbaa`(# 없어도 된다, 알파는 버린다)."""
    m = _HEX.fullmatch(text.strip())
    if not m:
        return None
    digits = m.group(1)
    if len(digits) in (3, 4):
        digits = "".join(ch * 2 for ch in digits[:3])
    return from_srgb(*(int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def _parts(args: str) -> list[str]:
    return [x for x in re.split(r"[\s,/]+", args.strip()) if x]


def _num(text: str) -> float:
    """수 글 하나. NaN·무한대는 ValueError(색으로 받지 않는다)."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _angle(text: str) -> float:
    return _num(text.lower().removesuffix("deg"))


def parse(text: str) -> LCH | None:
    """색 글 하나(hex, `rgb()`·`rgba()`, `hsl()`·`hsla()`, `oklch()`)의 OKLCH. 못 읽거나 NaN·무한대가 섞이면 None."""
    lch = _parse(text)
    return lch if lch is not None and all(math.isfinite(x) for x in lch) else None


def _parse(text: str) -> LCH | None:
    t = text.strip()
    if t.startswith("#"):
        return from_hex(t)
    m = _FUNC.fullmatch(t)
    if not m:
        return None
    name, args = m.group(1).lower(), _parts(m.group(2))
    if len(args) not in (3, 4):
        return None
    try:
        if len(args) == 4:  # 알파(수 또는 %)는 유한해야 하고 버린다
            _num(args[3][:-1] if args[3].endswith("%") else args[3])
        if name.startswith("rgb"):
            return from_srgb(*(_num(x[:-1]) / 100 if x.endswith("%") else _num(x) / 255 for x in args[:3]))
        if name.startswith("hsl"):
            h = _angle(args[0])
            s, l = (min(max(_num(x.rstrip("%")) / 100, 0.0), 1.0) for x in args[1:3])  # CSS: 0–1 로 자른다
            return from_srgb(*colorsys.hls_to_rgb((h % 360) / 360, l, s))
        lightness = _num(args[0][:-1]) / 100 if args[0].endswith("%") else _num(args[0])
        chroma = _num(args[1][:-1]) / 100 * 0.4 if args[1].endswith("%") else _num(args[1])
        h = 0.0 if args[2].lower() == "none" else _angle(args[2])
        lightness, chroma = min(max(lightness, 0.0), 1.0), max(chroma, 0.0)
        return (lightness, chroma, _hue(chroma, h))
    except ValueError:
        return None


def hue_distance(a: float, b: float) -> float:
    """두 hue 의 원형 거리(0–180)."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def oklab(lch: LCH) -> tuple[float, float, float]:
    lightness, chroma, h = lch
    r = math.radians(h)
    return (lightness, chroma * math.cos(r), chroma * math.sin(r))


def delta(x: LCH, y: LCH) -> float:
    """두 색의 OKLab 유클리드 거리. 0.02 아래면 눈으로 거의 같다(획일도 측정의 과용 색 일치)."""
    return math.dist(oklab(x), oklab(y))
