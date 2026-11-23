"""市場・教師なしで、固定参照帯と反応旗の意味・可視性・鏡像を検査する。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("局所帯分岐の人工対象", Path(__file__).with_name("特徴.py"))
N = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N)
OLD_SPEC = importlib.util.spec_from_file_location(
    "局所帯分岐の固定51人工材料",
    Path(__file__).resolve().parents[1] / "技法分岐学習/特徴の人工検査.py")
OLD = importlib.util.module_from_spec(OLD_SPEC)
OLD_SPEC.loader.exec_module(OLD)


def fixture(closes: list[float] | None = None, j: int = 24) -> tuple[dict, list[dict]]:
    """参照帯90..110と、明示した反応5終値の人工材料を作る。

    引数: closes(list[float]|None)は反応終値、j(int)は現足番号。
    返り値: tuple[dict,list[dict]]は人工slotと正本SOURCE13。
    """
    slot = OLD.fixture()
    frames = [OLD.source(index) for index in range(j + 1)]
    if j >= 14:
        for index, close in zip(range(j - 4, j + 1), closes or [100] * 5):
            frames[index].update(open=close, close=close, high=close + 1, low=close - 1)
    slot.update(scheduled=(j + 1) * 180, time=(j + 1) * 180)
    slot["current"], slot["previous"] = deepcopy(frames[-1]), deepcopy(frames[-2])
    slot["OR"]["sources"] = deepcopy(frames[:10])
    slot["diagnostic"]["old_R"]["current"] = deepcopy(slot["current"])
    slot["upper"]["source"] = OLD.source(
        (j + 1) // 5 - 1, minutes=15, open_=100, high=160, low=80, close=140)
    return slot, frames


def reflect(slot: dict, frames: list[dict]) -> tuple[dict, list[dict]]:
    """slotと価格正本を同じ定数で売買反射する。

    引数: slot(dict)とframes(list[dict])は人工材料。
    返り値: tuple[dict,list[dict]]は反射後の別入力。
    """
    other, changed = OLD.reflect(slot), deepcopy(frames)
    for row in changed:
        row["open"], row["close"] = 500 - row["open"], 500 - row["close"]
        row["high"], row["low"] = 500 - row["low"], 500 - row["high"]
    return other, changed


class ContextTests(unittest.TestCase):
    """手計算した反応経路を、旧15prefixと独立に確認する。"""

    def test_own_continuation_and_context_values(self) -> None:
        """最初の外切替を数え、局所幅・位置の明示値を検査する。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([115, 112, 114, 116, 115])
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"], result["reason"])
        self.assertEqual(result["control_vectors"]["1"][15:], [float(Fraction(4, 5)), float(Fraction(3, 5))])
        self.assertEqual(result["control_vectors"]["-1"][15:], [float(Fraction(4, 5)), -float(Fraction(3, 5))])
        self.assertEqual(result["history"]["upper"]["out_count"], 1)
        self.assertEqual(result["history"]["upper"]["events"][0]["index"], 20)
        self.assertEqual(result["history"]["contexts"]["1"], {"own_continuation": True, "opposite_return": False, "z": 1})
        self.assertEqual(result["vectors"]["-1"][-1], 0)

    def test_opposite_return_separate_from_di_role(self) -> None:
        """下端外→内の買い旗を作り、DI役割を価格旗へ混ぜない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([85, 90, 95, 97, 100])
        result = N.extract(slot, frames)
        self.assertEqual(result["history"]["contexts"]["1"], {"own_continuation": False, "opposite_return": True, "z": 1})
        self.assertEqual((result["history"]["lower"]["out_count"], result["history"]["lower"]["in_count"]), (1, 1))
        slot["upper"].update(plus_di=10, minus_di=30)
        reversed_di = N.extract(slot, frames)
        self.assertEqual(reversed_di["history"], result["history"])
        self.assertEqual(reversed_di["background_direction"], -1)

    def test_both_flags_and_both_directions_possible(self) -> None:
        """同方向の両旗、両方向のZをORとし、排他的と誤認しない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([85, 95, 115, 105, 115])
        context = N.extract(slot, frames)["history"]["contexts"]["1"]
        self.assertEqual(context, {"own_continuation": True, "opposite_return": True, "z": 1})
        slot, frames = fixture([85, 95, 115, 105, 100])
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertEqual([result["vectors"][s][-1] for s in ("1", "-1")], [1, 1])

    def test_z_zero_ready_and_anchor_inside(self) -> None:
        """無反応・中間帯を準備済みZ0とし、参照端終値でもinsideで始める。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([110] * 5)
        frames[19]["close"] = 110
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertEqual(result["history"]["upper"]["initial_state"], -1)
        self.assertEqual([r["state"] for r in result["history"]["upper"]["states"]], [-1] * 5)
        self.assertEqual([result["vectors"][s][-1] for s in ("1", "-1")], [0, 0])
        self.assertIsNone(result["history"]["upper"]["age_bars"])

    def test_equalities_and_ulp(self) -> None:
        """±5等号とその内側1ULPを精密に分ける。

        引数: なし。
        返り値: None。
        """
        closes = [math.nextafter(115.0, -math.inf), 115, math.nextafter(105.0, math.inf), 105, 110]
        slot, frames = fixture(closes)
        upper = N.extract(slot, frames)["history"]["upper"]
        self.assertEqual([r["state"] for r in upper["states"]], [-1, 1, 1, -1, -1])
        self.assertEqual((upper["out_count"], upper["in_count"], upper["age_bars"]), (1, 1, 1))
        slot, frames = fixture([115, 105, 115, 105, 115])
        upper = N.extract(slot, frames)["history"]["upper"]
        self.assertEqual((upper["out_count"], upper["in_count"], upper["last_change_sign"]), (3, 2, 1))

    def test_reference_fixed_before_reaction(self) -> None:
        """反応5本の極端なヒゲを帯へ混ぜず、終値だけで反応する。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        for row in frames[20:]:
            row.update(high=1000, low=1)
        slot["current"], slot["previous"] = deepcopy(frames[-1]), deepcopy(frames[-2])
        slot["diagnostic"]["old_R"]["current"] = deepcopy(slot["current"])
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertEqual((result["history"]["band"]["low"], result["history"]["band"]["high"]), (90, 110))
        self.assertEqual([result["vectors"][s][-1] for s in ("1", "-1")], [0, 0])

    def test_reference_known_before_first_reaction_observation(self) -> None:
        """参照確認が反応開始後でも、最初の反応公開keyより前なら許す。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([115] * 5, j=14)
        frames[9].update(confirm=1805)
        slot["OR"]["sources"] = deepcopy(frames[:10])
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"], result["reason"])
        self.assertGreater(frames[9]["confirm"], frames[10]["start"])
        frames[9].update(confirm=1980, confirm_line=109)
        slot["OR"]["sources"] = deepcopy(frames[:10])
        self.assertTrue(N.extract(slot, frames)["ready"])
        frames[9]["confirm_line"] = 110
        slot["OR"]["sources"] = deepcopy(frames[:10])
        self.assertFalse(N.extract(slot, frames)["ready"])

    def test_early_and_first_complete_window(self) -> None:
        """j9基礎が準備済みでも局所15本は未知、j14から準備可能とする。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture(j=9)
        result = N.extract(slot, frames)
        self.assertTrue(result["base"]["ready"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["vectors"], {"1": [], "-1": []})
        slot, frames = fixture(j=14)
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertEqual(result["history"]["reference_indices"], list(range(10)))
        self.assertEqual(result["history"]["reaction_indices"], list(range(10, 15)))

    def test_mirror_all_columns(self) -> None:
        """高安反射と実方向交換で18列と両旗を保つ。

        引数: なし。
        返り値: None。
        """
        for closes in ([115] * 5, [85, 90, 95, 97, 100], [85, 95, 115, 105, 115], [100] * 5):
            slot, frames = fixture(closes)
            a = N.extract(slot, frames)
            b = N.extract(*reflect(slot, frames))
            self.assertTrue(a["ready"] and b["ready"])
            self.assertEqual(a["vectors"]["1"], b["vectors"]["-1"])
            self.assertEqual(a["vectors"]["-1"], b["vectors"]["1"])
            self.assertEqual(a["history"]["contexts"]["1"], b["history"]["contexts"]["-1"])

    def test_translation(self) -> None:
        """一定価格移動で局所帯の文脈と反応を変えない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([85, 95, 115, 105, 115])
        before = N.extract(slot, frames)
        other, changed = deepcopy(slot), deepcopy(frames)
        rows = [other["current"], other["previous"], other["upper"]["source"],
                other["diagnostic"]["old_R"]["current"], *other["OR"]["sources"], *changed]
        for row in rows:
            for name in ("open", "high", "low", "close"):
                row[name] += 0.125
        other["OR"]["low"] += 0.125
        other["OR"]["high"] += 0.125
        self.assertEqual(N.extract(other, changed)["vectors"], before["vectors"])

    def test_window_external_past_and_future(self) -> None:
        """参照外の過去・未使用未来を現在帯や反応へ混入させない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture(j=29)
        before = N.extract(slot, frames)
        changed = deepcopy(frames)
        for row in changed[10:15]:
            row.update(high=1000, low=1, close=900)
        changed += [OLD.source(30, close=999), OLD.source(31)]
        self.assertEqual(N.extract(slot, changed), before)

    def test_missing_duplicate_and_invalid(self) -> None:
        """参照・反応の欠足・重複・NP・不完全を両候補未知にする。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        variants = [[r for r in frames if r["index"] != i] for i in (12, 21)]
        variants += [frames + [deepcopy(frames[12])]]
        for change in ({"publish": False}, {"missing": 1}, {"start": 2161}, {"high": 1}):
            changed = deepcopy(frames)
            changed[12].update(change)
            variants.append(changed)
        for changed in variants:
            result = N.extract(slot, changed)
            self.assertTrue(result["base"]["ready"])
            self.assertFalse(result["ready"])
            self.assertEqual((result["control_vectors"], result["vectors"]), ({"1": [], "-1": []}, {"1": [], "-1": []}))

    def test_asof_and_current_or_match(self) -> None:
        """未来公開・予定後終了・OR現在出典差を拒否し、同判断keyは許す。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        changed = deepcopy(frames)
        changed[12]["confirm"] = 4501
        self.assertFalse(N.extract(slot, changed)["ready"])
        changed[12].update(start=4321, end=4501)
        delayed = deepcopy(slot)
        delayed["time"] = 4510
        self.assertFalse(N.extract(delayed, changed)["ready"])
        for index in (4, 24):
            changed = deepcopy(frames)
            changed[index]["close"] -= 0.25
            self.assertFalse(N.extract(slot, changed)["ready"])
        slot["current"].update(confirm=4500, confirm_line=999)
        slot["diagnostic"]["old_R"]["current"] = deepcopy(slot["current"])
        frames[-1] = deepcopy(slot["current"])
        self.assertTrue(N.extract(slot, frames)["ready"])
        frames[-1]["confirm_line"] = 1000
        self.assertFalse(N.extract(slot, frames)["ready"])

    def test_metadata_prefix_and_zero_width(self) -> None:
        """旧15prefixと17/18列を保ち、零幅局所帯も有効とする。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        for row in frames[10:20]:
            row.update(open=100, high=100, low=100, close=100)
        result = N.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertEqual(N.FEATURES[:15], N.F.FEATURES)
        self.assertEqual([m["method"] for m in N.FEATURES[15:]], ["P03", "P06", "P10"])
        for side in ("1", "-1"):
            self.assertEqual(result["vectors"][side][:15], result["base"]["vectors"][side])
            self.assertEqual(result["vectors"][side][:17], result["control_vectors"][side])
            self.assertEqual(result["control_vectors"][side][15:], [0.0, 0.0])
            self.assertEqual((len(result["control_vectors"][side]), len(result["vectors"][side])), (17, 18))

    def test_nonfinite_new_values_are_unknown(self) -> None:
        """有限な入力から追加特徴のfloat表示があふれる場合も補完しない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        slot["atr"] = 1e-300
        for row in frames[10:20]:
            row["high"] = 1e308
        result = N.extract(slot, frames)
        self.assertTrue(result["base"]["ready"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["vectors"], {"1": [], "-1": []})

    def test_base_unknown_nonmutation_and_no_io(self) -> None:
        """基礎不明を救済せず、準備済み抽出でもI/Oや入力改変をしない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([115] * 5)
        before = deepcopy((slot, frames, N.F.FEATURES))
        with patch("builtins.open", side_effect=AssertionError("抽出時I/O禁止")), \
                patch("io.open", side_effect=AssertionError("抽出時I/O禁止")):
            result = N.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertEqual((slot, frames, N.F.FEATURES), before)
        result["history"]["reference_sources"][0]["close"] = 999
        self.assertEqual((slot, frames, N.F.FEATURES), before)
        slot["atr"] = None
        self.assertTrue(N.extract(slot, object())["reason"].startswith("基礎特徴未準備: "))


if __name__ == "__main__":
    unittest.main(verbosity=2)
