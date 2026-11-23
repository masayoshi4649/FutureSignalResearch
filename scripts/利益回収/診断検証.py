"""診断の原行境界・費用込み赤字・期限要求の既知板を合成経路で確認する。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

import numpy as np


PATH = Path(__file__).with_name("診断.py")
SPEC = importlib.util.spec_from_file_location("利益回収診断検証対象", PATH)
D = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = D
SPEC.loader.exec_module(D)


def route(values: list[float], clocks: list[float] | None = None, side: int = 1) -> dict:
    """任意の返済差から正常気配列を作る。

    引数: values (list[float]) は新規1000ptからの方向別差、clocks (list[float]|None) は時計、
    side (int) は買い1または売り-1。
    返り値: dict は正常板と原行索引。
    """
    now = np.asarray(clocks if clocks is not None else list(range(len(values))), dtype=float)
    mark = 1000 + side * np.asarray(values, dtype=float)
    bid, ask = (mark, mark + 5) if side == 1 else (mark - 5, mark)
    lines = np.arange(1, len(values) + 1)
    return {"now": now, "line": lines, "bid": bid, "ask": ask, "at": {int(v): i for i, v in enumerate(lines)}}


def trade(mfe: float, mae: float, final: float, end: int, side: int = 1,
          request: float | None = None, request_line: int | None = None, exit_clock: float | None = None) -> dict:
    """期待値を明示した保存取引の最小例を作る。

    引数: mfe/mae/final (float) は手計算した最大順逆行・最終粗pt、end (int) は返済原行、
    side (int) は方向、request (float|None) は要求時計、request_line (int|None) は要求原行、
    exit_clock (float|None) は返済時計。
    返り値: dict は診断に必要な取引。
    """
    return {"手法": "合成", "場": "合成場", "建玉ID": "建玉1", "方向": "買い" if side == 1 else "売り",
            "新規原板行": 1, "返済原板行": end, "新規価格": 1000, "観測最大順行pt": mfe,
            "観測最大逆行pt": mae, "粗損益円": final * 10, "基準純損益円": final * 10 - 22,
            "返済要求原板行": end - 1 if request_line is None else request_line,
            "返済要求時計秒": end - 2 if request is None else request,
            "新規時計秒": 0, "新規要求時計秒": -1,
            "返済時計秒": end - 1 if exit_clock is None else exit_clock}


class 診断検証(unittest.TestCase):
    """実データを使わない境界検証。"""

    def test_到達前の赤字を再訪に混ぜない(self) -> None:
        """到達前の初期赤字だけでは到達後赤字にしない。

        引数: self (診断検証) はテスト。
        返り値: None。
        """
        r = D.diagnose(trade(40, 10, 40, 5), route([-5, -10, 20, 30, 40]))
        self.assertIsNone(r["20pt後の初粗赤字時計秒"])
        self.assertIsNone(r["20pt後の初純赤字時計秒"])
        self.assertEqual(r["初正粗益時計秒"], 2)
        self.assertEqual(r["初正粗益までのMAEpt"], 10)

    def test_建値は純赤字だが粗赤字ではない(self) -> None:
        """20pt到達後の建値戻りとその後の回復を区別する。

        引数: self (診断検証) はテスト。
        返り値: None。
        """
        r = D.diagnose(trade(40, 5, 40, 4), route([-5, 20, 0, 40]))
        self.assertIsNone(r["20pt後の初粗赤字時計秒"])
        self.assertEqual(r["20pt後の初純赤字時計秒"], 2)
        self.assertEqual(r["失った正含み益pt"], 0)
        self.assertEqual(r["峰から返済の返し幅pt"], 0)

    def test_同時計の返済後原行を含めない(self) -> None:
        """返済後の同時計巨大値をMFEへ混ぜず両端の値を含める。

        引数: self (診断検証) はテスト。
        返り値: None。
        """
        q = route([-5, 20, -10, 40, 1000], [0, 1, 1, 1, 1])
        r = D.diagnose(trade(40, 10, 40, 4, request=1, exit_clock=1), q)
        self.assertEqual(r["追跡正常板数"], 4)
        self.assertEqual(r["20pt後の初粗赤字時計秒"], 1)
        self.assertEqual(r["観測峰原板行"], 4)

    def test_売買の鏡像(self) -> None:
        """同じ方向別差の買いと売りで診断値が一致する。

        引数: self (診断検証) はテスト。
        返り値: None。
        """
        a = D.diagnose(trade(30, 125, -125, 4), route([-5, 30, -10, -125]))
        b = D.diagnose(trade(30, 125, -125, 4, side=-1), route([-5, 30, -10, -125], side=-1))
        for key in ("峰から返済の返し幅pt", "失った正含み益pt", "20pt後の初粗赤字時計秒", "峰までのMAEpt"):
            self.assertEqual(a[key], b[key])
        self.assertEqual(a["失った正含み益pt"], 30)
        self.assertEqual(a["峰から返済の返し幅pt"], 155)

    def test_MFEゼロと観測した峰を区別(self) -> None:
        """全区間赤字ならMFEの初期0を観測返済機会にしない。

        引数: self (診断検証) はテスト。
        返り値: None。
        """
        r = D.diagnose(trade(0, 10, -5, 3), route([-5, -10, -5]))
        self.assertEqual(r["最大観測返済差pt"], -5)
        self.assertIsNone(r["初正粗益時計秒"])
        self.assertEqual(r["峰から返済の返し幅pt"], 0)
        self.assertEqual(r["MFEから返済の差pt"], 5)
        self.assertEqual(r["失った正含み益pt"], 0)

    def test_期限要求の同時計後続板は未知(self) -> None:
        """原行0の期限要求は厳密に過去の気配だけを参照する。

        引数: self (診断検証) はテスト。
        返り値: None。
        """
        q = route([-5, 20, 500, 30], [0, 9, 10, 11])
        r = D.diagnose(trade(500, 5, 30, 4, request=10, request_line=0, exit_clock=11), q)
        self.assertEqual(r["返済要求参照の返済差pt"], 20)
        self.assertEqual(r["返済要求参照板の古さ秒"], 1)
        self.assertEqual(r["返済要求参照から約定の差pt"], 10)

    def test_峰の初回と最終を区別(self) -> None:
        """同じ峰が繰り返す場合は最初と最後の時計を保存する。

        引数: self (診断検証) はテスト。
        返り値: None。
        """
        r = D.diagnose(trade(40, 5, 20, 5), route([-5, 40, 30, 40, 20]))
        self.assertEqual(r["観測峰時計秒"], 1)
        self.assertEqual(r["観測峰最終時計秒"], 3)
        self.assertEqual(r["峰から返済秒"], 3)

    def test_保存MFE矛盾を停止(self) -> None:
        """保存MFEが違えば診断の続行を拒否する。

        引数: self (診断検証) はテスト。
        返り値: None。
        """
        with self.assertRaises(ValueError):
            D.diagnose(trade(50, 5, 40, 3), route([-5, 20, 40]))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(診断検証))
    D.write(D.STUDY / "診断合成検証.json", {"全件成功": result.wasSuccessful(), "件数": result.testsRun,
                                      "失敗数": len(result.failures), "例外数": len(result.errors),
                                      "検証コードSHA256": D.sha(Path(__file__)), "診断コードSHA256": D.sha(PATH)})
    if not result.wasSuccessful():
        raise SystemExit(1)
