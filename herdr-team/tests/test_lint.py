"""디자인 자동 검사(설계 11.6): 이모지, 왼쪽 강조 테두리, 파랑·보라 그라디언트, 대상 파일, 상한, `hteam lint --task`."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT, TeamCase
from hteam import state
from hteam import palette
from hteam.errors import HteamError
from hteam.lint import (DESIGN_ROLES, MAX_BYTES, MAX_FINDINGS, STYLE_RULES_MARKER, WEB_SUFFIXES, cap, design_findings,
                        design_lint, font_stack, has_style_rules, hue_family, scan, strip_comments, style_findings, style_scan,
                        web_findings, web_scan)
from hteam.paths import Project

VS16 = chr(0xFE0F)  # 이모지 표시 선택자. 소스에서 보이지 않으므로 이름으로 쓴다


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hteam-lint-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)

    def put(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return rel

    def heads(self, *rels):
        """`파일:줄: 패턴` 부분만(발췌 앞 첫 괄호까지)."""
        return [item.split("(", 1)[0] for item in design_lint(self.root, list(rels))]

    def test_design_roles(self):
        self.assertEqual(DESIGN_ROLES, ("director", "designer", "developer"))

    def test_emoji_once_per_line(self):
        rel = self.put("src/ui/home.tsx", "<h1>홈</h1>\n<p>🚀 빠르게 시작 ✨</p>\n<p>→ 다음 • 항목</p>\n")
        self.assertEqual(design_lint(self.root, [rel]), ["src/ui/home.tsx:2: 이모지(🚀)"])

    def test_emoji_presentation_and_variation_selector_only(self):
        # 글자 기호(✓ ★ ❯ ➜ ⬆ ▶)는 잡지 않는다. BMP 이모지 표시 글자와 FE0F 가 붙은 글자는 잡는다
        rel = self.put("src/ui/icons.tsx", "✓ ★ ❯ ➜ ⬆ ▶ 다음\n✅ 완료\n⏰ 알림\n⭐ 별\n▶️ 재생\n☀️ 맑음\n")
        self.assertEqual(design_lint(self.root, [rel]), [
            "src/ui/icons.tsx:2: 이모지(✅)", "src/ui/icons.tsx:3: 이모지(⏰)", "src/ui/icons.tsx:4: 이모지(⭐)",
            "src/ui/icons.tsx:5: 이모지(▶️)", "src/ui/icons.tsx:6: 이모지(☀️)"])

    def test_variation_selector_after_space_is_not_emoji(self):
        rel = self.put("src/ui/stray.tsx", f"<p>a {VS16} b</p>\n<p>\t{VS16}</p>\n<p>▶{VS16} 재생</p>\n")
        self.assertEqual(design_lint(self.root, [rel]), [f"src/ui/stray.tsx:3: 이모지(▶{VS16})"])

    def test_left_border_in_css_and_jsx(self):
        css = self.put("src/ui/card.css", ".card {\n  border-left: 4px solid #2563eb;\n}\n"
                                          ".quote { border-inline-start: 0.25rem solid var(--accent); }\n"
                                          ".table td { border-left: 1px solid #e5e7eb; }\n.none { border-left: 0; }\n")
        jsx = self.put("src/ui/Note.jsx", "const s = { borderLeft: '4px solid #7c3aed', padding: 12 };\n")
        self.assertEqual(design_lint(self.root, [css])[0], "src/ui/card.css:2: 왼쪽 강조 테두리(border-left: 4px solid #2563eb;)")
        self.assertEqual(self.heads(css, jsx), ["src/ui/card.css:2: 왼쪽 강조 테두리", "src/ui/card.css:4: 왼쪽 강조 테두리",
                                                "src/ui/Note.jsx:1: 왼쪽 강조 테두리"])

    def test_invisible_left_border_is_not_reported(self):
        rel = self.put("src/ui/tabs.css", ".tab { border-left: 4px solid transparent; }\n"
                                          ".a { border-left: 4px none #2563eb; }\n"
                                          ".b { border-inline-start: 3px hidden #2563eb; }\n"
                                          ".c { border-left: 4px solid var(--accent, transparent); }\n"
                                          ".on { border-left: 4px solid #2563eb; }\n")
        self.assertEqual(self.heads(rel), ["src/ui/tabs.css:4: 왼쪽 강조 테두리", "src/ui/tabs.css:5: 왼쪽 강조 테두리"])

    def test_left_border_widths(self):
        css = self.put("src/ui/kw.css", ".a { border-left-width: thick; }\n.b { border-inline-start-width: 0.25rem; }\n"
                                        ".c { border-left-width: thin; }\n.d { border-left-width: var(--thick); }\n")
        jsx = self.put("src/ui/Kw.tsx", "const a = { borderLeftWidth: 4 };\nconst b = { borderInlineStartWidth: '1px' };\n")
        self.assertEqual(self.heads(css, jsx), ["src/ui/kw.css:1: 왼쪽 강조 테두리", "src/ui/kw.css:2: 왼쪽 강조 테두리",
                                                "src/ui/Kw.tsx:1: 왼쪽 강조 테두리"])

    def test_tailwind_left_border_needs_width_and_color(self):
        rel = self.put("src/ui/Callout.tsx", '<div className="border-l-4 border-blue-500 pl-4">a</div>\n'
                                             '<div className="border-l-4 pl-4">b</div>\n'
                                             '<td className="border-l border-gray-200">c</td>\n'
                                             '<div className="border-s-[3px] border-s-blue-500">d</div>\n'
                                             '<div className="border-l-[1px] border-blue-500">e</div>\n')
        self.assertEqual(self.heads(rel), ["src/ui/Callout.tsx:1: 왼쪽 강조 테두리", "src/ui/Callout.tsx:4: 왼쪽 강조 테두리"])

    def test_hue_family(self):
        for color, family in (("#2563eb", "blue"), ("#7c3aed", "purple"), ("blue", "blue"), ("indigo", "purple"),
                              ("#9ca3af", None), ("hsl(220, 80%, 50%)", "blue"), ("rgb(124, 58, 237)", "purple"),
                              ("oklch(62.3% 0.214 259.815)", "blue"), ("oklch(60.6% 0.25 292.717)", "purple"),
                              ("oklch(0.606 0.25 292.717 / 0.5)", "purple"), ("oklch(60% 0.02 280)", None),
                              ("oklch(70% 0.2 30)", None)):
            with self.subTest(color=color):
                self.assertEqual(hue_family(color), family)

    def test_blue_purple_gradients(self):
        rel = self.put("src/ui/hero.css", ".hero {\n  background: linear-gradient(\n    135deg,\n    #667eea 0%,\n"
                                          "    #764ba2 100%\n  );\n}\n"
                                          ".ok { background: linear-gradient(#3b82f6, #1d4ed8); }\n"
                                          ".named { background: radial-gradient(circle, blue, purple); }\n"
                                          ".warm { background: linear-gradient(90deg, #f97316, #db2777); }\n"
                                          ".v4 { background: linear-gradient(oklch(62.3% 0.214 259.815), "
                                          "oklch(62.7% 0.265 303.9)); }\n")
        self.assertEqual(self.heads(rel), ["src/ui/hero.css:2: 파랑·보라 그라디언트", "src/ui/hero.css:9: 파랑·보라 그라디언트",
                                           "src/ui/hero.css:11: 파랑·보라 그라디언트"])

    def test_tailwind_gradient(self):
        rel = self.put("src/ui/Hero.tsx", '<h1 className="bg-gradient-to-r from-indigo-500 to-violet-600">x</h1>\n'
                                          '<div className="bg-gradient-to-r from-blue-500 to-sky-400">y</div>\n')
        self.assertEqual(self.heads(rel), ["src/ui/Hero.tsx:1: 파랑·보라 그라디언트"])

    def test_tailwind_combo_is_per_class_list(self):
        rel = self.put("src/ui/Split.tsx",
                       '<h1 className="bg-gradient-to-r\n  from-blue-500\n  to-violet-600">a</h1>\n'
                       '<p><b className="from-blue-500 to-blue-600">b</b><i className="from-violet-500 to-violet-600">c</i></p>\n'
                       '<div className={cn("border-l-4 pl-2", "border-blue-500")}>d</div>\n'  # 문자열 둘: 한 목록이 아니다
                       '<div className="border-l-4\n  border-blue-500">e</div>\n'
                       '<div class="px-2 from-indigo-500\n via-sky-500 to-purple-600">f</div>\n')
        # 4줄(한 줄 두 요소)은 알려진 거짓 경고다: 한 줄 방식과 클래스 목록 방식을 함께 쓴다(설계 11.6). 5줄은 한 줄 방식.
        self.assertEqual(self.heads(rel), ["src/ui/Split.tsx:2: 파랑·보라 그라디언트",
                                           "src/ui/Split.tsx:4: 파랑·보라 그라디언트",
                                           "src/ui/Split.tsx:5: 왼쪽 강조 테두리",
                                           "src/ui/Split.tsx:6: 왼쪽 강조 테두리",
                                           "src/ui/Split.tsx:8: 파랑·보라 그라디언트",
                                           "src/ui/Split.tsx:9: 파랑·보라 그라디언트"])  # 9줄: 한 줄 방식이 목록의 뒷줄을 또 본다

    def test_rgb_percent_channels_and_case(self):
        rel = self.put("src/ui/pct.css",
                       ".a { background: linear-gradient(rgb(10%,20%,50%),rgb(40%,10%,50%)); }\n"
                       ".b { background: linear-gradient(rgb(26,51,128),rgb(102,26,128)); }\n"
                       ".c { background: linear-gradient(RGB(37,99,235),RGB(124,58,237)); }\n"
                       ".d { background: linear-gradient(Hsl(220,80%,50%),HSL(270,70%,50%)); }\n")
        self.assertEqual(self.heads(rel), ["src/ui/pct.css:1: 파랑·보라 그라디언트", "src/ui/pct.css:2: 파랑·보라 그라디언트",
                                           "src/ui/pct.css:3: 파랑·보라 그라디언트", "src/ui/pct.css:4: 파랑·보라 그라디언트"])

    def test_escaped_quotes_do_not_close_class_list(self):
        rel = self.put("src/ui/Esc.tsx",
                       'const a = "border-l-4 before:content-[\\"x\\"] border-blue-500";\n'
                       "const b = 'border-l-4 before:content-[\\'x\\'] border-blue-500';\n"
                       'const c = `border-l-4 before:content-[\\`x\\`] border-blue-500`;\n'
                       '<i className={"from-blue-500 before:content-[\\"x\\"] to-violet-600"}>y</i>\n'
                       'x = cn(`border-l-4 \\\n border-blue-500`)\n'
                       '<div class="icon-\\"></div>\n<div class="border-l-4 border-blue-500">z</div>\n'
                       'const className = "border-l-4 before:content-[\\"x\\"] border-blue-500";\n'
                       'el.className = "border-l-4 before:content-[\\"x\\"] border-blue-500";\n'
                       "<p>Don't <span className={'border-l-4 border-blue-500'}>x</span></p>\n")
        self.assertEqual(self.heads(rel), ["src/ui/Esc.tsx:1: 왼쪽 강조 테두리", "src/ui/Esc.tsx:2: 왼쪽 강조 테두리",
                                           "src/ui/Esc.tsx:3: 왼쪽 강조 테두리", "src/ui/Esc.tsx:4: 파랑·보라 그라디언트",
                                           "src/ui/Esc.tsx:5: 왼쪽 강조 테두리", "src/ui/Esc.tsx:8: 왼쪽 강조 테두리",
                                           "src/ui/Esc.tsx:9: 왼쪽 강조 테두리", "src/ui/Esc.tsx:10: 왼쪽 강조 테두리",
                                           "src/ui/Esc.tsx:11: 왼쪽 강조 테두리"])

    def test_many_string_literals_stay_fast(self):
        import json
        import time
        rel = self.put("data/big.json", json.dumps({f"k{n}": f"v{n}" for n in range(24000)}))
        start = time.monotonic()
        self.assertEqual(design_lint(self.root, [rel]), [])
        self.assertLess(time.monotonic() - start, 3.0)

    def test_skips_excluded_unsupported_outside_missing_large_and_non_utf8(self):
        rels = [self.put("docs/planning/spec.md", "🚀\n"), self.put("docs/design/references.md", "🚀\n"),
                self.put("docs/tasks/T-001/report.md", "🚀\n"), self.put("docs/reviews/T-001/r1.md", "🚀\n"),
                self.put("scripts/run.py", "print('🚀')\n"), "src/deleted.css", "../outside.css"]
        self.put("src/big.css", "🚀\n" + "a" * MAX_BYTES)
        (self.root / "src/bad.css").write_bytes(b"\xff\xfe border-left: 4px solid red;\n")
        self.assertEqual(design_lint(self.root, [*rels, "src/big.css", "src/bad.css"]), [])

    def test_screen_artifact_files_are_skipped(self):
        # 10단계(설계 11.6·11.8): 화면 아티팩트 파일은 index.html 을 바꾼 것이라 같은 지적이 두 번 나온다
        skipped = [self.put("docs/design/screens/home/artifact/project/Home.dc.html", "<p>🚀</p>\n"),
                   self.put("docs/design/screens/home/artifact/project/canvas.json", '{"a": "🚀"}\n')]
        self.assertEqual(design_lint(self.root, skipped), [])
        screen = self.put("docs/design/screens/home/index.html", "<p>🚀</p>\n")
        self.assertEqual([f.split(":")[0] for f in design_lint(self.root, [screen, *skipped])], [screen])

    def test_caps_findings(self):
        rel = self.put("docs/design/screens/home/notes.md", "".join(f"{n} 🚀\n" for n in range(MAX_FINDINGS + 10)))
        found = design_lint(self.root, [rel])
        self.assertEqual(len(found), MAX_FINDINGS + 1)
        self.assertEqual(found[-1], "… 외 10건")
        # 상한 없는 목록과 자르기는 따로다(디자인 절이 diff 검사와 합친 뒤 자른다, 설계 11.6)
        whole = design_findings(self.root, [rel])
        self.assertEqual(len(whole), MAX_FINDINGS + 10)
        self.assertEqual(cap(whole), found)
        self.assertEqual(cap(whole[:3]), whole[:3])

    def test_many_gradients_keep_line_numbers(self):
        line = "linear-gradient(blue, purple)\n"
        found = scan("src/ui/many.css", line * 2000)
        self.assertEqual(len(found), 2000)
        self.assertEqual(found[-1].split("(", 1)[0], "src/ui/many.css:2000: 파랑·보라 그라디언트")


class StyleScanTest(unittest.TestCase):
    """13단계 색·글꼴 검사(설계 11.13 의 1)."""

    def setUp(self):
        self.over = palette.load_overused()

    def scan(self, rel, text):
        return style_scan(rel, text, self.over)

    def test_overused_colors_once_per_file(self):
        text = ".a { color: #1E3A8A; }\n.b { background: #1e3a8a80; }\n.c { color: #d97757 }\n.d { color: #2563eb }\n.e { color: #6366f1 }\n"
        self.assertEqual(self.scan("src/a.css", text), [
            "src/a.css:1: 과용 기본 색 4개(#1e3a8a Tailwind blue-900, #d97757 Anthropic 군집 테라코타, "
            "#2563eb Tailwind blue-600, …) — design-rules §1 의 11"])
        self.assertEqual(self.scan("src/b.css", ".a { color: #1e3a8b; }\n<p>&#2563; #fffeee</p>\n"), [])  # 숫자 문자 참조는 hex 가 아니다

    def test_tailwind_ramp_needs_three_besides_overused(self):
        two = ".a { color: #fb923c; border-color: #c2410c }\n.b { color: #2563eb }\n"  # orange-400·700 둘, blue-600 은 과용 색
        self.assertEqual([x.split(" — ")[0] for x in self.scan("src/a.css", two)], ["src/a.css:2: 과용 기본 색 1개(#2563eb Tailwind blue-600)"])
        three = "x\n:root { --a: #fb923c; --b: #c2410c; --c: #fff1f2; --d: #fb923c }\n"
        self.assertEqual(self.scan("src/t.css", three), ["src/t.css:2: Tailwind 기본 램프 값 3개 — design-rules §3 의 11"])

    def test_role_color_scan_is_bounded(self):
        import time
        from hteam import lint
        self.assertEqual(len(lint._role_colors(":root { --primary: #2f6fed; }")), 1)
        start = time.monotonic()
        lint._role_colors("--primary: " * 100000)
        self.assertLess(time.monotonic() - start, 1.5)
        start = time.monotonic()
        self.scan("src/a.css", "--primary: " * 100000 + "\n")
        self.assertLess(time.monotonic() - start, 1.5)

    def test_primary_hue_pretty_json_tokens(self):
        import json
        dtcg = json.dumps({"color": {"primary": {"$type": "color", "$value": "oklch(0.6 0.15 260)"}}}, indent=2)
        self.assertEqual(self.scan("tokens.json", dtcg),
                         ["tokens.json:5: 주 강조가 파랑·남색·보라 계열(h 260°) — 근거를 적는다(§1 의 11)"])
        steps = json.dumps({"color": {"primary": {"500": "#2f6fed"}}}, indent=2)
        got = self.scan("tokens.json", steps)
        self.assertEqual(len(got), 1, got)
        self.assertTrue(got[0].startswith("tokens.json:4: 주 강조가 파랑·남색·보라 계열(h 26"), got)
        many = json.dumps({"color": {"primary": {"400": "#4a7df0", "500": "#2f6fed", "600": "#2a55c9"}}}, indent=2)
        got = self.scan("tokens.json", many)
        self.assertEqual(len(got), 1, got)
        self.assertTrue(got[0].startswith("tokens.json:4:"), got)
        warm = json.dumps({"color": {"primary": {"$type": "color", "$value": "oklch(0.6 0.15 40)"}}}, indent=2)
        self.assertEqual(self.scan("tokens.json", warm), [])
        self.assertEqual(self.scan("tokens.json", '{"color": {"primary": {\n  "x": "#2f6fed",\n}}}\n'), [])  # 깨진 JSON 은 줄 단위로
        note = json.dumps({"primary": {"$type": "color", "$description": "#2f6fed 계열", "$value": "#c2410c"}}, indent=2)
        self.assertEqual(self.scan("tokens.json", note), [])

    def test_primary_accent_brand_hue(self):
        text = (":root { --color-primary: #1e40af; --accent-ink: #ffffff; }\n"
                '{"brand": {"value": "oklch(0.55 0.2 290)"}, "neutral": "#64748b"}\n'
                "$brand-accent: hsl(250 60% 50%);\n"
                ":root { --primary: oklch(0.6 0.05 260); --accent: #c2410c; }\n"  # C 0.05 은 무채색에 가깝다, 주황은 아니다
                '"secondary": "#2563eb", "primary": "#0f7d45"\n'
                "--surface: #1e3a8a;\n")
        found = [x for x in self.scan("tokens.json", text) if "주 강조" in x]
        later = ":root { --primary-foreground: #fff; --primary: oklch(0.6 0.15 260); }\n"  # 앞 토큰이 괜찮아도 뒤 토큰을 본다
        self.assertEqual(self.scan("src/t.css", later),
                         ["src/t.css:1: 주 강조가 파랑·남색·보라 계열(h 260°) — 근거를 적는다(§1 의 11)"])
        self.assertEqual(found, ["tokens.json:1: 주 강조가 파랑·남색·보라 계열(h 266°) — 근거를 적는다(§1 의 11)",
                                 "tokens.json:2: 주 강조가 파랑·남색·보라 계열(h 290°) — 근거를 적는다(§1 의 11)",
                                 "tokens.json:3: 주 강조가 파랑·남색·보라 계열(h 281°) — 근거를 적는다(§1 의 11)"])

    def test_overused_fonts(self):
        text = ("body { font-family: Inter, SUIT, sans-serif; }\n"
                "h1 { font-family: 'Pretendard Variable', -apple-system, sans-serif !important; }\n"
                'p { font-family: "IBM Plex Sans KR", sans-serif; }\n'
                '{"fontFamily": ["Noto Sans KR", "sans-serif"]}\n'
                "const s = { fontFamily: 'SUIT, sans-serif' };\n"
                "code { font-family: ui-monospace, monospace; }\n"
                "div { font-family: system-ui, sans-serif; }\n"
                ":root { --font-family: Roboto; }\n"
                ".x { font-family: var(--font-body); }\n")
        self.assertEqual(self.scan("src/a.css", text), [
            "src/a.css:1: 과용 글꼴 Inter — §1 의 7", "src/a.css:2: 과용 글꼴 Pretendard Variable — §1 의 7",
            "src/a.css:4: 과용 글꼴 Noto Sans KR — §1 의 7", "src/a.css:7: 과용 글꼴 system-ui — §1 의 7",
            "src/a.css:8: 과용 글꼴 Roboto — §1 의 7"])
        self.assertEqual(font_stack(' "A B", \'C\' , d ;'), ["A B", "C", "d"])
        self.assertEqual(font_stack('["SUIT", "sans-serif"]'), ["SUIT", "sans-serif"])
        self.assertEqual(font_stack('"SUIT, serif"'), ["SUIT", "serif"])

    def test_multiline_font_declarations(self):
        css = "body {\n  font-family:\n    Inter,\n    sans-serif;\n}\n"
        self.assertEqual(self.scan("a.css", css), ["a.css:2: 과용 글꼴 Inter — §1 의 7"])
        css2 = "p { font-family: Newsreader,\n  SUIT,\n  serif; }\n"  # 한글 글꼴은 Newsreader(과용 아님)
        self.assertEqual(self.scan("a.css", css2), [])
        arr = '{\n  "fontFamily": [\n    "Pretendard",\n    "sans-serif"\n  ]\n}\n'
        self.assertEqual(self.scan("t.json", arr), ["t.json:2: 과용 글꼴 Pretendard — §1 의 7"])
        self.assertEqual(self.scan("t.json", '{"fontFamily": [\n "Inter",\n "SUIT"\n]}\n'), ["t.json:1: 과용 글꼴 Inter — §1 의 7"])
        self.assertEqual(self.scan("t.json", '{"fontFamily": [\n "Newsreader",\n "SUIT"\n]}\n'), [])

    def test_tailwind_nested_font_family(self):
        one = "module.exports = { theme: { fontFamily: { display: ['Newsreader', 'serif'], sans: ['Inter', 'sans-serif'] } } }\n"
        self.assertEqual(self.scan("tailwind.config.js", one), ["tailwind.config.js:1: 과용 글꼴 Inter — §1 의 7"])
        multi = "fontFamily: {\n  display: ['Newsreader', 'serif'],\n  body: [\n    'Roboto',\n    'sans-serif',\n  ],\n},\n"
        self.assertEqual(self.scan("tailwind.config.js", multi), ["tailwind.config.js:1: 과용 글꼴 Roboto — §1 의 7"])
        ok = "fontFamily: { display: ['Newsreader', 'serif'], mono: ['ui-monospace', 'monospace'] }\n"
        self.assertEqual(self.scan("tailwind.config.js", ok), [])

    def test_role_color_value_boundary(self):
        self.assertEqual(self.scan("a.css", ":root { --primary: var(--orange); color: oklch(0.6 0.15 260); }\n"), [])
        self.assertEqual(self.scan("a.css", "x { --accent: var(--o)\n; }\ny { color: oklch(0.6 0.15 260) }\n"), [])
        self.assertEqual(self.scan("t.json", '{"primary": "var(--o)", "link": "oklch(0.6 0.15 260)"}\n'), [])
        want = ["t.json:1: 주 강조가 파랑·남색·보라 계열(h 260°) — 근거를 적는다(§1 의 11)"]
        self.assertEqual(self.scan("t.json", '{"primary": "oklch(0.6 0.15 260)", "x": 1}\n'), want)  # 괄호 안 공백
        self.assertEqual(self.scan("t.json", '{"primary": "rgb(30, 64, 175)", "x": 1}\n')[0].split(" — ")[0], "t.json:1: 주 강조가 파랑·남색·보라 계열(h 266°)")

    def test_dtcg_metadata_order(self):
        want = ["t.json:1: 주 강조가 파랑·남색·보라 계열(h 260°) — 근거를 적는다(§1 의 11)"]
        a = '{"primary":{"$type":"color","$value":"oklch(0.6 0.15 260)"}}\n'
        b = '{"primary":{"$value":"oklch(0.6 0.15 260)","$type":"color"}}\n'
        c = '{"primary":{"$type":"color","$description":"x, y","$extensions":{"a":1},"value":"oklch(0.6 0.15 260)"}}\n'
        for text in (a, b, c):
            self.assertEqual(self.scan("t.json", text), want)
        self.assertEqual(self.scan("t.json", '{"primary":{"$type":"color","$description":"oklch(0.6 0.15 260)"}}\n'), [])

    def test_metadata_subtree_not_token_value(self):
        # 메타데이터(`$extensions` 하위 트리)의 value·preview 는 토큰 값이 아니다. JSON 경로와 줄 단위 되돌림 모두.
        ok = ('{\n  "primary": {\n    "$type": "color",\n    "$extensions": {"vendor": {"value": "oklch(0.55 0.2 260)", "preview": "oklch(0.55 0.2 290)"}},\n'
              '    "$value": "oklch(0.55 0.15 40)"\n  }\n}\n')
        self.assertEqual(self.scan("t.json", ok), [])
        bad_json = ok.replace('\n  }\n}', ',\n  }\n}')  # 끝 쉼표 — JSON 이 아니라 줄 단위로 되돌아간다
        self.assertEqual(self.scan("t.json", bad_json), [])
        one_line = '{"primary": {"$extensions": {"value": "oklch(0.55 0.2 260)"}, "$value": "oklch(0.55 0.15 40)",}}\n'
        self.assertEqual(self.scan("t.json", one_line), [])
        real = '{"primary": {"$extensions": {"value": "oklch(0.55 0.15 40)"}, "$value": "oklch(0.55 0.2 260)",}}\n'
        self.assertEqual(len(self.scan("t.json", real)), 1)

    def test_array_themes_distinct(self):
        text = ('{\n  "themes": [\n    {"primary": "oklch(0.55 0.2 260)"},\n    {"primary": "oklch(0.55 0.2 290)"}\n  ]\n}\n')
        got = self.scan("t.json", text)
        self.assertEqual([x.split(":")[1] for x in got], ["3", "4"])

    def test_dtcg_font_tokens(self):
        pretty = '{\n  "font": {\n    "body": {\n      "$type": "fontFamily",\n      "$value": ["%s", "sans-serif"]\n    }\n  }\n}\n'
        got = self.scan("t.json", pretty % "Pretendard")
        self.assertEqual(len(got), 1)
        self.assertIn("과용 글꼴", got[0])
        self.assertTrue(got[0].startswith("t.json:5:"))
        self.assertEqual(self.scan("t.json", pretty % "SUIT"), [])
        s = '{"font": {"body": {"$type": "fontFamily", "$value": "Pretendard, sans-serif"}}}\n'
        self.assertEqual(len(self.scan("t.json", s)), 1)

    def test_claude_design_tokens(self):
        # 실환경 13단계 D1: 디렉터의 시스템 사본은 Claude Design 꼴 tokens.json 이다(이름이 값인 토큰 목록, 테마, 참조 값,
        # type.families). 역할은 토큰 객체의 name 으로, 색은 value 의 참조를 따라가 읽는다.
        import json
        doc = {"color": {"themes": [{"id": "light"}], "tokens": [
            {"name": "amber-300", "value": {"light": "oklch(0.82 0.14 80)"}},
            {"name": "violet-600", "value": {"light": "oklch(0.5 0.2 285)"}},
            {"name": "surface-accent", "value": {"light": "{amber-300}"}, "usage": "호박색 주 강조 면"},
            {"name": "brand-primary", "value": {"light": "{violet-600}"}},
            {"name": "text-accent", "value": {"light": "oklch(0.45 0.18 265)", "dark": "oklch(0.7 0.15 265)"}},
            {"name": "accent-loop", "value": {"light": "{accent-loop}"}},
            {"name": "accent-missing", "value": {"light": "{없는-토큰}"}},
            {"name": "brand-site", "link": "oklch(0.5 0.2 285)"}]},
            "type": {"fonts": [{"family": "Pretendard", "file": "fonts/P.woff2"}],
                     "families": {"body": "\"Pretendard\", \"Apple SD Gothic Neo\", sans-serif",
                                  "display": "\"Do Hyeon\", sans-serif", "mono": ["Roboto Mono", "monospace"]}}}
        text = json.dumps(doc, ensure_ascii=False, indent=2)

        def line(needle, nth=1):
            at = -1
            for _ in range(nth):
                at = text.index(needle, at + 1)
            return text[:at].count("\n") + 1
        ref, direct, body = line("{violet-600}"), line("oklch(0.45"), line('"body"')
        self.assertEqual(self.scan("docs/design/system/tokens.json", text), [
            f"docs/design/system/tokens.json:{ref}: 주 강조가 파랑·남색·보라 계열(h 285°) — 근거를 적는다(§1 의 11)",
            f"docs/design/system/tokens.json:{direct}: 주 강조가 파랑·남색·보라 계열(h 265°) — 근거를 적는다(§1 의 11)",
            f"docs/design/system/tokens.json:{body}: 과용 글꼴 Pretendard — §1 의 7"])
        # DTCG 경로 참조 `{a.b.c}` 도 같은 파일 안에서 따라간다
        text = json.dumps({"color": {"blue": {"500": {"$type": "color", "$value": "oklch(0.6 0.15 260)"}},
                                     "primary": {"$type": "color", "$value": "{color.blue.500}"}}}, indent=2)
        self.assertEqual(self.scan("t.json", text),
                         [f"t.json:{line('{color.blue.500}')}: 주 강조가 파랑·남색·보라 계열(h 260°) — 근거를 적는다(§1 의 11)"])

    def test_font_custom_properties(self):
        css = (":root {\n  --font-body: \"Pretendard\", sans-serif;\n  --font-size-lg: 1.25rem;\n"
               "  --bs-font-sans-serif: Inter, sans-serif;\n  --color-accent: #c2410c;\n  --fonts: Roboto;\n"
               "  --fontFamily: Roboto;\n}\n")
        self.assertEqual(self.scan("a.css", css), ["a.css:2: 과용 글꼴 Pretendard — §1 의 7",
                                                   "a.css:4: 과용 글꼴 Inter — §1 의 7",
                                                   "a.css:7: 과용 글꼴 Roboto — §1 의 7"])
        js = "const t = { '--font-display': 'Roboto, serif', fontSize: 12 };\n"
        self.assertEqual(self.scan("a.js", js), ["a.js:1: 과용 글꼴 Roboto — §1 의 7"])

    def test_font_heads_on_one_long_line_are_linear(self):
        # 한 줄에 글꼴 선언 머리가 되풀이돼도 값마다 줄 끝까지 읽지 않는다(실환경 13단계 D1 수정과 함께)
        import time
        for text in ("a{font-family: Inter, " * 50000, "--font-x: " * 100000, "--font-x:a," * 100000,
                     '{"fontFamily": ["Inter", ' * 50000):
            t = time.monotonic()
            self.scan("a.css", text)
            self.assertLess(time.monotonic() - t, 1.5, text[:12])

    def test_performance_bounds(self):
        import time
        css = "".join(".a%d { font-family: SUIT, sans-serif; }\n" % i for i in range(25000))
        js = "".join("fontFamily: {\n" for _ in range(5000))
        big = "{" + ",\n".join('"key_number_%d": "value"' % i for i in range(40000)) + "}"
        for rel, text in (("a.css", css), ("a.json", big), ("a.js", js)):
            t = time.monotonic()
            self.scan(rel, text)
            self.assertLess(time.monotonic() - t, 1.5, rel)

    def test_unclosed_role_object_repeats_are_linear(self):
        # 따옴표 키 뒤에 닫히지 않는 `{` 가 되풀이되는 한 줄(최종 리뷰 4)
        import time
        line = '"primary":{' * 90000 + "\n"
        t = time.monotonic()
        self.scan("t.json", line)
        self.assertLess(time.monotonic() - t, 1.5)

    def test_targets_and_isolation(self):
        root = Path(tempfile.mkdtemp(prefix="hteam-style-")).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in (("src/a.css", ".a { color: #1e3a8a }\n"), ("docs/planning/spec.md", "#1e3a8a\n"),
                          ("scripts/a.py", "'#1e3a8a'\n"), ("docs/design/screens/h/artifact/project/x.html", "#1e3a8a\n")):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        files = ["src/a.css", "docs/planning/spec.md", "scripts/a.py", "docs/design/screens/h/artifact/project/x.html",
                 "../x.css", "src/gone.css"]
        self.assertEqual([x.split("(")[0] for x in style_findings(root, files)], ["src/a.css:1: 과용 기본 색 1개"])
        with mock.patch.object(palette, "load_overused", side_effect=palette._invalid("x")):
            with self.assertRaises(HteamError):
                style_findings(root, files)
            self.assertEqual(style_findings(root, ["docs/planning/spec.md"]), [])  # 볼 파일이 없으면 카탈로그를 읽지 않는다
        self.assertEqual(design_lint(root, files), [])  # 이모지 등 내용 검사는 색·글꼴 경고를 섞지 않는다
        self.assertFalse(has_style_rules(root / "없는 파일.md"))
        (root / "rules.md").write_bytes(b"\xff\xfe")
        self.assertFalse(has_style_rules(root / "rules.md"))
        (root / "rules.md").write_text("x\n" + STYLE_RULES_MARKER + "(…) [기계] [판단]\n", encoding="utf-8")
        self.assertTrue(has_style_rules(root / "rules.md"))


class WebScanTest(unittest.TestCase):
    """13단계 웹 검사(설계 11.13 의 1 웹): 잡는 것과 잡지 않는 것(주석, 속성 값 안의 태그·비교식, 글 하나가 아닌 JS 값, JS 객체 키,
    CSS 글, 크기를 알 수 없는 태그), CSS 템플릿 글, HTML 의 대문자 태그, 대상 파일, 1 MB 입력의 시간."""

    def heads(self, rel, text):
        """`파일:줄: 이름` 부분만(발췌 앞 첫 괄호까지)."""
        return [item.split("(", 1)[0] for item in web_scan(rel, text)]

    def test_transition_values(self):
        css = (".a { transition: all .2s ease; }\n"
               ".b { transition: opacity .2s, max-height .3s; }\n"
               ".c { transition-property: width; }\n"
               ".d { transition: opacity .2s, transform .2s; transition-behavior: allow-discrete; }\n"
               ".e { transition: margin-left .2s, min-width .2s; }\n"
               ".f:has(.top) { --fade-transition: top; }\n"
               ".g { content: 'transition: all .2s'; }\n"
               ".h { color: red;transition: top 1s }\n")
        self.assertEqual(web_scan("src/a.css", css), [
            "src/a.css:1: transition all(transition: all .2s ease; }) — design-rules §6 의 3, web-rules §5 의 1",
            "src/a.css:2: transition max-height(transition: opacity .2s, max-height .3s; }) — design-rules §6 의 3, "
            "web-rules §5 의 1",
            "src/a.css:3: transition width(transition-property: width; }) — design-rules §6 의 3, web-rules §5 의 1",
            "src/a.css:8: transition top(transition: top 1s }) — design-rules §6 의 3, web-rules §5 의 1"])
        jsx = ("<div style={{ transition: 'opacity .2s', left: 0 }} />\n"
               '<div style={{ transition: "height 0.3s" }} />\n'
               "const s = { transitionProperty: 'top' }\n"
               '<p className="transition-all duration-200">x</p>\n'
               '<p className="transition-[max-height,opacity] transition-opacity">x</p>\n'
               "<p transition:slide>Move left</p>\n"
               '{"transition": "all 0.2s", "transition-duration": "200ms"}\n'
               'const t = { transition: enabled ? "opacity .2s" : "none", left: 0 };\n'
               "const u = { transition: theme.transitions.create('width'), top: 0 };\n"
               'const v = { transition: `${prop} .2s`, w: { transition: "left .2s" } };\n'
               'const x = "transition-all";\n'
               '<div style="transition: width .3s">x</div>\n')
        self.assertEqual(self.heads("src/a.tsx", jsx),
                         ["src/a.tsx:2: transition height", "src/a.tsx:3: transition top", "src/a.tsx:4: transition all",
                          "src/a.tsx:5: transition max-height", "src/a.tsx:7: transition all", "src/a.tsx:10: transition left",
                          "src/a.tsx:12: transition width"])

    def test_comments_are_not_code(self):
        # Codex 계획 리뷰 r1·r2: 주석 안의 선언·태그·가져오기(여러 줄 주석 포함)는 경고하지 않는다. 줄 번호는 그대로다. 본문의
        # 아포스트로피가 뒤의 주석을 가리지 않고, `//` 는 줄의 첫 글자일 때만 주석이라 `https://` 는 코드다
        css = ('/* transition: all .2s;\n   @import "old.css"; */\n'
               '.a { color: red; } /* will-change: transform */\n'
               '@import "real.css";\n')
        self.assertEqual(web_scan("src/a.css", css), ["src/a.css:4: CSS @import 1개 — web-rules §6 의 4"])
        scss = ('.a {\n  // transition: all .2s;\n  color: red; }\n'
                '.b { background: url(//cdn.example.com/a.png); transition: top .2s; }\n')
        self.assertEqual(self.heads("src/a.scss", scss), ["src/a.scss:4: transition top"])
        html = ('<!-- <img src="old.png"> -->\n'
                '<!--\n<iframe src="x"></iframe>\n-->\n'
                '<p>https://example.com 참고</p><img src="new.png">\n'
                "<p>Don't worry</p><!-- <img src=x> -->\n")
        self.assertEqual(self.heads("src/a.html", html), ["src/a.html:5: 크기 없는 <img>"])
        tsx = ('// <div onClick={go}>\n'
               '/* <div role="button">\n   <li tabindex="2"> */\n'
               '{/* <span onClick={go}>열기</span> */}\n'
               'const a = { transition: "left .2s" };\n'
               '  // const b = { transition: "all .2s" };\n'
               '<a href="https://example.com/a">링크</a><div tabIndex={3}>x</div>\n'
               "<p>Don't worry</p>{/* <img src=x> */}\n"
               'const u = "https://example.com"; const c = { transition: "top 1s" };\n')
        self.assertEqual(self.heads("src/a.tsx", tsx),
                         ["src/a.tsx:5: transition left", "src/a.tsx:7: 양수 tabindex", "src/a.tsx:9: transition top"])

    def test_strip_comments_keeps_positions(self):
        # 따옴표 글을 가리지 않는다: 글 안의 `/* */` 도 지우고(놓치는 쪽), 줄 가운데의 `//` 는 그대로 둔다
        text = 'a /* x\ny */ b <!-- c\n--> "/* 글 */" // d\n  // e\n{/* f */}\n'
        out = strip_comments(text)
        self.assertEqual(len(out), len(text))
        self.assertEqual(out.split("\n"), ["a     ", "     b       ", '    "       " // d', "      ", "{       }", ""])
        self.assertEqual(strip_comments("  // a\nb", line_comments=False), "  // a\nb")

    def test_css_import_once_per_file(self):
        css = ('@import "tailwindcss";\n@import url("https://fonts.googleapis.com/css2?family=Gowun+Dodum");\n.a {}\n'
               '  @import "./b.css";\n/* @import "c.css"; */\n')
        self.assertEqual(web_scan("src/app.css", css), ["src/app.css:2: CSS @import 2개 — web-rules §6 의 4"])
        self.assertEqual(web_scan("src/app.scss", '@import "vars";\n'), [])  # Sass 의 가져오기
        self.assertEqual(web_scan("src/app.css", '@import "tailwindcss/preflight";\n'), [])
        self.assertEqual(web_scan("src/a.html", '<style>@import "b.css";</style>\n'), [])  # .css 의 줄 머리만 본다

    def test_media_without_size_and_frame_without_title(self):
        html = ('<img src="a.png" alt="">\n'
                '<img src="b.png" alt="" width="40" height="40">\n'
                '<img src="c.png" alt="" width="40">\n'
                '<img class="avatar" src="d.png" alt="">\n'
                '<img className="w-full" src={u} alt="" />\n'
                '<img style="aspect-ratio: 4 / 3" src="e.png" alt="">\n'
                '<video controls :class="cls"></video><video src="m.mp4"></video>\n'
                '<img {...props} />\n'
                '<img alt="a > b" src="x.png"\n'
                '<Img src="x" /><img src="x" onLoad={() => setReady(true)} />\n'
                '<img\n  src="f.png"\n  alt=""\n/>\n'
                '<div title="<img src=x>">x</div>\n'
                '<iframe src="https://example.com/map"></iframe>\n'
                '<iframe title="매장 지도" src="https://example.com/map"></iframe>\n'
                '<iframe :title="t" src="x"></iframe><iframe aria-label="지도" src="y"></iframe>\n')
        self.assertEqual(self.heads("src/a.html", html),
                         ["src/a.html:1: 크기 없는 <img>", "src/a.html:3: 크기 없는 <img>", "src/a.html:7: 크기 없는 <video>",
                          "src/a.html:10: 크기 없는 <img>", "src/a.html:16: title 없는 <iframe>",
                          "src/a.html:18: title 없는 <iframe>"])
        found = web_scan("src/a.html", html)
        self.assertEqual(found[0], 'src/a.html:1: 크기 없는 <img>(<img src="a.png" alt="">) — web-rules §6 의 2')
        self.assertEqual(found[-1],
                         'src/a.html:18: title 없는 <iframe>(<iframe aria-label="지도" src="y"></iframe>) — web-rules §7 의 9')

    def test_keyboard_and_native_controls(self):
        jsx = ('<div tabIndex={2}>x</div>\n'
               '<li tabindex="1">x</li><li tabindex="0">y</li><li tabindex="-1">z</li>\n'
               'const [tabIndex, setTabIndex] = useState(0); tabIndex = 1; <p data-tabindex="3" />\n'
               '<div role="button" tabIndex={0} onClick={go} onKeyDown={key}>열기</div>\n'
               '<div\n  className="card"\n  onClick={() => open(item)}\n>\n'
               '<button onClick={save}>저장</button><span>{a > b ? 1 : 2}</span>\n'
               'el.onclick = go;\n'
               '<span @click.stop="toggle">펼치기</span>\n'
               '<div aria-hidden={count > 0} onClick={go}>x</div>\n'
               '<div data-x={a<b} onClick={go}>y</div>\n'
               "<p title=\"role='button'\">x</p><Box role={'button'} />\n"
               '<div :role="button">a</div><div :role="\'button\'">b</div><i v-bind:tabindex="2" />\n'
               "<p title={'it\\'s fine'} />\n<div onClick={go}>x</div>\n<img src=x>\n")
        self.assertEqual(self.heads("src/a.tsx", jsx),
                         ["src/a.tsx:1: 양수 tabindex", "src/a.tsx:2: 양수 tabindex", 'src/a.tsx:4: role="button"',
                          "src/a.tsx:4: 클릭 처리기를 단 <div>", "src/a.tsx:7: 클릭 처리기를 단 <div>",
                          "src/a.tsx:11: 클릭 처리기를 단 <span>", "src/a.tsx:12: 클릭 처리기를 단 <div>",
                          "src/a.tsx:13: 클릭 처리기를 단 <div>", 'src/a.tsx:14: role="button"', 'src/a.tsx:15: role="button"',
                          "src/a.tsx:15: 양수 tabindex", "src/a.tsx:17: 클릭 처리기를 단 <div>", "src/a.tsx:18: 크기 없는 <img>"])
        found = web_scan("src/a.tsx", jsx)
        self.assertEqual(found[0], "src/a.tsx:1: 양수 tabindex(tabIndex={2}>x</div>) — design-rules §2 의 3")
        self.assertEqual(found[4], "src/a.tsx:7: 클릭 처리기를 단 <div>(onClick={() => open(item)}) — design-rules §2 의 1")

    def test_html_tag_names_ignore_case(self):
        # Codex 계획 리뷰 r2: .html 의 대문자 태그는 같은 네이티브 태그다. 컴포넌트 파일은 소문자 태그만 네이티브다
        text = '<IMG src=x>\n<DIV onclick="go()">x</DIV>\n<Span ONCLICK="go()">y</Span>\n'
        self.assertEqual(self.heads("src/a.html", text),
                         ["src/a.html:1: 크기 없는 <img>", "src/a.html:2: 클릭 처리기를 단 <div>", "src/a.html:3: 클릭 처리기를 단 <span>"])
        self.assertEqual(web_scan("src/A.tsx", text), [])

    def test_css_in_js_templates(self):
        # Codex 계획 리뷰 r2: styled-components·emotion 의 CSS 템플릿 글은 CSS 다. `${…}` 는 지우고 본다
        tsx = ('const Box = styled.div`transition: all .2s; will-change: transform;`;\n'
               'const B = styled(Button).attrs({ type: "button" })`\n'
               '  transition: ${p => p.speed};\n'
               '  will-change: ${(p) => (p.on ? "transform" : "auto")};\n'
               '  &:invalid { color: red; }\n'
               '`;\n'
               'const fade = keyframes`from { opacity: 0 } to { opacity: 1 }`;\n'
               'const c = css`\n  content: "transition: all";\n  transition: height ${d}ms;\n`;\n'
               'const t = `transition: all .2s`;\n')
        self.assertEqual(self.heads("src/a.tsx", tsx),
                         ["src/a.tsx:1: transition all", "src/a.tsx:1: will-change", "src/a.tsx:5: user- 없는 :invalid",
                          "src/a.tsx:10: transition height"])
        self.assertEqual(web_scan("src/a.vue", "<script>const B = styled.div`transition: all .2s;`</script>\n"), [])
        # Codex 계획 리뷰 r3: 머리와 백틱 사이의 TypeScript 타입 인수(겹친 `<…>`, 안의 `=>`)도 CSS 템플릿 글이다
        typed = ('const A = styled.div<{ on: boolean; cb: () => void }>`transition: all .2s;`;\n'
                 'const B = styled(Button)<Props>`transition: all .2s;`;\n'
                 'const C = styled.div.attrs({ type: "button" })<P>`transition: all .2s;`;\n'
                 'const D = styled.div<Map<string, Array<number>>>`will-change: transform;`;\n'
                 'const E = a < b ? 1 : 2; const F = `transition: all`;\n')
        self.assertEqual(self.heads("src/b.tsx", typed),
                         ["src/b.tsx:1: transition all", "src/b.tsx:2: transition all", "src/b.tsx:3: transition all",
                          "src/b.tsx:4: will-change"])

    def test_invalid_and_will_change(self):
        css = ('input:invalid { border-color: red; }\n'
               'input:user-invalid { border-color: red; }\n'
               'form :not(:invalid),\n.b:invalid:focus {\n  color: red;\n}\n'
               '.c::before { content: ":invalid"; }\n'
               '.a { will-change: transform; }\n.b { will-change: auto; }\n')
        self.assertEqual(self.heads("src/a.css", css),
                         ["src/a.css:1: user- 없는 :invalid", "src/a.css:3: user- 없는 :invalid", "src/a.css:4: user- 없는 :invalid",
                          "src/a.css:8: will-change"])
        tsx = ('<input className="invalid:border-red-500 user-invalid:border-red-500 aria-invalid:ring" />\n'
               '<input className={cn("peer-invalid:block", ok && "group-invalid:flex")} />\n'
               'const errors = {invalid:true};\n'
               'form.querySelectorAll(":invalid, :out-of-range");\n'
               'input:invalid { color: red }\n'
               '<p className="will-change-transform will-change-auto">x</p>\n'
               'const s = { willChange: "opacity", w: { willChange: "auto" } };\n'
               'const t = { willChange: isOpen ? "transform" : "auto" };\n')
        self.assertEqual(self.heads("src/a.tsx", tsx),
                         ["src/a.tsx:1: user- 없는 :invalid", "src/a.tsx:2: user- 없는 :invalid", "src/a.tsx:6: will-change",
                          "src/a.tsx:7: will-change"])
        vue = ('<template><input :class="{ \'invalid:ring\': bad }" /></template>\n'
               '<style scoped>\ninput:invalid { color: red }\n.x { transition: height .2s; will-change: top }\n</style>\n'
               '<script>const s = { transition: open ? "height .2s" : "none" }</script>\n')
        self.assertEqual(self.heads("src/a.vue", vue),
                         ["src/a.vue:1: user- 없는 :invalid", "src/a.vue:3: user- 없는 :invalid", "src/a.vue:4: transition height",
                          "src/a.vue:4: will-change"])
        self.assertEqual(web_scan("src/a.css", "a:invalid{}\n"), ["src/a.css:1: user- 없는 :invalid(:invalid{}) — web-rules §3 의 2"])
        self.assertEqual(web_scan("src/a.css", "a{will-change:opacity}\n"),
                         ["src/a.css:1: will-change(will-change:opacity}) — web-rules §6 의 7"])

    def test_targets(self):
        root = Path(tempfile.mkdtemp(prefix="hteam-web-")).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        for rel in ("src/a.html", "docs/design/system/README.md", "docs/planning/spec.md", "scripts/a.py",
                    "docs/design/screens/h/artifact/project/x.html"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text('<div style="transition: all 1s"></div>\n<img src=x>\n', encoding="utf-8")
        files = ["src/a.html", "docs/design/system/README.md", "docs/planning/spec.md", "scripts/a.py",
                 "docs/design/screens/h/artifact/project/x.html", "../x.css", "src/gone.css"]
        self.assertEqual([x.split("(")[0] for x in web_findings(root, files)],
                         ["src/a.html:1: transition all", "src/a.html:2: 크기 없는 <img>"])
        self.assertNotIn(".md", WEB_SUFFIXES)
        self.assertEqual(design_lint(root, files), [])  # 이모지 등 내용 검사는 웹 경고를 섞지 않는다

    def test_linear_on_hostile_input(self):
        import time
        mb = 1 << 20
        cases = {
            "a.css": "transition:" * (mb // 11),
            "b.css": "/*" * (mb // 2),
            "c.html": "<!--" * (mb // 4),
            "d.tsx": "'a" * (mb // 2),
            "e.tsx": "//" * (mb // 2),
            "f.tsx": "`" + "a" * mb,
            "g.html": "<img " * (mb // 5),
            "h.html": "<img>" * (mb // 5),
            "i.tsx": "<div {" * (mb // 6),
            "j.tsx": '<div "' * (mb // 6),
            "k.tsx": "<div " + "x onClick={a} " * (mb // 14),
            "l.tsx": "<div\n onClick={a}\n>\n" * (mb // 18),
            "m.tsx": '<div className={cn("' + "invalid:x " * (mb // 10) + '")}>',
            "n.html": "<style" * (mb // 6),
            "o.html": 'style="' * (mb // 7),
            "p.html": "<style>" + "a{" * (mb // 2),
            "q.css": ".a{transition:all 1s}\n" * (mb // 22),
            "r.css": "@import x;\n" * (mb // 11),
            "s.tsx": 'transition: "' * (mb // 13),
            "t.tsx": "<a b=" * (mb // 5),
            "u.css": "a:invalid " * (mb // 10),
            "v.tsx": "styled.div`" * (mb // 11),
            "w.tsx": "css`${" * (mb // 6),
            "x.tsx": "styled.div.attrs((" * (mb // 18),
            "y.tsx": "css`" + "${'\\" * (mb // 4),
            "z.tsx": "\n  //" * (mb // 5),
            "aa.css": ".a{content:'" * (mb // 12),
            "ab.tsx": "<p title={'\\'" * (mb // 13),
            "ac.css": " " * mb + "transition: all",
            "ad.tsx": ('<div className={"\n' + r'\"a' * 1200 + '\n"} />\n') * 289,  # Codex 계획 리뷰 r3: 이스케이프 따옴표가 많은 깨진 JSX
            "ae.tsx": "styled.div<<<" * (mb // 13),
            "af.tsx": "styled(a)<" + "=" * mb,
        }
        for rel, text in cases.items():
            start = time.monotonic()
            web_scan(rel, text)
            self.assertLess(time.monotonic() - start, 1.5, rel)

    def test_rules_and_docs_name_the_checks(self):
        # 경고가 인용하는 항목이 자동 검사 절에 있고(검사 방식 표기 시험이 [기계] 를 본다) 리뷰 디자인 절·README 가 웹 검사를 적는다
        rules = (ROOT / "templates/design-rules.md").read_text(encoding="utf-8")
        auto = rules[rules.index("## 자동 검사"):rules.index("## 출처")]
        for needle in ("`role=\"button\"`(§2 의 1)", "양수 `tabindex`(§2 의 3)", "(§6 의 3)", "(web-rules §5 의 1)",
                       "(web-rules §3 의 2)", "(web-rules §6 의 2)", "(web-rules §6 의 4", "(web-rules §6 의 7)",
                       "(web-rules §7 의 9)", "(web-rules §7 의 10)", "(web-rules §7 의 3)", "web-rules.md 가 있을 때만",
                       "주석은 보지 않는다", "클래스·style 이 있는 `<img>`·`<video>` 는 크기를 알 수 없어 보지 않는다"):
            self.assertIn(needle, auto)
        review = (ROOT / "templates/review-design.md").read_text(encoding="utf-8")
        self.assertIn("웹 경고(`.herdr-team/web-rules.md` 가 있는 프로젝트에만 나오는", review)
        self.assertIn("표 머리(`<caption>`·`scope`)", review)
        readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("`.herdr-team/web-rules.md` 가 있는 프로젝트만", readme)
        self.assertIn("토글 `aria-expanded`·`aria-pressed`", readme)


class LintCommandTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)

    def test_lint_task_reads_review_target_files(self):
        self.write_spec("T-001", "developer")
        state.create(self.p, "T-001", "developer")
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual((code, out["files"], out["findings"]), (0, [], []), out)  # 아직 띄우지 않았다
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.act_work("T-001", {"src/app.css": ".card { border-left: 4px solid #2563eb; }\n", "src/app.py": "x = 1\n"})
        self.commit("src/other.css", ".x { border-left: 4px solid red; }\n", "다른 커밋")  # [T-001] 이 아니다
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["files"], ["docs/tasks/T-001/report.md", "src/app.css", "src/app.py"])
        self.assertEqual(out["findings"], ["src/app.css:1: 왼쪽 강조 테두리(.card { border-left: 4px solid #2563eb; })"])
        self.assertIsNone(out["text_findings"])  # text-rules.md 가 없는 프로젝트(0.1.x)
        self.commit(".herdr-team/text-rules.md", "# 문구 규칙\n", "chore: 문구 규칙")
        self.commit("src/app.tsx", 'a = "저장됬어요";\n', "[T-001] 문구")
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual(out["text_findings"], ['src/app.tsx:1: 오탈자 "됬"(a = "저장됬어요";)'], out)

    def test_lint_task_findings_merge_diff_and_content_checks(self):
        # 디자인 절과 같은 목록이다: diff 검사 먼저, 내용 검사 뒤. 디렉터 직무가 없어도 낸다(설계 11.6)
        self.commit("src/Btn.tsx", '<button aria-label="닫기"><X/></button>\n', "기존 버튼")
        self.write_spec("T-001", "developer")
        state.create(self.p, "T-001", "developer")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.act_work("T-001", {"src/Btn.tsx": "<button><X/></button>\n<span>🚀</span>\n"})
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual(out["findings"], ["src/Btn.tsx: 지운 줄에서 aria-label 1개가 줄었다(대체가 있는지 확인)",
                                           "src/Btn.tsx:2: 이모지(🚀)"], out)

    def test_style_checks_only_with_13th_stage_rules(self):
        # 색·글꼴 검사의 경고는 13단계 design-rules(§1 의 7·11, §3 의 11)를 인용한다. 프로젝트의 design-rules.md 가 그 판이
        # 아니면 내지 않는다: 옛 프로젝트(Codex 계획 리뷰 r1), palette.md 는 생겼는데 design-rules.md 는 건너뛴 upgrade(r2)
        rules = (ROOT / "templates/design-rules.md").read_text(encoding="utf-8")
        self.assertEqual(sum(line.startswith(STYLE_RULES_MARKER) for line in rules.split("\n")), 1)  # Task 3 이 쓴 표지
        review = (ROOT / "templates/review-design.md").read_text(encoding="utf-8")
        self.assertIn(f"`{STYLE_RULES_MARKER}`", review)  # 리뷰의 director 새 규칙 점검도 같은 줄로 가른다(Task 4)
        self.write_spec("T-001", "developer")
        state.create(self.p, "T-001", "developer")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.act_work("T-001", {"src/app.css": ".a { color: #1e3a8a; font-family: Pretendard, sans-serif; }\n"})
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual((code, out["findings"]), (0, []), out)  # design-rules.md 가 없다
        old = rules[:rules.index("11. 근거 없이 프레임워크")]  # 0.7.2 처럼 §1 의 11 이 없는 사본
        self.commit(".herdr-team/design-rules.md", old, "chore: 옛 규칙")
        self.commit(".herdr-team/palette.md", "# 팔레트 배정\n", "chore: palette.md 만 생긴 upgrade")
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual((code, out["findings"]), (0, []), out)
        self.commit(".herdr-team/design-rules.md", rules, "chore: 0.8.0 upgrade")
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual(out["findings"], ["src/app.css:1: 과용 글꼴 Pretendard — §1 의 7",
                                           "src/app.css:1: 과용 기본 색 1개(#1e3a8a Tailwind blue-900) — design-rules §1 의 11"],
                         out)

    def test_web_checks_only_with_web_rules(self):
        # 13단계 p13d(설계 11.13 의 1 웹): 웹 경고는 web-rules·design-rules 의 웹 항목을 인용한다. 프로젝트에 web-rules.md 가
        # 없으면(upgrade 전) 내지 않는다. 있으면 내용 검사 뒤에 붙는다
        self.write_spec("T-001", "developer")
        state.create(self.p, "T-001", "developer")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.act_work("T-001", {"src/Menu.tsx": "<div onClick={open}>메뉴</div>\n<span>🚀</span>\n"})
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual((code, out["findings"]), (0, ["src/Menu.tsx:2: 이모지(🚀)"]), out)
        self.commit(".herdr-team/web-rules.md", (ROOT / "templates/web-rules.md").read_text(encoding="utf-8"),
                    "chore: 0.8.0 upgrade")
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual(out["findings"], ["src/Menu.tsx:2: 이모지(🚀)",
                                           "src/Menu.tsx:1: 클릭 처리기를 단 <div>(onClick={open}>메뉴</div>) — design-rules §2 의 1"],
                         out)

    def test_lint_task_guard_findings(self):
        # 리뷰 프롬프트의 검사 약화 의심 절과 같은 목록이다(설계 6.6 의 1). 직무와 관계없다
        self.write_spec("T-001", "developer")
        state.create(self.p, "T-001", "developer")
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual((code, out["guard_findings"]), (0, []), out)
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.act_work("T-001", {"src/app.test.ts": "it.skip('저장', () => {});\n"})
        code, out = self.hteam("lint", "--task", "T-001", as_=None)
        self.assertEqual(out["guard_findings"], ["src/app.test.ts:1: 시험 건너뛰기 \".skip(\"(it.skip('저장', () => {});)"],
                         out)

    def test_scaffold_copies_design_rules(self):
        desc = self.tmp / "desc.txt"
        desc.write_text("앱\n")
        code, out = self.hteam("scaffold", "--description-file", str(desc), as_="main")
        self.assertEqual(code, 0, out)
        self.assertIn(".herdr-team/design-rules.md", out["created"])
        text = (self.team / "design-rules.md").read_text(encoding="utf-8")
        self.assertEqual(text, (ROOT / "templates/design-rules.md").read_text(encoding="utf-8"))
        import re
        rules = text[text.index("## §1 금지 목록 (AI 티)"):text.index("## §2 ")]
        self.assertEqual([int(m) for m in re.findall(r"(?m)^(\d+)\. ", rules)], list(range(1, 14)))  # 금지 목록 13개(13단계)
        for needle in ("### 디자인 점검", "`hteam review`", "## 즉시 차단 항목"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
