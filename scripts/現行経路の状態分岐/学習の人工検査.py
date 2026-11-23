"""手作り46特徴だけで、現T/R四群と同教師・支持gate・JSON予測を検査する。"""

from copy import deepcopy
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest

import numpy as np
from sklearn.tree import DecisionTreeRegressor


HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工工場と純学習コードを固有名で読む。

    引数: path(Path)は対象、name(str)はmodule名。
    返り値: ModuleTypeは読込結果。市場や保存モデルを読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = load(HERE.parent / "波の区間分離/学習の人工検査.py", "現経路の固定60人工材料")
M = load(HERE / "学習.py", "現行経路の人工学習対象")
F = OLD.F
EVALUATION = OLD.EVALUATION


def training_rows() -> list[dict]:
    """同じpairから四群へ方向行が分かれる800人工行を作る。

    引数: なし。
    返り値: list[dict]は人工46特徴/障壁/回収。実価格経路や本物教師ではない。
    """
    rows = OLD.training_rows()
    for index, row in enumerate(rows):
        pair, side_index = index // 2, index % 2
        t, r, signal = (pair % 2) ^ side_index, (pair // 2) % 2, (pair // 4) % 2
        values = [0.0] * 46
        values[15] = 1.0
        values[18:24] = [3, t, t, 0.2, 0, 0]
        values[24:30] = [4, r, r, 0.2, 0, 0]
        if t == 0 and r == 0:
            values[0] = 1.0 if signal else -1.0
            target = 200 if signal else -200
        elif t == 0 and r == 1:
            values[0], values[17] = 1.0, float(signal)
            target = 150 if signal else -150
        else:
            values[45] = float(signal)
            target = (250 if signal else -250) if r == 0 else (-300 if signal else -500)
        row["features"] = values
        row["outcome"] = "250" if target > 0 else "125"
        row.update(pnl0=str(target + 100), pnl5=str(target), pnl10=str(target - 100))
    return rows


class CurrentRouteTests(unittest.TestCase):
    """固定価格旗と子の技法選択を別に確認する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """四つの非空子を持つ人工回帰木だけを一度作る。

        引数: cls(type)は検査クラス。
        返り値: None。本物fitをしない。
        """
        cls.rows = training_rows()
        cls.model = M.fit(cls.rows, F.FEATURES, "A0", "人工61四群", EVALUATION)

    def test_固定四群と44列globalmap全所属(self) -> None:
        """四つの独立sklearn子と、合成全node/予測/global特徴を照合する。

        引数: self(CurrentRouteTests)は検査先。
        返り値: None。
        """
        indexes = [i for i in range(46) if i not in (19, 25)]
        structure = self.model["structure"]
        self.assertEqual((structure["kind"], structure["child_features"], structure["child_depth"], structure["max_depth"]), ("fixed_current_routes", 44, 2, 4))
        self.assertEqual(structure["child_feature_indices"], indexes)
        self.assertEqual([n["feature"] for n in self.model["nodes"][:3]], [19, 25, 25])
        self.assertTrue(all(n["threshold"] == .5 for n in self.model["nodes"][:3]))
        self.assertEqual(set(self.model["training"]["partition"]), {"T0_R0", "T0_R1", "T1_R0", "T1_R1"})
        for node_id, members in ((0, self.rows), (1, [v for v in self.rows if v["features"][19] == 0]),
                (2, [v for v in self.rows if v["features"][19] == 1])):
            ids = [{"session": v["session"], "slot_id": v["slot_id"], "side": v["side"]} for v in members]
            node = self.model["nodes"][node_id]
            self.assertEqual((node["direction_rows"], node["weighted_rows"]), (len(members), len(members) * .5))
            self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
        self.assertTrue(any(n["feature"] == 0 for n in self.model["nodes"][3:]))
        self.assertTrue(any(n["feature"] == 17 for n in self.model["nodes"][3:]))
        self.assertTrue(any(n["feature"] == 45 for n in self.model["nodes"][3:]))
        self.assertTrue(all(n["feature"] not in (19, 25) for n in self.model["nodes"][3:]))
        for t in (0, 1):
            for r in (0, 1):
                selected = [row for row in self.rows if row["features"][19] == t and row["features"][25] == r]
                x = np.asarray([row["features"] for row in selected], dtype=np.float32)[:, indexes]
                y = np.asarray([float(row["pnl5"]) for row in selected], dtype=np.float64)
                estimator = DecisionTreeRegressor(**M.regressor_parameters(2))
                estimator.fit(x, y, sample_weight=np.full(len(selected), .5))
                partition = self.model["training"]["partition"][f"T{t}_R{r}"]
                self.assertEqual((partition["t"], partition["r"], partition["policy"]), (t, r, "A0"))
                self.assertTrue(partition["fit_performed"])
                visits = estimator.decision_path(x)
                for local in range(estimator.tree_.node_count):
                    node = self.model["nodes"][partition["root"] + local]
                    members = [selected[i] for i in visits[:, local].nonzero()[0].tolist()]
                    ids = [{"session": v["session"], "slot_id": v["slot_id"], "side": v["side"]} for v in members]
                    self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
                    self.assertEqual((node["direction_rows"], node["weighted_rows"]), (len(members), .5 * len(members)))
                    self.assertEqual(node["regression_value"], float(estimator.tree_.value[local, 0, 0]))
                    self.assertEqual(node["impurity"], float(estimator.tree_.impurity[local]))
                    if node["feature"] >= 0:
                        self.assertEqual(node["feature"], indexes[estimator.tree_.feature[local]])
                for row, leaf, value in zip(selected, estimator.apply(x), estimator.predict(x)):
                    actual, path = M.walk(self.model, row["features"])
                    self.assertEqual(actual, partition["root"] + int(leaf))
                    self.assertEqual(self.model["nodes"][actual]["regression_value"], float(value))
                    self.assertLessEqual(len(path), 4)

    def test_旧46canonicalと全六指紋一致(self) -> None:
        """固定段変更の前に同じpairを確定し、旧18/30/38もそのまま保持する。

        引数: self(CurrentRouteTests)は検査先。
        返り値: None。
        """
        used, training = M.prepare_rows(self.rows, EVALUATION)
        old_used, old = M.LEGACY.prepare_rows(self.rows, EVALUATION)
        self.assertEqual(used, old_used)
        self.assertEqual(training["base46_fingerprints"], {k: old[k] for k in M.FINGERPRINT_FIELDS})
        for name in (*M.FINGERPRINT_FIELDS, "base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "row_ids"):
            self.assertEqual(training[name], old[name])
        self.assertEqual(training["feature_missing_handling"], "旧60全46特徴・同じ教師pair。追加情報・追加除外なし")
        for group in training_rows()[::2]:
            partner = next(row for row in self.rows if row["slot_id"] == group["slot_id"] and row["side"] == -1)
            self.assertNotEqual(group["features"][19], partner["features"][19])

    def test_pair除外は枝分割より先(self) -> None:
        """一側の回収未知でpair全体を落とし、別枝の片側だけを足さない。

        引数: self(CurrentRouteTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        rows[0]["pnl5"] = None
        used, training = M.prepare_rows(rows, EVALUATION)
        self.assertEqual((len(used), training["recovery_excluded_pair_count"]), (798, 1))
        self.assertFalse(any(row["slot_id"] == rows[0]["slot_id"] for row in used))
        self.assertEqual(training["base46_fingerprints"], {k: M.LEGACY.prepare_rows(rows, EVALUATION)[1][k] for k in M.FINGERPRINT_FIELDS})

    def test_未来境界と旗領域を旧60通り拒否(self) -> None:
        """回収終了同秒や非二値旗を許可する新しい救済を作らない。

        引数: self(CurrentRouteTests)は検査先。
        返り値: None。
        """
        for index, value in ((19, .5), (25, True), (19, 2), (25, float("inf"))):
            vector = deepcopy(self.rows[0]["features"])
            vector[index] = value
            with self.assertRaises(ValueError):
                M.float32(vector)
        rows = deepcopy(self.rows)
        rows[0]["recovery_end_time"] = EVALUATION
        with self.assertRaises(ValueError):
            M.prepare_rows(rows, EVALUATION)
        with self.assertRaises(ValueError):
            M.feature_metadata(F.FEATURES, "A1")

    def test_価格固定段だけでは複数技法条件を満たさない(self) -> None:
        """priceだけの到達葉は不適格、trend/oscを含む子pathだけを資格候補にする。

        引数: self(CurrentRouteTests)は検査先。
        返り値: None。
        """
        for key, part in self.model["training"]["partition"].items():
            leaves = [n for n in self.model["nodes"] if n["left"] == -1 and part["root"] <= n["id"] < part["root"] + part["node_count"]]
            expected = key == "T0_R0"
            for leaf in leaves:
                self.assertEqual(leaf["method_support"], expected)
                self.assertEqual(M.leaf_eligibility(leaf, leaf["path"])["method_support"], expected)
        self.assertTrue(all(node["family"] == "price" for node in self.model["nodes"][:3]))

    def test_最高側不適格でも低い側へ救済しない(self) -> None:
        """回帰平均や下位側の技法資格によって障壁最高側を入れ替えない。

        引数: self(CurrentRouteTests)は検査先。
        返り値: None。
        """
        model = deepcopy(self.model)
        high = next(row["features"] for row in self.rows if row["features"][19] == 1 and row["features"][25] == 0 and row["features"][45] == 1)
        low = next(row["features"] for row in self.rows if row["features"][19] == 0 and row["features"][25] == 0 and row["features"][0] > 0)
        hi, lo = M.walk(model, high)[0], M.walk(model, low)[0]
        for leaf, score, value in ((hi, .9, -1000), (lo, .5, 1000)):
            model["nodes"][leaf].update(score=score, regression_value=value, unique_slots=60, days=6, sessions=10)
        result = M.predict(model, {"1": high, "-1": low})
        self.assertEqual((result["side"], result["winner_side"]), (0, 1))
        self.assertIn("最高側複数技法不足", result["reason"])
        self.assertEqual(result["scores"], {"1": .9, "-1": .5})
        self.assertTrue(result["eligibility"]["-1"]["method_support"])

    def test_支持と同点とfloat32境界(self) -> None:
        """子に戻したDIの零化と最高側支持境界を、同じJSON走査で確認する。

        引数: self(CurrentRouteTests)は検査先。
        返り値: None。
        """
        vector = deepcopy(next(row["features"] for row in self.rows if row["features"][19] == 0 and row["features"][25] == 0))
        zero, tiny, positive = deepcopy(vector), deepcopy(vector), deepcopy(vector)
        zero[0], tiny[0], positive[0] = 0.0, math.nextafter(0.0, math.inf), float(np.nextafter(np.float32(0), np.float32(1)))
        self.assertEqual(M.walk(self.model, zero)[0], M.walk(self.model, tiny)[0])
        self.assertNotEqual(M.walk(self.model, zero)[0], M.walk(self.model, positive)[0])
        model = deepcopy(self.model)
        high, low = M.walk(model, positive)[0], M.walk(model, zero)[0]
        for leaf, score in ((high, .8), (low, .4)):
            model["nodes"][leaf].update(score=score, unique_slots=60, days=6, sessions=10)
        self.assertEqual(M.predict(model, {"1": positive, "-1": zero})["side"], 1)
        model["nodes"][high]["unique_slots"] = 59
        self.assertEqual(M.predict(model, {"1": positive, "-1": zero})["side"], 0)
        model["nodes"][high]["score"] = .4
        self.assertEqual(M.predict(model, {"1": positive, "-1": zero})["reason"], "同点WAIT")

    def test_空群でも固定三nodeと四群を保持(self) -> None:
        """一つの非空群だけを学習しても他群をscore0にせず、片側未知なら両WAITにする。

        引数: self(CurrentRouteTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][19] = row["features"][20] = 0
            row["features"][25] = row["features"][26] = 0
        model = M.fit(rows, F.FEATURES, "A0", "人工61空群", EVALUATION)
        self.assertEqual([node["feature"] for node in model["nodes"][:3]], [19, 25, 25])
        self.assertTrue(model["nodes"][2]["data_absent"])
        self.assertIsNone(model["nodes"][2]["score"])
        self.assertEqual(sum(v["fit_performed"] for v in model["training"]["partition"].values()), 1)
        known, unknown = rows[0]["features"], deepcopy(rows[0]["features"])
        unknown[19] = 1
        result = M.predict(model, {"1": unknown, "-1": known})
        self.assertEqual((result["side"], result["reason"]), (0, "未学習枝WAIT"))
        self.assertIsNone(result["scores"]["1"])
        self.assertIsNotNone(result["scores"]["-1"])

    def test_鏡像と入力旧global保全(self) -> None:
        """方向入替で全予測を交換し、旧moduleと入力辞書を変更しない。

        引数: self(CurrentRouteTests)は検査先。
        返り値: None。
        """
        before = deepcopy((self.rows, M.LEGACY.RULES, M.BASE.RULES, self.model))
        for index in range(0, 40, 2):
            vectors = {"1": self.rows[index]["features"], "-1": self.rows[index + 1]["features"]}
            a = M.predict(self.model, vectors)
            b = M.predict(self.model, {"1": vectors["-1"], "-1": vectors["1"]})
            self.assertEqual(b["side"], -a["side"])
            self.assertEqual(b["scores"], {"1": a["scores"]["-1"], "-1": a["scores"]["1"]})
            self.assertEqual(b["leafs"], {"1": a["leafs"]["-1"], "-1": a["leafs"]["1"]})
        self.assertEqual((self.rows, M.LEGACY.RULES, M.BASE.RULES, self.model), before)
        self.assertEqual(set(self.model["shared_source_sha256"]), {"scripts/方向局面分岐/学習.py", "scripts/局所帯分岐/学習.py", "scripts/回収目的分岐/学習.py", "scripts/波の区間分離/学習.py"})
        json.dumps(self.model, ensure_ascii=False, allow_nan=False)


def run() -> dict:
    """人工fitだけを実行し、件数と検査範囲を返す。

    引数: なし。
    返り値: dictは成功/件数。実入力・教師・保存モデルの読取や本物fitをしない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CurrentRouteTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun,
        "人工fit_API": 2, "人工回帰器fit_対象": 5, "独立比較回帰器fit": 4,
        "市場入力読取": False, "実モデル学習": False,
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["全件一致"] else 1)
