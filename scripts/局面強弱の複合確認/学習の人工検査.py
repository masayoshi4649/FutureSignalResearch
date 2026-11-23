"""手作り54特徴で、同46教師・未知mask・枝別52列とJSON採否を検査する。"""

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
    返り値: ModuleTypeは読込結果。実入力・保存モデルは読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = load(HERE.parent / "方向と再開確認/学習の人工検査.py", "局面強弱63の固定62人工材料")
M = load(HERE / "学習.py", "局面強弱63の人工対象")
F, EVALUATION = OLD.F, OLD.EVALUATION
ADDED = [("ADX15水準", "I08", "trend"), ("ADX15現前差", "I08", "trend"),
    ("絶対BB幅対現在ATR3", "I05", "vol"), ("絶対BB幅現前差対現在ATR3", "I05", "vol"),
    ("ADX現在有効", "I08", "trend"), ("ADX現前差有効", "I08", "trend"),
    ("BB現在有効", "I05", "vol"), ("BB現前差有効", "I05", "vol")]
METADATA = [*deepcopy(F.FEATURES), *[{"id": f"F{47 + i:02d}", "name": name, "method": method,
    "family": family, "scale": "m15"} for i, (name, method, family) in enumerate(ADDED)]]


# ----------------------------------------
def training_rows() -> list[dict]:
    """旧46の四群を保ち、両方向同値の追加指標で回収差を作る。

    引数: なし。
    返り値: list[dict]は800人工方向行。追加未知でもpairを落とさない。
    """
    rows = OLD.training_rows()
    for index, row in enumerate(rows):
        pair, side_index = index // 2, index % 2
        d, k = (pair % 2) ^ side_index, (pair // 2) % 2
        a, b, mask, c = (pair // 4) % 2, (pair // 8) % 2, (pair // 16) % 2, (pair // 32) % 2
        values = [0.0] * 46
        values[0], values[15] = 1.0 if d else -1.0, 1.0
        tk, rk = (0, k) if d == 0 else (k, 0)
        values[18:24] = [3, tk, tk, 0.2, 0, 0]
        values[24:30] = [4, rk, rk, 0.2, 0, 0]
        values += [0.0, (-.2 if a else 0.0) if mask else 0.0, .5 + 2 * b, 1.0 if c else -1.0,
            mask, mask, 1, 1]
        signal = b if d == 0 and k == 0 else c if d == 0 else mask if k == 0 else a
        target = (200 if signal else -200) if d == 0 and k == 0 else (150 if signal else -150) if d == 0 else (250 if signal else -250) if k == 0 else (-300 if signal else -500)
        row["features"] = values
        row["outcome"] = "250" if target > 0 else "125"
        row.update(pnl0=str(target + 100), pnl5=str(target), pnl10=str(target - 100))
    return rows


# ----------------------------------------
def group_of(row: dict) -> tuple:
    """期待群をnumpyのfloat32比較で独立に求める。

    引数: row(dict)は人工方向行。
    返り値: tuple[int,int]はDI枝と、その枝で参照するk旗。
    """
    values = np.asarray(row["features"], dtype=np.float32)
    d = int(values[0] > np.float32(0))
    return d, int(values[26 if d == 0 else 20] > np.float32(.5))


class DirectionConfirmationTests(unittest.TestCase):
    """DIと対応kを固定しても、教師・資格・未知の意味を変えないことを確認する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """四つの非空子を持つ人工回帰木だけを一度作る。

        引数: cls(type)は検査クラス。
        返り値: None。本物fitをしない。
        """
        cls.rows = training_rows()
        cls.model = M.fit(cls.rows, METADATA, "J0", "人工63四群", EVALUATION)

    # ----------------------------------------
    def test_固定三nodeと枝別52列の全所属(self) -> None:
        """四つの別sklearn子と合成全node・global特徴・全予測を照合する。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。
        """
        structure = self.model["structure"]
        self.assertEqual((structure["kind"], structure["child_features"], structure["child_depth"], structure["max_depth"]),
            ("fixed_direction_confirmation", 52, 2, 4))
        self.assertEqual([node["feature"] for node in self.model["nodes"][:3]], [0, 26, 20])
        self.assertEqual([node["threshold"] for node in self.model["nodes"][:3]], [0.0, .5, .5])
        self.assertEqual(set(self.model["training"]["partition"]), {"D0_K0", "D0_K1", "D1_K0", "D1_K1"})
        for node_id, selected in ((0, self.rows), (1, [v for v in self.rows if group_of(v)[0] == 0]),
                (2, [v for v in self.rows if group_of(v)[0] == 1])):
            ids = [{"session": v["session"], "slot_id": v["slot_id"], "side": v["side"]} for v in selected]
            node = self.model["nodes"][node_id]
            self.assertEqual((node["direction_rows"], node["weighted_rows"]), (len(selected), len(selected) * .5))
            self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
        for d in (0, 1):
            excluded = [0, 26 if d == 0 else 20]
            projection = [index for index in range(54) if index not in excluded]
            self.assertEqual(structure["child_feature_indices"][f"D{d}"], projection)
            self.assertEqual(structure["excluded_feature_indices"][f"D{d}"], excluded)
            self.assertIn(20 if d == 0 else 26, projection)
            for k in (0, 1):
                selected = [row for row in self.rows if group_of(row) == (d, k)]
                x = np.asarray([row["features"] for row in selected], dtype=np.float32)[:, projection]
                y = np.asarray([float(row["pnl5"]) for row in selected], dtype=np.float64)
                estimator = DecisionTreeRegressor(**M.regressor_parameters(2)).fit(x, y, sample_weight=np.full(len(y), .5))
                part = self.model["training"]["partition"][f"D{d}_K{k}"]
                self.assertEqual((part["d"], part["k"], part["route"], part["policy"]), (d, k, "R" if d == 0 else "T", "J0"))
                self.assertEqual((part["child_feature_indices"], part["excluded_feature_indices"]), (projection, excluded))
                self.assertTrue(part["fit_performed"])
                visits = estimator.decision_path(x)
                for local in range(estimator.tree_.node_count):
                    node = self.model["nodes"][part["root"] + local]
                    members = [selected[i] for i in visits[:, local].nonzero()[0].tolist()]
                    ids = [{"session": v["session"], "slot_id": v["slot_id"], "side": v["side"]} for v in members]
                    self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
                    self.assertEqual((node["direction_rows"], node["weighted_rows"]), (len(members), .5 * len(members)))
                    self.assertEqual(node["regression_value"], float(estimator.tree_.value[local, 0, 0]))
                    self.assertEqual(node["impurity"], float(estimator.tree_.impurity[local]))
                    if node["feature"] >= 0:
                        self.assertEqual(node["feature"], projection[estimator.tree_.feature[local]])
                        self.assertNotIn(node["feature"], excluded)
                for row, leaf, value in zip(selected, estimator.apply(x), estimator.predict(x)):
                    actual, path = M.walk(self.model, row["features"])
                    self.assertEqual(actual, part["root"] + int(leaf))
                    self.assertEqual(self.model["nodes"][actual]["regression_value"], float(value))
                    self.assertLessEqual(len(path), 4)

    # ----------------------------------------
    def test_同46射影の全六指紋と54canonical(self) -> None:
        """使用ID/回収target不変と、追加値を含む新指紋を分けて確認する。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。
        """
        used, training = M.prepare_rows(self.rows, EVALUATION)
        projected = [{**row, "features": row["features"][:46]} for row in self.rows]
        old_used, old = M.LEGACY.prepare_rows(projected, EVALUATION)
        self.assertEqual([row["features"][:46] for row in used], [row["features"] for row in old_used])
        self.assertEqual(training["base46_fingerprints"], {name: old[name] for name in M.FINGERPRINT_FIELDS})
        for name in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "row_ids", "row_ids_sha256", "target_rows_sha256", "period_sha256"):
            self.assertEqual(training[name], old[name])
        self.assertEqual(training["input_rows_sha256"], M.fingerprint(used))
        self.assertEqual(training["used_rows_sha256"], M.fingerprint(used))
        self.assertNotEqual(training["used_rows_sha256"], old["used_rows_sha256"])
        self.assertEqual(training["feature_missing_handling"], "旧62全46準備の同じ教師pair。追加8指標は未知0＋有効mask、追加除外なし")
        self.assertTrue(all(self.rows[i]["features"][46:] == self.rows[i + 1]["features"][46:] for i in range(0, len(self.rows), 2)))
        self.assertTrue(any(node["feature"] >= 46 for node in self.model["nodes"][3:]))

    # ----------------------------------------
    def test_pair除外は枝分割より先(self) -> None:
        """一側未知でpair全体を落とし、枝内で片側だけ教師へ救済しない。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        rows[0]["pnl5"] = None
        used, training = M.prepare_rows(rows, EVALUATION)
        self.assertEqual((len(used), training["recovery_excluded_pair_count"]), (798, 1))
        self.assertFalse(any(row["slot_id"] == rows[0]["slot_id"] for row in used))

    # ----------------------------------------
    def test_未来境界と旗領域を旧61通り拒否(self) -> None:
        """回収終了同秒・不正旗・別政策の学習を拒否する。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。
        """
        for index, value in ((20, .5), (26, True), (26, 2), (0, float("inf"))):
            vector = deepcopy(self.rows[0]["features"])
            vector[index] = value
            with self.assertRaises(ValueError):
                M.float32(vector)
        rows = deepcopy(self.rows)
        rows[0]["recovery_end_time"] = EVALUATION
        with self.assertRaises(ValueError):
            M.prepare_rows(rows, EVALUATION)
        with self.assertRaises(ValueError):
            M.feature_metadata(METADATA, "J1")

    # ----------------------------------------
    def test_固定trendとpriceでも技法gateを残す(self) -> None:
        """固定経路が旧条件を構造的に満たすことと、条件自体の維持を確認する。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。
        """
        self.assertEqual([node["family"] for node in self.model["nodes"][:3]], ["trend", "price", "price"])
        for leaf in [node for node in self.model["nodes"] if node["left"] == -1]:
            self.assertTrue(leaf["method_support"])
            self.assertTrue(M.leaf_eligibility(leaf, leaf["path"])["method_support"])
            self.assertTrue({"trend", "price"} <= set(leaf["families"]))
        self.assertFalse(M.leaf_eligibility({"score": .5, "unique_slots": 60, "days": 6, "sessions": 10}, [{"family": "price"}])["method_support"])

    # ----------------------------------------
    def test_最高側不適格と同点に低い側救済なし(self) -> None:
        """回収平均が高い下位側へ方向変更せず、支持59・同点をWAITにする。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。
        """
        model = deepcopy(self.model)
        high, low = self.rows[0]["features"], self.rows[-1]["features"]
        hi, lo = M.walk(model, high)[0], M.walk(model, low)[0]
        self.assertNotEqual(hi, lo)
        for leaf, score, mean in ((hi, .9, -1000), (lo, .5, 1000)):
            model["nodes"][leaf].update(score=score, regression_value=mean, unique_slots=60, days=6, sessions=10)
        self.assertEqual(M.predict(model, {"1": high, "-1": low})["side"], 1)
        model["nodes"][hi]["unique_slots"] = 59
        value = M.predict(model, {"1": high, "-1": low})
        self.assertEqual((value["side"], value["winner_side"]), (0, 1))
        self.assertEqual(value["scores"], {"1": .9, "-1": .5})
        self.assertIn("最高側葉支持不足", value["reason"])
        model["nodes"][hi]["score"] = .5
        self.assertEqual(M.predict(model, {"1": high, "-1": low})["reason"], "同点WAIT")

    # ----------------------------------------
    def test_float32DI零化と対応旗の境界(self) -> None:
        """微小正DIの零化は低側、最小正float32は高側へ進む。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。厳密DI0の運用WAITは後段で保持する。
        """
        zero = deepcopy(self.rows[0]["features"])
        tiny, positive = deepcopy(zero), deepcopy(zero)
        zero[0], tiny[0], positive[0] = 0.0, math.nextafter(0.0, math.inf), float(np.nextafter(np.float32(0), np.float32(1)))
        zero_leaf, zero_path = M.walk(self.model, zero)
        tiny_leaf, tiny_path = M.walk(self.model, tiny)
        positive_leaf, positive_path = M.walk(self.model, positive)
        self.assertEqual((zero_leaf, zero_path), (tiny_leaf, tiny_path))
        self.assertEqual([part["feature"] for part in zero_path[:2]], [0, 26])
        self.assertEqual([part["feature"] for part in positive_path[:2]], [0, 20])
        self.assertEqual((zero_path[0]["branch"], positive_path[0]["branch"]), ("left", "right"))
        self.assertNotEqual(zero_leaf, positive_leaf)
        negative_zero = deepcopy(zero)
        negative_zero[0] = -0.0
        self.assertEqual(M.walk(self.model, zero), M.walk(self.model, negative_zero))

    # ----------------------------------------
    def test_空群でも固定三nodeと未知を保持(self) -> None:
        """低側一群だけでも高側固定内部nodeを残し、片側未知なら両WAITにする。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][0] = -1
            row["features"][25] = row["features"][26] = 0
        model = M.fit(rows, METADATA, "J0", "人工63空群", EVALUATION)
        self.assertEqual([node["feature"] for node in model["nodes"][:3]], [0, 26, 20])
        self.assertTrue(model["nodes"][2]["data_absent"])
        self.assertIsNone(model["nodes"][2]["score"])
        self.assertEqual(sum(part["fit_performed"] for part in model["training"]["partition"].values()), 1)
        known, unknown = rows[0]["features"], deepcopy(rows[0]["features"])
        unknown[0] = 1
        value = M.predict(model, {"1": unknown, "-1": known})
        self.assertEqual((value["side"], value["reason"]), (0, "未学習枝WAIT"))
        self.assertIsNone(value["scores"]["1"])
        self.assertIsNotNone(value["scores"]["-1"])

    # ----------------------------------------
    def test_追加値域とmask整合と既知零(self) -> None:
        """未知0と既知0を区別し、mask不正と差だけ有効を拒否する。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。
        """
        zero = deepcopy(self.rows[0]["features"])
        zero[46:] = [0] * 8
        known = deepcopy(zero)
        known[50:] = [1] * 4
        self.assertEqual(M.float32(zero)[46:50], M.float32(known)[46:50])
        self.assertNotEqual(M.float32(zero)[50:], M.float32(known)[50:])
        for index, value in ((46, 1.01), (47, -1.01), (48, -1), (49, float("inf")), (50, .5), (51, True)):
            invalid = deepcopy(known)
            invalid[index] = value
            with self.assertRaises(ValueError):
                M.float32(invalid)
        for value_index, mask_index in zip(range(46, 50), range(50, 54)):
            invalid = deepcopy(known)
            invalid[mask_index] = 0
            invalid[value_index] = .1
            with self.assertRaises(ValueError):
                M.float32(invalid)
        for current_mask, delta_mask in ((50, 51), (52, 53)):
            invalid = deepcopy(known)
            invalid[current_mask], invalid[delta_mask] = 0, 1
            with self.assertRaises(ValueError):
                M.float32(invalid)
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][46:] = [0] * 8
        used, training = M.prepare_rows(rows, EVALUATION)
        self.assertEqual(len(used), 800)
        self.assertEqual(training["recovery_excluded_pair_count"], 0)

    # ----------------------------------------
    def test_鏡像と入力旧global保全(self) -> None:
        """方向入替でスコアと葉を交換し、旧module・入力・元木を変えない。

        引数: self(DirectionConfirmationTests)は検査先。
        返り値: None。
        """
        before = deepcopy((self.rows, M.LEGACY.RULES, M.BASE.RULES, self.model))
        for index in range(0, 40, 2):
            vectors = {"1": self.rows[index]["features"], "-1": self.rows[index + 1]["features"]}
            original = M.predict(self.model, vectors)
            reflected = M.predict(self.model, {"1": vectors["-1"], "-1": vectors["1"]})
            self.assertEqual(reflected["side"], -original["side"])
            self.assertEqual(reflected["scores"], {"1": original["scores"]["-1"], "-1": original["scores"]["1"]})
            self.assertEqual(reflected["leafs"], {"1": original["leafs"]["-1"], "-1": original["leafs"]["1"]})
        self.assertEqual((self.rows, M.LEGACY.RULES, M.BASE.RULES, self.model), before)
        self.assertEqual(set(self.model["shared_source_sha256"]), {"scripts/方向局面分岐/学習.py", "scripts/局所帯分岐/学習.py",
            "scripts/回収目的分岐/学習.py", "scripts/波の区間分離/学習.py", "scripts/現行経路の状態分岐/学習.py", "scripts/方向と再開確認/学習.py"})
        json.dumps(self.model, ensure_ascii=False, allow_nan=False)


# ----------------------------------------
def run() -> dict:
    """人工fitと独立比較だけを実行して小型結果を返す。

    引数: なし。
    返り値: dictは成功/件数。本物入力・教師・保存モデルの読取はしない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DirectionConfirmationTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun,
        "人工fit_API": 2, "人工回帰器fit_対象": 5, "独立比較回帰器fit": 4,
        "市場入力読取": False, "実モデル学習": False, "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["全件一致"] else 1)
