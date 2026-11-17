"""색 계산(설계 11.10, 13단계): 색 글을 OKLCH 로 바꾼다. 값은 조사 자료 anti-slop §4 와 CSS Color 4 의 예다."""
from __future__ import annotations

import unittest

import tests.helpers  # noqa: F401  (lib 를 sys.path 에 넣는다)
from hteam import color

RED = (0.62796, 0.25768, 29.2339)


class ColorTest(unittest.TestCase):
    def close(self, got, want, tol=(0.002, 0.002, 0.3)):
        self.assertIsNotNone(got)
        for g, w, t in zip(got, want, tol):
            self.assertAlmostEqual(g, w, delta=t, msg=(got, want))

    def test_hex(self):
        self.close(color.from_hex("#1e3a8a"), (0.379, 0.138, 265.5))  # Tailwind v3 blue-900
        self.close(color.parse("#d97757"), (0.672, 0.131, 38.8))  # Anthropic 군집의 테라코타
        self.close(color.parse("#FF0000"), RED)
        self.close(color.parse("#f00"), RED)
        self.close(color.parse("#ff0000cc"), RED)  # 알파는 버린다
        self.close(color.from_hex("ff0000"), RED)
        white = color.parse("#fff")
        self.assertAlmostEqual(white[0], 1.0, delta=0.001)
        self.assertLess(white[1], 0.001)
        self.assertEqual(white[2], 0.0)  # 무채색 hue 는 0

    def test_functions(self):
        for text in ("rgb(255 0 0)", "rgb(255, 0, 0)", "rgba(255,0,0,0.5)", "rgb(100% 0% 0%)", "hsl(0 100% 50%)",
                     "hsl(0deg, 100%, 50%)", "hsla(360, 100%, 50%, 1)"):
            self.close(color.parse(text), RED)
        self.assertEqual(color.parse("oklch(62.3% 0.214 259.815)"), (0.623, 0.214, 259.815))
        self.assertEqual(color.parse("oklch(0.5 0 none)"), (0.5, 0.0, 0.0))
        self.close(color.parse("OKLCH(0.7 50% 400deg)"), (0.7, 0.2, 40.0))  # C 100% = 0.4, hue 는 360 으로 나눈 나머지

    def test_unreadable(self):
        for text in ("blue", "#12", "#12345", "rgb(x y z)", "oklch(1 2)", "hsl()", "", "oklch(0.6 0.15 nan)",
                     "oklch(inf 0.1 30)", "rgb(nan 0 0)", "hsl(nan 100% 50%)"):
            self.assertIsNone(color.parse(text), text)

    def test_clamp_and_args(self):
        for a, b in (("hsl(0 200% 25%)", "hsl(0 100% 25%)"), ("hsla(0, 200%, 25%, 0.5)", "hsl(0 100% 25%)"),
                     ("hsl(0 -50% 50%)", "hsl(0 0% 50%)"), ("hsl(0 50% 250%)", "hsl(0 50% 100%)")):
            self.assertLess(color.delta(color.parse(a), color.parse(b)), 1e-9, a)
        self.assertEqual(color.parse("oklch(150% 0.1 30)"), (1.0, 0.1, 30.0))
        self.assertEqual(color.parse("oklch(-0.2 0.1 30)")[0], 0.0)
        self.assertEqual(color.parse("oklch(50% -0.2 30)"), (0.5, 0.0, 0.0))
        for text in ("rgb(255 0 0 / 50%)", "oklch(0.6 0.15 30 / 0.8)"):
            self.assertIsNotNone(color.parse(text), text)
        for text in ("rgba(255,0,0,nan)", "oklch(0.6 0.15 30 / inf)", "rgb(255 0 0 garbage garbage)",
                     "rgb(255 0 0 1 1)", "rgb(255 0 0 x)", "rgb(255 0)"):
            self.assertIsNone(color.parse(text), text)

    def test_distances(self):
        self.assertEqual(color.hue_distance(350, 10), 20)
        self.assertEqual(color.hue_distance(10, 350), 20)
        self.assertEqual(color.hue_distance(0, 180), 180)
        self.assertEqual(color.hue_distance(30, 30), 0)
        self.assertLess(color.delta(color.parse("#1e3a8a"), color.parse("#1e3a8b")), 0.01)
        self.assertGreater(color.delta(color.parse("#ff0000"), color.parse("#0000ff")), 0.3)
        L, a, b = color.oklab((0.5, 0.1, 90.0))
        self.assertAlmostEqual(L, 0.5)
        self.assertAlmostEqual(a, 0.0, places=9)
        self.assertAlmostEqual(b, 0.1, places=9)
