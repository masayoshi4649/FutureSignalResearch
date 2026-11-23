"""手作りの旧予測契約だけで、適格先行の方向選択を検査する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("適格方向66の人工対象", HERE / "選択.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SIDES = ("1", "-1")


# ----------------------------------------
class ManualLearner:
    """木を学習せず、同じ手作り葉辞書を両方向へ適用する人工の旧API。"""

    @staticmethod
    def predict(model: dict, vectors: dict) -> dict:
        """旧learnerと同じ返却契約を手作りの葉から作る。

        引数: model(dict)は人工2葉、vectors(dict)は各側の葉番号1値又は両空。
        返り値: dictはraw score最高側と従来資格。実モデル・fit・市場を読まない。
        """
        if vectors == {"1": [], "-1": []}:
            return {"scores": {s: None for s in SIDES}, "leafs": {s: None for s in SIDES},
                "side": 0, "winner_side": 0, "reason": "特徴未準備WAIT", "eligibility": {s: None for s in SIDES}}
        scores, leafs, eligibility = {}, {}, {}
        for side in SIDES:
            leaf = vectors[side][0]
            node = model["nodes"][leaf]
            leafs[side], scores[side] = leaf, node["score"]
            eligibility[side] = None if node["score"] is None else {"score": node["score"] >= 1 / 3,
                "leaf_support": node["unique_slots"] >= 60 and node["days"] >= 6 and node["sessions"] >= 10,
                "method_support": len(node["families"]) >= 2 and bool(set(node["families"]) & {"trend", "osc"}),
                "families": deepcopy(node["families"])}
        result = {"scores": scores, "leafs": leafs, "side": 0, "winner_side": 0,
            "reason": "同点WAIT", "eligibility": eligibility}
        if any(scores[s] is None for s in SIDES):
            result["reason"] = "未学習枝WAIT"
            return result
        if scores["1"] == scores["-1"]:
            return result
        winner = "1" if scores["1"] > scores["-1"] else "-1"
        result["winner_side"] = int(winner)
        failures = [reason for name, reason in (("score", "最高側score下限未達"),
            ("leaf_support", "最高側葉支持不足"), ("method_support", "最高側複数技法不足")) if not eligibility[winner][name]]
        result.update(side=0 if failures else int(winner), reason="/".join(failures) if failures else "採用")
        return result


# ----------------------------------------
def recovery_leaf(leaf: int, mean: str = "10", unique: int = 60, days: int = 6, sessions: int = 10) -> dict:
    """回収支持とstrict正額を独立な人工値から作る。

    引数: leaf(int)は葉ID、mean(str)は人工平均、unique/days/sessions(int)は支持件数。
    返り値: dictは旧cal予測が必要とする保存部分集合。集計対象行や実損益は持たない。
    """
    value = Decimal(mean)
    return {"leaf": leaf, "unique_slots": unique, "days": days, "sessions": sessions,
        "support": unique >= 60 and days >= 6 and sessions >= 10, "positive": value > 0,
        "sum_yen": {"5": str(value * unique)}, "mean_yen": {"5": float(value)}}


# ----------------------------------------
def fixture() -> tuple:
    """旧最高側が買いで両側適格の人工入力を作る。

    引数: なし。
    返り値: tuple[dict,dict,dict]は人工model/cal/vectors。実入力は参照しない。
    """
    nodes = [{"id": index, "score": score, "unique_slots": 60, "days": 6, "sessions": 10,
        "families": ["price", "trend"]} for index, score in enumerate((.6, .4))]
    return {"model_id": "人工66", "nodes": nodes}, {"model_id": "人工66",
        "leaves": {"0": recovery_leaf(0), "1": recovery_leaf(1, "20")}}, {"1": [0], "-1": [1]}


class SelectionTests(unittest.TestCase):
    """資格と順位の順序だけが変わり、旧WAIT境界を保つことを確認する。"""

    def test_元最高側適格なら旧互換欄が完全一致(self) -> None:
        """E0/E1とも最高側を保ち、旧R55の全referenceを複写する。

        引数: self(SelectionTests)は検査先。
        返り値: None。新fitをしない。
        """
        model, cal, vectors = fixture()
        for policy, reference_policy in (("E0", "C0"), ("E1", "R0")):
            value = M.predict(model, cal, vectors, ManualLearner, policy)
            expected = M.REFERENCE.predict(model, cal, vectors, ManualLearner, reference_policy)
            self.assertEqual(value["reference"], expected)
            self.assertEqual({name: value[name] for name in expected}, expected)
            self.assertEqual((value["side"], value["original_winner_side"], value["selected_side"], value["rescued"]), (1, 1, 1, False))
            self.assertEqual(value["eligible_sides"], [1, -1])

    # ----------------------------------------
    def test_複数技法不足を他側が補う(self) -> None:
        """元最高側の技法不足だけを理由に、全資格適格な低側を選べる。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, vectors = fixture()
        model["nodes"][0]["families"] = ["trend"]
        value = M.predict(model, cal, vectors, ManualLearner, "E0")
        self.assertEqual((value["side"], value["rescued"], value["reference"]["side"]), (-1, True, 0))
        self.assertEqual(value["rescue_reasons"], ["複数技法不足"])
        self.assertEqual(value["reason"], "適格な他方向を採用")
        self.assertEqual(value["recovery_leaf"], 1)

    # ----------------------------------------
    def test_葉支持不足を他側が補う(self) -> None:
        """60枠/6日/10場の各不足を個別に救済理由へ保存する。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        for field, invalid in (("unique_slots", 59), ("days", 5), ("sessions", 9)):
            model, cal, vectors = fixture()
            model["nodes"][0][field] = invalid
            value = M.predict(model, cal, vectors, ManualLearner, "E0")
            self.assertEqual(value["side"], -1)
            self.assertEqual(value["rescue_reasons"], ["葉支持不足"])

    # ----------------------------------------
    def test_回収支持不足を他側が補う(self) -> None:
        """旧回収支持の各不足を読み、回収値の高低では順位を変えない。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        for kwargs in ({"unique": 59}, {"days": 5}, {"sessions": 9}):
            model, cal, vectors = fixture()
            cal["leaves"]["0"] = recovery_leaf(0, "1000", **kwargs)
            value = M.predict(model, cal, vectors, ManualLearner, "E0")
            self.assertEqual((value["side"], value["reference"]["reason"]), (-1, "回収支持不足WAIT"))
            self.assertEqual(value["rescue_reasons"], ["回収支持不足"])

    # ----------------------------------------
    def test_正回収条件でE1はE0と方向が逆転し得る(self) -> None:
        """E0は元最高側、E1は正回収の低側を選び同方向包含を要求しない。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, vectors = fixture()
        cal["leaves"]["0"] = recovery_leaf(0, "-10")
        basic = M.predict(model, cal, vectors, ManualLearner, "E0")
        positive = M.predict(model, cal, vectors, ManualLearner, "E1")
        self.assertEqual((basic["side"], positive["side"]), (1, -1))
        self.assertEqual(positive["rescue_reasons"], ["過去回収平均非正"])
        self.assertEqual(positive["reference"]["reason"], "過去回収平均非正WAIT")

    # ----------------------------------------
    def test_両側不適格と全理由を保持(self) -> None:
        """理由の優先で他の不足を隠さず、両側不適格ならWAITにする。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, vectors = fixture()
        for node in model["nodes"]:
            node.update(score=.2, unique_slots=59, families=["trend"])
        model["nodes"][1]["score"] = .1
        cal["leaves"]["0"] = recovery_leaf(0, "0", unique=59)
        cal["leaves"]["1"] = recovery_leaf(1, "-1", days=5)
        value = M.predict(model, cal, vectors, ManualLearner, "E1")
        self.assertEqual((value["side"], value["reason"], value["eligible_sides"]), (0, "両方向不適格WAIT", []))
        self.assertEqual(value["direction_eligibility"]["1"]["reasons"],
            ["score下限未達", "葉支持不足", "複数技法不足", "回収支持不足", "過去回収平均非正"])

    # ----------------------------------------
    def test_raw同点は片側だけ適格でもWAIT(self) -> None:
        """資格でraw同点を解消しない。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, vectors = fixture()
        model["nodes"][0].update(score=.4, families=["trend"])
        value = M.predict(model, cal, vectors, ManualLearner, "E0")
        self.assertEqual(value["eligible_sides"], [-1])
        self.assertEqual((value["side"], value["reason"], value["ranking_block_reason"], value["rescued"]),
            (0, "同点WAIT", "同点WAIT", False))

    # ----------------------------------------
    def test_片側未知は既知側が適格でもWAIT(self) -> None:
        """未学習葉をscore0へ置換せず、既知側のみで採用しない。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, vectors = fixture()
        model["nodes"][0]["score"] = None
        value = M.predict(model, cal, vectors, ManualLearner, "E1")
        self.assertEqual((value["side"], value["reason"], value["eligible_sides"]), (0, "未学習枝WAIT", [-1]))
        self.assertIsNone(value["prior"]["scores"]["1"])
        self.assertFalse(value["direction_eligibility"]["1"]["known"])
        self.assertEqual(value["direction_eligibility"]["-1"]["score_value"], .4)

    # ----------------------------------------
    def test_両空の未準備を保持(self) -> None:
        """両空は未学習葉とも零scoreとも区別する。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, _ = fixture()
        value = M.predict(model, cal, {"1": [], "-1": []}, ManualLearner, "E0")
        self.assertEqual((value["side"], value["reason"]), (0, "特徴未準備WAIT"))
        self.assertEqual(value["direction_eligibility"]["1"]["reasons"], ["特徴未準備"])
        self.assertIsNone(value["recovery_leaf"])

    # ----------------------------------------
    def test_modelcal不一致と欠落を拒否(self) -> None:
        """別model_id、既知葉cal欠落、不正政策を拒否する。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, vectors = fixture()
        invalid = deepcopy(cal)
        invalid["model_id"] = "別モデル"
        with self.assertRaises(ValueError):
            M.predict(model, invalid, vectors, ManualLearner, "E0")
        invalid = deepcopy(cal)
        invalid["leaves"].pop("1")
        with self.assertRaises(ValueError):
            M.predict(model, invalid, vectors, ManualLearner, "E0")
        with self.assertRaises(ValueError):
            M.predict(model, cal, vectors, ManualLearner, "E2")

    # ----------------------------------------
    def test_鏡像と入力保全(self) -> None:
        """同じ木への方向交換で選択・元最高側・資格が鏡像になる。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, vectors = fixture()
        cal["leaves"]["0"] = recovery_leaf(0, "-10")
        before = deepcopy((model, cal, vectors))
        for policy in M.POLICIES:
            normal = M.predict(model, cal, vectors, ManualLearner, policy)
            reverse = M.predict(model, cal, {"1": vectors["-1"], "-1": vectors["1"]}, ManualLearner, policy)
            self.assertEqual(reverse["side"], -normal["side"])
            self.assertEqual(reverse["original_winner_side"], -normal["original_winner_side"])
            self.assertEqual(reverse["rescued"], normal["rescued"])
            self.assertEqual(reverse["direction_eligibility"], {"1": normal["direction_eligibility"]["-1"], "-1": normal["direction_eligibility"]["1"]})
        self.assertEqual((model, cal, vectors), before)

    # ----------------------------------------
    def test_正回収はstrict零境界かつfloat平均を再判定しない(self) -> None:
        """Decimal正額の保存boolを使い、未知・丸め零・epsilonを混ぜない。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        for mean in ("0", "-0", "1e-100", "-1e-100", "1e-400"):
            model, cal, vectors = fixture()
            cal["leaves"]["0"] = recovery_leaf(0, mean)
            value = M.predict(model, cal, vectors, ManualLearner, "E1")
            self.assertEqual(value["side"], 1 if Decimal(mean) > 0 else -1)

    # ----------------------------------------
    def test_score下限等号と回収によらない順位(self) -> None:
        """1/3等号は可、回収平均が大きいだけで低側へ変えない。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, vectors = fixture()
        model["nodes"][0]["score"] = 1 / 3
        model["nodes"][1]["score"] = .3
        cal["leaves"]["1"] = recovery_leaf(1, "100000")
        value = M.predict(model, cal, vectors, ManualLearner, "E1")
        self.assertEqual((value["side"], value["rescued"]), (1, False))
        model["nodes"][0]["score"] = .32
        self.assertEqual(M.predict(model, cal, vectors, ManualLearner, "E1")["eligible_sides"], [])

    # ----------------------------------------
    def test_WAITの互換回収欄とreferenceは同じ(self) -> None:
        """不採用時に互換回収値を他側へ差し替えず旧値を保つ。

        引数: self(SelectionTests)は検査先。
        返り値: None。
        """
        model, cal, vectors = fixture()
        cal["leaves"]["0"] = recovery_leaf(0, "-10")
        cal["leaves"]["1"] = recovery_leaf(1, "-20")
        value = M.predict(model, cal, vectors, ManualLearner, "E1")
        self.assertEqual(value["side"], 0)
        for name in ("recovery_leaf", "recovery_support", "recovery_mean5", "prior"):
            self.assertEqual(value[name], value["reference"][name])
        value["reference"]["prior"]["scores"]["1"] = 0
        self.assertEqual(value["prior"]["scores"]["1"], .6)
        self.assertEqual(model["nodes"][0]["score"], .6)


# ----------------------------------------
def run() -> dict:
    """手作り予測の人工だけを実行し、既存参照コード不変も確認する。

    引数: なし。
    返り値: dictは成功・人工件数。市場・教師・本物木・fitは一切読まない。
    """
    before = hashlib.sha256(M.REFERENCE_PATH.read_bytes()).hexdigest()
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SelectionTests))
    unchanged = before == hashlib.sha256(M.REFERENCE_PATH.read_bytes()).hexdigest()
    return {"全件一致": result.wasSuccessful() and unchanged, "人工件数": result.testsRun,
        "人工fit": 0, "新特徴": 0, "本物入力読取": False, "参照コード不変": unchanged,
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if value["全件一致"] else 1)
