"""팔레트·글꼴·과용 카탈로그(설계 11.10·15.1 13단계): 플러그인에 넣는 lib/hteam/data/ 의 스키마, 출처, 라이선스, 칸 덮기."""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests.helpers  # noqa: F401  (lib 를 sys.path 에 넣는다)
from hteam import color, palette
from hteam.errors import HteamError

DATA = palette.DATA


class CatalogTest(unittest.TestCase):
    def test_palettes_schema_and_sources(self):
        raw = json.loads((DATA / "palettes.json").read_text(encoding="utf-8"))
        self.assertEqual([s["id"] for s in raw["sources"]], ["taste-skill", "impeccable"])
        for s in raw["sources"]:
            self.assertRegex(s["commit"], r"^[0-9a-f]{40}$")
            self.assertTrue(s["repo"].startswith("https://github.com/"), s)
            self.assertEqual(set(s) >= {"repo", "commit", "path", "license", "date"}, True, s)
        self.assertEqual({s["id"]: s["license"] for s in raw["sources"]}, {"taste-skill": "MIT", "impeccable": "Apache-2.0"})
        palettes = palette.load_palettes()
        self.assertEqual(palettes, raw["palettes"])
        by_source = {"taste-skill": ("taste:", "MIT"), "impeccable": ("impeccable:", "Apache-2.0")}
        self.assertEqual([sum(p["source"] == s for p in palettes) for s in by_source], [64, 128])
        for p in palettes:
            prefix, lic = by_source[p["source"]]
            self.assertTrue(p["id"].startswith(prefix), p["id"])
            self.assertEqual(p["license"], lic, p["id"])
            lch = color.parse(p["accent"])
            if lch[1] >= color.ACHROMATIC_C:
                self.assertLessEqual(color.hue_distance(lch[2], p["hue"]), 0.05, p["id"])  # hue 는 accent 의 h 다

    def test_chromatic_palettes_cover_nine_allowed_buckets(self):
        covered = {palette.bucket(p["hue"]) for p in palette.load_palettes() if palette.chromatic(p)}
        self.assertEqual(palette.ALLOWED, (0, 1, 2, 3, 4, 5, 6, 7, 10, 11))
        self.assertGreaterEqual(len(covered & set(palette.ALLOWED)), 9)
        self.assertEqual(set(palette.ALLOWED) - covered, {10})  # 300–330° 는 두 출처 모두 비었다(설계 1장 13단계)

    def test_fonts_deal_only_verified_ofl_body_fonts(self):
        fonts = palette.load_fonts()
        self.assertEqual(len(fonts), 23)
        over = palette.load_overused()
        overused = {palette.font_key(n) for n in over["fonts_ko"] + over["fonts_latin"]}
        dealt = [f for f in fonts if f["deal"]]
        self.assertGreaterEqual(len(dealt), 3)
        for f in fonts:
            self.assertIsInstance(f.get("verified"), bool, f["id"])
            self.assertTrue(f["license_url"].startswith("https://") and f["source_url"].startswith("https://"), f["id"])
            if f["deal"]:
                self.assertTrue(f["verified"], f["id"])
                self.assertEqual(f["license"], "OFL-1.1", f["id"])
                self.assertIn(f["class"], ("돋움", "부리"), f["id"])
                self.assertNotIn(palette.font_key(f["name"]), overused, f["id"])
            if not f["verified"]:
                self.assertFalse(f["deal"], f["id"])
                self.assertEqual(f["license"], "확인 못 함", f["id"])

    def test_reserved_font_names_from_license_texts(self):
        # OFL 의 예약 이름(Reserved Font Name): 라이선스 원문의 저작권 줄 뒤 "with Reserved Font Name …"(조사 2026-11-18).
        # 예약 이름이 있는 글꼴을 바꾼 판(서브셋 포함)은 그 이름을 쓸 수 없다(fonts-ko.md 의 4)
        fonts = palette.load_fonts()
        self.assertTrue(all("reserved_name" in f for f in fonts))
        self.assertEqual({f["id"]: f["reserved_name"] for f in fonts if f["reserved_name"] is not None}, {
            "suit": "SUIT", "suite": "SUITE", "spoqa-han-sans-neo": "Spoqa Han Sans, Spoqa Han Sans JP, Spoqa Han Sans Neo",
            "ibm-plex-sans-kr": "Plex",
            "nanum-myeongjo": "Nanum, Naver Nanum, NanumGothic, Naver NanumGothic, NanumMyeongjo, Naver NanumMyeongjo, "
                              "NanumBrush, Naver NanumBrush, NanumPen, Naver NanumPen"})

    def test_overused_lists(self):
        over = palette.load_overused()
        hexes = [c["hex"] for c in over["colors"]]
        self.assertEqual(len(hexes), len(set(hexes)))
        names = {c["hex"]: c["name"] for c in over["colors"]}
        self.assertEqual(names["#1e3a8a"], "Tailwind blue-900")  # 사용자 예시(설계 1장 13단계)
        for h in ("#d97757", "#f4f1ea", "#0d6efd", "#007aff", "#6750a4", "#6200ee", "#0ea5e9", "#10b981"):
            self.assertIn(h, names)
        ramp = over["tailwind_ramp"]
        self.assertEqual(len(ramp), len(set(ramp)))
        self.assertGreaterEqual(len(ramp), 200)
        for c in over["colors"]:
            if c["name"].startswith("Tailwind "):
                self.assertIn(c["hex"], ramp, c)
        self.assertEqual(over["sources"][0]["id"], "tailwindcss")
        for name in ("Pretendard", "Noto Sans KR", "Nanum Gothic", "Apple SD Gothic Neo", "Malgun Gothic", "맑은 고딕",
                     "system-ui", "-apple-system"):
            self.assertIn(name, over["fonts_ko"])
        self.assertEqual(over["fonts_latin"], ["Inter", "Roboto", "Open Sans", "Poppins", "Montserrat", "DM Sans",
                                               "Plus Jakarta Sans", "Space Grotesk", "Geist", "Fraunces"])

    def test_licenses_hold_each_source_text(self):
        text = (DATA / "LICENSES.md").read_text(encoding="utf-8")
        for needle in ("Copyright (c) 2026 Leonxlnx", "Apache License", "Version 2.0, January 2004",
                       "Copyright (c) Tailwind Labs, Inc.", "### impeccable NOTICE.md", "## 바꾼 점",
                       "Apache-2.0 4(b) 의 바꾼 점 알림", "`scripts/import-palettes.py`"):
            self.assertIn(needle, text)
        raw = json.loads((DATA / "palettes.json").read_text(encoding="utf-8"))
        over = json.loads((DATA / "overused.json").read_text(encoding="utf-8"))
        for s in raw["sources"] + over["sources"]:
            self.assertIn(s["commit"], text)
        self.assertIsNone(re.search(r"/[U]sers/|/private/[t]mp|~[/]Workspace|/[h]ome/", text))

    def test_font_key_and_hangul_font(self):
        self.assertEqual(palette.font_key('"Pretendard Variable"'), "pretendard")
        self.assertEqual(palette.font_key("Wanted Sans VF"), "wantedsans")
        self.assertEqual(palette.font_key("맑은 고딕"), "맑은고딕")
        latin = {palette.font_key(n) for n in ("Inter", "Roboto")}
        self.assertEqual(palette.hangul_font(["Inter", "SUIT", "sans-serif"], latin), "SUIT")
        self.assertIsNone(palette.hangul_font(["Inter", "Roboto"], latin))
        self.assertEqual(palette.bucket(359.99), 11)
        self.assertEqual(palette.bucket(360.0), 0)


