"""66の選択結果と旧純判断・DI役割を、架空の保存行で検査する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location("適格方向66の人工主", Path(__file__).with_name("検証.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def input_slot(identity: str = "架空0", ready: bool = True, background: int = 1) -> dict:
    """市場と無関係な当時入力を作る。

    引数: identity(str)は枠名、ready(bool)は準備、background(int)はraw背景方向。
    返り値: dictはslots_forに必要な最小保存行。
    """
    return {"session": "架空場", "slot_id": identity, "scheduled": 0, "time": 1, "line": 2,
        "phase": "W20", "model_id": "架空木", "feature": {"ready": ready, "reason": "架空未準備",
            "vectors": {"1": [1], "-1": [-1]}, "background_direction": background, "atr": 20, "D": 20}}


def saved_pair(before: int, after: int, identity: str = "架空0") -> tuple:
    """旧予測参照が同一な新旧の架空判断を作る。

    引数: before/after(int)は旧新side、identity(str)は枠名。
    返り値: tuple[dict,dict]は新行・旧行。
    """
    old = {**input_slot(identity), "side": before, "ready": True, "reason": "旧不適格",
        "prediction": {"side": before, "reason": "旧不適格"}}
    new = {**deepcopy(old), "side": after, "prediction": {"side": after,
        "reference": deepcopy(old["prediction"]), "rescued": not before and bool(after)}}
    return new, old


class ConnectionTests(unittest.TestCase):
    """架空接続だけを検査し、保存本物・市場・学習を開かない。"""

    def test_unready_does_not_predict(self) -> None:
        """未準備で選択器を呼ばず、理由を保持する。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        row = input_slot(ready=False)
        result = M.slots_for({"slots": [row]}, {}, {}, SimpleNamespace(), "E0")[0]
        self.assertEqual((result["side"], result["role"], result["prediction"]), (0, "待機", None))
        self.assertEqual(result["reason"], "架空未準備")

    def test_raw_di_zero_keeps_prediction_but_waits(self) -> None:
        """raw同値の後段WAITと予測救済を区別する。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        row = input_slot(background=0)
        prediction = {"side": -1, "reason": "適格な他方向を採用", "rescued": True}
        selector = SimpleNamespace(predict=lambda *args: prediction)
        result = M.slots_for({"slots": [row]}, {}, {}, selector, "E1")[0]
        self.assertEqual((result["side"], result["role"]), (0, "待機"))
        self.assertEqual(result["prediction"], prediction)
        self.assertIs(result["feature"], row["feature"])

    def test_mirrored_role_and_policy(self) -> None:
        """売買を反射しても同じ反転役割と当時入力を保つ。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        for side in (1, -1):
            row = input_slot(background=-side)
            selector = SimpleNamespace(predict=lambda *args: {"side": side, "reason": "採用"})
            result = M.slots_for({"slots": [row]}, {}, {}, selector, "E0")[0]
            self.assertEqual((result["side"], result["role"], result["policy"]), (side, "反転", "E0"))
            self.assertEqual((result["time"], result["line"]), (1, 2))

    def test_pure_addition_has_separate_denominator(self) -> None:
        """旧採用と新追加を同じ二枠で分離する。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        a, b = saved_pair(1, 1, "共通"), saved_pair(0, -1, "追加")
        result = M.selection_stats([a[0], b[0]], [a[1], b[1]])
        self.assertEqual((result["全予定枠"], result["旧純採用"], result["新純採用"]), (2, 1, 2))
        self.assertEqual((result["共通同方向"], result["追加純候補"], result["予測救済"]), (1, 1, 1))
        self.assertEqual(result["追加時旧理由"], {"旧不適格": 1})

    def test_existing_choice_cannot_be_changed(self) -> None:
        """対応する旧政策の採用を消す又は反転する誤接続を拒否する。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        for after in (0, -1):
            new, old = saved_pair(1, after)
            with self.assertRaises(ValueError):
                M.selection_stats([new], [old])

    def test_reference_or_feature_mutation_is_rejected(self) -> None:
        """同じ入力又は旧予測を名目だけで再用する誤りを拒否する。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        for target in ("feature", "reference"):
            new, old = saved_pair(0, 1)
            if target == "feature":
                new["feature"]["atr"] = 99
            else:
                new["prediction"]["reference"]["reason"] = "別理由"
            with self.assertRaises(ValueError):
                M.selection_stats([new], [old])


if __name__ == "__main__":
    unittest.main()
