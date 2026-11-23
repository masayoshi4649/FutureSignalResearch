"""同60接続・実役割・現在有効四群の分母を人工で確認する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


SPEC = importlib.util.spec_from_file_location("現在状態の人工接続", Path(__file__).with_name("検証.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture() -> tuple:
    """U0とU1の同じ最高側を作る人工入力を用意する。

    引数: なし。
    返り値: tupleはblock/prepared/model/calibration/learner。
    """
    block = {"slots": [{"session": "2026-10-05_Day", "slot_id": "人工", "scheduled": 900., "time": 900., "line": 1}]}
    prepared = {"人工": {"ready": True, "reason": "", "vectors": {"1": [0.] * 60, "-1": [0.] * 60},
        "background_direction": 1, "atr": 50., "D": 50.}}
    model = {"model_id": "人工U0", "policy": "U0"}
    calibration = {"model_id": "人工U0", "leaves": {"3": {"leaf": 3, "support": True, "positive": False, "mean_yen": {"5": -1.}}}}

    def predict(actual: dict, vectors: dict) -> dict:
        """60列の参照を確認し、評価損益を見ない人工買いを返す。

        引数: actual/vectors(dict)は当時入力。
        返り値: dictは人工予測。
        """
        assert actual is model and vectors is prepared["人工"]["vectors"]
        assert all(len(value) == 60 for value in vectors.values())
        return {"side": 1, "reason": "採用", "leafs": {"1": 3, "-1": 4}}

    return block, prepared, model, calibration, SimpleNamespace(predict=predict)


def path(identity: str | None, active: bool, stage: str | None = "b") -> dict:
    """出生から取消までの小さい経路辞書を用意する。

    引数: identity(str|None)は形成ID、active(bool)は現在有効、stage(str|None)は到達段階。
    返り値: dictはT/R共通の人工状態。
    """
    names = ("b", "f", "r", "k")
    end = names.index(stage) if stage else -1
    return {"episode_id": identity, "episode_valid": active,
        "cancel": {"理由": "人工取消"} if identity and not active else None,
        "stage": end + 1, "k_valid": active and stage == "k",
        **{name: {"index": index} if identity and index <= end else None for index, name in enumerate(names)}}


def float32(values: list) -> list:
    """DIの零化を含む旧精度へ人工列を変換する。

    引数: values(list)は特徴。
    返り値: listはfloat32へ丸めた値。
    """
    return M.C.np.asarray(values, dtype=M.C.np.float32).tolist()


class ConnectionTests(unittest.TestCase):
    """本物入力を開かず判断接続の境界を確認する。"""

    def test_同じ最高側への回収条件(self):
        """回収正条件が最高側を除くだけで元入力を変えない。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        args = fixture()
        before = deepcopy(args[:4])
        base = M.slots_for(*args, "U0", "W20")[0]
        strict = M.slots_for(*args, "U1", "W20")[0]
        self.assertEqual((base["side"], base["role"]), (1, "順行"))
        self.assertEqual((strict["side"], strict["reason"]), (0, "過去回収平均非正WAIT"))
        self.assertEqual(args[:4], before)

    def test_DI同値と実役割(self):
        """群の対応とraw DIの最終役割を区別する。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        args = fixture()
        args[1]["人工"]["background_direction"] = -1
        self.assertEqual(M.slots_for(*args, "U0", "W20")[0]["role"], "反転")
        args[1]["人工"]["background_direction"] = 0
        item = M.slots_for(*args, "U0", "W20")[0]
        self.assertEqual((item["side"], item["reason"]), (0, "上位DI同値の役割未確定WAIT"))

    def test_未準備は予測しない(self):
        """準備不足を予測や既知0へ置換しない。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        block, prepared, model, cal, _ = fixture()
        prepared["人工"].update(ready=False, reason="未準備")
        item = M.slots_for(block, prepared, model, cal, None, "U0", "W20")[0]
        self.assertIsNone(item["prediction"])
        self.assertEqual(item["reason"], "未準備")

    def test_政策の取り違いを拒否(self):
        """旧Q木や不明政策を新Uとして実行しない。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        args = fixture()
        with self.assertRaises(ValueError):
            M.slots_for(*args, "Q0", "W20")
        args[2]["policy"] = "Q0"
        with self.assertRaises(ValueError):
            M.slots_for(*args, "U0", "W20")

    def test_段階と取消は排他的(self):
        """出生の過去成立数を現在の出生段階数と混同しない。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        self.assertEqual(M.current_stage(path(None, False, None)), "未ID又は失効")
        for stage in ("b", "f", "r", "k"):
            self.assertEqual(M.current_stage(path("一形成", True, stage)), stage + "有効")
            self.assertEqual(M.current_stage(path("一形成", False, stage)), stage + "取消")

    def test_四群と対応経路を分ける(self):
        """相手の旗で群を決めず、出生有効を再開完成と呼ばない。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        rows, prepared = [], {}
        for d in (0, 1):
            for v in (0, 1):
                identity = f"{d}_{v}"
                values = [0.] * 60
                values[0], values[25 if d == 0 else 19], values[19 if d == 0 else 25] = 1. if d else -1., v, 1 - v
                rows.append({"session": "2026-10-05_Day", "slot_id": identity, "side": 1, "features": values})
                prepared[identity] = {"paths": {"1": {"T": path("T" + identity, bool(values[19])), "R": path("R" + identity, bool(values[25]))}}}
        before = deepcopy((rows, prepared))
        actual = M.state_distribution(rows, prepared, SimpleNamespace(float32=float32))
        self.assertEqual(list(actual), ["D0_V0", "D0_V1", "D1_V0", "D1_V1"])
        for key, item in actual.items():
            self.assertEqual(item["方向行"], 1)
            route = "R" if key.startswith("D0") else "T"
            self.assertEqual(item["対象経路"], route)
            self.assertEqual(item[route]["kあり"], 0)
            self.assertEqual(item["対象現在段階"], {"b有効" if key.endswith("1") else "b取消": 1})
        self.assertEqual((rows, prepared), before)

    def test_形成反復とfloat32零化(self):
        """微小DIはR枝とし、同形成の観測2枠を2形成にしない。

        引数: self(ConnectionTests)は検査器。
        返り値: None。
        """
        values = [0.] * 60
        values[0], values[19], values[25] = 1e-50, 0, 1
        rows = [{"session": "2026-10-05_Day", "slot_id": str(i), "side": 1, "features": values} for i in range(2)]
        prepared = {str(i): {"paths": {"1": {"T": path(None, False, None), "R": path("同一形成", True, "r")}}} for i in range(2)}
        result = M.state_distribution(rows, prepared, SimpleNamespace(float32=float32))
        selected = result["D0_V1"]
        self.assertEqual((selected["方向行"], selected["unique枠"], selected["R"]["形成ID数"], selected["R"]["最大反復"]), (2, 2, 1, 2))
        self.assertEqual(result["D1_V1"]["方向行"], 0)


if __name__ == "__main__":
    unittest.main()
