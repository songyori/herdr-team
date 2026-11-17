#!/usr/bin/env python3
"""획일도 측정(설계 15.5, 13단계). 저장소 개발용이고 플러그인에 넣지 않는다.

  python3 scripts/design-eval/eval.py run --variant before|after [--reps 2] [--briefs budget,clinic]
  python3 scripts/design-eval/eval.py metrics <결과 폴더>
  python3 scripts/design-eval/eval.py report <before 폴더> <after 폴더>
  python3 scripts/design-eval/eval.py judge-prompt <결과 폴더>

run 은 claude -p(opus, 도구 없음, --safe-mode 라 CLAUDE.md·스킬·플러그인·훅·MCP 가 없어 개인 지침이 두 판 어디에도 들어가지 않는다)를 빈 임시 폴더에서 부른다. 결과는 저장소 .design-eval/ 아래다
(git 제외). before 판은 0.7.2(커밋 8cd549c)의 director.md·design-rules.md 를 git 에서 읽고, after 판은 작업 트리의 템플릿과
palette.deal 의 배정을 쓴다. 정성 판정은 judge-prompt 가 만든 프롬프트를 scripts/codex-review.sh doc 으로 돌린다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "herdr-team" / "lib"
sys.path.insert(0, str(LIB))
from hteam import color  # noqa: E402

BASE = "8cd549c"  # 0.7.2(설계 15.5 의 before)
OUT = REPO / ".design-eval"
BRIEFS = Path(__file__).with_name("briefs.json")
OVERUSED = LIB / "hteam" / "data" / "overused.json"
CLASSES = ("돋움", "부리", "표시")
CLAUDE = ["claude", "-p", "--model", "opus", "--tools", "", "--output-format", "json", "--no-session-persistence",
          "--strict-mcp-config", "--setting-sources", "project", "--safe-mode"]
SCHEMA = ('JSON 객체 하나만 낸다(코드 블록·설명 없이). 키는 "A"·"B"·"C" 이고 값마다 다음 키를 둔다: "bg"·"ink"·"accent"'
          '(색, oklch(L C H) 글), "neutral"("순회색" 또는 "틴트"), "heading_font"·"body_font"(글꼴 이름), "heading_class"'
          '("돋움"·"부리"·"표시" 가운데 하나), "posture"(색 자세 낱말), "radius"(px 수), "mood"(무드 문장), "idea"(이 서비스만의 '
          '아이디어 한 문장).')


def stage2(director: str) -> str:
    """director.md 의 `## 단계 ② 톤 시안` 절(다음 `## ` 앞까지)."""
    m = re.search(r"^## 단계 ② 톤 시안\n.*?(?=^## )", director, re.M | re.S)
    if not m:
        raise SystemExit("director.md 에 단계 ② 절이 없다")
    return m.group(0).strip()


def sources(variant: str) -> dict[str, str]:
    if variant == "after":
        try:
            from hteam import palette  # noqa: F401  p13b 가 만든다. 실행 폴더를 만들기 전에 없으면 멈춘다
        except ImportError:
            raise SystemExit("after 판에는 hteam/palette.py 가 필요하다(p13b 뒤에 잰다)")
    tpl = REPO / "herdr-team" / "templates"
    if variant == "before":
        def show(rel: str) -> str:
            return subprocess.run(["git", "-C", str(REPO), "show", f"{BASE}:herdr-team/templates/{rel}"],
                                  capture_output=True, text=True, check=True).stdout
        return {"director": show("roles/director.md"), "design_rules": show("design-rules.md")}
    out = {"director": (tpl / "roles" / "director.md").read_text(encoding="utf-8"),
           "design_rules": (tpl / "design-rules.md").read_text(encoding="utf-8")}
    for name in ("palette.md", "fonts-ko.md"):
        if not (tpl / name).is_file():
            raise SystemExit(f"after 판에는 templates/{name} 가 필요하다(p13b 뒤에 잰다)")
        out[name] = (tpl / name).read_text(encoding="utf-8")
    return out


def deal_for(brief_id: str, rep: int) -> dict:
    from hteam import palette  # p13b 가 만든다(after 판만)
    return palette.deal(f"{brief_id}:{rep}")


def prompt(variant: str, src: dict, brief: dict, deal: dict | None = None) -> str:
    parts = ["너는 herdr-team 의 디자인 디렉터다. 아래 지시의 단계 ② 톤 시안만 한다. 도구를 쓰지 않고, 아티팩트를 만들지 않고, "
             "질문하지 않는다. 실제 디렉터라면 만들 톤 A·B·C 를 정해 JSON 으로만 답한다.",
             "## 서비스", json.dumps(brief, ensure_ascii=False, indent=1),
             "## 지시(director.md 단계 ②)", stage2(src["director"]),
             "## 디자인 규칙(design-rules.md)", src["design_rules"]]
    if variant == "after":
        parts += ["## 배정 절차(palette.md)", src["palette.md"], "## 한글 글꼴(fonts-ko.md)", src["fonts-ko.md"],
                  "## 받은 배정(hteam palette deal 출력)", json.dumps(deal, ensure_ascii=False, indent=1)]
    parts += ["## 출력", SCHEMA]
    return "\n\n".join(parts) + "\n"


def parse_output(text: str) -> dict | None:
    t = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    if m:
        t = m.group(1)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def validate(obj) -> str | None:
    """유효하면 None, 아니면 까닭(설계 15.5 의 유효한 실행)."""
    if not isinstance(obj, dict):
        return "JSON 객체가 아니다"
    for key in "ABC":
        opt = obj.get(key)
        if not isinstance(opt, dict):
            return f"{key} 가 없다"
        for name in ("bg", "ink", "accent"):
            if not isinstance(opt.get(name), str) or color.parse(opt[name]) is None:
                return f"{key}.{name} 를 색으로 읽지 못했다"
        if color.parse(opt["accent"])[1] < 0.03:
            return f"{key}.accent 가 무채색이다"
        for name in ("heading_font", "body_font", "posture", "mood"):
            if not isinstance(opt.get(name), str) or not opt[name].strip():
                return f"{key}.{name} 가 비었다"
        if opt.get("heading_class") not in CLASSES:
            return f"{key}.heading_class 가 돋움·부리·표시가 아니다"
    return None


def call_claude(text: str, cwd: Path) -> str:
    env = {**os.environ, "DISABLE_AUTOUPDATER": "1"}
    proc = subprocess.run(CLAUDE + [text], cwd=cwd, capture_output=True, text=True, timeout=900, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exit {proc.returncode}: {proc.stderr[-300:]}")
    return str(json.loads(proc.stdout).get("result", ""))


def run(variant: str, reps: int, only: list[str]) -> Path:
    briefs = [b for b in json.loads(BRIEFS.read_text(encoding="utf-8")) if not only or b["id"] in only]
    src = sources(variant)
    out = OUT / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{variant}"
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="design-eval-") as tmp:
        for brief in briefs:
            for rep in range(1, reps + 1):
                deal = deal_for(brief["id"], rep) if variant == "after" else None
                text = prompt(variant, src, brief, deal)
                record = {"brief": brief["id"], "rep": rep, "variant": variant, "deal": deal, "attempts": []}
                obj, why = None, "실행 안 함"
                for attempt in range(2):
                    ask = text if attempt == 0 else text + f"\n앞 출력이 형식에 맞지 않았다({why}). JSON 객체 하나만 다시 낸다.\n"
                    try:
                        raw = call_claude(ask, Path(tmp))
                    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                        raw, obj, why = "", None, f"호출 실패: {exc}"
                    else:
                        obj = parse_output(raw)
                        why = validate(obj) if obj is not None else "JSON 이 아니다"
                    record["attempts"].append({"raw": raw, "error": why})
                    if why is None:
                        break
                record.update(output=obj if why is None else None, valid=why is None, error=why)
                (out / f"{brief['id']}-{rep}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                                               encoding="utf-8")
                print(f"{brief['id']} {rep}: {'ok' if why is None else why}", flush=True)
    return out


def _font(name: str) -> str:
    """글꼴 이름 하나를 비교용으로 고른다: 소문자, 공백·따옴표 없음, 끝의 variable/vf 제거."""
    return re.sub(r"(variable|vf)$", "", re.sub(r"[\s\"']", "", name).lower())


def hangul_font(body_font: str, latin: set[str]) -> str | None:
    """CSS 글꼴 스택에서 한글을 그리는 글꼴. 라틴 전용이 아닌 첫 항목이고 없으면 시스템 글꼴(None)이다."""
    for entry in body_font.split(","):
        f = _font(entry)
        if f and f not in latin:
            return f
    return None


def is_cluster(opt: dict) -> bool:
    """크림·베이지 배경 + 부리 제목 + 테라코타 강조(설계 15.5)."""
    bg, accent = color.parse(opt["bg"]), color.parse(opt["accent"])
    return (bg[0] >= 0.9 and 60 <= bg[2] <= 100 and 0.01 <= bg[1] <= 0.05 and opt.get("heading_class") == "부리"
            and 20 <= accent[2] <= 50)


def metrics(runs: list[dict], overused: dict) -> dict:
    """설계 15.5 의 숫자. 비율은 모든 실행의 안(실행 × 3)이 분모이고 실패한 실행의 세 안은 나쁜 쪽으로 센다(거리는 60° 미만).
    군집 수는 유효한 실행만 센다. 유효한 실행이 80% 보다 적으면 measured 가 거짓이다(다시 잰다)."""
    total = len(runs)
    valid = [r for r in runs if r.get("valid")]
    failed = total - len(valid)
    options = [r["output"][k] for r in valid for k in "ABC"]
    hues = [color.parse(o["accent"])[2] for o in options]
    buckets = Counter(int(h // 30) % 12 for h in hues)
    shares = [buckets[i] / len(hues) for i in range(12) if hues and buckets[i]]
    slots = max(total * 3, 1)

    def spread(r: dict) -> float:
        hs = [color.parse(r["output"][k]["accent"])[2] for k in "ABC"]
        return min(color.hue_distance(a, b) for i, a in enumerate(hs) for b in hs[i + 1:])

    fonts_ko = {_font(f) for f in overused.get("fonts_ko", [])}
    fonts_latin = {_font(f) for f in overused.get("fonts_latin", [])}
    pool = [color.parse(c["hex"]) for c in overused.get("colors", [])]
    ramp = [color.parse(h) for h in overused.get("tailwind_ramp", [])]

    def hits(group: list) -> int:
        return sum(1 for o in options for k in ("bg", "ink", "accent")
                   if any(p is not None and color.delta(color.parse(o[k]), p) < 0.02 for p in group))

    out = {
        "runs": total, "valid": len(valid), "measured": total > 0 and len(valid) >= 0.8 * total,
        "buckets": [buckets[i] for i in range(12)],
        "entropy": round(-sum(s * math.log2(s) for s in shares), 3),
        "blue_violet": round((sum(1 for h in hues if 240 <= h < 300) + failed * 3) / slots, 3),
        "spread_ge_60": round(sum(1 for r in valid if spread(r) >= 60) / max(total, 1), 3),
        "overused_body": round((sum(1 for o in options if (lambda h: h is None or h in fonts_ko)(hangul_font(o["body_font"], fonts_latin)))
                                + failed * 3) / slots, 3),  # 한글을 그리는 글꼴만 본다(없으면 시스템 글꼴 = 과용)
        "overused_color_hits": hits(pool), "tailwind_ramp_hits": hits(ramp),
        "cluster": sum(1 for o in options if is_cluster(o)),
        "postures": dict(Counter(o["posture"] for o in options)),
    }
    out["targets"] = {"blue_violet_le_20": out["blue_violet"] <= 0.20, "spread_ge_60_ge_90": out["spread_ge_60"] >= 0.90,
                      "overused_body_le_40": out["overused_body"] <= 0.40, "cluster_zero": out["cluster"] == 0}
    return out


def load_runs(folder: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*-[0-9]*.json"))]


def load_overused() -> dict:
    if not OVERUSED.is_file():
        raise SystemExit(f"{OVERUSED.relative_to(REPO)} 가 없다(p13b 의 카탈로그 뒤에 집계한다)")
    return json.loads(OVERUSED.read_text(encoding="utf-8"))


def write_metrics(folder: Path) -> dict:
    m = metrics(load_runs(folder), load_overused())
    (folder / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return m


def report(before: Path, after: Path) -> Path:
    a, b = write_metrics(before), write_metrics(after)
    rows = [("유효 실행", f"{a['valid']}/{a['runs']}", f"{b['valid']}/{b['runs']}", "80% 이상"),
            ("240–300° 주 강조 비율", a["blue_violet"], b["blue_violet"], "≤ 0.20"),
            ("최소 hue 거리 60° 이상 실행 비율", a["spread_ge_60"], b["spread_ge_60"], "≥ 0.90"),
            ("과용 한글 본문 글꼴 비율", a["overused_body"], b["overused_body"], "≤ 0.40"),
            ("크림+세리프+테라코타 군집", a["cluster"], b["cluster"], "0"),
            ("hue 12칸 엔트로피(bit)", a["entropy"], b["entropy"], "높을수록 고르다"),
            ("과용 색 일치", a["overused_color_hits"], b["overused_color_hits"], "-"),
            ("Tailwind 램프 일치", a["tailwind_ramp_hits"], b["tailwind_ramp_hits"], "-")]
    lines = [f"# 획일도 측정 {dt.date.today()}", "", f"- before: `{before.name}`", f"- after: `{after.name}`", "",
             "| 지표 | before | after | 목표 |", "|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |" for r in rows]
    def mark(m: dict) -> str:
        return f"{'유효' if m['measured'] else '무효'} ({m['valid']}/{m['runs']})"

    targets = (json.dumps(b["targets"], ensure_ascii=False) if b["measured"]
               else "무효(유효 실행이 80% 보다 적다. 다시 잰다)")
    lines += ["", f"- before 측정: {mark(a)}", f"- after 측정: {mark(b)}", f"- after 목표: {targets}",
              f"- before hue 칸: {a['buckets']}", f"- after hue 칸: {b['buckets']}",
              f"- before 자세: {a['postures']}", f"- after 자세: {b['postures']}"]
    path = OUT / f"report-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def judge_prompt(folder: Path) -> Path:
    rows = []
    for r in load_runs(folder):
        if not r.get("valid"):
            continue
        for k in "ABC":
            o = r["output"][k]
            cell = {name: " ".join(str(o.get(name) or "-").replace("|", "/").split()) for name in
                    ("bg", "ink", "accent", "heading_font", "heading_class", "body_font", "posture", "mood", "idea")}
            rows.append(f"| {r['brief']} | {r['rep']} | {k} | {cell['bg']} / {cell['ink']} / {cell['accent']} | "
                        f"{cell['heading_font']}({cell['heading_class']}) / {cell['body_font']} | {cell['posture']} | "
                        f"{cell['mood']} | {cell['idea']} |")
    text = "\n".join([
        "너는 디자인 리뷰어다. 읽기만 한다. 아래 표는 같은 지시를 받은 디자인 디렉터가 서비스 브리프 다섯에 낸 톤 시안이다"
        f"(판 `{folder.name}`). 브리프는 `scripts/design-eval/briefs.json` 이다.",
        "안마다 다음을 매긴다: AI 군집 닮음 1–5(5 = AI 생성 디자인의 흔한 모습: 크림+세리프+테라코타, 슬레이트+파랑, 검정+네온, "
        "옅은 배경+소심한 강조 하나), 거울 시험 예/아니오(같은 분야 다른 서비스에 그대로 붙여도 맞으면 예), 무드 구체성 1–5"
        "(5 = 구체적인 장면·소재), 한 줄 이유.",
        "출력: 마크다운 표 `| 브리프 | 반복 | 안 | 군집 닮음 | 거울 | 구체성 | 이유 |` 와 마지막 줄 "
        "`평균 군집 닮음 <x>, 거울 예 <n>/<m>, 평균 구체성 <y>`.", "",
        "| 브리프 | 반복 | 안 | 배경/글자/강조 | 제목(계열)/본문 글꼴 | 자세 | 무드 | 아이디어 |",
        "|---|---|---|---|---|---|---|---|", *rows])
    path = folder / "judge-prompt.md"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="획일도 측정(설계 15.5)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--variant", choices=("before", "after"), required=True)
    r.add_argument("--reps", type=int, default=2)
    r.add_argument("--briefs", default="")
    sub.add_parser("metrics").add_argument("folder", type=Path)
    rp = sub.add_parser("report")
    rp.add_argument("before", type=Path)
    rp.add_argument("after", type=Path)
    sub.add_parser("judge-prompt").add_argument("folder", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "run":
        print(run(args.variant, args.reps, [x for x in args.briefs.split(",") if x]))
    elif args.cmd == "metrics":
        print(json.dumps(write_metrics(args.folder), ensure_ascii=False, indent=1))
    elif args.cmd == "report":
        print(report(args.before, args.after))
    else:
        path = judge_prompt(args.folder)
        print(path)
        print(f"scripts/codex-review.sh doc design-eval-{args.folder.name} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
