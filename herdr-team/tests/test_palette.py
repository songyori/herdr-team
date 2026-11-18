"""팔레트 배정(설계 11.10·15.1 13단계): `hteam palette deal` 과 palette.deal."""
import contextlib
import io
import json
import unittest
from collections import Counter
from unittest import mock

from tests.helpers import TeamCase
from hteam import cli, color, palette
from hteam.errors import HteamError

SEEDS = [f"proj:T-{n:03d}:0" for n in range(200)]
BY_ID = {p["id"]: p for p in palette.load_palettes()}


def ks(result: dict) -> list[int]:
    return [palette.bucket(s["hue"][0]) for s in result["slots"]]


class DealTest(unittest.TestCase):
    def test_same_seed_same_result_and_shape(self):
        a = palette.deal("memo:T-004:0")
        self.assertEqual(a, palette.deal("memo:T-004:0"))
        self.assertEqual(list(a), ["seed", "turn", "brand_hue", "excluded_hue", "slots"])
        self.assertEqual((a["seed"], a["turn"], a["brand_hue"], a["excluded_hue"]), ("memo:T-004:0", 0, None, [240, 300]))
        self.assertEqual([s["slot"] for s in a["slots"]], ["A", "B", "C"])
        for s in a["slots"]:
            self.assertEqual(list(s), ["slot", "hue", "posture", "palettes", "body_font"])
            self.assertEqual(s["hue"][1] - s["hue"][0], 30)
            self.assertEqual(list(s["body_font"]), ["id", "name", "class", "license", "url"])
            for p in s["palettes"]:
                self.assertEqual(list(p)[:7], ["id", "source", "license", "accent", "bg", "ink", "mood"])
        self.assertNotEqual(a, palette.deal("memo:T-004:1"))
        json.dumps(a, allow_nan=False)  # JSON 으로 그대로 나간다

    def test_many_seeds(self):
        results = [palette.deal(seed) for seed in SEEDS]
        firsts = Counter(ks(r)[0] for r in results)
        self.assertEqual(set(firsts), set(palette.ALLOWED))  # A 칸이 허용 칸 10개에 퍼진다
        self.assertGreater(len({tuple(ks(r)) for r in results}), 50)  # 시드가 다르면 대체로 다르다
        overused = {palette.font_key(n) for n in palette.load_overused()["fonts_ko"]}
        for seed, r in zip(SEEDS, results):
            with self.subTest(seed=seed):
                k = ks(r)
                self.assertEqual(len(set(k)), 3)
                self.assertTrue(all(palette.gap(x, y) >= 3 for i, x in enumerate(k) for y in k[i + 1:]), k)
                self.assertFalse(set(k) & {8, 9}, k)  # 240–300° 칸은 나오지 않는다
                self.assertEqual(len({s["posture"] for s in r["slots"]}), 3)
                self.assertTrue({s["posture"] for s in r["slots"]} <= set(palette.POSTURES))
                fonts = [s["body_font"] for s in r["slots"]]
                self.assertEqual(len({f["id"] for f in fonts}), 3)
                self.assertFalse({palette.font_key(f["name"]) for f in fonts} & overused)
                for s in r["slots"]:
                    ids = [p["id"] for p in s["palettes"]]
                    self.assertEqual(len(set(ids)), 2, s)
                    for p in s["palettes"]:
                        lo = s["hue"][0]
                        inside = lo <= BY_ID[p["id"]]["hue"] < lo + 30
                        self.assertEqual(p.get("near", False), not inside, p)

    def test_empty_bucket_is_filled_with_near_palettes(self):
        seed = next(s for s in SEEDS if 10 in ks(palette.deal(s)))
        slot = next(s for s in palette.deal(seed)["slots"] if s["hue"] == [300, 330])
        self.assertEqual([p.get("near") for p in slot["palettes"]], [True, True])
        dist = [color.hue_distance(BY_ID[p["id"]]["hue"], 315) for p in slot["palettes"]]
        nearest = sorted(color.hue_distance(p["hue"], 315) for p in palette.load_palettes() if palette.chromatic(p))[:2]
        self.assertEqual(dist, nearest)

    def test_brand_hue_fixes_slot_a(self):
        for hue in (0.0, 41.5, 239.9, 265.5, 299.99, 359.9):
            for seed in SEEDS[:20]:
                r = palette.deal(seed, brand_hue=hue)
                k = ks(r)
                self.assertEqual(k[0], palette.bucket(hue))
                self.assertTrue(all(palette.gap(x, y) >= 3 for i, x in enumerate(k) for y in k[i + 1:]), k)
                self.assertFalse(set(k[1:]) & {8, 9})
                self.assertEqual((r["brand_hue"], r["slots"][0]["palettes"]), (hue, []))
                self.assertEqual([len(s["palettes"]) for s in r["slots"][1:]], [2, 2])
        for first in range(12):
            pairs = palette.brand_pairs(first)
            self.assertTrue(pairs, first)  # 어느 칸을 고정해도 B·C 를 고를 수 있다
            for b, c in pairs:
                self.assertTrue({b, c} <= set(palette.ALLOWED) and palette.gap(b, c) >= 3, (first, b, c))
                self.assertTrue(palette.gap(first, b) >= 3 and palette.gap(first, c) >= 3, (first, b, c))
        # B·C 쌍은 고르게, 차례도 고르게: A 를 0칸에 고정하면 쌍은 (3, 6)·(3, 7)·(4, 7) 셋이고 차례까지 여섯이 다 나온다
        orders = Counter(palette.pick_buckets(palette.Draw(f"b{i}"), 0)[1:] for i in range(600))
        self.assertEqual(set(orders), {(3, 6), (6, 3), (3, 7), (7, 3), (4, 7), (7, 4)})
        self.assertTrue(all(70 < n < 130 for n in orders.values()), orders)

    def test_set_weights_make_every_bucket_equal(self):
        # 설계 11.10: 칸 셋의 집합 20개에 가중치를 줘 칸마다 뽑힐 확률이 같다(각 0.3). 표본이 아니라 가중치로 계산한다
        sets = palette.bucket_sets()
        self.assertEqual(len(sets), 20)
        self.assertTrue(all(palette.gap(a, b) >= 3 for s in sets for a, b in ((s[0], s[1]), (s[0], s[2]), (s[1], s[2]))))
        weights = palette.set_weights()
        self.assertEqual(len(weights), 20)
        self.assertAlmostEqual(sum(weights), 1.0, places=12)
        self.assertTrue(all(w > 0 for w in weights), weights)
        for k, m in palette.marginals(list(weights)).items():
            self.assertAlmostEqual(m, 0.3, delta=1e-9, msg=k)
        self.assertEqual(weights, palette.set_weights())  # 결정적이다
        uniform = palette.marginals([1 / 20] * 20)
        self.assertGreater(max(uniform.values()), 0.45)  # 고르게 뽑으면 빈칸 옆 칸(7·10)이 치우친다

    def test_golden_weights_and_draws(self):
        # Python 판이 바뀌어도 같은 배정이다(합은 math.fsum, 뽑기는 SHA-256). 값이 바뀌면 같은 시드의 배정이 바뀐 것이다
        self.assertEqual([round(w, 12) for w in palette.set_weights()], [
            0.16875, 0.05625, 0.075000000001, 0.099999999999, 0.1, 0.075000000001, 0.01875, 0.00625, 0.056249999999,
            0.16875, 0.0140625, 0.0421875, 0.0046875, 0.0140625, 0.0140625, 0.0421875, 0.0046875, 0.0140625, 0.00625,
            0.01875])
        self.assertEqual(palette.cumulative()[-1], 1.0)
        got = {seed: palette.pick_buckets(palette.Draw(seed)) for seed in ("memo:T-004:0", "budget:1", "clinic:2",
                                                                            "proj:T-001:0")}
        self.assertEqual(got, {"memo:T-004:0": (1, 7, 4), "budget:1": (3, 6, 11), "clinic:2": (7, 4, 1),
                               "proj:T-001:0": (10, 1, 5)})
        self.assertEqual(palette.pick_buckets(palette.Draw("brand"), 8), (8, 5, 2))

    def test_each_bucket_in_about_thirty_percent_of_deals(self):
        counts = Counter(k for n in range(2000) for k in set(ks(palette.deal(f"spread:T-{n:04d}:0"))))
        self.assertEqual(set(counts), set(palette.ALLOWED))
        for k in palette.ALLOWED:
            self.assertTrue(0.27 <= counts[k] / 2000 <= 0.33, (k, counts[k]))
        firsts = Counter(ks(palette.deal(f"spread:T-{n:04d}:0"))[0] for n in range(300))
        self.assertEqual(set(firsts), set(palette.ALLOWED))  # 차례도 섞인다: A 칸이 허용 칸 10개에 퍼진다

    def test_draw_is_unbiased_sha256(self):
        draw = palette.Draw("x")
        self.assertEqual([draw.below(1) for _ in range(3)], [0, 0, 0])
        counts = Counter(palette.Draw(f"s{i}").below(3) for i in range(3000))
        self.assertTrue(all(900 < counts[v] < 1100 for v in range(3)), counts)
        with self.assertRaises(ValueError):
            draw.below(0)
        fractions = [palette.Draw(f"f{i}").fraction() for i in range(2000)]
        self.assertTrue(all(0 <= f < 1 for f in fractions))
        self.assertTrue(0.47 < sum(fractions) / 2000 < 0.53)

    def test_catalog_invalid(self):
        with mock.patch.object(palette, "load_palettes", side_effect=palette._invalid("x")):
            with self.assertRaises(HteamError) as caught:
                palette.deal("a")
        self.assertEqual((caught.exception.code, caught.exception.exit_code), ("catalog_invalid", 1))


