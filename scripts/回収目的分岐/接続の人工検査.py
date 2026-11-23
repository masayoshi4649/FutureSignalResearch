"""回収目的の新木を、既存回収条件と定時判断へ接続する人工検査。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


spec = importlib.util.spec_from_file_location("回収目的主の人工接続", Path(__file__).with_name("検証.py"))
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)


def fixture() -> tuple:
    """未来回収を含まない人工の一枠と固定過去予測を作る。

    引数：なし。
    返り値：tupleはblock/prepared/model/calibration/learner。
    """
    block = {"slots": [{"session": "2026-10-05_Day", "slot_id": "人工一枠", "scheduled": 900., "time": 900., "line": 1}]}
    prepared = {"人工一枠": {"ready": True, "reason": "", "vectors": {"1": [0.] * 18, "-1": [0.] * 18},
        "background_direction": 1, "atr": 50., "D": 50.}}
    model = {"model_id": "人工G0", "policy": "G0"}
    calibration = {"model_id": "人工G0", "leaves": {"3": {"leaf": 3, "support": True, "positive": False, "mean_yen": {"5": -1.}}}}
    def predict(actual_model: dict, vectors: dict) -> dict:
        """人工の先着最高側を返す。

        引数：actual_model/vectors(dict)は固定木と当時の18列。
        返り値：dictは買いを選ぶ人工予測。
        """
        if actual_model is not model or vectors is not prepared["人工一枠"]["vectors"]:
            raise AssertionError("当時入力の接続差")
        return {"side": 1, "reason": "採用", "leafs": {"1": 3, "-1": 4}}
    return block, prepared, model, calibration, SimpleNamespace(predict=predict)


class ConnectionTests(unittest.TestCase):
    """当時入力、追加回収条件、DI同値待機を人工で確認する。"""

    def test_policy_gate_and_no_input_change(self):
        """G0/G1が同じ先着側へ回収条件だけを追加する。

        引数：self(ConnectionTests)は検査器。
        返り値：None。
        """
        args = fixture()
        snapshot = deepcopy(args[:4])
        first = M.slots_for(*args, "G0", "W20")[0]
        second = M.slots_for(*args, "G1", "W20")[0]
        self.assertEqual((first["side"], first["role"]), (1, "順行"))
        self.assertEqual((second["side"], second["reason"]), (0, "過去回収平均非正WAIT"))
        self.assertEqual(args[:4], snapshot)

    def test_positive_and_direction_tie(self):
        """回収正を通過してもDI同値では役割未確定として待つ。

        引数：self(ConnectionTests)は検査器。
        返り値：None。
        """
        block, prepared, model, cal, learner = fixture()
        cal["leaves"]["3"].update(positive=True, mean_yen={"5": 1.})
        self.assertEqual(M.slots_for(block, prepared, model, cal, learner, "G1", "W20")[0]["side"], 1)
        prepared["人工一枠"]["background_direction"] = 0
        result = M.slots_for(block, prepared, model, cal, learner, "G1", "W20")[0]
        self.assertEqual((result["side"], result["reason"]), (0, "上位DI同値の役割未確定WAIT"))

    def test_unready_never_calls_prediction(self):
        """技法未準備なら未来回収や保存予測で補わず判断不能を保持する。

        引数：self(ConnectionTests)は検査器。
        返り値：None。
        """
        block, prepared, model, cal, _ = fixture()
        prepared["人工一枠"].update(ready=False, reason="人工の準備不足")
        result = M.slots_for(block, prepared, model, cal, None, "G0", "W20")[0]
        self.assertIsNone(result["prediction"])
        self.assertEqual((result["side"], result["reason"]), (0, "人工の準備不足"))


if __name__ == "__main__":
    unittest.main()
