"""局面追加の鏡像・公開時計・数値助走と欠測を人工価格で検査する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("局面特徴人工の対象", Path(__file__).with_name("特徴.py"))
F = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F)


def session(count: int = 40, name: str = "人工場", begin: float = 1000, reflected: bool = False) -> dict:
    """人工の完全15分OHLCと空の下位足を作る。

    引数: count(int)は本数、name(str)は場名、begin(float)は起点、reflected(bool)は価格反射。
    返り値: dictは固定49銀行へ渡す一場。
    """
    rows = []
    for index in range(count):
        c = 1000 + index * 2 + (index % 3) * 3
        o, h, low = c - 2, c + 4, c - 5
        if reflected:
            o, h, low, c = 3000 - o, 3000 - low, 3000 - h, 3000 - c
        start = begin + index * 900
        rows.append({"index": index, "minutes": 15, "start": start, "end": start + 900,
            "confirm": start + 901, "confirm_line": index, "publish": True, "missing": 0,
            "open": o, "high": h, "low": low, "close": c})
    return {"session": name, "contract": ("人工限月",), "begin": begin, "end": begin + count * 900,
        "frames3": [], "frames15": rows}


def inputs(row: dict) -> tuple:
    """現15分出典に整合する人工の旧46特徴と定時枠を作る。

    引数: row(dict)は局面銀行の現足。
    返り値: tuple[dict,dict]はslotと旧特徴。
    """
    slot = {"scheduled": row["end"], "time": row["confirm"], "line": row["confirm_line"],
        "upper": {"source": F.I49.source(row), "plus_di": row["plus_di"], "minus_di": row["minus_di"]}}
    old = {"ready": True, "reason": "", "atr": 20.0,
        "vectors": {"1": [0.0] * 46, "-1": [0.0] * 46}, "付随状態": {"保存": True}}
    return slot, old


class FeatureTests(unittest.TestCase):
    """本物を使わず局面追加の各境界を検査する。"""

    def test_width(self) -> None:
        """母分散・未準備・既知零幅を確かめる。

        引数: self(FeatureTests)。
        返り値: None。
        """
        self.assertIsNone(F.width([1] * 19))
        self.assertEqual(F.width([1] * 20), 0)
        self.assertEqual(F.width([1, 3] * 10), 4)
        self.assertEqual(F.width(list(range(20))), F.width([100 - x for x in range(20)]))

    def test_prefix_and_control(self) -> None:
        """未来末尾と入力変更を加えず、旧射影を完全保持する。

        引数: self(FeatureTests)。
        返り値: None。
        """
        short = F.build_context([session(30)])["人工場"]
        long = F.build_context([session(40)])["人工場"]
        self.assertEqual(short, long[:30])
        slot, old = inputs(short[-1])
        saved = deepcopy((slot, old, short))
        new = F.extend(slot, old, short)
        self.assertEqual(F.control_projection(new), old)
        self.assertEqual(new["vectors"]["1"][46:], new["vectors"]["-1"][46:])
        self.assertEqual(new["vectors"]["1"][50:], [1, 1, 1, 1])
        self.assertEqual((slot, old, short), saved)

    def test_mask(self) -> None:
        """BB準備とADX準備の時計、初回BBの差欠測を分ける。

        引数: self(FeatureTests)。
        返り値: None。
        """
        rows = F.build_context([session()])["人工場"]
        slot, old = inputs(rows[19])
        value = F.extend(slot, old, rows)["vectors"]["1"][46:]
        self.assertEqual(value[:2], [0, 0])
        self.assertGreater(value[2], 0)
        self.assertEqual(value[3:], [0, 0, 0, 1, 0])

    def test_reset(self) -> None:
        """欠枠で数値種を解除し、BB20本を改めて数える。

        引数: self(FeatureTests)。
        返り値: None。
        """
        raw = session(65)
        raw["frames15"][30]["missing"] = 1
        rows = F.build_context([raw])["人工場"]
        self.assertEqual(rows[30]["bb_count"], 0)
        self.assertIsNone(rows[49]["bb_width"])
        self.assertEqual(rows[50]["bb_count"], 20)
        self.assertIsNotNone(rows[50]["bb_width"])

    def test_carry_and_contract(self) -> None:
        """同限月の現値carryと、当場現前差・限月resetを分ける。

        引数: self(FeatureTests)。
        返り値: None。
        """
        first, second = session(40), session(4, "次場", 50000)
        row = F.build_context([first, second])["次場"][0]
        slot, old = inputs(row)
        new = F.extend(slot, old, [row])
        self.assertEqual(new["vectors"]["1"][50:], [1, 0, 1, 0])
        second["contract"] = ("別限月",)
        row = F.build_context([first, second])["次場"][0]
        self.assertIsNone(row["adx"])
        self.assertIsNone(row["bb_width"])

    def test_hidden_previous(self) -> None:
        """非可視の前足は診断を含めて保存せず、古い足へ代替しない。

        引数: self(FeatureTests)。
        返り値: None。
        """
        rows = F.build_context([session()])["人工場"]
        slot, old = inputs(rows[-1])
        rows[-2]["confirm"] = slot["time"] + 1
        result = F.extend(slot, old, rows)
        self.assertIsNone(result["regime"]["previous_source"])
        self.assertIsNone(result["regime"]["previous_adx"])
        self.assertIsNone(result["regime"]["previous_bb_width"])
        self.assertEqual(result["vectors"]["1"][50:], [1, 0, 1, 0])

    def test_source_rejection(self) -> None:
        """現出典やDI不一致を欠測へ隠さず拒否する。

        引数: self(FeatureTests)。
        返り値: None。
        """
        rows = F.build_context([session()])["人工場"]
        slot, old = inputs(rows[-1])
        slot["upper"]["plus_di"] += 1
        with self.assertRaises(ValueError):
            F.extend(slot, old, rows)
        slot, old = inputs(rows[-1])
        slot["time"] -= 1
        with self.assertRaises(ValueError):
            F.extend(slot, old, rows)

    def test_mirror(self) -> None:
        """価格反射でADX・絶対幅・追加8列が同値になることを確認する。

        引数: self(FeatureTests)。
        返り値: None。
        """
        vectors = []
        for reflected in (False, True):
            rows = F.build_context([session(reflected=reflected)])["人工場"]
            slot, old = inputs(rows[-1])
            vectors.append(F.extend(slot, old, rows)["vectors"]["1"][46:])
        self.assertEqual(vectors[0], vectors[1])

    def test_unready(self) -> None:
        """旧未準備を追加数値で復活させず、旧辞書へ戻せることを確認する。

        引数: self(FeatureTests)。
        返り値: None。
        """
        old = {"ready": False, "reason": "旧欠測", "vectors": {"1": [], "-1": []}}
        new = F.extend({}, old, [])
        self.assertEqual(F.control_projection(new), old)
        self.assertFalse(new["ready"])


if __name__ == "__main__":
    unittest.main()
