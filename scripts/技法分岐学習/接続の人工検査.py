"""時系列の場分割と、旧判断・将来教師を採否へ戻さない接続を検査する。"""

from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location("技法分岐_接続人工主", Path(__file__).with_name("検証.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def chosen(model: dict, vectors: dict) -> dict:
    """入力特徴だけで選ぶ偽学習済み判定を返す。

    引数: model(dict)は未使用モデル、vectors(dict)は方向特徴。
    返り値: dictは偽得点と方向。
    """
    return {"side": 1, "reason": "人工採用", "scores": {"1": .8, "-1": .2}}


def fixture() -> tuple[dict, dict]:
    """元の採否が不正でも新特徴が準備済みの人工枠を作る。

    引数: なし。
    返り値: tuple[dict,dict]は保存枠と準備特徴。
    """
    slot = {"session": "2026-10-19_Day", "slot_id": "人工枠", "scheduled": 100.0,
            "time": 100.0, "line": 1, "side": -1, "ready": False, "role": "反転"}
    feature = {"ready": True, "reason": "準備済", "vectors": {"1": [1.0] * 15, "-1": [-1.0] * 15},
               "background_direction": 1, "atr": 25.0, "D": 25.0}
    return slot, feature


class ConnectionTests(unittest.TestCase):
    """本物の学習と市場価格を使わない主接続の検査。"""

    def test_whole_session_forward_phases(self) -> None:
        """全場単位で学習と後続が分離され、初20を評価へ混ぜないことを確認する。

        引数: なし。
        返り値: None。
        """
        origin = datetime(2026, 9, 1)
        entries = [{"session": (origin + timedelta(days=day)).date().isoformat() + "_" + kind}
                   for day in range(33) for kind in ("Day", "Night")]
        phases = M.phases(entries)
        self.assertEqual([(len(p["train"]), len(p["evaluation"])) for p in phases], [(20, 10), (30, 10), (40, 26)])
        all_evaluation = [e["session"] for p in phases for e in p["evaluation"]]
        self.assertEqual(all_evaluation, [e["session"] for e in entries[20:]])
        self.assertEqual(len(set(all_evaluation)), 46)
        for phase in phases:
            self.assertLess(M.C.bounds(phase["train"][-1]["session"])[2], phase["evaluation_start"])

    def test_old_adoption_and_future_labels_not_inputs(self) -> None:
        """旧採否・将来の結果を変えても、同じ新特徴の方向は変わらない。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        model = {"model_id": "Q0_W20"}
        actual = M.new_slots({"slots": [slot]}, {"人工枠": feature}, SimpleNamespace(predict=chosen), model, "Q0", "W20")
        changed = {**slot, "side": 1, "ready": True, "outcome": "250", "holding": True, "role": "順行"}
        repeated = M.new_slots({"slots": [changed]}, {"人工枠": feature}, SimpleNamespace(predict=chosen), model, "Q0", "W20")
        self.assertEqual(actual, repeated)
        self.assertEqual((actual[0]["side"], actual[0]["role"]), (1, "順行"))

    def test_unknown_features_do_not_score(self) -> None:
        """特徴未準備では予測器を呼ばず、不足を0得点に置換しない。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        feature.update(ready=False, reason="特徴不足", vectors={"1": [], "-1": []}, background_direction=None)
        actual = M.new_slots({"slots": [slot]}, {"人工枠": feature}, object(), {"model_id": "Q0_W20"}, "Q0", "W20")[0]
        self.assertIsNone(actual["prediction"])
        self.assertEqual((actual["ready"], actual["side"], actual["reason"]), (False, 0, "特徴不足"))

    def test_di_neutral_keeps_wait(self) -> None:
        """上位同値を反転という意味ラベルへ捏造しない。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        feature["background_direction"] = 0
        actual = M.new_slots({"slots": [slot]}, {"人工枠": feature}, SimpleNamespace(predict=chosen), {"model_id": "Q0_W20"}, "Q0", "W20")[0]
        self.assertTrue(actual["ready"])
        self.assertEqual((actual["side"], actual["role"]), (0, "待機"))

    def test_unknown_teacher_pair_reaches_fit(self) -> None:
        """将来不足を特徴準備へ戻さず、両方向教師を学習器へ渡す。

        引数: なし。
        返り値: None。
        """
        slot, feature = fixture()
        baseline = {("人工枠", side): {**{k: slot[k] for k in ("slot_id", "session", "scheduled", "time", "line")},
                    "side": side, "filled": True, "outcome": "250" if side == 1 else "不足"} for side in (1, -1)}
        rows, quality = M.training_rows([{"session": slot["session"]}], {slot["session"]: {"slots": [slot]}}, {"人工枠": feature}, baseline)
        self.assertEqual([r["outcome"] for r in rows], ["250", "不足"])
        self.assertEqual((quality["特徴準備枠"], quality["方向行数"]), (1, 2))
        before = deepcopy(slot)
        feature["ready"] = False
        rows, quality = M.training_rows([{"session": slot["session"]}], {slot["session"]: {"slots": [slot]}}, {"人工枠": feature}, {})
        self.assertEqual(rows, [])
        self.assertEqual(slot, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
