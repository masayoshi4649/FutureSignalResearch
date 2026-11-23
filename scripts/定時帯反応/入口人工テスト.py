"""原板・キャッシュ・試行結果を開かず、入口の数値と時計を人工検査する。"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("定時帯反応の人工対象", Path(__file__).with_name("入口.py"))
I = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = I
SPEC.loader.exec_module(I)


def frame(index: int, close: float = 100, minutes: int = 3, begin: float = 0,
          high: float | None = None, low: float | None = None) -> dict:
    """一つの完全公開足を人工生成する。

    引数: index(int)は番号、close(float)は終値、minutes(int)は幅、begin(float)は場開始、
        high(float|None)/low(float|None)は任意の高安。
    返り値: dictはSOURCE12だけ。ファイルを参照しない。
    """
    end = begin + (index + 1) * minutes * 60
    return {"index": index, "minutes": minutes, "start": begin + index * minutes * 60,
            "end": end, "confirm": end, "confirm_line": index + 1,
            "publish": True, "missing": 0, "open": close,
            "high": close + 5 if high is None else high,
            "low": close - 5 if low is None else low, "close": close}


def session(name: str = "人工場", begin: float = 0, count: int = 30,
            contract: tuple = ("人工2026-12",)) -> dict:
    """3/15分が同じ場幅を覆う小さい人工セッションを作る。

    引数: name(str)は場名、begin(float)は開始、count(int)は3分本数、
        contract(tuple)は限月。
    返り値: dictはbuild_bankへの入力。本数は5の倍数を使う。
    """
    return {"session": name, "contract": contract, "begin": begin, "end": begin + count * 180,
            "frames3": [frame(index, begin=begin) for index in range(count)],
            "frames15": [frame(index, minutes=15, begin=begin) for index in range(count // 5)]}


def fixture(kind: str = "T") -> tuple[dict, float]:
    """OR90〜110に対する順行又は反転の小系列を作る。

    引数: kind(str)はT又はR。
    返り値: tuple[dict,float]は銀行入力とindex19の予定時計。
    """
    item = session()
    rows = item["frames3"]
    for index in range(10):
        rows[index] = frame(index, high=110, low=90)
    if kind == "T":
        for index in range(10, 20):
            value = 102 + 2 * (index - 10)
            rows[index] = frame(index, close=value, high=value + 2, low=value - 2)
    else:
        for index in range(10, 18):
            rows[index] = frame(index, close=108, high=110, low=106)
        rows[16] = frame(16, close=108, high=120, low=106)
        rows[18] = frame(18, close=104, high=106, low=102)
        rows[19] = frame(19, close=103, high=105, low=101)
    return item, 3600


def reflected(item: dict, center: float = 300) -> dict:
    """人工価格だけを一定値から反射する。

    引数: item(dict)はセッション、center(float)は反射定数。
    返り値: dictは時点と番号を変えない深い写し。
    """
    result = deepcopy(item)
    for rows in (result["frames3"], result["frames15"]):
        for row in rows:
            row["open"], row["close"] = center - row["open"], center - row["close"]
            row["high"], row["low"] = center - row["low"], center - row["high"]
    return result


def evaluate(item: dict, scheduled: float = 3600, policy: str = "S0",
             time: float | None = None, line: int = 999) -> tuple[dict, dict]:
    """人工場を一度だけ構築し、一枠を評価する。

    引数: item(dict)は人工場、scheduled(float)は予定、policy(str)は候補、
        time(float|None)/line(int)は実判断key。
    返り値: tuple[dict,dict]は判断と銀行。
    """
    bank = I.build_bank([item])
    return I.evaluate_slot(bank, item["session"], scheduled, scheduled if time is None else time, line, policy), bank


class NumericTests(unittest.TestCase):
    """明示式・手計算期待値で数値銀行を検査する。"""

    def test_atr_and_fast_seed(self) -> None:
        """ATR14本種とFast14/現前15本種を検査する。

        引数: なし。
        返り値: None。
        """
        rows = [frame(index, close=100 + index) for index in range(30)]
        output, _ = I.NumericBank(3).build(rows, "人工", ("限月",), 0, 5400)
        self.assertIsNone(output[12]["atr"])
        self.assertEqual(output[13]["atr"], 10)
        self.assertFalse(output[12]["fast_k"]["valid"])
        self.assertEqual(I.fraction(output[13]["fast_k"]), Fraction(1800, 23))
        self.assertFalse(output[13]["fast_change"]["valid"])
        self.assertEqual(I.fraction(output[14]["fast_change"]), 0)

    def test_dmi_and_adx_seed(self) -> None:
        """14差分でDI10、14DXでADX100となる直線高安を検査する。

        引数: なし。
        返り値: None。
        """
        rows = [frame(index, close=100 + index, minutes=15) for index in range(30)]
        output, _ = I.NumericBank(15).build(rows, "人工", ("限月",), 0, 27000)
        self.assertIsNone(output[13]["plus_di"])
        self.assertEqual(output[14]["plus_di"], 10)
        self.assertEqual(output[14]["minus_di"], 0)
        self.assertIsNone(output[26]["adx"])
        self.assertEqual(output[27]["adx"], 100)

    def test_tr_zero_and_di_zero_are_distinct(self) -> None:
        """TR0の欠測と、TR正・DM両0の準備済み0を区別する。

        引数: なし。
        返り値: None。
        """
        for width, expected in ((0, None), (2, 0)):
            rows = [frame(index, high=100 + width, low=100 - width, minutes=15) for index in range(30)]
            output, _ = I.NumericBank(15).build(rows, "人工", ("限月",), 0, 27000)
            self.assertEqual(output[20]["plus_di"], expected)
            self.assertEqual(output[20]["minus_di"], expected)
        self.assertEqual(output[27]["adx"], 0)

    def test_carry_contract_and_tail(self) -> None:
        """場間だけでは保持し、限月変更と末尾欠枠で解除する。

        引数: なし。
        返り値: None。
        """
        for changed, tail in ((False, False), (True, False), (False, True)):
            numeric = I.NumericBank(3)
            first = [frame(index) for index in range(20)]
            numeric.build(first, "前場", ("A",), 0, 3780 if tail else 3600)
            output, _ = numeric.build([frame(0, begin=10000)], "次場",
                                      ("B",) if changed else ("A",), 10000, 10180)
            self.assertEqual(output[0]["numeric_count"], 1 if changed or tail else 21)
            self.assertEqual(output[0]["atr"], None if changed or tail else 10)

    def test_gap_seed_and_bad_noninsertion(self) -> None:
        """番号飛越の有効当足は種にし、NP/missing/部分/不正当足は投入しない。

        引数: なし。
        返り値: None。
        """
        for kind in ("gap", "NP", "missing", "partial", "bad"):
            rows = [frame(index) for index in range(20)]
            if kind == "gap":
                del rows[16]
            elif kind == "NP":
                rows[16]["publish"] = False
            elif kind == "missing":
                rows[16]["missing"] = 1
            elif kind == "partial":
                rows[16]["start"] += 1
            else:
                rows[16]["close"] = math.nan
            output, _ = I.NumericBank(3).build(rows, "人工", ("A",), 0, 3600)
            indexed = {row["index"]: row for row in output}
            self.assertEqual(indexed[17]["numeric_count"], 1)
            if kind != "gap":
                self.assertFalse(indexed[16]["valid"])

    def test_fast_zero_width_breaks_connection(self) -> None:
        """14幅0はK未定義とし、次Kを過去Kへ接続しない。

        引数: なし。
        返り値: None。
        """
        rows = [frame(index, high=100, low=100) for index in range(20)]
        rows[18] = frame(18, close=101, high=101, low=100)
        output, _ = I.NumericBank(3).build(rows, "人工", ("A",), 0, 3600)
        self.assertFalse(output[17]["fast_k"]["valid"])
        self.assertTrue(output[18]["fast_k"]["valid"])
        self.assertFalse(output[18]["fast_change"]["valid"])

    def test_reflection_numeric(self) -> None:
        """反射でATR不変、K補数、DI交換になることを検査する。

        引数: なし。
        返り値: None。
        """
        item = session(count=150)
        item["frames3"] = [frame(index, close=100 + index / 4) for index in range(150)]
        item["frames15"] = [frame(index, close=100 + index, minutes=15) for index in range(30)]
        a, b = I.build_bank([item]), I.build_bank([reflected(item)])
        for left, right in zip(a["人工場"]["frames3"], b["人工場"]["frames3"]):
            self.assertEqual(left["atr"], right["atr"])
            if left["fast_k"]["valid"]:
                self.assertEqual(I.fraction(left["fast_k"]) + I.fraction(right["fast_k"]), 100)
            if left["fast_change"]["valid"]:
                self.assertEqual(I.fraction(left["fast_change"]), -I.fraction(right["fast_change"]))
        for left, right in zip(a["人工場"]["frames15"], b["人工場"]["frames15"]):
            self.assertEqual(left["plus_di"], right["minus_di"])
            self.assertEqual(left["minus_di"], right["plus_di"])

    def test_distance_exact_boundaries(self) -> None:
        """上方5pt丸め、1ULP上、125上限を明示値へ照合する。

        引数: なし。
        返り値: None。
        """
        for value, expected in ((0.1, 5), (5, 5), (math.nextafter(5, math.inf), 10),
                                (120, 120), (120.1, 125), (999, 125)):
            self.assertEqual(I.distance(value), expected)
        with self.assertRaises(I.InputError):
            I.distance(0)

    def test_source_sequence_rejection(self) -> None:
        """公開キー同値/後退と番号重複を補正せず拒否する。

        引数: なし。
        返り値: None。
        """
        for kind in ("key", "index"):
            item = session()
            if kind == "key":
                item["frames3"][1]["confirm"] = item["frames3"][0]["confirm"]
                item["frames3"][1]["confirm_line"] = item["frames3"][0]["confirm_line"]
            else:
                item["frames3"][1]["index"] = 0
            with self.assertRaises(I.InputError):
                I.build_bank([item])


class DecisionTests(unittest.TestCase):
    """人工価格と公開keyから、枠の判断を直接検査する。"""

    def test_t_and_r_with_reflection(self) -> None:
        """順行買いと反転売り、およびそれぞれの鏡像を確認する。

        引数: なし。
        返り値: None。
        """
        for kind, side, role in (("T", 1, "順行"), ("R", -1, "反転")):
            item, scheduled = fixture(kind)
            for mirror, expected in ((False, side), (True, -side)):
                result, _ = evaluate(reflected(item) if mirror else item, scheduled)
                self.assertTrue(result["ready"])
                self.assertEqual((result["side"], result["role"], result["kind"]), (expected, role, kind))
                if kind == "R":
                    self.assertEqual(result["excursion"]["index"], 16)

    def test_or_publication_is_keyed(self) -> None:
        """OR最終足の未公開を補完せず、同秒の原行境界で利用可能にする。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture()
        item["frames3"][9]["confirm"] = 1801
        a, bank = evaluate(item, scheduled=1800, time=1800)
        b = I.evaluate_slot(bank, "人工場", 1800, 1801, 9, "S0")
        c = I.evaluate_slot(bank, "人工場", 1800, 1801, 10, "S0")
        self.assertFalse(a["OR"]["ready"])
        self.assertFalse(b["OR"]["ready"])
        self.assertTrue(c["OR"]["ready"])

    def test_delayed_latest_fallback_and_staleness(self) -> None:
        """未公開最新端は前足可とし、180秒等号だけ許可する。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture()
        item["frames3"][20]["confirm"] = 4000
        # 次の公開足も後にし、公開順の後退を作らない。
        item["frames3"][21]["confirm"] = 4001
        a, bank = evaluate(item, scheduled=3780)
        self.assertTrue(a["ready"])
        self.assertEqual(a["current"]["index"], 19)
        b = I.evaluate_slot(bank, "人工場", 3781, 3781, 999, "S0")
        self.assertFalse(b["ready"])
        self.assertEqual(b["reason"], "最新3分足が180秒超過")

    def test_bad_visible_latest_does_not_fallback(self) -> None:
        """最新の公開足が不正なら古い正常足へ戻さない。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture()
        item["frames3"][19]["high"] = 1
        result, _ = evaluate(item)
        self.assertFalse(result["ready"])
        self.assertEqual(result["current"]["index"], 19)

    def test_r_excursion_order_and_or_exclusion(self) -> None:
        """外到達は現/前足とOR10本を除き、最近の適格足を採る。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture("R")
        item["frames3"][16]["high"] = 110
        item["frames3"][18]["high"] = 120
        result, _ = evaluate(item)
        self.assertTrue(result["ready"])
        self.assertEqual(result["side"], 0)
        item["frames3"][17]["high"] = 121
        result, _ = evaluate(item)
        self.assertEqual(result["side"], -1)
        self.assertEqual(result["excursion"]["index"], 17)

    def test_mid_and_exact_buffer_equalities(self) -> None:
        """帯中央等号と外側バッファ等号を採用へ混ぜない。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture("R")
        item["frames3"][19] = frame(19, close=100)
        result, _ = evaluate(item)
        self.assertTrue(result["ready"])
        self.assertEqual(result["side"], 0)
        item, _ = fixture("T")
        item["frames3"][17] = frame(17, close=115)
        result, _ = evaluate(item)
        self.assertTrue(result["ready"])
        self.assertEqual(result["side"], 0)

    def test_previous_return_is_only_one_boundary(self) -> None:
        """前終値の反対端越えを、未指定のANDとして加えない。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture("R")
        item["frames3"][18] = frame(18, close=80)
        bank = I.build_bank([item])["人工場"]
        band = I.opening_range(bank["frames3"], 0, 3600, 3600, 999)
        shape = I.structure(bank["frames3"], bank["frames3"][19], band, 3600, 999)
        self.assertEqual([(row["kind"], row["side"]) for row in shape["candidates"]], [("R", -1)])

    def test_r_ten_window_does_not_gate_t(self) -> None:
        """Rだけに必要な10本不足で、3本完成Tを落とさない。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture("T")
        rows = I.build_bank([item])["人工場"]["frames3"]
        band = I.opening_range(rows, 0, 3600, 3600, 999)
        shortened = [row for row in rows if row["index"] != 12]
        shape = I.structure(shortened, rows[19], band, 3600, 999)
        self.assertTrue(shape["ready"])
        self.assertEqual(shape["candidates"][0]["kind"], "T")
        item, _ = fixture("R")
        rows = I.build_bank([item])["人工場"]["frames3"]
        shape = I.structure([row for row in rows if row["index"] != 12],
                            rows[19], band, 3600, 999)
        self.assertFalse(shape["ready"])
        self.assertIn("10本", shape["reason"])

    def test_s0_does_not_require_upper(self) -> None:
        """S0の上位なしを維持し、S1準備不足は待機と別にする。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture("T")
        s0, bank = evaluate(item)
        s1 = I.evaluate_slot(bank, "人工場", 3600, 3600, 999, "S1")
        self.assertEqual(s0["side"], 1)
        self.assertFalse(s1["ready"])

    def test_di_equality_t_rejected_r_allowed(self) -> None:
        """DI等号は順行不採用、反転は旧外方向禁止なしとして許可する。

        引数: なし。
        返り値: None。
        """
        for kind, expected in (("T", 0), ("R", -1)):
            item, _ = fixture(kind)
            bank = I.build_bank([item])
            upper = bank["人工場"]["frames15"][3]
            upper.update(plus_di=0.0, minus_di=0.0)
            result = I.evaluate_slot(bank, "人工場", 3600, 3600, 999, "S1")
            self.assertTrue(result["ready"])
            self.assertEqual(result["side"], expected)
            upper.update(plus_di=20.0, minus_di=10.0)
            result = I.evaluate_slot(bank, "人工場", 3600, 3600, 999, "S1")
            self.assertEqual(result["side"], 1 if kind == "T" else 0)

    def test_upper_stale_and_latest_unready(self) -> None:
        """上位900秒等号は可、最新準備不足は古正常へ戻さない。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture("T")
        bank = I.build_bank([item])
        upper = bank["人工場"]["frames15"]
        upper[2].update(plus_di=20, minus_di=10)
        upper[3]["publish"] = False
        a = I.evaluate_slot(bank, "人工場", 3600, 3600, 999, "S1")
        self.assertTrue(a["ready"])
        b = I.evaluate_slot(bank, "人工場", 3601, 3601, 999, "S1")
        self.assertFalse(b["ready"])
        upper[3]["publish"] = True
        c = I.evaluate_slot(bank, "人工場", 3600, 3600, 999, "S1")
        self.assertFalse(c["ready"])
        self.assertEqual(c["upper"]["index"], 3)

    def test_fast_zero_and_progress_zero(self) -> None:
        """順行進行0は可、水準50等号と反転進行0は不可とする。

        引数: なし。
        返り値: None。
        """
        for kind in ("T", "R"):
            item, _ = fixture(kind)
            bank = I.build_bank([item])
            row = bank["人工場"]["frames3"][19]
            row.update(fast_k=I.exact(Fraction(60)), fast_change=I.exact(Fraction(0)))
            result = I.evaluate_slot(bank, "人工場", 3600, 3600, 999, "S0")
            self.assertEqual(result["side"], 1 if kind == "T" else 0)
            if kind == "T":
                row["fast_k"] = I.exact(Fraction(50))
                result = I.evaluate_slot(bank, "人工場", 3600, 3600, 999, "S0")
                self.assertEqual(result["side"], 0)

    def test_conflict_defense(self) -> None:
        """構造から通常は到達しない複数候補を、防御契約として全見送りにする。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture("T")
        bank = I.build_bank([item])
        shape = {"ready": True, "recent": None, "reason": "", "excursion": None,
                 "candidates": [{"kind": "T"}, {"kind": "R"}]}
        with patch.object(I, "structure", return_value=shape):
            result = I.evaluate_slot(bank, "人工場", 3600, 3600, 999, "S0")
        self.assertTrue(result["ready"])
        self.assertEqual(result["reason"], "T/R同時候補WAIT")

    def test_future_prefix_and_input_nonmutation(self) -> None:
        """未来OHLC・公開の追加で過去判断を変えず、入力を改変しない。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture("R")
        original = deepcopy(item)
        full, _ = evaluate(item)
        self.assertEqual(item, original)
        short = deepcopy(item)
        short["frames3"] = short["frames3"][:20]
        short["frames15"] = short["frames15"][:4]
        prefix, _ = evaluate(short)
        self.assertEqual(full, prefix)
        for index in range(20, 30):
            item["frames3"][index] = frame(index, close=250 + index)
        future, _ = evaluate(item)
        self.assertEqual(full, future)

    def test_clock_and_policy_errors(self) -> None:
        """実判断猶予外と未知候補を入力エラーへ分ける。

        引数: なし。
        返り値: None。
        """
        item, _ = fixture()
        bank = I.build_bank([item])
        for time, policy in ((3599, "S0"), (3631, "S0"), (3600, "不明")):
            with self.assertRaises(I.InputError):
                I.evaluate_slot(bank, "人工場", 3600, time, 999, policy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
