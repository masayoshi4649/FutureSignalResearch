"""入口探索の集計と、未来の結果を参照しない間引きを合成入力で検証する。"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
import unittest
from unittest.mock import patch

import numpy as np


仕様 = importlib.util.spec_from_file_location("入口探索の評価検証対象", Path(__file__).with_name("評価.py"))
評価 = importlib.util.module_from_spec(仕様)
sys.modules[仕様.name] = 評価
仕様.loader.exec_module(評価)


# ----------------------------------------
# 最小の合成候補

def 行(label: str = "順行先着", seconds: str = "0", session: str = "2026-10-01_Day",
      side: int = 1, line: int = 1) -> dict[str, Any]:
    """CSVから読んだ形の合成候補を作る。

    引数: label/seconds/session (str) はラベル・要求秒・場名、side/line (int) は方向・要求原行。
    返り値: dict[str, Any] は文字列を中心とする合成行。
    """
    return {"ラベル": label, "要求時計秒": seconds, "場": session, "side": str(side),
            "要求原板行": str(line), "新規時計秒": "999999", "判定時計秒": "9999999"}


# ----------------------------------------
# 分母・支持範囲・標準型

class 集計の検証(unittest.TestCase):
    """全約定分母と、開始日単位の支持範囲を確認する。"""

    def test_五分類と全約定分母を保つ(self) -> None:
        """期限・不明を分母へ残し、未約定だけを除く。

        引数: なし。
        返り値: None。
        """
        rows = [行(label, str(index * 1800)) for index, label in enumerate(評価.LABELS)]
        result = 評価.evaluate(rows, np.ones(5, dtype=bool), "後続")
        self.assertEqual(result["候補数"], 5)
        self.assertEqual(result["約定候補数"], 4)
        self.assertEqual(result["確認率"], 0.25)
        for label in 評価.LABELS:
            self.assertEqual(result[label], 1)

    def test_デイとナイトを同じ開始日へまとめる(self) -> None:
        """場数と開始日数を混同せず、成功日寄与を成功数で重み付けする。

        引数: なし。
        返り値: None。
        """
        rows = [行(), 行(session="2026-10-01_Night"), 行(session="2026-10-02_Day"),
                行("未約定", session="2026-10-03_Day")]
        result = 評価.evaluate(rows, [True] * 4, "選択")
        self.assertEqual((result["候補場数"], result["約定場数"]), (4, 3))
        self.assertEqual((result["候補開始日数"], result["約定開始日数"], result["成功開始日数"]), (3, 2, 2))
        self.assertEqual(result["最大成功日寄与率"], 2 / 3)
        daily = 評価.group_by_day(rows, [True] * 4)
        self.assertEqual([row["開始日"] for row in daily], ["2026-10-01", "2026-10-02", "2026-10-03"])
        self.assertEqual(daily[0]["候補場数"], 2)
        self.assertIsNone(daily[2]["確認率"])

    def test_空選択と未約定だけの率はNone(self) -> None:
        """分母ゼロを0%やNaNへ変換しない。

        引数: なし。
        返り値: None。
        """
        for rows, mask in (([], []), ([行()], [False]), ([行("未約定")], [True])):
            result = 評価.evaluate(rows, mask, "空")
            self.assertIsNone(result["確認率"])
            self.assertIsNone(result["Wilson95下限_独立参考"])
            self.assertIsNone(result["Wilson95上限_独立参考"])
            self.assertIsNone(result["最大成功日寄与率"])
            self.assertIsNone(result["30分間引き_確認率"])

    def test_分割済み行と全行マスクの集計が一致する(self) -> None:
        """元の行番号に依存せず、同じ候補集合は同じ集計になる。

        引数: なし。
        返り値: None。
        """
        rows = [行(seconds=str(index * 1800)) for index in range(6)]
        mask = np.array([False, True, True, False, True, False])
        sliced = [row for row, selected in zip(rows, mask) if selected]
        self.assertEqual(評価.evaluate(rows, mask, "学習"), 評価.evaluate(sliced, [True] * 3, "学習"))

    def test_返り値はJSONへNaNなしで保存できる(self) -> None:
        """NumPyの真偽マスクを受けても、出力にはNumPy型やDecimalを残さない。

        引数: なし。
        返り値: None。
        """
        rows = [行(), 行("逆行先着", session="2026-10-02_Day")]
        for result in (評価.evaluate(rows, np.ones(2, dtype=bool), "後続"),
                       評価.group_by_day(rows, np.ones(2, dtype=bool)),
                       評価.date_bootstrap(rows, np.ones(2, dtype=bool), draws=50)):
            json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_マスクの長さ次元型と未知ラベルを拒否する(self) -> None:
        """不正入力を候補ゼロや非成功へ黙って変換しない。

        引数: なし。
        返り値: None。
        """
        for mask in ([], np.array([[True]])):
            with self.assertRaises(ValueError):
                評価.evaluate([行()], mask, "不正")
        with self.assertRaises(TypeError):
            評価.evaluate([行()], [1], "不正")
        with self.assertRaises(ValueError):
            評価.evaluate([行("未知")], [True], "不正")

    def test_Wilson既知例と端点(self) -> None:
        """14/20の広い区間を再現し、0成功・全成功でも0～1を保つ。

        引数: なし。
        返り値: None。
        """
        lower, upper = 評価.wilson95(14, 20)
        self.assertAlmostEqual(lower, 0.4810271816464765)
        self.assertAlmostEqual(upper, 0.8545227551323956)
        for successes in (0, 20):
            lower, upper = 評価.wilson95(successes, 20)
            self.assertTrue(0 <= lower <= upper <= 1)
        self.assertEqual(評価.wilson95(0, 0), (None, None))
        with self.assertRaises(ValueError):
            評価.wilson95(2, 1)


# ----------------------------------------
# 因果的な30分間引きと、日別の再標本

class 間引きと再標本の検証(unittest.TestCase):
    """未約定と未来の結果で候補選択が変わらないことを確かめる。"""

    def test_30分ちょうどを採用し直前を除く(self) -> None:
        """時刻を文字列順にせず、1800秒境界を等号込みで採用する。

        引数: なし。
        返り値: None。
        """
        rows = [行(seconds="1800", line=4), 行(seconds="0", line=1),
                行(seconds="1799.999", line=3), 行(seconds="3600", line=5), 行(seconds="2", line=2)]
        self.assertEqual(評価.thin30_mask(rows, [True] * 5), [True, True, False, True, False])

    def test_未約定も間引きの起点にする(self) -> None:
        """後から未約定と分かった要求を取り除いて、有利な後続候補を救わない。

        引数: なし。
        返り値: None。
        """
        rows = [行("未約定", "0"), 行("順行先着", "600"), 行("逆行先着", "1800")]
        result = 評価.evaluate(rows, [True] * 3, "後続")
        self.assertEqual(評価.thin30_mask(rows, [True] * 3), [True, False, True])
        self.assertEqual(result["30分間引き_候補数"], 2)
        self.assertEqual(result["30分間引き_約定候補数"], 1)
        self.assertEqual(result["30分間引き_確認率"], 0)

    def test_場と方向ごとに間引きが独立する(self) -> None:
        """同じ時刻の反対方向と別の場を、先行要求で消さない。

        引数: なし。
        返り値: None。
        """
        rows = [行(), 行(side=-1), 行(session="2026-10-01_Night"), 行(seconds="100")]
        self.assertEqual(評価.thin30_mask(rows, [True] * 4), [True, True, True, False])

    def test_選択されない候補を起点にしない(self) -> None:
        """条件外の先行要求が、条件内の最初の要求を消さない。

        引数: なし。
        返り値: None。
        """
        rows = [行(seconds="0"), 行(seconds="100"), 行(seconds="1800")]
        self.assertEqual(評価.thin30_mask(rows, [False, True, True]), [False, True, False])

    def test_未来列とラベルを書き換えても間引き位置は不変(self) -> None:
        """新規・判定・所要分・順逆行・成否から採用位置を選ばない。

        引数: なし。
        返り値: None。
        """
        rows = [行("未約定", "0"), 行("逆行先着", "600"), 行("順行先着", "1800")]
        expected = 評価.thin30_mask(rows, [True] * 3)
        changed = copy.deepcopy(rows)
        for index, row in enumerate(changed):
            row.update({"ラベル": 評価.LABELS[index], "新規時計秒": "-999999",
                        "判定時計秒": str(-index), "所要分": 999, "最大順行pt": 100000,
                        "最大逆行pt": -100000, "新規価格": -1})
        self.assertEqual(評価.thin30_mask(changed, [True] * 3), expected)

    def test_同時計は要求原行順に一つだけ採用する(self) -> None:
        """入力の配列順が違っても、既知の要求原行を順序に用いる。

        引数: なし。
        返り値: None。
        """
        rows = [行(line=20), 行(line=10)]
        self.assertEqual(評価.thin30_mask(rows, [True, True]), [False, True])

    def test_日別再標本は日内比率の単純平均にしない(self) -> None:
        """4/4の日と0/1の日を一組ずつ引いた場合は4/5であり1/2ではない。

        引数: なし。
        返り値: None。
        """
        rows = [行(seconds=str(i * 1800)) for i in range(4)] + [行("逆行先着", session="2026-10-02_Day")]
        first = 評価.date_bootstrap(rows, [True] * 5, seed=12, draws=200)
        second = 評価.date_bootstrap(rows, [True] * 5, seed=12, draws=200)
        self.assertEqual(first, second)
        self.assertEqual(first["再標本日数"], 2)
        self.assertEqual(first["有効抽出回数"], 200)
        self.assertEqual(first["日別再標本95下限_参考"], 0)
        self.assertEqual(first["日別再標本95上限_参考"], 1)
        daily = 評価.group_by_day(rows, [True] * 5)
        self.assertEqual(sum(x["順行先着"] for x in daily) / sum(x["約定候補数"] for x in daily), 0.8)

        class 交互抽出:
            """日ごとの比率平均との違いが出るよう、毎回両日を一つずつ選ぶ。"""

            def __init__(self) -> None:
                """次に返す日番号を初期化する。

                引数: なし。
                返り値: None。
                """
                self.index = 0

            def randrange(self, stop: int) -> int:
                """0と1を交互に返す。

                引数: stop (int) は選べる日数。
                返り値: int は次の抽出日番号。
                """
                result = self.index % stop
                self.index += 1
                return result

        with patch.object(評価.random, "Random", return_value=交互抽出()):
            paired = 評価.date_bootstrap(rows, [True] * 5, draws=10)
        self.assertAlmostEqual(paired["日別再標本95下限_参考"], 0.8)
        self.assertAlmostEqual(paired["日別再標本95上限_参考"], 0.8)

    def test_一日以下と全未約定では再標本区間を作らない(self) -> None:
        """日数が足りない退化区間や分母ゼロを、強い証拠として返さない。

        引数: なし。
        返り値: None。
        """
        for rows in ([], [行()], [行("未約定"), 行("未約定", session="2026-10-02_Day")]):
            result = 評価.date_bootstrap(rows, [True] * len(rows), draws=20)
            self.assertIsNone(result["日別再標本95下限_参考"])
            self.assertIsNone(result["日別再標本95上限_参考"])
        with self.assertRaises(ValueError):
            評価.date_bootstrap([], [], draws=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
