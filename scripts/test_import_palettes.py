"""카탈로그 들여오기 스크립트의 순수 함수 시험(설계 11.10). 네트워크를 쓰지 않는다."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("import_palettes", HERE / "import-palettes.py")
ip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ip)

TASTE = json.dumps([
    {"id": "blue-ink", "name": "Blue ink", "note": "Ink on paper.", "accent": "#1e3a8a", "bg": "#ffffff", "ink": "#111111",
     "surface": "#f4f4f4", "tags": ["x"]},
    {"id": "grey", "name": "Grey", "note": "Only grey.", "accent": "#777777", "bg": "#000000", "ink": "#ffffff"},
])
RS = '''//! Generated. Do not edit.

pub struct Seed { pub id: &'static str, pub l: f64, pub c: f64, pub h: f64, pub mood: &'static str, pub strategy: &'static str }

pub const SEEDS: &[Seed] = &[
    Seed { id: "seed-000", l: 0.4, c: 0.13, h: 0.0, mood: "oxblood \\"leather\\" banquette", strategy: "Near-black bg." },
    Seed { id: "seed-001", l: 0.62, c: 0.15, h: 352.5, mood: "rose", strategy: "White." },
];

pub const TEMPLATE: &str = "Seed { id: \\"not-a-seed\\" }";
'''


def tailwind() -> str:
    shades = (50, 500, 600, 700, 800, 900)
    families = ("slate", "gray", "zinc", "sky", "emerald", "blue", "indigo", "violet", "purple")
    body = ["export default {", "  black: '#000',"]
    for i, fam in enumerate(families):
        body.append(f"  {fam}: {{")
        body += [f"    {s}: '#{i:02x}{s // 10:02x}{s % 251:02x}'," for s in shades]
        body.append("  },")
    body += ["  zinc2: {", "    50: '#fafafa',", "  },", "  get lightBlue() {", "    return this.sky", "  },", "}"]
    return "\n".join(body) + "\n"


LICENSES = {"taste-skill/LICENSE": "MIT License\n\nCopyright (c) 2026 Leonxlnx\n", "impeccable/LICENSE": "Apache\n",
            "impeccable/NOTICE.md": "Notice\n", "tailwindcss/LICENSE": "MIT License\n"}


class ImportTest(unittest.TestCase):
    def test_convert_is_deterministic_and_keeps_text(self):
        out = ip.convert(TASTE, RS, tailwind(), LICENSES)
        self.assertEqual(out, ip.convert(TASTE, RS, tailwind(), LICENSES))
        pal = json.loads(out["palettes.json"])
        self.assertEqual([s["id"] for s in pal["sources"]], ["taste-skill", "impeccable"])
        self.assertEqual(pal["palettes"][0], {"id": "taste:blue-ink", "source": "taste-skill", "license": "MIT",
                                              "accent": "oklch(0.379 0.138 265.5)", "bg": "oklch(1.000 0.000 0.0)",
                                              "ink": "oklch(0.178 0.000 0.0)", "mood": "Blue ink — Ink on paper.",
                                              "hue": 265.5})
        self.assertEqual(pal["palettes"][2], {"id": "impeccable:seed-000", "source": "impeccable", "license": "Apache-2.0",
                                              "accent": "oklch(0.4 0.13 0.0)", "bg": None, "ink": None,
                                              "mood": 'oxblood "leather" banquette', "hue": 0.0})
        self.assertEqual(pal["palettes"][3]["accent"], "oklch(0.62 0.15 352.5)")
        self.assertEqual(len(pal["palettes"]), 4)  # TEMPLATE 안의 Seed 글은 항목이 아니다
        over = json.loads(out["overused.json"])
        self.assertEqual(over["colors"][0]["name"], "Tailwind blue-500")
        self.assertEqual(over["colors"][-1], {"hex": "#d97757", "name": "Anthropic 군집 테라코타"})
        self.assertEqual(len(over["colors"]), 37)
        self.assertEqual(len(over["tailwind_ramp"]), len(set(over["tailwind_ramp"])))
        self.assertNotIn("#000", over["tailwind_ramp"])
        self.assertIn("```text\nMIT License\n\nCopyright (c) 2026 Leonxlnx\n```", out["LICENSES.md"].replace("````", "```"))
        self.assertTrue(out["palettes.json"].endswith("}\n"))

    def test_strict_parsing(self):
        bad_seed = RS.replace('    Seed { id: "seed-001"', '    // 주석\n    Seed { id: "seed-001"')
        with self.assertRaises(ValueError):
            ip.parse_impeccable(bad_seed)
        with self.assertRaises(ValueError):
            ip.parse_impeccable(RS.replace('\\"leather\\"', "\\q"))
        with self.assertRaises(ValueError):
            ip.parse_tailwind(tailwind().replace("    50: '#fafafa',", "    50: colors.x,"))
        with self.assertRaises(ValueError):
            ip.parse_taste(json.dumps([{"id": "a", "name": "A", "note": "n", "accent": "red", "bg": "#fff", "ink": "#000"}]))
        with self.assertRaises(ValueError):
            ip.build_overused([("blue-500", "#3b82f6")])  # 과용 색 이름이 모자라다

    def test_fetch_checks_sha256(self):
        body = b"MIT License\n"

        def opener(url, timeout):
            self.assertTrue(url.startswith("https://raw.githubusercontent.com/Leonxlnx/taste-skill/f6b76575"), url)
            return io.BytesIO(body)

        real = ip.SOURCES["taste-skill"]["files"]["LICENSE"]
        try:
            ip.SOURCES["taste-skill"]["files"]["LICENSE"] = hashlib.sha256(body).hexdigest()
            self.assertEqual(ip.fetch("taste-skill", "LICENSE", opener), "MIT License\n")
            ip.SOURCES["taste-skill"]["files"]["LICENSE"] = "0" * 64
            with self.assertRaises(SystemExit):
                ip.fetch("taste-skill", "LICENSE", opener)
        finally:
            ip.SOURCES["taste-skill"]["files"]["LICENSE"] = real

    def test_committed_data_uses_this_format(self):
        # 네트워크 없이 볼 수 있는 것: 저장소의 데이터 파일이 이 스크립트의 직렬화 꼴 그대로다(손으로 고치지 않았다)
        for name in ("palettes.json", "overused.json"):
            text = (ip.DATA / name).read_text(encoding="utf-8")
            self.assertEqual(ip.dump(json.loads(text)), text, name)
        over = json.loads((ip.DATA / "overused.json").read_text(encoding="utf-8"))
        self.assertEqual((over["fonts_ko"], over["fonts_latin"]), (list(ip.FONTS_KO), list(ip.FONTS_LATIN)))
        licenses = (ip.DATA / "LICENSES.md").read_text(encoding="utf-8")
        self.assertTrue(licenses.startswith(ip.build_licenses(LICENSES).split("## taste-skill (MIT)")[0]))


if __name__ == "__main__":
    unittest.main()