class DealCommandTest(TeamCase):
    def setUp(self):
        super().setUp()
        (self.proj / ".herdr-team").mkdir()
        (self.proj / ".herdr-team" / "config.toml").write_text("", encoding="utf-8")

    def test_seed_from_state_root_task_and_turn(self):
        code, out = self.hteam("palette", "deal", "--task", "T-004", as_=None)
        self.assertEqual((code, out["ok"], out["seed"], out["turn"]), (0, True, "proj:T-004:0", 0), out)
        self.assertEqual({k: v for k, v in out.items() if k != "ok"}, palette.deal("proj:T-004:0"))
        code, out = self.hteam("palette", "deal", "--task", "T-004", "--turn", "2", "--brand-hue", "265.5", as_=None)
        self.assertEqual((code, out["seed"], out["turn"], out["brand_hue"]), (0, "proj:T-004:2", 2, 265.5), out)
        self.assertEqual(out["slots"][0]["hue"], [240, 270])
        code, out = self.hteam("palette", "deal", "--task", "T-004", "--seed", "budget:1", as_=None, cwd=self.tmp)
        self.assertEqual((code, out["seed"]), (0, "budget:1"), out)  # --seed 면 프로젝트 밖에서도 된다
        self.assertEqual(sorted(p.name for p in (self.proj / ".herdr-team").iterdir()), ["config.toml"])  # 쓰지 않는다

    def test_usage_errors(self):
        for args in (("--task", "T-4"), ("--task", "t-004"), ("--task", "T-004", "--turn", "-1"),
                     ("--task", "T-004", "--turn", "x"), ("--task", "T-004", "--brand-hue", "360"),
                     ("--task", "T-004", "--brand-hue", "-0.5"), ("--task", "T-004", "--brand-hue", "nan"),
                     ("--task", "T-004", "--brand-hue", "파랑"), ("--task", "T-004", "--seed", " "), ()):
            with self.subTest(args=args):
                code, out = self.hteam("palette", "deal", *args, as_=None)
                self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)

    def test_broken_catalog_is_exit_1(self):
        out = io.StringIO()
        with mock.patch.object(palette, "load_fonts", side_effect=palette._invalid("x")), contextlib.redirect_stdout(out):
            code = cli.main(["--root", str(self.proj), "palette", "deal", "--task", "T-004"])
        self.assertEqual((code, json.loads(out.getvalue())["error"]["code"]), (1, "catalog_invalid"))

if __name__ == "__main__":
    unittest.main()
