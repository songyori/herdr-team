#!/usr/bin/env python3
"""팔레트·과용 색 카탈로그 들여오기(설계 11.10, 13단계). 저장소 개발용이고 플러그인에 넣지 않는다.

  python3 scripts/import-palettes.py          # 고정한 커밋의 원본을 받아 herdr-team/lib/hteam/data/ 의 세 파일을 쓴다
  python3 scripts/import-palettes.py --check  # 받은 원본으로 만든 글이 저장소 파일과 같은지만 본다(쓰지 않는다)

원본은 raw.githubusercontent.com 의 고정한 커밋에서 받는다. 받은 바이트의 SHA-256 이 SOURCES 의 값과 다르면 아무것도 쓰지
않고 멈춘다. 형식만 바꾼다(LICENSES.md 의 "바꾼 점"). 같은 원본이면 늘 같은 글이 나온다(날짜도 상수다). fonts-ko.json 은
손으로 고른 목록이라 이 스크립트가 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "herdr-team" / "lib" / "hteam" / "data"
sys.path.insert(0, str(REPO / "herdr-team" / "lib"))
from hteam import color  # noqa: E402

DATE = "2026-11-18"  # 들여온 날(다시 돌려도 같은 파일이 나오게 상수로 둔다)
RAW = "https://raw.githubusercontent.com"
# 출처마다 저장소, 커밋, 파일과 그 SHA-256. 커밋을 바꾸면 SHA-256 도 새로 적는다.
SOURCES = {
    "taste-skill": {"repo": "https://github.com/Leonxlnx/taste-skill", "commit": "f6b76575f949707b4e3c37cd86cb44b0b98643e8",
                    "license": "MIT", "data": "skills/taste-skill/library/palettes.json",
                    "files": {"skills/taste-skill/library/palettes.json":
                              "96d594648249b2dff17addcd0e2965b0eee0cf2815ae68542add82a87d856d6d",
                              "LICENSE": "4575a543ab88dad12ccea7d97e563d0bce5b448b06072e65d3264497dad326df"}},
    "impeccable": {"repo": "https://github.com/pbakaus/impeccable", "commit": "d41d9860b0094dcb68030657da63461212835aaa",
                   "license": "Apache-2.0", "data": "crates/context/src/palette_data.rs",
                   "files": {"crates/context/src/palette_data.rs":
                             "9c5a828a4160e7a812e1c7b66ce678d67f9ad9c3481c9671424ebf1968c25f55",
                             "LICENSE": "02bb8c3b4e70190e3986c0404ad2fd8d639b4f534252d82379cc1b502b6d1812",
                             "NOTICE.md": "c60a093c2845fd9fb82f9c6f742ece31f379f8190b535309d32d66c45ccffdcb"}},
    "tailwindcss": {"repo": "https://github.com/tailwindlabs/tailwindcss", "commit": "4f9f603e12b51cc53b8a09c7739b8f88c8eb87eb",
                    "license": "MIT", "data": "src/public/colors.js", "tag": "v3.4.17",
                    "files": {"src/public/colors.js": "28907aa147f4ca19fb3c07bd21e88aac459df8a533e629530eb8b384bcae760d",
                              "LICENSE": "60e0b68c0f35c078eef3a5d29419d0b03ff84ec1df9c3f9d6e39a519a5ae7985"}},
}
# 과용 색(설계 11.10): Tailwind v3 이름과 그 밖의 값. Tailwind v4 는 색을 oklch 로 정의해 hex 일치 검사에 맞지 않아 넣지 않는다
# (주 강조 hue 검사가 h 240–300° 로 본다).
TAILWIND_OVERUSED = ([f"{f}-{s}" for f in ("blue", "indigo", "violet", "purple") for s in (500, 600, 700, 800, 900)]
                     + ["sky-500", "emerald-500"] + [f"{f}-{s}" for f in ("slate", "gray", "zinc") for s in (50, 500, 900)])
OTHER_OVERUSED = (("#0d6efd", "Bootstrap 5 primary"), ("#007aff", "iOS systemBlue"), ("#6750a4", "Material 3 primary"),
                  ("#6200ee", "Material 2 primary"), ("#f4f1ea", "Anthropic 군집 크림"), ("#d97757", "Anthropic 군집 테라코타"))
# 과용 글꼴(설계 11.10). fonts_ko 끝의 일반 이름(sans-serif 등)은 시스템 글꼴이다(스택에 한글 글꼴이 없을 때 그린다).
FONTS_LATIN = ("Inter", "Roboto", "Open Sans", "Poppins", "Montserrat", "DM Sans", "Plus Jakarta Sans", "Space Grotesk",
               "Geist", "Fraunces")
FONTS_KO = ("Pretendard", "Noto Sans KR", "Nanum Gothic", "Apple SD Gothic Neo", "Malgun Gothic", "맑은 고딕", "system-ui",
            "-apple-system", "BlinkMacSystemFont", "ui-sans-serif", "sans-serif", "ui-serif", "serif")


def fetch(source: str, path: str, opener=urllib.request.urlopen) -> str:
    """SOURCES[source] 의 고정 커밋에서 path 를 받아 SHA-256 을 맞춰 본 뒤 UTF-8 글로. 다르면 SystemExit."""
    src = SOURCES[source]
    owner_name = src["repo"].removeprefix("https://github.com/")
    url = f"{RAW}/{owner_name}/{src['commit']}/{path}"
    with opener(url, timeout=60) as resp:
        body = resp.read()
    got = hashlib.sha256(body).hexdigest()
    if got != src["files"][path]:
        raise SystemExit(f"{url} 의 SHA-256 이 다르다({got}). 아무것도 쓰지 않았다")
    return body.decode("utf-8")


def oklch_text(lch: tuple[float, float, float]) -> str:
    """OKLCH 글(L·C 소수 셋째, h 첫째 자리). 반올림한 h 가 360 이면 0 이다."""
    lightness, chroma, h = lch
    return f"oklch({lightness:.3f} {chroma:.3f} {round(h, 1) % 360:.1f})"


def parse_taste(text: str) -> list[dict]:
    """taste-skill palettes.json: 항목마다 id·name·note·accent·bg·ink 가 글이다. 아니면 ValueError."""
    data = json.loads(text)
    if not isinstance(data, list) or not data:
        raise ValueError("taste-skill: 목록이 아니다")
    for i, p in enumerate(data):
        if not isinstance(p, dict) or not all(isinstance(p.get(k), str) and p[k].strip()
                                               for k in ("id", "name", "note", "accent", "bg", "ink")):
            raise ValueError(f"taste-skill[{i}]: id·name·note·accent·bg·ink 가 글이 아니다")
        for k in ("accent", "bg", "ink"):
            if color.from_hex(p[k]) is None or not p[k].startswith("#"):
                raise ValueError(f"taste-skill[{i}].{k}: hex 가 아니다: {p[k]!r}")
    return data


_STR = r'"((?:[^"\\]|\\.)*)"'
_NUM = r"(\d+(?:\.\d+)?)"
_SEED = re.compile(rf"\s*Seed \{{ id: {_STR}, l: {_NUM}, c: {_NUM}, h: {_NUM}, mood: {_STR}, strategy: {_STR} \}},")
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "'": "'"}


def _unescape(text: str) -> str:
    """Rust 문자열의 이스케이프(\\" \\\\ \\n \\t \\'). 다른 이스케이프는 ValueError(조용히 바꾸지 않는다)."""
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            nxt = text[i + 1:i + 2]
            if nxt not in _ESCAPES:
                raise ValueError(f"impeccable: 모르는 이스케이프 \\{nxt}")
            out.append(_ESCAPES[nxt])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_impeccable(text: str) -> list[dict]:
    """impeccable palette_data.rs 의 `SEEDS` 배열. 배열 안의 빈 줄이 아닌 줄은 모두 Seed 한 줄이어야 한다(아니면 ValueError).
    L·C·h 는 글 그대로 둔다."""
    start = text.find("pub const SEEDS: &[Seed] = &[\n")
    end = text.find("\n];", start)
    if start < 0 or end < 0:
        raise ValueError("impeccable: SEEDS 배열을 찾지 못했다")
    seeds = []
    for line in text[text.index("\n", start) + 1:end].split("\n"):
        if not line.strip():
            continue
        m = _SEED.fullmatch(line)
        if not m:
            raise ValueError(f"impeccable: Seed 줄이 아니다: {line[:80]!r}")
        sid, lightness, chroma, h, mood, _strategy = m.groups()
        seeds.append({"id": _unescape(sid), "l": lightness, "c": chroma, "h": h, "mood": _unescape(mood)})
    if not seeds:
        raise ValueError("impeccable: SEEDS 가 비었다")
    return seeds


_FAMILY = re.compile(r"  (\w+): \{")
_SHADE = re.compile(r"    (\d+): '(#[0-9a-f]{6})',")


def parse_tailwind(text: str) -> list[tuple[str, str]]:
    """tailwindcss v3 colors.js 의 색 계열 객체. (`<계열>-<단계>`, hex) 를 나온 차례로. 계열 안에 다른 줄이 있으면 ValueError."""
    out, family = [], None
    for line in text.split("\n"):
        if family is None:
            m = _FAMILY.fullmatch(line)
            if m:
                family = m.group(1)
            continue
        if line == "  },":
            family = None
            continue
        m = _SHADE.fullmatch(line)
        if not m:
            raise ValueError(f"tailwind: {family} 안의 줄이 아니다: {line[:80]!r}")
        out.append((f"{family}-{m.group(1)}", m.group(2)))
    if family is not None or not out:
        raise ValueError("tailwind: 색 계열을 읽지 못했다")
    return out


def _source(name: str) -> dict:
    src = SOURCES[name]
    out = {"id": name, "repo": src["repo"], "commit": src["commit"], "path": src["data"], "license": src["license"],
           "date": DATE}
    if "tag" in src:
        out["tag"] = src["tag"]
    return out


def build_palettes(taste: list[dict], seeds: list[dict]) -> dict:
    palettes = []
    for p in taste:
        accent = color.from_hex(p["accent"])
        text = oklch_text(accent)
        palettes.append({"id": f"taste:{p['id']}", "source": "taste-skill", "license": "MIT", "accent": text,
                         "bg": oklch_text(color.from_hex(p["bg"])), "ink": oklch_text(color.from_hex(p["ink"])),
                         "mood": f"{p['name']} — {p['note']}", "hue": float(text.rsplit(" ", 1)[1].rstrip(")"))})
    for s in seeds:
        palettes.append({"id": f"impeccable:{s['id']}", "source": "impeccable", "license": "Apache-2.0",
                         "accent": f"oklch({s['l']} {s['c']} {s['h']})", "bg": None, "ink": None, "mood": s["mood"],
                         "hue": float(s["h"]) % 360})
    ids = [p["id"] for p in palettes]
    if len(ids) != len(set(ids)):
        raise ValueError("palettes: id 가 겹친다")
    return {"sources": [_source("taste-skill"), _source("impeccable")], "palettes": palettes}


def build_overused(ramp: list[tuple[str, str]]) -> dict:
    names = dict(ramp)
    missing = [n for n in TAILWIND_OVERUSED if n not in names]
    if missing:
        raise ValueError(f"tailwind: {', '.join(missing)} 가 없다")
    colors = [{"hex": names[n], "name": f"Tailwind {n}"} for n in TAILWIND_OVERUSED]
    colors += [{"hex": h, "name": name} for h, name in OTHER_OVERUSED]
    return {"sources": [_source("tailwindcss")], "colors": colors,
            "tailwind_ramp": list(dict.fromkeys(h for _, h in ramp)),
            "fonts_ko": list(FONTS_KO), "fonts_latin": list(FONTS_LATIN)}


def _fence(text: str) -> str:
    return "````text\n" + text.rstrip("\n") + "\n````"


def build_licenses(licenses: dict[str, str]) -> str:
    """licenses: `<출처>/<파일>` → 원문(taste-skill/LICENSE, impeccable/LICENSE, impeccable/NOTICE.md, tailwindcss/LICENSE)."""
    rows = []
    for name, what in (("taste-skill", "`palettes.json` 의 `taste:` 항목"),
                       ("impeccable", "`palettes.json` 의 `impeccable:` 항목"),
                       ("tailwindcss", "`overused.json` 의 `tailwind_ramp` 와 `Tailwind` 이름의 과용 색")):
        src = SOURCES[name]
        rows.append(f"| {what} | {name} `{src['data']}` ({src['repo']}) | `{src['commit']}` | {src['license']} |")
    parts = [
        "# 들여온 데이터의 라이선스",
        "",
        "herdr-team 플러그인의 `lib/hteam/data/` 가운데 아래 데이터는 고정한 커밋의 원본에서 형식만 바꿔 들여왔다. 저장소의 "
        f"`scripts/import-palettes.py` 가 원본을 받아 다시 만든다(들여온 날 {DATE}, 다시 돌리면 같은 파일이 나온다).",
        "",
        "| 데이터 | 원본 | 커밋 | 라이선스 |",
        "|---|---|---|---|",
        *rows,
        "",
        "`fonts-ko.json` 은 글꼴 이름·라이선스·받는 곳만 적은 목록이고 글꼴 파일은 들여오지 않는다. `overused.json` 의 "
        "Bootstrap·iOS·Material·Anthropic 색과 과용 글꼴 이름은 조사(2026-11-16)에서 모은 값이고 들여온 데이터가 아니다.",
        "",
        "## 바꾼 점",
        "",
        "- taste-skill: 항목마다 `id` 앞에 `taste:` 를 붙였다. `accent`·`bg`·`ink` 의 hex 를 OKLCH 글(`oklch(L C h)`, L·C 는 "
        "소수 셋째 자리, h 는 첫째 자리)로 바꿨다. `name` 과 `note` 를 ` — ` 로 이어 `mood` 에 두었다. 다른 필드(`surface`·"
        "`muted`·`accentInk`·`fields`·`tags`·`trades`·`seenIn`)는 넣지 않았다.",
        "- impeccable(Apache-2.0 4(b) 의 바꾼 점 알림): `SEEDS` 의 항목마다 `id` 앞에 `impeccable:` 를 붙였다. `l`·`c`·`h` "
        "글을 그대로 `accent` 의 `oklch(l c h)` 에 넣었다. `mood` 는 그대로 두었다. `strategy` 와 `TEMPLATE` 은 넣지 않았다.",
        "- tailwindcss: 색 계열 객체의 hex 를 나온 차례로 모으고 같은 값은 한 번만 두었다. 계열 이름이 붙은 과용 색은 그 hex 를 "
        "`Tailwind <계열>-<단계>` 이름과 함께 두었다.",
        "",
        "## taste-skill (MIT)",
        "",
        _fence(licenses["taste-skill/LICENSE"]),
        "",
        "## impeccable (Apache-2.0)",
        "",
        _fence(licenses["impeccable/LICENSE"]),
        "",
        "### impeccable NOTICE.md",
        "",
        _fence(licenses["impeccable/NOTICE.md"]),
        "",
        "## tailwindcss (MIT)",
        "",
        _fence(licenses["tailwindcss/LICENSE"]),
    ]
    return "\n".join(parts) + "\n"


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def convert(taste: str, impeccable: str, tailwind: str, licenses: dict[str, str]) -> dict[str, str]:
    """원본 글들 → 파일 이름별 글(palettes.json, overused.json, LICENSES.md). 네트워크를 쓰지 않는 순수 함수다."""
    return {"palettes.json": dump(build_palettes(parse_taste(taste), parse_impeccable(impeccable))),
            "overused.json": dump(build_overused(parse_tailwind(tailwind))),
            "LICENSES.md": build_licenses(licenses)}


def fetch_all(opener=urllib.request.urlopen) -> dict[str, str]:
    return {f"{name}/{path}": fetch(name, path, opener) for name, src in SOURCES.items() for path in src["files"]}


def from_fetched(texts: dict[str, str]) -> dict[str, str]:
    return convert(texts[f"taste-skill/{SOURCES['taste-skill']['data']}"],
                   texts[f"impeccable/{SOURCES['impeccable']['data']}"],
                   texts[f"tailwindcss/{SOURCES['tailwindcss']['data']}"],
                   {k: v for k, v in texts.items() if k.endswith(("/LICENSE", "/NOTICE.md"))})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="팔레트·과용 색 카탈로그 들여오기(설계 11.10)")
    ap.add_argument("--check", action="store_true", help="저장소 파일과 같은지만 본다")
    args = ap.parse_args(argv)
    out = from_fetched(fetch_all())
    if args.check:
        differ = [name for name, text in out.items()
                  if not (DATA / name).is_file() or (DATA / name).read_text(encoding="utf-8") != text]
        print("다르다: " + ", ".join(differ) if differ else "같다")
        return 1 if differ else 0
    DATA.mkdir(parents=True, exist_ok=True)
    for name, text in out.items():
        tmp = DATA / f".{name}.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, DATA / name)
        print(f"썼다: {(DATA / name).relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
