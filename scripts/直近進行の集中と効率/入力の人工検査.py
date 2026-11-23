"""架空の六終値だけで共通準備・精密三値・公開時計を確認する。"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("直近73の人工対象入力", HERE / "入力.py")
I = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = I
SPEC.loader.exec_module(I)


def fixture(differences: list | None = None) -> tuple:
    """実保存値を読まず、現在index14の架空61特徴を作る。

    引数: differences(list|None)は5差分。Noneは単調な1刻み。
    返り値: tuple[dict,dict]はslotと旧61特徴。参照10本・反応5本を持つ。
    """
    differences = [1, 1, 1, 1, 1] if differences is None else differences
    if len(differences) != 5:
        raise ValueError("人工差分は5つが必要")
    closes = [1000]
    for value in differences:
        closes.append(closes[-1] + value)
    rows = []
    for index in range(15):
        close = closes[max(0, index - 9)]
        start = float(1000 + index * 180)
        rows.append({"session": "2026-01-01_Day", "index": index, "minutes": 3, "start": start,
            "end": start + 180, "confirm": start + 180, "confirm_line": index + 1, "publish": True,
            "missing": 0, "open": close, "high": close, "low": close, "close": close})
    slot = {"session": rows[-1]["session"], "slot_id": "人工予定", "scheduled": rows[-1]["end"],
        "time": rows[-1]["confirm"], "line": rows[-1]["confirm_line"]}
    old = {"ready": True, "reason": "", "vectors": {"1": [0.0] * 61, "-1": [0.0] * 61},
        "atr": 50.0, "D": 50.0, "background_direction": 1,
        "base": {"history": {"reference_sources": deepcopy(rows[:10]), "reaction_sources": deepcopy(rows[10:])},
            "base": {"sources": {"current": deepcopy(rows[-1])}}}, "任意の旧項目": {"値": [1, 2, 3]}}
    return slot, old


def sync_current(old: dict) -> None:
    """人工の反応末尾を現在SOURCEにも同じ値で反映する。

    引数: old(dict)は加工中の架空旧特徴。
    返り値: None。現在出典の不一致と時計条件を別々に検査するための補助。
    """
    old["base"]["base"]["sources"]["current"] = deepcopy(old["base"]["history"]["reaction_sources"][-1])


def fractions(progress: dict, side: str = "1") -> list:
    """人工の精密表示をFractionへ戻して期待式と比較する。

    引数: progress(dict)は新診断、side(str)は方向。
    返り値: list[Fraction]はC/E/J。表示floatから期待値を作らない。
    """
    return [Fraction(row["numerator"], row["denominator"]) for row in progress["exact"][side]]


class RecentInputTests(unittest.TestCase):
    """市場も旧入力再構成も起動せず、現在窓だけの契約を検査する。"""

    def test_三反例は同CE別J(self) -> None:
        """2値では失う最大変化の向きと正負同値を区別する。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        for changes, expected in (([-10, 4, 4, 4, 0], -1), ([10, -4, -4, -2, 2], 1), ([10, -10, 1, 1, 0], 0)):
            slot, old = fixture(changes)
            progress = I.recent_values(slot, old)
            self.assertEqual(fractions(progress), [Fraction(5, 11), Fraction(1, 11), Fraction(expected)])
            self.assertEqual(progress["largest"]["mixed_tie"], expected == 0)

    def test_単調と一足集中(self) -> None:
        """同じ純進行でも集中率が異なる架空経路を確認する。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture()
        self.assertEqual(fractions(I.recent_values(slot, old)), [Fraction(1, 5), Fraction(1), Fraction(1)])
        slot, old = fixture([0, 0, 0, 0, 5])
        self.assertEqual(fractions(I.recent_values(slot, old)), [Fraction(1), Fraction(1), Fraction(1)])

    def test_往復E零は有効(self) -> None:
        """純進行0と総変動0を混同しない。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture([1, -1, 1, -1, 0])
        progress = I.recent_values(slot, old)
        self.assertTrue(progress["valid"])
        self.assertEqual(fractions(progress), [Fraction(1, 4), Fraction(0), Fraction(0)])

    def test_TV零は両政策共通落ち(self) -> None:
        """6終値同値は既知J0やE0で補完せず、共通WAITへ分ける。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture([0] * 5)
        b, q = I.extend(slot, old)
        for feature in (b, q):
            self.assertFalse(feature["ready"])
            self.assertEqual(feature["vectors"], {"1": [], "-1": []})
            self.assertEqual(feature["recent_progress"]["TV"]["numerator"], 0)
            self.assertEqual(feature["recent_progress"]["values"], {"1": [], "-1": []})
            self.assertEqual(I.old_projection(feature), old)

    def test_鏡像は方向vector交換(self) -> None:
        """価格反射とside反転により対応三値が同値になる。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture([-10, 4, 4, 4, 0])
        before = I.recent_values(slot, old)
        reflected = deepcopy(old)
        history = reflected["base"]["history"]
        for row in [*history["reference_sources"], *history["reaction_sources"]]:
            row.update(open=3000 - row["open"], close=3000 - row["close"], high=3000 - row["low"], low=3000 - row["high"])
        sync_current(reflected)
        after = I.recent_values(slot, reflected)
        self.assertEqual(before["values"]["1"], after["values"]["-1"])
        self.assertEqual(before["values"]["-1"], after["values"]["1"])
        self.assertEqual(before["values"]["1"][0], before["values"]["-1"][0])
        self.assertEqual(before["values"]["1"][1:], [-v for v in before["values"]["-1"][1:]])

    def test_平行移動と正倍率(self) -> None:
        """絶対価格の位置と単位を変えても比と方向は不変になる。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture([10, -4, -4, -2, 2])
        before = fractions(I.recent_values(slot, old))
        for multiplier, shift in ((1, 500), (10, 0)):
            shifted = deepcopy(old)
            history = shifted["base"]["history"]
            for row in [*history["reference_sources"], *history["reaction_sources"]]:
                for key in ("open", "high", "low", "close"):
                    row[key] = multiplier * row[key] + shift
            sync_current(shifted)
            self.assertEqual(fractions(I.recent_values(slot, shifted)), before)

    def test_並替不変と位置の来歴(self) -> None:
        """三列が順序を識別せず、最大差分の出典だけが変わることを残す。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        a, fa = fixture([5, 0, 0, 0, 0])
        b, fb = fixture([0, 0, 0, 0, 5])
        pa, pb = I.recent_values(a, fa), I.recent_values(b, fb)
        self.assertEqual(pa["values"], pb["values"])
        self.assertNotEqual(pa["largest"]["sources"], pb["largest"]["sources"])

    def test_六終値と旧投影(self) -> None:
        """6出典5差分とB61/Q64、両方の旧全文投影を照合する。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture()
        snapshot = deepcopy(old)
        b, q = I.extend(slot, old)
        self.assertEqual(old, snapshot)
        self.assertEqual([len(b["vectors"]["1"]), len(q["vectors"]["1"])], [61, 64])
        self.assertEqual(I.baseline_projection(q), b)
        self.assertEqual(I.old_projection(b), old)
        self.assertEqual(I.old_projection(q), old)
        self.assertEqual(len(q["recent_progress"]["sources"]), 6)
        self.assertEqual(len(q["recent_progress"]["deltas"]), 5)
        self.assertEqual(len(q["recent_progress"]["deltas_exact"]), 5)

    def test_同秒公開原行の境界(self) -> None:
        """同秒同原行は許し、一行後の確認は当時未公開にする。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture()
        self.assertTrue(I.recent_values(slot, old)["valid"])
        old["base"]["history"]["reaction_sources"][-1]["confirm_line"] += 1
        sync_current(old)
        b, q = I.extend(slot, old)
        self.assertFalse(b["ready"])
        self.assertFalse(q["ready"])
        self.assertIn("未公開", b["reason"])

    def test_予定後の足を使わない(self) -> None:
        """判断timeが遅れていても予定後endの足を取り込まない。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture()
        slot["scheduled"] -= 1
        self.assertFalse(I.recent_values(slot, old)["valid"])
        future = deepcopy(old)
        future["base"]["history"]["reaction_sources"][-1]["close"] = None
        sync_current(future)
        self.assertIn("未公開", I.recent_values(slot, future)["reason"])

    def test_欠足と過去穴を埋めない(self) -> None:
        """窓不足や途中番号穴を古い別足で埋めず共通落ちにする。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture()
        missing = deepcopy(old)
        missing["base"]["history"]["reaction_sources"].pop(1)
        self.assertIn("不足", I.recent_values(slot, missing)["reason"])
        hole = deepcopy(old)
        hole["base"]["history"]["reference_sources"][-1]["index"] = 8
        self.assertIn("不連続", I.recent_values(slot, hole)["reason"])
        self.assertEqual(len(hole["base"]["history"]["reference_sources"]), 10)

    def test_非公開欠枠部分足は共通落ち(self) -> None:
        """完全性の不足を未知とし、両政策を同じ準備へ制御する。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        for field, value in (("publish", False), ("missing", 1), ("start", 3521.0)):
            slot, old = fixture()
            old["base"]["history"]["reaction_sources"][-1][field] = value
            sync_current(old)
            b, q = I.extend(slot, old)
            self.assertFalse(b["ready"])
            self.assertEqual(I.baseline_projection(q), b)

    def test_schema不正とcurrent差は停止(self) -> None:
        """不正出典を通常の共通準備落ちへ隠さない。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        for kind in ("項目", "型", "他場", "重複", "価格", "current", "vector"):
            slot, old = fixture()
            row = old["base"]["history"]["reaction_sources"][0]
            if kind == "項目":
                row.pop("close")
            elif kind == "型":
                row["minutes"] = True
            elif kind == "他場":
                row["session"] = "2026-01-01_Night"
            elif kind == "重複":
                row["index"] = 9
            elif kind == "価格":
                row["close"] = float("nan")
            elif kind == "current":
                old["base"]["base"]["sources"]["current"]["close"] += 1
            else:
                old["vectors"]["1"].pop()
            with self.assertRaises(ValueError):
                I.extend(slot, old)

    def test_旧未準備はそのまま(self) -> None:
        """旧未準備枠では六終値を探して準備を復活させない。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture()
        old.update(ready=False, reason="旧準備不足", vectors={"1": [], "-1": []}, base=None)
        b, q = I.extend(slot, old)
        self.assertFalse(b["ready"])
        self.assertEqual(b["reason"], "旧準備不足")
        self.assertEqual(I.old_projection(q), old)
        self.assertEqual(b["recent_progress"]["sources"], [])

    def test_窓外情報は参照しない(self) -> None:
        """必要6足より前の参照価格や無関係な将来項目で三値を変えない。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        slot, old = fixture([10, -4, -4, -2, 2])
        before = I.recent_values(slot, old)
        changed = deepcopy(old)
        changed["base"]["history"]["reference_sources"][0]["close"] = None
        changed["未来のラベル"] = {"pnl5": 1e100, "outcome": "250"}
        changed["未来足"] = {"end": slot["time"] + 180, "close": None}
        self.assertEqual(I.recent_values(slot, changed), before)

    def test_metadataと旧固定非変更(self) -> None:
        """同61prefixと3つの既存価格票、旧コードのSHAを確認する。

        引数: self(RecentInputTests)は検査先。
        返り値: None。
        """
        self.assertEqual(I.FEATURES[:61], I.BASE_FEATURES)
        self.assertEqual([v["id"] for v in I.FEATURES[61:]], ["F62", "F63", "F64"])
        self.assertTrue(all(v["method"] == "P05" and v["family"] == "price" and v["scale"] == "m03" for v in I.FEATURES[61:]))
        self.assertEqual(hashlib.sha256(I.PREVIOUS_PATH.read_bytes()).hexdigest(), I.PREVIOUS_SHA)


def self_test() -> dict:
    """人工クラスだけを実行し、公式人工へ小型結果を返す。

    引数: なし。
    返り値: dictは成功/テスト件数/失敗/エラー。実入力再構成・学習・市場再生は0。
    """
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=0).run(unittest.defaultTestLoader.loadTestsFromTestCase(RecentInputTests))
    return {"成功": result.wasSuccessful(), "テスト件数": result.testsRun,
        "失敗": [text for _, text in result.failures], "エラー": [text for _, text in result.errors],
        "実入力再構成": False, "fit": 0, "市場再生": False}


if __name__ == "__main__":
    answer = self_test()
    print(json.dumps(answer, ensure_ascii=False, indent=2, allow_nan=False))
    if not answer["成功"]:
        raise SystemExit(1)
