"""旧採否から独立した同特徴・同教師の接続とDI同値待機を人工で確認する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location("方向局面接続人工主", Path(__file__).with_name("検証.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture() -> tuple[dict, dict]:
    """Z0でも準備済みの人工枠を作る。

    引数: なし。
    返り値: tuple[dict,dict]は保存枠と18列特徴。
    """
    slot = {"session": "2026-10-19_Day", "slot_id": "人工枠", "scheduled": 100., "time": 100., "line": 1,
            "side": -1, "ready": False, "role": "反転"}
    vectors = {str(s): [float(s)] * 17 + [0.] for s in (1, -1)}
    feature = {"ready": True, "reason": "", "base": {"ready": True}, "vectors": vectors,
        "control_vectors": {s: v[:17] for s, v in vectors.items()}, "atr": 25., "D": 25., "background_direction": 1,
        "history": {"contexts": {s: {"z": 0} for s in vectors}}}
    return slot, feature


class ConnectionTests(unittest.TestCase):
    """市場へ触れず、当時特徴から純判断までを確認する。"""

    def test_same_eighteen_columns_as_53(self) -> None:
        """53F0と同じ18列・readyだけを渡し、元辞書を変更しない。

        引数: なし。
        返り値: None。
        """
        _, feature = fixture()
        before = deepcopy(feature)
        current = M.policy_features({"人工枠": feature})
        prior = M.P53.policy_features({"人工枠": feature}, "F0")
        self.assertEqual(current, prior)
        self.assertEqual(len(current["人工枠"]["vectors"]["1"]), 18)
        self.assertEqual(feature, before)

    def test_old_adoption_and_future_result_not_used(self) -> None:
        """旧採否・将来結果・保有を変えても現在特徴だけで判断する。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        observed = []

        def predict(model: dict, vectors: dict) -> dict:
            """渡された特徴を記録し一定方向を返す。

            引数: model(dict)はモデル、vectors(dict)は人工18列。
            返り値: dictは一定の買い判断。
            """
            observed.append(deepcopy(vectors))
            return {"side": 1, "reason": "人工採用"}

        args = ({"人工枠": feature}, SimpleNamespace(predict=predict), {"model_id": "D0_W20"}, "W20")
        a = M.new_slots({"slots": [slot]}, *args)
        changed = {**slot, "side": 1, "ready": True, "holding": True, "outcome": "250"}
        b = M.new_slots({"slots": [changed]}, *args)
        self.assertEqual(a, b)
        self.assertEqual(observed, [feature["vectors"], feature["vectors"]])
        self.assertEqual((a[0]["side"], a[0]["role"]), (1, "順行"))

    def test_unready_never_rescued(self) -> None:
        """基礎特徴だけ準備済みでも局所帯不足を補完しない。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        feature.update(ready=False, reason="局所不足", vectors={"1": [], "-1": []})
        row = M.new_slots({"slots": [slot]}, {"人工枠": feature}, object(), {"model_id": "D0_W20"}, "W20")[0]
        self.assertEqual((row["ready"], row["side"], row["prediction"]), (False, 0, None))
        self.assertEqual(row["slot_id"], slot["slot_id"])

    def test_same_teacher_rows_as_53(self) -> None:
        """未来不足pairも学習器の除外へ渡すまで53と同じ教師行にする。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        baseline = {("人工枠", s): {**{k: slot[k] for k in ("slot_id", "session", "scheduled", "time", "line")},
            "side": s, "outcome": "不足" if s == -1 else "250"} for s in (1, -1)}
        args = ([{"session": slot["session"]}], {slot["session"]: {"slots": [slot]}})
        a = M.P.training_rows(*args, M.policy_features({"人工枠": feature}), baseline)
        b = M.P.training_rows(*args, M.P53.policy_features({"人工枠": feature}, "F0"), baseline)
        self.assertEqual(a, b)
        self.assertEqual(a[1]["方向行数"], 2)

    def test_neutral_background_wait(self) -> None:
        """固定DI左枝へ入る同値を反転役割として売買しない。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        feature["background_direction"] = 0

        def predict(model: dict, vectors: dict) -> dict:
            """一定の買い判断を返す人工予測器。

            引数: model(dict)とvectors(dict)は未使用。
            返り値: dictは買い判断。
            """
            return {"side": 1, "reason": "人工採用"}

        row = M.new_slots({"slots": [slot]}, {"人工枠": feature}, SimpleNamespace(predict=predict), {"model_id": "D0_W20"}, "W20")[0]
        self.assertEqual((row["side"], row["role"], row["reason"]), (0, "待機", "上位DI同値の役割未確定WAIT"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
