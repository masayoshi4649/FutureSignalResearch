"""手作り60特徴で、DIと対応現在有効の四群・58列投影・JSON採否を検査する。"""

from copy import deepcopy
from decimal import Decimal, localcontext
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


OLD = load(HERE.parent / "量と価格進行/学習の人工検査.py", "現在状態65の固定64人工材料")
M = load(HERE / "学習.py", "現在状態と量価格65の人工対象")
METADATA, EVALUATION = deepcopy(OLD.META60), OLD.EVALUATION


# ----------------------------------------
def training_rows() -> list[dict]:
    """四つの現在状態群に別の人工回収差を持つ800方向行を作る。

    引数: なし。
    返り値: list[dict]は人工60特徴/障壁/回収。市場・数量入力は使わない。
    """
    rows = OLD.training_rows()
    for index, row in enumerate(rows):
        pair, side_index = index // 2, index % 2
        d, v, signal = (pair % 2) ^ side_index, (pair // 2) % 2, (pair // 4) % 2
        values = [0.0] * 60
        values[0], values[15] = 1.0 if d else -1.0, 1.0
        tv, rv = (0, v) if d == 0 else (v, 0)
        values[18:24], values[24:30] = [1, tv, 0, -1, 0, 0], [1, rv, 0, -1, 0, 0]
        values[50:54] = [1, 1, 1, 1]
        values[54:] = [1.0, 0.0, 0.0, 0.0, 1, 1]
        if d == 0 and v == 0:
            values[54] = .5 + signal
            target = 200 if signal else -200
        elif d == 0 and v == 1:
            values[17] = signal
            target = 150 if signal else -150
        elif d == 1 and v == 0:
            values[2] = 1.0 if signal else -1.0
            target = 250 if signal else -250
        else:
            values[59] = signal
            target = -300 if signal else -500
        row.update(features=values, outcome="250" if target > 0 else "125",
            pnl0=str(target + 100), pnl5=str(target), pnl10=str(target - 100))
    return rows


# ----------------------------------------
def group_of(row: dict) -> tuple:
    """期待群をnumpyのfloat32比較で独立に求める。

    引数: row(dict)は人工方向行。
    返り値: tuple[int,int]はDI枝と、その枝で参照する現在有効旗。
    """
    values = np.asarray(row["features"], dtype=np.float32)
    d = int(values[0] > np.float32(0))
    return d, int(values[25 if d == 0 else 19] > np.float32(.5))


class CurrentEpisodeTests(unittest.TestCase):
    """DIと対応現在有効を固定しても、教師・資格・未知の意味を変えないことを確認する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """四つの非空子を持つ人工回帰木だけを一度作る。

        引数: cls(type)は検査クラス。
        返り値: None。本物fitをしない。
        """
        cls.rows = training_rows()
        cls.model = M.fit(cls.rows, METADATA, "U0", "人工65四群", EVALUATION)

    # ----------------------------------------
    def assert_statistics(self, node: dict, rows: list[dict]) -> None:
        """独立所属から障壁率・費用別Decimal平均・MSEを別検算する。

        引数: self(CurrentEpisodeTests)は検査先、node(dict)は保存node、rows(list[dict])は独立所属。
        返り値: None。回収と障壁の目的を混ぜない。
        """
        score = sum(row["outcome"] == "250" for row in rows) / len(rows)
        self.assertEqual(node["score"], score)
        self.assertEqual(node["barrier_gini"], 2 * score * (1 - score))
        self.assertEqual(node["unique_slots"], len({(row["session"], row["slot_id"]) for row in rows}))
        self.assertEqual(node["days"], len({row["session"][:10] for row in rows}))
        self.assertEqual(node["sessions"], len({row["session"] for row in rows}))
        with localcontext() as context:
            context.prec = 80
            for field in ("pnl0", "pnl5", "pnl10"):
                total = sum((Decimal(row[field]) for row in rows), Decimal(0))
                self.assertEqual(Decimal(node["recovery"][field]["sum"]), total)
                self.assertEqual(Decimal(node["recovery"][field]["mean_decimal"]), total / len(rows))
            values = [Decimal(row["pnl5"]) for row in rows]
            total = sum(values)
            mse = (len(rows) * sum(value * value for value in values) - total * total) / len(rows) ** 2
            self.assertEqual(Decimal(node["recovery_mse_decimal"]), mse)
            self.assertEqual(node["recovery_positive"], total > 0)

    # ----------------------------------------
    def test_固定三nodeと枝別58列の全所属(self) -> None:
        """四つの別sklearn子と合成全node・global特徴・全予測を照合する。

        引数: self(CurrentEpisodeTests)は検査先。
        返り値: None。
        """
        structure = self.model["structure"]
        self.assertEqual((structure["kind"], structure["child_features"], structure["child_depth"], structure["max_depth"]),
            ("fixed_direction_current_episode", 58, 2, 4))
        self.assertEqual([node["feature"] for node in self.model["nodes"][:3]], [0, 25, 19])
        self.assertEqual([node["threshold"] for node in self.model["nodes"][:3]], [0.0, .5, .5])
        self.assertEqual(set(self.model["training"]["partition"]), {"D0_V0", "D0_V1", "D1_V0", "D1_V1"})
        for node_id, selected in ((0, self.rows), (1, [v for v in self.rows if group_of(v)[0] == 0]),
                (2, [v for v in self.rows if group_of(v)[0] == 1])):
            ids = [{"session": v["session"], "slot_id": v["slot_id"], "side": v["side"]} for v in selected]
            node = self.model["nodes"][node_id]
            self.assertEqual((node["direction_rows"], node["weighted_rows"]), (len(selected), len(selected) * .5))
            self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
            self.assert_statistics(node, selected)
        for d in (0, 1):
            excluded = [0, 25 if d == 0 else 19]
            projection = [index for index in range(60) if index not in excluded]
            self.assertEqual(structure["child_feature_indices"][f"D{d}"], projection)
            self.assertEqual(structure["excluded_feature_indices"][f"D{d}"], excluded)
            self.assertIn(19 if d == 0 else 25, projection)
            for v in (0, 1):
                selected = [row for row in self.rows if group_of(row) == (d, v)]
                x = np.asarray([row["features"] for row in selected], dtype=np.float32)[:, projection]
                y = np.asarray([float(row["pnl5"]) for row in selected], dtype=np.float64)
                estimator = DecisionTreeRegressor(**M.regressor_parameters(2)).fit(x, y, sample_weight=np.full(len(y), .5))
                part = self.model["training"]["partition"][f"D{d}_V{v}"]
                self.assertEqual((part["d"], part["v"], part["route"], part["policy"]), (d, v, "R" if d == 0 else "T", "U0"))
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
                    self.assert_statistics(node, members)
                    if node["feature"] >= 0:
                        self.assertEqual(node["feature"], projection[estimator.tree_.feature[local]])
                        self.assertNotIn(node["feature"], excluded)
                for row, leaf, value in zip(selected, estimator.apply(x), estimator.predict(x)):
                    actual, path = M.walk(self.model, row["features"])
                    self.assertEqual(actual, part["root"] + int(leaf))
                    self.assertEqual(self.model["nodes"][actual]["regression_value"], float(value))
                    self.assertLessEqual(len(path), 4)

    # ----------------------------------------
    def test_旧60canonicalと全六指紋一致(self) -> None:
        """固定段変更前に同じpairを確定し、旧18/30/38/46指紋も保つ。

        引数: self(CurrentEpisodeTests)は検査先。
        返り値: None。
        """
        used, training = M.prepare_rows(self.rows, EVALUATION)
        old_used, old = M.LEGACY.prepare_rows(self.rows, EVALUATION)
        self.assertEqual(used, old_used)
        for name in (*M.FINGERPRINT_FIELDS, "base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints", "base54_fingerprints", "row_ids"):
            self.assertEqual(training[name], old[name])
        self.assertEqual(training["base60_fingerprints"], {name: old[name] for name in M.FINGERPRINT_FIELDS})
        self.assertEqual(training["feature_missing_handling"], "旧64全60特徴・同じ教師pair。追加情報・追加除外なし")
        self.assertTrue(all(group_of(self.rows[index])[0] != group_of(self.rows[index + 1])[0] for index in range(0, len(self.rows), 2)))

    # ----------------------------------------
    def test_pair除外は枝分割より先(self) -> None:
        """一側未知でpair全体を落とし、枝内で片側だけ教師へ救済しない。

        引数: self(CurrentEpisodeTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        rows[0]["pnl5"] = None
        used, training = M.prepare_rows(rows, EVALUATION)
        self.assertEqual((len(used), training["recovery_excluded_pair_count"]), (798, 1))
        self.assertFalse(any(row["slot_id"] == rows[0]["slot_id"] for row in used))

    # ----------------------------------------
    def test_未来境界と旗領域を旧64通り拒否(self) -> None:
        """回収終了同秒・不正旗・別政策の学習を拒否する。

        引数: self(CurrentEpisodeTests)は検査先。
        返り値: None。
        """
        for index, value in ((19, .5), (25, True), (25, 2), (0, float("inf"))):
            vector = deepcopy(self.rows[0]["features"])
            vector[index] = value
            with self.assertRaises(ValueError):
                M.float32(vector)
        rows = deepcopy(self.rows)
        rows[0]["recovery_end_time"] = EVALUATION
        with self.assertRaises(ValueError):
            M.prepare_rows(rows, EVALUATION)
        with self.assertRaises(ValueError):
            M.feature_metadata(METADATA, "U1")

    # ----------------------------------------
    def test_固定trendとpriceでも技法gateを残す(self) -> None:
        """固定経路が旧条件を構造的に満たすことと、条件自体の維持を確認する。

        引数: self(CurrentEpisodeTests)は検査先。
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

        引数: self(CurrentEpisodeTests)は検査先。
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

        引数: self(CurrentEpisodeTests)は検査先。
        返り値: None。厳密DI0の運用WAITは後段で保持する。
        """
        zero = deepcopy(self.rows[0]["features"])
        tiny, positive = deepcopy(zero), deepcopy(zero)
        zero[0], tiny[0], positive[0] = 0.0, math.nextafter(0.0, math.inf), float(np.nextafter(np.float32(0), np.float32(1)))
        zero_leaf, zero_path = M.walk(self.model, zero)
        tiny_leaf, tiny_path = M.walk(self.model, tiny)
        positive_leaf, positive_path = M.walk(self.model, positive)
        self.assertEqual((zero_leaf, zero_path), (tiny_leaf, tiny_path))
        self.assertEqual([part["feature"] for part in zero_path[:2]], [0, 25])
        self.assertEqual([part["feature"] for part in positive_path[:2]], [0, 19])
        self.assertEqual((zero_path[0]["branch"], positive_path[0]["branch"]), ("left", "right"))
        self.assertNotEqual(zero_leaf, positive_leaf)
        negative_zero = deepcopy(zero)
        negative_zero[0] = -0.0
        self.assertEqual(M.walk(self.model, zero), M.walk(self.model, negative_zero))

    # ----------------------------------------
    def test_空群でも固定三nodeと未知を保持(self) -> None:
        """低側一群だけでも高側固定内部nodeを残し、片側未知なら両WAITにする。

        引数: self(CurrentEpisodeTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][0] = -1
            row["features"][19] = row["features"][25] = 0
        model = M.fit(rows, METADATA, "U0", "人工65空群", EVALUATION)
        self.assertEqual([node["feature"] for node in model["nodes"][:3]], [0, 25, 19])
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
    def test_鏡像と入力旧global保全(self) -> None:
        """方向入替でスコアと葉を交換し、旧module・入力・元木を変えない。

        引数: self(CurrentEpisodeTests)は検査先。
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
            "scripts/回収目的分岐/学習.py", "scripts/波の区間分離/学習.py", "scripts/現行経路の状態分岐/学習.py",
            "scripts/方向と再開確認/学習.py", "scripts/局面強弱の複合確認/学習.py", "scripts/量と価格進行/学習.py"})
        json.dumps(self.model, ensure_ascii=False, allow_nan=False)

    # ----------------------------------------
    def test_共同mask未知と既知零で教師を追加除外しない(self) -> None:
        """量価格未知も同じ教師IDを保ち、共同mask矛盾だけを拒否する。

        引数: self(CurrentEpisodeTests)は検査先。
        返り値: None。数量入力のloadや市場計算は呼ばない。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][54:] = [0] * 6
        used, training = M.prepare_rows(rows, EVALUATION)
        self.assertEqual(len(used), 800)
        self.assertEqual(training["row_ids"], self.model["training"]["row_ids"])
        old_used, old = M.LEGACY.prepare_rows(rows, EVALUATION, 60)
        self.assertEqual(used, old_used)
        self.assertEqual(training["base60_fingerprints"], {name: old[name] for name in M.FINGERPRINT_FIELDS})
        unknown = deepcopy(rows[0]["features"])
        known = deepcopy(unknown)
        known[58:] = [1, 1]
        self.assertEqual(M.float32(known)[54:58], M.float32(unknown)[54:58])
        self.assertNotEqual(M.float32(known)[58:], M.float32(unknown)[58:])
        for index, value in ((54, -1), (56, -1), (55, float("inf")), (58, .5), (59, True)):
            bad = deepcopy(known)
            bad[index] = value
            with self.assertRaises(ValueError):
                M.float32(bad)
        for mask, field in ((58, 54), (58, 55), (59, 56), (59, 57)):
            bad = deepcopy(known)
            bad[mask], bad[field] = 0, .1
            with self.assertRaises(ValueError):
                M.float32(bad)
        independent = deepcopy(known)
        independent[58] = 0
        self.assertEqual(M.float32(independent)[59], 1)

    # ----------------------------------------
    def test_政策と60次元及びmetadataを厳密検査(self) -> None:
        """U1別fit・54列・不正metadataを新規に許可しない。

        引数: self(CurrentEpisodeTests)は検査先。
        返り値: None。人工の不正入力を拒否する。
        """
        with self.assertRaises(ValueError):
            M.float32(self.rows[0]["features"][:54])
        with self.assertRaises(ValueError):
            M.float32(self.rows[0]["features"][:54], 54)
        with self.assertRaises(ValueError):
            M.prepare_rows(self.rows, EVALUATION, 54)
        with self.assertRaises(ValueError):
            M.feature_metadata(METADATA, "U1")
        with self.assertRaises(ValueError):
            M.feature_metadata(METADATA[:54], "U0")
        bad = deepcopy(METADATA)
        bad[54]["family"] = "price"
        with self.assertRaises(ValueError):
            M.feature_metadata(bad, "U0")

    # ----------------------------------------
    def test_旧64純予測の局所射影と全負回収群(self) -> None:
        """政策射影で旧globalを変えず、全負平均でも子の分岐を作る。

        引数: self(CurrentEpisodeTests)は検査先。
        返り値: None。方向順位は回収でなく障壁scoreのまま。
        """
        part = self.model["training"]["partition"]["D1_V1"]
        self.assertGreater(part["node_count"], 1)
        selected = self.model["nodes"][part["root"]:part["root"] + part["node_count"]]
        self.assertTrue(all(node["recovery_positive"] is False for node in selected))
        self.assertTrue(any(node["feature"] == 59 for node in selected))
        before = deepcopy((self.model, M.LEGACY.RULES))
        for index in range(0, 40, 2):
            vectors = {"1": self.rows[index]["features"], "-1": self.rows[index + 1]["features"]}
            projected = {**self.model, "policy": "Q0"}
            self.assertEqual(M.predict(self.model, vectors), M.LEGACY.predict(projected, vectors))
        self.assertEqual((self.model, M.LEGACY.RULES), before)


# ----------------------------------------
def run() -> dict:
    """人工fitと独立比較だけを実行して小型結果を返す。

    引数: なし。
    返り値: dictは成功/件数。本物入力・教師・保存モデルの読取はしない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CurrentEpisodeTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun,
        "人工fit_API": 2, "人工回帰器fit_対象": 5, "独立比較回帰器fit": 4,
        "市場入力読取": False, "実モデル学習": False, "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["全件一致"] else 1)
