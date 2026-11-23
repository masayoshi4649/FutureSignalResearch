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
    prepared = {"人工一枠": {"ready": True, "reason": "", "vectors": {"1": [0.] * 46, "-1": [0.] * 46},
        "background_direction": 1, "atr": 50., "D": 50.}}
    model = {"model_id": "人工A0", "policy": "A0"}
    calibration = {"model_id": "人工A0", "leaves": {"3": {"leaf": 3, "support": True, "positive": False, "mean_yen": {"5": -1.}}}}
    def predict(actual_model: dict, vectors: dict) -> dict:
        """人工の先着最高側を返す。

        引数：actual_model/vectors(dict)は固定木と当時の46列。
        返り値：dictは買いを選ぶ人工予測。
        """
        if actual_model is not model or vectors is not prepared["人工一枠"]["vectors"]:
            raise AssertionError("当時入力の接続差")
        return {"side": 1, "reason": "採用", "leafs": {"1": 3, "-1": 4}}
    return block, prepared, model, calibration, SimpleNamespace(predict=predict)


class ConnectionTests(unittest.TestCase):
    """当時入力、追加回収条件、DI同値待機を人工で確認する。"""

    def test_policy_gate_and_no_input_change(self):
        """A0/A1が同じ先着側へ回収条件だけを追加する。

        引数：self(ConnectionTests)は検査器。
        返り値：None。
        """
        args = fixture()
        snapshot = deepcopy(args[:4])
        first = M.slots_for(*args, "A0", "W20")[0]
        second = M.slots_for(*args, "A1", "W20")[0]
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
        self.assertEqual(M.slots_for(block, prepared, model, cal, learner, "A1", "W20")[0]["side"], 1)
        prepared["人工一枠"]["background_direction"] = 0
        result = M.slots_for(block, prepared, model, cal, learner, "A1", "W20")[0]
        self.assertEqual((result["side"], result["reason"]), (0, "上位DI同値の役割未確定WAIT"))

    def test_unready_never_calls_prediction(self):
        """技法未準備なら未来回収や保存予測で補わず判断不能を保持する。

        引数：self(ConnectionTests)は検査器。
        返り値：None。
        """
        block, prepared, model, cal, _ = fixture()
        prepared["人工一枠"].update(ready=False, reason="人工の準備不足")
        result = M.slots_for(block, prepared, model, cal, None, "A0", "W20")[0]
        self.assertIsNone(result["prediction"])
        self.assertEqual((result["side"], result["reason"]), (0, "人工の準備不足"))

    def test_同じ形成の反復を独立件数にしない(self):
        """同じIDの三観測と不在・失効記憶を別の分母へ数える。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        paths = [{"episode_id": "同一b", "k": {"index": 20}, "k_valid": valid, "last_expired": {"episode_id": "過去b"}}
                 for valid in (True, True, False)]
        paths.append({"episode_id": None, "k": None, "k_valid": False, "last_expired": None})
        self.assertEqual(M.episode_counts(paths), {"episode数": 1, "episode最大反復": 3, "episodeなし": 1,
            "k形成episode数": 1, "k有効episode数": 1, "期限失効観測": 3})
        self.assertEqual(M.episode_counts([]), {"episode数": 0, "episode最大反復": 0, "episodeなし": 0,
            "k形成episode数": 0, "k有効episode数": 0, "期限失効観測": 0})

    def test_現在有効旗の四群と空群(self):
        """0群の未登録/取消混合と、r未形成の有効1を人工で区別する。

        引数: self(ConnectionTests)は検査器。
        返り値: None。本物教師・価格・モデルは読まない。
        """
        rows, prepared = [], {}
        for index, valid in enumerate((0, 0, 1)):
            vector = [0.] * 46
            vector[19] = valid
            identity, session = "人工" + str(index), "2026-10-05_Day"
            rows.append({"slot_id": identity, "session": session, "side": 1, "features": vector})
            absent = {"episode_id": None, "cancel": None, "r": None, "k": None, "k_valid": False}
            path = deepcopy(absent)
            if index:
                path.update(episode_id="同じID", cancel={} if index == 1 else None)
            prepared[identity] = {"paths": {"1": {"T": path, "R": absent}}}
        actual = M.state_distribution(rows, prepared, SimpleNamespace(float32=list))
        self.assertEqual(sum(x["方向行"] for x in actual.values()), 3)
        self.assertEqual(actual["T0_R0"]["方向行"], 2)
        self.assertEqual(actual["T0_R0"]["T"], {"形成あり": 1, "形成なし": 1, "取消あり": 1,
            "rあり": 0, "kあり": 0, "k有効": 0, "形成ID数": 1})
        self.assertEqual(actual["T1_R0"]["T"]["rあり"], 0)
        self.assertEqual(actual["T1_R1"]["方向行"], 0)
        self.assertEqual(actual["T1_R1"]["unique枠"], 0)


if __name__ == "__main__":
    unittest.main()
