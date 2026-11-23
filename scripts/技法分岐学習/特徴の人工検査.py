"""市場・教師を開かず、15特徴の明示期待値と出典・鏡像を検査する。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "技法分岐学習の人工対象", Path(__file__).with_name("特徴.py"))
F = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F)


def exact(value: Fraction | None) -> dict:
    """人工Fast値を保存契約へ写す。

    引数: value(Fraction|None)は明示した精密値又は欠測。
    返り値: dictは表示値・分子・分母・有効旗を持つ。
    """
    return {"value": float(value) if value is not None else None,
            "numerator": value.numerator if value is not None else None,
            "denominator": value.denominator if value is not None else None,
            "valid": value is not None}


def source(index: int, minutes: int = 3, open_: float = 100,
           high: float = 110, low: float = 90, close: float = 100) -> dict:
    """小さな完全公開SOURCEを作る。

    引数: index(int)は番号、minutes(int)は幅、open_/high/low/close(float)は価格。
    返り値: dictは人工場のSOURCE13。数値銀行は呼ばない。
    """
    end = (index + 1) * minutes * 60
    return {"session": "人工場", "index": index, "minutes": minutes,
            "start": index * minutes * 60, "end": end, "confirm": end,
            "confirm_line": 100 + index, "publish": True, "missing": 0,
            "open": open_, "high": high, "low": low, "close": close}


def fixture() -> dict:
    """全15値を手計算できるslotを作る。

    引数: なし。
    返り値: dictは採否旗Falseでも必要材料が揃った人工P0slot。
    """
    current = source(19, open_=120, high=145, low=110, close=135)
    previous = source(18, open_=112, high=130, low=100, close=120)
    upper = source(3, minutes=15, open_=100, high=160, low=80, close=140)
    return {"session": "人工場", "scheduled": 3600, "time": 3600, "line": 999,
            "policy": "P0", "slot_id": "人工枠", "ready": False, "side": 0, "role": "待機",
            "reason": "旧R判定不能: R過去10本の公開完全隣接不足",
            "atr": 25.0, "D": -999,
            "current": current, "previous": previous,
            "OR": {"ready": True, "low": 90, "high": 110, "mid": exact(Fraction(100)),
                   "sources": [source(index) for index in range(10)]},
            "upper": {"ready": True, "source": upper, "plus_di": 30.0, "minus_di": 10.0,
                      "direction": 1, "adx": 999},
            "diagnostic": {"old_R": {"ready": False, "side": 0, "role": "待機",
                                     "current": deepcopy(current),
                                     "fast_k": exact(Fraction(70)),
                                     "fast_change": exact(Fraction(5))}}}


def reflect(slot: dict, center_sum: float = 500) -> dict:
    """価格反射・DI交換・Fast反射を人工入力へ施す。

    引数: slot(dict)は人工slot、center_sum(float)は反射和。
    返り値: dictは入力を改変せず作った反射slot。
    """
    result = deepcopy(slot)
    rows = [result["current"], result["previous"], result["upper"]["source"],
            result["diagnostic"]["old_R"]["current"], *result["OR"]["sources"]]
    for row in rows:
        row["open"], row["close"] = center_sum - row["open"], center_sum - row["close"]
        row["high"], row["low"] = center_sum - row["low"], center_sum - row["high"]
    band = result["OR"]
    band["high"], band["low"] = center_sum - band["low"], center_sum - band["high"]
    band["mid"] = exact((Fraction(band["high"]) + Fraction(band["low"])) / 2)
    upper = result["upper"]
    upper["plus_di"], upper["minus_di"] = upper["minus_di"], upper["plus_di"]
    upper["direction"] = -upper["direction"]
    old = result["diagnostic"]["old_R"]
    old["fast_k"] = exact(100 - Fraction(old["fast_k"]["numerator"], old["fast_k"]["denominator"]))
    old["fast_change"] = exact(-Fraction(old["fast_change"]["numerator"], old["fast_change"]["denominator"]))
    return result


# ----------------------------------------
# 数値は手置き期待値、出典は人工SOURCEだけで検査する。

class FeatureTests(unittest.TestCase):
    """特徴の意味・時点・欠測を互いに異なる境界から検査する。"""

    def test_fifteen_golden_values(self) -> None:
        """全15値と売方向の高安交換を明示した有理数へ照合する。

        引数: なし。
        返り値: None。
        """
        result = F.extract(fixture())
        expected = [Fraction(1, 5), Fraction(2, 5), Fraction(1, 20), Fraction(1, 5),
                    Fraction(4, 5), Fraction(7, 5), Fraction(3, 5), Fraction(3, 5),
                    Fraction(7, 5), Fraction(3, 7), Fraction(3, 5), Fraction(2, 5),
                    Fraction(8, 5), Fraction(16, 5), Fraction(1, 2)]
        sell = [-value if index not in (3, 4, 8, 13) else value
                for index, value in enumerate(expected)]
        sell[10], sell[11] = -Fraction(2, 5), -Fraction(3, 5)
        self.assertTrue(result["ready"], result["reason"])
        self.assertEqual(result["vectors"]["1"], list(map(float, expected)))
        self.assertEqual(result["vectors"]["-1"], list(map(float, sell)))
        self.assertEqual((result["atr"], result["D"], result["background_direction"]), (25, 25, 1))

    def test_metadata_order_and_roles(self) -> None:
        """15列のID順と技法・役割metadataを固定する。

        引数: なし。
        返り値: None。
        """
        self.assertEqual([row["id"] for row in F.FEATURES], [f"F{i:02d}" for i in range(1, 16)])
        self.assertTrue(all(set(row) == {"id", "name", "method", "family", "scale"} for row in F.FEATURES))
        self.assertEqual([row["family"] for row in F.FEATURES], ["trend", "osc", "osc", "vol"] + ["price"] * 11)

    def test_reflection_all_columns(self) -> None:
        """売買反射で同じ実方向15値を完全に保つ。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        a, b = F.extract(slot), F.extract(reflect(slot))
        self.assertTrue(b["ready"], b["reason"])
        self.assertEqual(a["vectors"]["1"], b["vectors"]["-1"])
        self.assertEqual(a["vectors"]["-1"], b["vectors"]["1"])
        self.assertEqual(a["D"], b["D"])
        self.assertEqual(a["background_direction"], -b["background_direction"])

    def test_translation_invariance(self) -> None:
        """一定価格移動で価格の水準を特徴へ混入させない。

        引数: なし。
        返り値: None。
        """
        a = fixture()
        b = deepcopy(a)
        rows = [b["current"], b["previous"], b["upper"]["source"],
                b["diagnostic"]["old_R"]["current"], *b["OR"]["sources"]]
        for row in rows:
            for key in ("open", "high", "low", "close"):
                row[key] += 0.125
        b["OR"]["low"] += 0.125
        b["OR"]["high"] += 0.125
        self.assertEqual(F.extract(a)["vectors"], F.extract(b)["vectors"])

    def test_zero_width_current_and_upper(self) -> None:
        """有効な零幅足のCLVを0にし、欠測としない。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        for row in (slot["current"], slot["upper"]["source"]):
            row.update(open=100, high=100, low=100, close=100)
        slot["diagnostic"]["old_R"]["current"] = deepcopy(slot["current"])
        result = F.extract(slot)
        self.assertTrue(result["ready"], result["reason"])
        for side in ("1", "-1"):
            self.assertEqual([result["vectors"][side][i] for i in (8, 9, 13, 14)], [0] * 4)

    def test_zero_width_opening_range(self) -> None:
        """完全公開で全同値の開始帯も幅0という有効値にする。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        slot["OR"].update(low=100, high=100)
        for row in slot["OR"]["sources"]:
            row.update(open=100, high=100, low=100, close=100)
        result = F.extract(slot)
        self.assertTrue(result["ready"])
        self.assertEqual(result["vectors"]["1"][4], 0)

    def test_price_source_missing_and_invalid(self) -> None:
        """NP・欠枠・部分足・不正OHLCを古い足へ置換しない。

        引数: なし。
        返り値: None。
        """
        changes = ({"publish": False}, {"missing": 1}, {"start": 3421},
                   {"high": 1}, {"open": None}, {"session": "別場"})
        for name in ("current", "previous"):
            for change in changes:
                with self.subTest(name=name, change=change):
                    slot = fixture()
                    slot[name].update(change)
                    result = F.extract(slot)
                    self.assertFalse(result["ready"])
                    self.assertEqual(result["vectors"], {"1": [], "-1": []})

    def test_nonadjacent_sources(self) -> None:
        """番号・終了開始・公開順の隣接不一致を区別して拒否する。

        引数: なし。
        返り値: None。
        """
        for change in ({"index": 17}, {"start": 3239, "end": 3419},
                       {"confirm": 3600, "confirm_line": 119}):
            slot = fixture()
            slot["previous"].update(change)
            self.assertFalse(F.extract(slot)["ready"])

    def test_publication_key_boundary(self) -> None:
        """同秒同原行は可、同秒後行・未来公開は不可とする。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        slot["current"].update(confirm=3600, confirm_line=999)
        slot["diagnostic"]["old_R"]["current"] = deepcopy(slot["current"])
        self.assertTrue(F.extract(slot)["ready"])
        for change in ({"confirm_line": 1000}, {"confirm": 3600.25}):
            other = deepcopy(slot)
            other["current"].update(change)
            self.assertFalse(F.extract(other)["ready"])

    def test_scheduled_end_precedes_quote_visibility(self) -> None:
        """実判断keyまでに公開済みでも予定後終了足は使わない。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        slot["time"] = 3620
        slot["current"].update(start=3430, end=3610, confirm=3610)
        self.assertFalse(F.extract(slot)["ready"])

    def test_current_age_180_inclusive(self) -> None:
        """最新3分の180秒等号を採り、その超過を拒否する。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        slot.update(scheduled=3780, time=3780)
        self.assertTrue(F.extract(slot)["ready"])
        slot.update(scheduled=3781, time=3781)
        self.assertFalse(F.extract(slot)["ready"])

    def test_upper_age_900_inclusive(self) -> None:
        """上位900秒等号と最新不良・未来公開を補完なしで検査する。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        slot["upper"]["source"] = source(2, minutes=15, open_=100, high=160, low=80, close=140)
        self.assertTrue(F.extract(slot)["ready"])
        for change in ({"start": 1799, "end": 2699, "confirm": 2699},
                       {"publish": False}, {"confirm": 3601}, {"missing": 1}):
            other = deepcopy(slot)
            other["upper"]["source"].update(change)
            self.assertFalse(F.extract(other)["ready"])

    def test_opening_range_all_ten_sources(self) -> None:
        """OR.readyだけを信じず1本の未来・欠落・高安不一致も拒否する。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        for change in ({"confirm": 3601}, {"publish": False}, {"missing": 1}, {"index": 99}):
            other = deepcopy(slot)
            other["OR"]["sources"][4].update(change)
            self.assertFalse(F.extract(other)["ready"])
        slot["OR"]["sources"].pop()
        self.assertFalse(F.extract(slot)["ready"])
        slot = fixture()
        slot["OR"]["high"] = 111
        self.assertFalse(F.extract(slot)["ready"])

    def test_old_fast_source_mismatch(self) -> None:
        """Fast出典の番号・価格・公開原行の違いを全SOURCE比較で拒否する。

        引数: なし。
        返り値: None。
        """
        for change in ({"index": 18}, {"close": 134}, {"confirm_line": 118}):
            slot = fixture()
            slot["diagnostic"]["old_R"]["current"].update(change)
            self.assertEqual(F.extract(slot)["reason"], "Fastと現3分出典不一致")

    def test_exact_fast_missing_and_inconsistent(self) -> None:
        """Fast欠測・不正分母・表示不一致を0補完しない。

        引数: なし。
        返り値: None。
        """
        for name in ("fast_k", "fast_change"):
            for value in (exact(None), {"valid": True, "value": 1, "numerator": 1, "denominator": 0},
                          {"valid": True, "value": 2, "numerator": 1, "denominator": 1}):
                slot = fixture()
                slot["diagnostic"]["old_R"][name] = value
                self.assertFalse(F.extract(slot)["ready"])

    def test_fraction_intermediate_and_di_equal(self) -> None:
        """Fast分数と保存floatのDI差を丸めず計算し、DI0も準備可にする。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        slot["diagnostic"]["old_R"].update(fast_k=exact(Fraction(70, 3)), fast_change=exact(Fraction(1, 3)))
        slot["upper"].update(plus_di=0.3, minus_di=0.2)
        result = F.extract(slot)
        self.assertEqual(result["vectors"]["1"][0], float((Fraction(0.3) - Fraction(0.2)) / 100))
        self.assertEqual(result["vectors"]["1"][1], float(Fraction(-8, 15)))
        self.assertEqual(result["vectors"]["1"][2], float(Fraction(1, 300)))
        slot["upper"].update(plus_di=0, minus_di=0)
        result = F.extract(slot)
        self.assertTrue(result["ready"])
        self.assertEqual(result["background_direction"], 0)

    def test_atr_distance_and_missing(self) -> None:
        """現ATRでDを作り、旧Dを使わず5・125の制限と欠測を検査する。

        引数: なし。
        返り値: None。
        """
        for atr, expected in ((0.1, 5), (5, 5), (math.nextafter(5.0, math.inf), 10),
                              (126, 125)):
            slot = fixture()
            slot["atr"] = atr
            self.assertEqual(F.extract(slot)["D"], expected)
        for atr in (0, -1, None, math.nan, math.inf, True):
            slot = fixture()
            slot["atr"] = atr
            self.assertFalse(F.extract(slot)["ready"])

    def test_quote_and_clock_invalid(self) -> None:
        """原行欠測・BBO不正・30秒超の判断を特徴不明として残す。

        引数: なし。
        返り値: None。
        """
        for change in ({"line": None}, {"line": True}, {"reason": "判断BBO不正"},
                       {"time": 3631}, {"time": 3599}):
            slot = fixture()
            slot.update(change)
            result = F.extract(slot)
            self.assertFalse(result["ready"])
            self.assertEqual(result["vectors"], {"1": [], "-1": []})

    def test_old_decision_teacher_and_holdings_irrelevant(self) -> None:
        """旧採否・教師・保有の書換えで出典由来の特徴を変えない。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        expected = F.extract(slot)
        slot.update(ready=True, side=-1, role="反転", labels={"未来": "別値"},
                    operation={"保有": True}, pnl=10**9, D=125, reason="採用")
        slot["diagnostic"]["old_R"].update(ready=True, side=1, role="順行", outcome="250",
                                           structure=None, atr=-999, reason="採用")
        self.assertEqual(F.extract(slot), expected)

    def test_missing_material_and_nonmutation(self) -> None:
        """入力を改変せず欠測字段は理由付き判定不能にする。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        original = deepcopy(slot)
        result = F.extract(slot)
        self.assertEqual(slot, original)
        result["sources"]["current"]["close"] = 1
        self.assertEqual(slot, original)
        for name in ("current", "previous", "OR", "upper", "diagnostic", "session"):
            other = deepcopy(slot)
            del other[name]
            self.assertFalse(F.extract(other)["ready"])
        self.assertFalse(F.extract(None)["ready"])

    def test_extract_performs_no_io(self) -> None:
        """抽出中のファイル読取を禁止し、有限float配列だけを返す。

        引数: なし。
        返り値: None。
        """
        slot = fixture()
        with patch("builtins.open", side_effect=AssertionError("抽出時I/O禁止")), \
                patch("io.open", side_effect=AssertionError("抽出時I/O禁止")):
            result = F.extract(slot)
        self.assertTrue(result["ready"])
        self.assertTrue(all(type(value) is float and math.isfinite(value)
                            for values in result["vectors"].values() for value in values))


if __name__ == "__main__":
    unittest.main(verbosity=2)
