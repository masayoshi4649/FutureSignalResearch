"""回収の未知pair除外、未来境界、支持、平均の符号を人工値で検査する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("回収集計の人工対象", Path(__file__).with_name("回収集計.py"))
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


class Learner:
    """固定木の到達先と旧採否を独立に指定する人工予測器。"""

    @staticmethod
    def walk(model: dict, values: list) -> tuple:
        """人工の符号から葉を選ぶ。

        引数: model(dict)は未使用、values(list)は人工値。
        返り値: tupleは葉IDと空経路。
        """
        return (1 if values[0] > 0 else 2), []

    @staticmethod
    def predict(model: dict, vectors: dict) -> dict:
        """人工の旧候補を返す。

        引数: model(dict)は旧side、vectors(dict)は人工値。
        返り値: dictは旧予測。
        """
        return {"side": model.get("old_side", 1), "reason": "旧採用", "leafs": {"1": 1, "-1": 2}}


def fixture(count: int = 60) -> tuple:
    """両側・十日十場に分散する人工過去教師を作る。

    引数: count(int)は枠数。
    返り値: tupleは木と測定行辞書。
    """
    model = {"model_id": "人工", "nodes": [{"id": 1, "left": -1}, {"id": 2, "left": -1}, {"id": 3, "left": -1}],
        "training": {"row_ids": []}}
    rows = {}
    for i in range(count):
        session = "2026-01-" + str(i % 10 + 1).zfill(2) + "_Day"
        for side in (1, -1):
            identity = {"slot_id": "枠" + str(i), "side": side, "session": session}
            model["training"]["row_ids"].append(identity)
            rows[identity["slot_id"], side] = {**identity, "ready": True, "features": [side], "status": "確定完結",
                "barrier": {"outcome": "250" if side == 1 else "125", "end_time": 50.0},
                "recovery_end_time": 60.0, "operation": {"closed": [{"pnl0": 200.0 * side + 100,
                    "pnl5": 200.0 * side, "pnl10": 200.0 * side - 100}]}}
    return model, rows


class Tests(unittest.TestCase):
    """旧木を変更せず回収条件だけ加わることを検査する。"""

    def test_support_and_mean(self) -> None:
        """60枠支持と正負・空葉を検査する。

        引数: なし。
        返り値: None。
        """
        model, rows = fixture()
        before = deepcopy((model, rows))
        result = R.aggregate(model, rows, 100.0, Learner)
        self.assertEqual(result["used_direction_rows"], 120)
        self.assertTrue(result["leaves"]["1"]["support"])
        self.assertEqual(result["leaves"]["1"]["mean_yen"]["5"], 200.0)
        self.assertTrue(result["leaves"]["1"]["positive"])
        self.assertFalse(result["leaves"]["2"]["positive"])
        self.assertIsNone(result["leaves"]["3"]["mean_yen"]["5"])
        self.assertEqual(before, (model, rows))

    def test_one_unknown_removes_both(self) -> None:
        """片側品質注意を両側の校正から除く。

        引数: なし。
        返り値: None。
        """
        model, rows = fixture()
        rows["枠0", -1]["status"] = "品質注意完結"
        result = R.aggregate(model, rows, 100, Learner)
        self.assertEqual(result["used_direction_rows"], 118)
        self.assertFalse(result["leaves"]["1"]["support"])

    def test_same_leaf_unique(self) -> None:
        """同枠両側の葉内所属を2枠として数えない。

        引数: なし。
        返り値: None。
        """
        model, rows = fixture(30)
        for row in rows.values():
            row["features"] = [1]
        leaf = R.aggregate(model, rows, 100, Learner)["leaves"]["1"]
        self.assertEqual((leaf["direction_rows"], leaf["unique_slots"]), (60, 30))
        self.assertFalse(leaf["support"])
        self.assertFalse(leaf["positive"])

    def test_future_recovery(self) -> None:
        """回収終点の評価開始同秒も拒否する。

        引数: なし。
        返り値: None。
        """
        model, rows = fixture()
        rows["枠0", 1]["recovery_end_time"] = 100.0
        with self.assertRaises(ValueError):
            R.aggregate(model, rows, 100.0, Learner)

    def test_future_barrier(self) -> None:
        """障壁終点が未来の教師を拒否する。

        引数: なし。
        返り値: None。
        """
        model, rows = fixture()
        rows["枠0", 1]["barrier"]["end_time"] = 101.0
        with self.assertRaises(ValueError):
            R.aggregate(model, rows, 100.0, Learner)

    def test_pair_required(self) -> None:
        """旧教師の片側欠落を拒否する。

        引数: なし。
        返り値: None。
        """
        model, rows = fixture()
        model["training"]["row_ids"].pop()
        with self.assertRaises(ValueError):
            R.aggregate(model, rows, 100.0, Learner)

    def test_no_rescue_and_strict_zero(self) -> None:
        """回収0と最高側非正で次点へ救済しない。

        引数: なし。
        返り値: None。
        """
        model, rows = fixture()
        for row in rows.values():
            if row["side"] == 1:
                row["operation"]["closed"][0]["pnl5"] = 0.0
            else:
                row["operation"]["closed"][0]["pnl5"] = 1000.0
        calibration = R.aggregate(model, rows, 100.0, Learner)
        self.assertEqual(R.predict(model, calibration, {}, Learner, "C0")["side"], 1)
        self.assertEqual(R.predict(model, calibration, {}, Learner, "R0")["side"], 0)

    def test_decimal_sign(self) -> None:
        """十進数で相殺する平均0を正へ丸めない。

        引数: なし。
        返り値: None。
        """
        model, rows = fixture()
        values = (0.1, 0.2, -0.3)
        for i in range(60):
            rows["枠" + str(i), 1]["operation"]["closed"][0]["pnl5"] = values[i % 3]
        leaf = R.aggregate(model, rows, 100.0, Learner)["leaves"]["1"]
        self.assertFalse(leaf["positive"])
        self.assertEqual(leaf["mean_yen"]["5"], 0.0)

    def test_original_wait_preserved(self) -> None:
        """元のWAITを回収条件で採用へ変更しない。

        引数: なし。
        返り値: None。
        """
        model, rows = fixture()
        calibration = R.aggregate(model, rows, 100.0, Learner)
        model["old_side"] = 0
        self.assertEqual(R.predict(model, calibration, {}, Learner, "R0")["side"], 0)


if __name__ == "__main__":
    unittest.main()
