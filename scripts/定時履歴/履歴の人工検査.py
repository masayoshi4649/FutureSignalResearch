"""市場・教師なしで、窓内二端履歴と同準備対照を検査する。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("定時履歴の人工対象", Path(__file__).with_name("履歴.py"))
H = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(H)
OLD_SPEC = importlib.util.spec_from_file_location(
    "定時履歴の固定51人工材料",
    Path(__file__).resolve().parents[1] / "技法分岐学習/特徴の人工検査.py")
OLD = importlib.util.module_from_spec(OLD_SPEC)
OLD_SPEC.loader.exec_module(OLD)


def fixture(closes: list[float] | None = None, end_index: int = 19) -> tuple[dict, list[dict]]:
    """固定51の人工出典へ、明示した最大10終値だけを接続する。

    引数: closes(list[float]|None)は現在窓の終値、end_index(int)は最新番号。
    返り値: tuple[dict,list[dict]]は人工slotと正本SOURCE13配列。
    """
    slot = OLD.fixture()
    frames = [OLD.source(index) for index in range(end_index + 1)]
    start = max(9, end_index - 9)
    closes = [100] * (end_index - start + 1) if closes is None else closes
    if len(closes) != end_index - start + 1:
        raise ValueError("人工終値の本数不一致")
    for index, close in zip(range(start, end_index + 1), closes):
        if index < 10:
            frames[index]["close"] = close
        else:
            frames[index].update(open=close, close=close, high=close + 1, low=close - 1)
    slot.update(scheduled=(end_index + 1) * 180, time=(end_index + 1) * 180)
    slot["current"], slot["previous"] = deepcopy(frames[-1]), deepcopy(frames[-2])
    slot["OR"]["sources"] = deepcopy(frames[:10])
    slot["diagnostic"]["old_R"]["current"] = deepcopy(slot["current"])
    slot["upper"]["source"] = OLD.source(
        (end_index + 1) // 5 - 1, minutes=15, open_=100, high=160, low=80, close=140)
    return slot, frames


def reflected(slot: dict, frames: list[dict]) -> tuple[dict, list[dict]]:
    """slotと正本の全SOURCEを同じ定数で反射する。

    引数: slot(dict)とframes(list[dict])は人工材料。
    返り値: tuple[dict,list[dict]]は売買反射後の別材料。
    """
    other = OLD.reflect(slot)
    output = deepcopy(frames)
    for row in output:
        row["open"], row["close"] = 500 - row["open"], 500 - row["close"]
        row["high"], row["low"] = 500 - row["low"], 500 - row["high"]
    return other, output


class HistoryTests(unittest.TestCase):
    """価格系列からの独立した明示期待値へ履歴の意味を照合する。"""

    def test_hysteresis_and_rebreak_golden(self) -> None:
        """保持・内帰還・再突破の順序を、上端3外2内へ照合する。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([100, 115, 112, 105, 109, 115, 114, 95, 112, 115])
        result = H.extract(slot, frames)
        self.assertTrue(result["ready"], result["reason"])
        self.assertEqual(result["history"]["upper"]["values"], [1, 3, 2, 1, 0.0])
        self.assertEqual(result["history"]["lower"]["values"], [-1, 0, 0, 0, -1.0])
        self.assertEqual(result["vectors"]["1"][15:], [1, 3, 2, 1, 0.0, -1, 0, 0, 0, -1.0])
        self.assertEqual(result["vectors"]["-1"][15:], [-1, 0, 0, 0, -1.0, 1, 3, 2, 1, 0.0])

    def test_neutral_seed_and_age(self) -> None:
        """最初の明瞭側は種だけで、中間帯は保持する。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([112, 111, 115, 114, 105, 106, 115, 110, 105, 104])
        result = H.extract(slot, frames)
        upper = result["history"]["upper"]
        self.assertTrue(result["ready"])
        self.assertEqual((upper["initial_state"], upper["seed_index"], upper["seed_state"]), (0, 12, 1))
        self.assertEqual(upper["values"], [-1, 1, 2, -1, 0.1])
        self.assertEqual(upper["age_bars"], 1)

    def test_unoccurred_is_ready(self) -> None:
        """全neutral・初期outside・最後だけ種の三経路を欠測にしない。

        引数: なし。
        返り値: None。
        """
        for closes, expected in (([110] * 10, [0, 0, 0, 0, -1.0]),
                                 ([115] * 10, [1, 0, 0, 0, -1.0]),
                                 ([110] * 9 + [115], [1, 0, 0, 0, -1.0])):
            slot, frames = fixture(closes)
            result = H.extract(slot, frames)
            self.assertTrue(result["ready"])
            self.assertEqual(result["history"]["upper"]["values"], expected)

    def test_five_point_equalities_and_ulp(self) -> None:
        """±5等号は切替し、1ULP内側はneutralとして保持する。

        引数: なし。
        返り値: None。
        """
        closes = [math.nextafter(115.0, -math.inf), 115.0,
                  math.nextafter(105.0, math.inf), 105.0]
        window = [OLD.source(i + 10, open_=c, high=c + 1, low=c - 1, close=c)
                  for i, c in enumerate(closes)]
        endpoint = H.endpoint_history(window, 110, 1)
        self.assertEqual((endpoint["seed_index"], endpoint["out_count"], endpoint["in_count"]), (11, 0, 1))
        self.assertEqual(endpoint["values"], [-1, 0, 1, -1, 0.0])

    def test_single_opening_range_last_foot(self) -> None:
        """j9の一本窓はイベント0でも準備済みとする。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture(end_index=9)
        result = H.extract(slot, frames)
        self.assertTrue(result["ready"], result["reason"])
        self.assertEqual((result["history"]["start_index"], result["history"]["end_index"],
                          result["history"]["source_count"]), (9, 9, 1))
        self.assertEqual(result["vectors"]["1"][15:], [-1, 0, 0, 0, -1.0] * 2)

    def test_short_window_and_ten_limit(self) -> None:
        """OR最終足を含む短窓と最大10本の番号境界を確認する。

        引数: なし。
        返り値: None。
        """
        for index, start, count in ((12, 9, 4), (18, 9, 10), (19, 10, 10), (29, 20, 10)):
            slot, frames = fixture(end_index=index)
            result = H.extract(slot, frames)
            self.assertTrue(result["ready"], result["reason"])
            self.assertEqual((result["history"]["start_index"], result["history"]["source_count"]), (start, count))
            self.assertEqual([r["index"] for r in result["history"]["window_sources"]], list(range(start, index + 1)))

    def test_age_divides_by_ten_in_short_window(self) -> None:
        """短窓でも最終切替後2本は固定分母10で0.2とする。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([100, 115, 115, 115], end_index=12)
        result = H.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertEqual(result["history"]["upper"]["values"], [1, 1, 0, 1, 0.2])

    def test_old_past_and_future_outside_window_ignored(self) -> None:
        """窓外過去・未使用未来の有無を現在の状態へ持ち込まない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture(end_index=29)
        expected = H.extract(slot, frames)
        changed = deepcopy(frames)
        for row in changed[10:20]:
            row.update(open=150, high=200, low=90, close=195)
        changed += [OLD.source(30, close=1000), OLD.source(31, close=1)]
        self.assertEqual(H.extract(slot, changed), expected)

    def test_mirror_all_twenty_five(self) -> None:
        """実方向端順を交換するだけで25列の売買鏡像を保つ。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([100, 115, 105, 100, 85, 90, 95, 105, 115, 110])
        a = H.extract(slot, frames)
        other, reverse = reflected(slot, frames)
        b = H.extract(other, reverse)
        self.assertTrue(a["ready"] and b["ready"])
        self.assertEqual(a["vectors"]["1"], b["vectors"]["-1"])
        self.assertEqual(a["vectors"]["-1"], b["vectors"]["1"])
        self.assertEqual(a["control_vectors"]["1"], b["control_vectors"]["-1"])

    def test_translation(self) -> None:
        """全出典と固定端の一定価格移動で特徴を変えない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture([100, 115, 105, 100, 85, 90, 95, 105, 115, 110])
        expected = H.extract(slot, frames)
        other, changed = deepcopy(slot), deepcopy(frames)
        rows = [other["current"], other["previous"], other["upper"]["source"],
                other["diagnostic"]["old_R"]["current"], *other["OR"]["sources"], *changed]
        for row in rows:
            for name in ("open", "high", "low", "close"):
                row[name] += 0.125
        other["OR"]["high"] += 0.125
        other["OR"]["low"] += 0.125
        result = H.extract(other, changed)
        self.assertEqual(result["vectors"], expected["vectors"])

    def test_same_ready_control_and_base_prefix(self) -> None:
        """25列prefixと対照15列を旧51抽出結果へ厳密に合わせる。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        result = H.extract(slot, frames)
        self.assertEqual(result["base"], H.F.extract(slot))
        self.assertEqual(result["control_vectors"], result["base"]["vectors"])
        for side in ("1", "-1"):
            self.assertEqual(result["vectors"][side][:15], result["control_vectors"][side])
            self.assertEqual(len(result["vectors"][side]), 25)
            self.assertTrue(all(type(result["vectors"][side][i]) is int for i in (15, 16, 17, 18, 20, 21, 22, 23)))
            self.assertTrue(all(type(result["vectors"][side][i]) is float for i in (19, 24)))

    def test_metadata_contract(self) -> None:
        """旧15を保持し、新10列の順・技法・familyを固定する。

        引数: なし。
        返り値: None。
        """
        self.assertEqual(H.FEATURES[:15], H.F.FEATURES)
        self.assertEqual([m["id"] for m in H.FEATURES], [f"F{i:02d}" for i in range(1, 26)])
        self.assertEqual([m["method"] for m in H.FEATURES[15:]], ["P06", "P03", "P09", "P10", "P10"] * 2)
        self.assertTrue(all(m["family"] == "price" and m["scale"] == "m03+m30" for m in H.FEATURES[15:]))

    def test_missing_and_duplicate_are_not_zero(self) -> None:
        """窓内欠足と重複番号を未発生0と区別して両候補未準備にする。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        for changed in ([r for r in frames if r["index"] != 14], frames + [deepcopy(frames[14])], None):
            result = H.extract(slot, changed)
            self.assertTrue(result["base"]["ready"])
            self.assertFalse(result["ready"])
            self.assertEqual(result["vectors"], {"1": [], "-1": []})
            self.assertEqual(result["control_vectors"], {"1": [], "-1": []})

    def test_future_window_and_public_key(self) -> None:
        """選択窓の未来公開・予定後終了を拒否する。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        for change in ({"confirm": 3601}, {"confirm": 3600, "confirm_line": 1000},
                       {"start": 3421, "end": 3601, "confirm": 3601}):
            changed = deepcopy(frames)
            changed[14].update(change)
            self.assertFalse(H.extract(slot, changed)["ready"])
        delayed, changed = deepcopy(slot), deepcopy(frames)
        delayed["time"] = 3610
        changed[14].update(start=3421, end=3601, confirm=3601)
        self.assertFalse(H.extract(delayed, changed)["ready"])
        slot["current"].update(confirm=3600, confirm_line=999)
        slot["diagnostic"]["old_R"]["current"] = deepcopy(slot["current"])
        frames[-1] = deepcopy(slot["current"])
        self.assertTrue(H.extract(slot, frames)["ready"])

    def test_partial_np_missing_and_key_order(self) -> None:
        """窓内不完全・NP・missingと公開順逆転を補完しない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        for change in ({"missing": 1}, {"publish": False}, {"start": 2521},
                       {"high": 1}, {"confirm": 3500}, {"session": "別場"}):
            changed = deepcopy(frames)
            changed[14].update(change)
            self.assertFalse(H.extract(slot, changed)["ready"])

    def test_current_and_opening_range_source_match(self) -> None:
        """現在足・OR10足は保存slotと正本で全SOURCEを一致させる。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        for index in (4, 19):
            changed = deepcopy(frames)
            changed[index]["close"] -= 0.25
            result = H.extract(slot, changed)
            self.assertFalse(result["ready"])
            self.assertIn("SOURCE不一致", result["reason"])

    def test_base_unknown_short_circuit(self) -> None:
        """基礎不明を履歴で救済せず、正本配列へ触れずに返す。

        引数: なし。
        返り値: None。
        """
        slot, _ = fixture()
        slot["atr"] = None
        result = H.extract(slot, object())
        self.assertFalse(result["ready"])
        self.assertTrue(result["reason"].startswith("基礎特徴未準備: "))

    def test_nonmutation_and_no_io(self) -> None:
        """I/Oを禁止し、入力・旧metadata・出典を改変しない。

        引数: なし。
        返り値: None。
        """
        slot, frames = fixture()
        before = deepcopy((slot, frames, H.F.FEATURES))
        with patch("builtins.open", side_effect=AssertionError("抽出I/O禁止")), \
                patch("io.open", side_effect=AssertionError("抽出I/O禁止")):
            result = H.extract(slot, frames)
        self.assertTrue(result["ready"])
        self.assertEqual((slot, frames, H.F.FEATURES), before)
        result["history"]["window_sources"][0]["close"] = 999
        self.assertEqual((slot, frames, H.F.FEATURES), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
