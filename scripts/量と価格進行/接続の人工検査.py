"""B/Qの列投影・回収条件・実役割を人工だけで検査する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


SPEC = importlib.util.spec_from_file_location("量価格の人工接続", Path(__file__).with_name("検証.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture(parent: str) -> tuple:
    """モデル群に対応する人工入力を用意する。

    引数: parent(str)はB0又はQ0。
    返り値: tupleはblock/prepared/model/calibration/learner。
    """
    count = M.MODEL_POLICIES[parent]
    block = {"slots": [{"session": "2026-10-05_Day", "slot_id": "人工", "scheduled": 900., "time": 900., "line": 1}]}
    prepared = {"人工": {"ready": True, "reason": "", "vectors": {"1": [0.] * count, "-1": [0.] * count},
        "background_direction": 1, "atr": 50., "D": 50.}}
    model = {"model_id": "人工" + parent, "policy": parent}
    calibration = {"model_id": model["model_id"], "leaves": {"3": {"leaf": 3, "support": True, "positive": False, "mean_yen": {"5": -1.}}}}

    def predict(actual: dict, vectors: dict) -> dict:
        """当時の期待列数だけを受け取り人工買いを返す。

        引数: actual/vectors(dict)はモデルと当時入力。
        返り値: dictは人工予測。評価損益を見ない。
        """
        assert actual is model and vectors is prepared["人工"]["vectors"]
        assert all(len(v) == count for v in vectors.values())
        return {"side": 1, "reason": "採用", "leafs": {"1": 3, "-1": 4}}

    return block, prepared, model, calibration, SimpleNamespace(predict=predict)


class ConnectionTests(unittest.TestCase):
    """同じ入口・価格出口へ接続する前段の不変条件を検査する。"""

    def test_両モデル群の回収条件(self):
        """同じ最高側へだけstrict正条件を足す。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        for parent in M.MODEL_POLICIES:
            args = fixture(parent)
            original = deepcopy(args[:4])
            base = M.slots_for(*args, parent, "W20")[0]
            positive = M.slots_for(*args, parent[0] + "1", "W20")[0]
            self.assertEqual((base["side"], base["role"]), (1, "順行"))
            self.assertEqual((positive["side"], positive["reason"]), (0, "過去回収平均非正WAIT"))
            self.assertEqual(args[:4], original)

    def test_DI同値と実役割(self):
        """特徴のT/R投影と実背景DIの役割を混同しない。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        args = fixture("Q0")
        args[3]["leaves"]["3"].update(positive=True, mean_yen={"5": 1.})
        args[1]["人工"]["background_direction"] = -1
        self.assertEqual(M.slots_for(*args, "Q1", "W20")[0]["role"], "反転")
        args[1]["人工"]["background_direction"] = 0
        item = M.slots_for(*args, "Q1", "W20")[0]
        self.assertEqual((item["side"], item["reason"]), (0, "上位DI同値の役割未確定WAIT"))

    def test_準備不足を予測で補わない(self):
        """旧準備がない枠では予測を呼ばない。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        block, prepared, model, cal, _ = fixture("B0")
        prepared["人工"].update(ready=False, reason="未準備")
        row = M.slots_for(block, prepared, model, cal, None, "B0", "W20")[0]
        self.assertIsNone(row["prediction"])
        self.assertEqual(row["reason"], "未準備")

    def test_モデル群混同を拒否(self):
        """BとQの回収木を取り違えた接続を止める。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        with self.assertRaises(ValueError):
            M.slots_for(*fixture("B0"), "Q0", "W20")

    def test_教師投影は同じ属性を保つ(self):
        """B54とQ60で目的値やIDを変更しない。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        rows = [{"features": list(range(60)), "slot_id": "同じ", "pnl5": 123, "side": -1}]
        before = deepcopy(rows)
        b, q = M.rows_for(rows, 54), M.rows_for(rows, 60)
        self.assertEqual(b[0]["features"], list(range(54)))
        self.assertEqual(q, rows)
        self.assertEqual({k: v for k, v in b[0].items() if k != "features"}, {k: v for k, v in rows[0].items() if k != "features"})
        self.assertEqual(rows, before)
        with self.assertRaises(ValueError):
            M.rows_for(rows, 59)


if __name__ == "__main__":
    unittest.main()
