"""同じ履歴準備を使う二候補の特徴射影と定時運用への接続を検査する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location("局所帯分岐接続人工主", Path(__file__).with_name("検証.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture() -> tuple[dict, dict]:
    """未発生だが履歴準備が整った人工枠を作る。

    引数: なし。
    返り値: tuple[dict,dict]は元枠と新特徴。
    """
    slot = {"session": "2026-10-19_Day", "slot_id": "人工枠", "scheduled": 100., "time": 100., "line": 1,
            "side": -1, "ready": False, "role": "反転"}
    vectors = {str(s): [float(s)] * 17 for s in (1, -1)}
    history = [0]
    prepared = {"ready": True, "reason": "履歴準備済", "base": {"ready": True}, "control_vectors": vectors,
        "vectors": {s: values + history for s, values in vectors.items()}, "atr": 25., "D": 25.,
        "background_direction": 1, "history": {"人工": True}}
    return slot, prepared


class ConnectionTests(unittest.TestCase):
    """特徴の選び方と共通準備を、未来結果なしで検査する。"""

    def test_common_readiness_different_columns(self) -> None:
        """共通準備のまま17/18列だけを切り替える。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        before = deepcopy(feature)
        c = M.policy_features({"人工枠": feature}, "B0")["人工枠"]
        h = M.policy_features({"人工枠": feature}, "F0")["人工枠"]
        self.assertTrue(c["ready"] and h["ready"])
        self.assertEqual(c["vectors"]["1"], h["vectors"]["1"][:17])
        self.assertEqual((len(c["vectors"]["1"]), len(h["vectors"]["1"])), (17, 18))
        self.assertEqual(feature, before)
        self.assertNotIn("side", c)

    def test_old_adoption_and_future_result_not_used(self) -> None:
        """旧採否・保有・先着を変えても新しい特徴だけで判定する。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        observed = []

        def predict(model: dict, vectors: dict) -> dict:
            """予測に渡された列数を記録する偽得点器。

            引数: model(dict)はモデル、vectors(dict)は方向特徴。
            返り値: dictは一定の選択方向。
            """
            observed.append(len(vectors["1"]))
            return {"side": 1, "reason": "人工採用"}

        for policy, size in (("B0", 17), ("F0", 18)):
            model = {"model_id": policy + "_W20"}
            a = M.new_slots({"slots": [slot]}, {"人工枠": feature}, SimpleNamespace(predict=predict), model, policy, "W20")
            changed = {**slot, "side": 1, "ready": True, "holding": True, "outcome": "250"}
            b = M.new_slots({"slots": [changed]}, {"人工枠": feature}, SimpleNamespace(predict=predict), model, policy, "W20")
            self.assertEqual(a, b)
            self.assertEqual(observed[-2:], [size, size])
            self.assertEqual((a[0]["side"], a[0]["role"]), (1, "順行"))

    def test_history_gap_never_rescued_by_base(self) -> None:
        """基礎特徴が準備済みでも、履歴不足なら両候補とも予測しない。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        feature.update(ready=False, reason="窓欠測", vectors={"1": [], "-1": []}, control_vectors={"1": [], "-1": []})
        for policy in M.POLICIES:
            row = M.new_slots({"slots": [slot]}, {"人工枠": feature}, object(), {"model_id": policy + "_W20"}, policy, "W20")[0]
            self.assertEqual((row["ready"], row["side"], row["prediction"]), (False, 0, None))
            self.assertTrue(row["feature"]["base"]["ready"])

    def test_same_teacher_pair_in_both_controls(self) -> None:
        """履歴未発生を除かず、同じ両方向教師を列数だけ変えて渡す。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        baseline = {("人工枠", s): {**{k: slot[k] for k in ("slot_id", "session", "scheduled", "time", "line")},
            "side": s, "outcome": "不足" if s == -1 else "250"} for s in (1, -1)}
        rows = {}
        for policy in M.POLICIES:
            rows[policy], quality = M.P.training_rows([{"session": slot["session"]}], {slot["session"]: {"slots": [slot]}},
                M.policy_features({"人工枠": feature}, policy), baseline)
            self.assertEqual((quality["特徴準備枠"], quality["方向行数"]), (1, 2))
        self.assertEqual([{k: v for k, v in r.items() if k != "features"} for r in rows["B0"]],
                         [{k: v for k, v in r.items() if k != "features"} for r in rows["F0"]])

    def test_neutral_background_wait(self) -> None:
        """DI同値を反転という役割へ付け替えない。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        feature["background_direction"] = 0

        def predict(model: dict, vectors: dict) -> dict:
            """一定方向を返す人工予測器。

            引数: model(dict)とvectors(dict)は未使用。
            返り値: dictは買い方向。
            """
            return {"side": 1, "reason": "人工採用"}

        row = M.new_slots({"slots": [slot]}, {"人工枠": feature}, SimpleNamespace(predict=predict), {"model_id": "F0_W20"}, "F0", "W20")[0]
        self.assertEqual((row["side"], row["role"]), (0, "待機"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
