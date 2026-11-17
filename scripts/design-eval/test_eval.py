"""획일도 측정 스크립트의 순수 함수 시험(설계 15.5). claude·codex 를 부르지 않는다."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("design_eval", HERE / "eval.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def option(accent="oklch(0.6 0.15 30)", bg="oklch(0.98 0.01 90)", heading_class="돋움", body_font="SUIT",
           posture="절제"):
    return {"bg": bg, "ink": "oklch(0.2 0.01 90)", "accent": accent, "neutral": "틴트", "heading_font": "Hahmlet",
            "heading_class": heading_class, "body_font": body_font, "posture": posture, "radius": 6,
            "mood": "봄 시장 좌판의 종이 간판", "idea": "영수증 모양 요약"}


def run(*accents, valid=True, **kw):
    if not valid:
        return {"valid": False, "output": None, "error": "JSON 이 아니다"}
    return {"valid": True, "output": {k: option(accent=a, **kw) for k, a in zip("ABC", accents)}}


OVERUSED = {"colors": [{"hex": "#1e3a8a", "name": "Tailwind blue-900"}], "tailwind_ramp": ["#fb923c"],
            "fonts": ["Pretendard", "Noto Sans KR"]}


class EvalTest(unittest.TestCase):
    def test_stage2_is_cut_from_director(self):
        director = (HERE.parents[1] / "herdr-team" / "templates" / "roles" / "director.md").read_text(encoding="utf-8")
        text = ev.stage2(director)
        self.assertTrue(text.startswith("## 단계 ② 톤 시안"))
        self.assertNotIn("## 단계 ③", text)

    def test_parse_output(self):
        self.assertEqual(ev.parse_output('```json\n{"A": 1}\n```'), {"A": 1})
        self.assertEqual(ev.parse_output('{"A": 1}'), {"A": 1})
        self.assertIsNone(ev.parse_output("[1, 2]"))
        self.assertIsNone(ev.parse_output("설명 {"))

    def test_validate(self):
        good = run("oklch(0.6 0.15 30)", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)")["output"]
        self.assertIsNone(ev.validate(good))
        bad = json.loads(json.dumps(good))
        del bad["C"]
        self.assertEqual(ev.validate(bad), "C 가 없다")
        bad = json.loads(json.dumps(good))
        bad["A"]["accent"] = "oklch(0.6 0.01 30)"
        self.assertEqual(ev.validate(bad), "A.accent 가 무채색이다")
        bad = json.loads(json.dumps(good))
        bad["B"]["heading_class"] = "세리프"
        self.assertEqual(ev.validate(bad), "B.heading_class 가 돋움·부리·표시가 아니다")
        bad = json.loads(json.dumps(good))
        bad["B"]["bg"] = "아이보리"
        self.assertEqual(ev.validate(bad), "B.bg 를 색으로 읽지 못했다")
        bad = json.loads(json.dumps(good))
        bad["C"]["mood"] = " "
        self.assertEqual(ev.validate(bad), "C.mood 가 비었다")

    def test_cluster(self):
        self.assertTrue(ev.is_cluster(option(accent="oklch(0.6 0.13 39)", bg="oklch(0.95 0.02 85)", heading_class="부리")))
        self.assertFalse(ev.is_cluster(option(accent="oklch(0.6 0.13 39)", bg="oklch(0.95 0.02 85)")))  # 돋움 제목
        self.assertFalse(ev.is_cluster(option(accent="oklch(0.6 0.13 150)", bg="oklch(0.95 0.02 85)",
                                              heading_class="부리")))

    def test_metrics_count_failed_runs_against_targets(self):
        runs = [run("oklch(0.6 0.15 30)", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)"),  # 거리 90
                run("oklch(0.6 0.15 250)", "oklch(0.6 0.15 280)", "oklch(0.6 0.15 30)", body_font="Pretendard"),
                run(valid=False)]
        m = ev.metrics(runs, OVERUSED)
        self.assertEqual((m["runs"], m["valid"], m["measured"]), (3, 2, False))  # 2/3 < 80%
        self.assertEqual(m["blue_violet"], round((2 + 3) / 9, 3))  # 실패 실행의 세 안은 나쁜 쪽으로 센다
        self.assertEqual(m["spread_ge_60"], round(1 / 3, 3))
        self.assertEqual(m["overused_body"], round((3 + 3) / 9, 3))
        self.assertEqual(m["cluster"], 0)
        self.assertEqual(sum(m["buckets"]), 6)
        self.assertEqual(m["targets"], {"blue_violet_le_20": False, "spread_ge_60_ge_90": False,
                                        "overused_body_le_40": False, "cluster_zero": True})
        hit = run("#1e3a8a", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)")
        self.assertEqual(ev.metrics([hit], OVERUSED)["overused_color_hits"], 1)
        variant = run("oklch(0.6 0.15 30)", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)", body_font="Pretendard Variable")
        self.assertEqual(ev.metrics([variant], OVERUSED)["overused_body"], 1.0)

    def test_judge_prompt_tolerates_missing_optional_fields(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            r = run("oklch(0.6 0.15 30)", "oklch(0.6 0.15 120)", "oklch(0.6 0.15 210)")
            del r["output"]["A"]["idea"]  # 유효 조건에 들지 않는 필드
            r["output"]["B"]["mood"] = "가|나\n둘째 줄"  # 표를 깨는 글자와 개행
            (folder / "budget-1.json").write_text(json.dumps({"brief": "budget", "rep": 1, **r}, ensure_ascii=False),
                                                  encoding="utf-8")
            text = ev.judge_prompt(folder).read_text(encoding="utf-8")
        self.assertIn("| budget | 1 | A |", text)
        self.assertIn("| 봄 시장 좌판의 종이 간판 | - |", text)
        self.assertIn("| 가/나 둘째 줄 |", text)
