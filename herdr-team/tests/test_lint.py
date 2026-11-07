"""디자인 자동 검사(설계 11.6): 이모지, 왼쪽 강조 테두리, 파랑·보라 그라디언트, 대상 파일, 상한, `hteam lint --task`."""
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, TeamCase
from hteam import state
from hteam.lint import DESIGN_ROLES, MAX_BYTES, MAX_FINDINGS, design_lint, hue_family, scan
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

    def test_caps_findings(self):
        rel = self.put("docs/design/screens/home/notes.md", "".join(f"{n} 🚀\n" for n in range(MAX_FINDINGS + 10)))
        found = design_lint(self.root, [rel])
        self.assertEqual(len(found), MAX_FINDINGS + 1)
        self.assertEqual(found[-1], "… 외 10건")

    def test_many_gradients_keep_line_numbers(self):
        line = "linear-gradient(blue, purple)\n"
        found = scan("src/ui/many.css", line * 2000)
        self.assertEqual(len(found), 2000)
        self.assertEqual(found[-1].split("(", 1)[0], "src/ui/many.css:2000: 파랑·보라 그라디언트")


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

    def test_scaffold_copies_design_rules(self):
        desc = self.tmp / "desc.txt"
        desc.write_text("앱\n")
        code, out = self.hteam("scaffold", "--description-file", str(desc), as_="main")
        self.assertEqual(code, 0, out)
        self.assertIn(".herdr-team/design-rules.md", out["created"])
        text = (self.team / "design-rules.md").read_text(encoding="utf-8")
        self.assertEqual(text, (ROOT / "templates/design-rules.md").read_text(encoding="utf-8"))
        import re
        self.assertEqual([int(m) for m in re.findall(r"(?m)^(\d+)\. ", text)], list(range(1, 11)))  # 금지 규칙 10개
        for needle in ("### 금지 목록 점검", "hteam lint --task T"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