class BrokenCatalogTest(unittest.TestCase):
    """카탈로그가 깨지면 catalog_invalid(exit 1). 없는 파일, NaN, 빈 글, 겹친 id, 모자란 팔레트·배정 대상."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hteam-catalog-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for f in DATA.glob("*.json"):
            shutil.copy(f, self.tmp / f.name)
        patcher = mock.patch.object(palette, "DATA", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def broken(self, name: str, text: str | None, load) -> str:
        if text is None:
            (self.tmp / name).unlink()
        else:
            (self.tmp / name).write_text(text, encoding="utf-8")
        with self.assertRaises(HteamError) as caught:
            load()
        self.assertEqual((caught.exception.code, caught.exception.exit_code), ("catalog_invalid", 1))
        return caught.exception.message

    def test_palettes(self):
        good = {"id": "x:1", "source": "s", "license": "MIT", "accent": "oklch(0.6 0.15 30)", "bg": None, "ink": None,
                "mood": "m", "hue": 30.0}
        self.assertIn("읽지 못했다", self.broken("palettes.json", None, palette.load_palettes))
        nan = '{"sources": [], "palettes": [{"id": "x:1", "hue": NaN}]}'
        self.assertIn("NaN", self.broken("palettes.json", nan, palette.load_palettes))
        for key, value in {"hue": 360, "accent": "파랑", "bg": 3, "mood": " ", "id": None}.items():
            with self.subTest(key=key):
                text = json.dumps({"sources": [], "palettes": [good, {**good, "id": "x:2", key: value}]})
                self.assertIn("palettes[1]", self.broken("palettes.json", text, palette.load_palettes))
        huge = json.dumps({"sources": [], "palettes": [good, {**good, "id": "x:2", "hue": 10 ** 309}]})
        self.assertIn("hue", self.broken("palettes.json", huge, palette.load_palettes))  # OverflowError 가 아니라 catalog_invalid
        dup = json.dumps({"sources": [], "palettes": [good, good]})
        self.assertIn("겹친다", self.broken("palettes.json", dup, palette.load_palettes))
        grey = json.dumps({"sources": [], "palettes": [good, {**good, "id": "x:2", "accent": "#777777"}]})
        self.assertIn("2개보다 적다", self.broken("palettes.json", grey, palette.load_palettes))
        # 저장한 hue 가 accent 의 실제 h 와 다르면 엉뚱한 칸의 후보가 된다(Codex 계획 리뷰 r2): 실제 카탈로그를 망가뜨린 사본
        real = json.loads((DATA / "palettes.json").read_text(encoding="utf-8"))
        real["palettes"][0].update(accent="oklch(0.6 0.15 265)", hue=35.0)
        self.assertIn("다르다", self.broken("palettes.json", json.dumps(real, ensure_ascii=False), palette.load_palettes))
        near = json.loads((DATA / "palettes.json").read_text(encoding="utf-8"))
        near["palettes"][0].update(accent="oklch(0.6 0.15 265)", hue=265.4)  # 0.5° 안은 받는다
        (self.tmp / "palettes.json").write_text(json.dumps(near, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(palette.load_palettes()[0]["hue"], 265.4)
        self.assertIn("sources", self.broken("palettes.json", "[]", palette.load_palettes))

    def test_fonts_and_overused(self):
        font = {"id": "a", "name": "A", "class": "돋움", "license": "OFL-1.1", "license_url": "https://a",
                "source_url": "https://a", "weights": "400", "variable": False, "deal": True, "verified": True,
                "reserved_name": None}
        two = json.dumps([font, {**font, "id": "b"}, {**font, "id": "c", "deal": False}])
        self.assertIn("3개보다 적다", self.broken("fonts-ko.json", two, palette.load_fonts))
        self.assertIn("class", self.broken("fonts-ko.json", json.dumps([{**font, "class": "고딕"}]), palette.load_fonts))
        self.assertIn("deal", self.broken("fonts-ko.json", json.dumps([{**font, "deal": 1}]), palette.load_fonts))
        no_key = {k: v for k, v in font.items() if k != "reserved_name"}
        self.assertIn("reserved_name", self.broken("fonts-ko.json", json.dumps([no_key]), palette.load_fonts))
        # 배정 대상은 확인한 OFL 본문 글꼴이어야 한다: 실제 카탈로그의 배정 대상 하나를 망가뜨린 사본
        real = json.loads((DATA / "fonts-ko.json").read_text(encoding="utf-8"))
        i = next(n for n, f in enumerate(real) if f["deal"])
        for change in ({"verified": False}, {"license": "확인 못 함"}, {"class": "표시"}, {"name": "Pretendard"},
                       {"name": "Inter Variable"}):
            with self.subTest(change=change):
                bad = [dict(f) for f in real]
                bad[i].update(change)
                self.assertIn("배정 대상", self.broken("fonts-ko.json", json.dumps(bad, ensure_ascii=False),
                                                     palette.load_fonts))  # 과용 글꼴 이름(Pretendard 등)도 받지 않는다
        bad = {"colors": [{"hex": "#ABC", "name": "x"}], "tailwind_ramp": [], "fonts_ko": ["a"], "fonts_latin": ["b"]}
        self.assertIn("overused.json", self.broken("overused.json", json.dumps(bad), palette.load_overused))
        self.assertIn("overused.json", self.broken("overused.json", json.dumps({**bad, "colors": [], "fonts_ko": []}),
                                                   palette.load_overused))


if __name__ == "__main__":
    unittest.main()
