"""本物教師を読まず、回収目的の固定四群合成と障壁採点の境界を確認する。"""

from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest

import numpy as np
from sklearn.tree import DecisionTreeRegressor


HERE = Path(__file__).resolve().parent
OLD_TEST = HERE.parent / "方向局面分岐/学習の人工検査.py"
SPEC = importlib.util.spec_from_file_location("回収目的の固定54人工factory", OLD_TEST)
T54 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T54)
SPEC = importlib.util.spec_from_file_location("回収目的の人工対象", HERE / "学習.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
EVALUATION = T54.EVALUATION


def training_rows() -> list[dict]:
    """旧人工400枠へ、障壁ラベルとは別の回収目的値を置く。

    引数: なし。
    返り値: list[dict]は18列/800方向行。市場・保存教師を読まない。
    """
    rows = T54.T53.training_rows(18)
    for i, row in enumerate(rows):
        category = (i // 2) % 4
        row["features"][15] = float(category)
        value = Decimal((-320, -80, 120, 480)[category])
        row.update(pnl0=str(value + 100), pnl5=str(value), pnl10=str(value - 100), recovery_end_time=row["end_time"] + 60)
    return rows


def oracle(rows: list[dict]) -> DecisionTreeRegressor:
    """明示した固定ハイパーパラメータで、群内17列の独立回帰器を作る。

    引数: rows(list[dict])は既知回収の群内方向行。
    返り値: DecisionTreeRegressorは比較専用。主のパラメータ生成を呼ばない。
    """
    estimator = DecisionTreeRegressor(criterion="squared_error", splitter="best", max_depth=2,
        min_samples_leaf=60, random_state=51, ccp_alpha=0.0, max_features=None)
    estimator.fit(np.asarray([r["features"][:17] for r in rows], dtype=np.float32),
        np.asarray([float(r["pnl5"]) for r in rows], dtype=np.float64), sample_weight=np.repeat(0.5, len(rows)))
    return estimator


class ArtificialTests(unittest.TestCase):
    """回帰と障壁の目的差、未来境界、未知枝、float32を少数人工で確認する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """共通の小型人工モデルを一度だけ学習する。

        引数: cls(type)は検査クラス。
        返り値: None。本物教師・相場・実モデルは扱わない。
        """
        cls.rows, cls.meta = training_rows(), T54.T53.metadata(18)
        cls.model = M.fit(cls.rows, cls.meta, "G0", "人工回収", EVALUATION)

    def test_独立四群回帰器と全node全予測一致(self) -> None:
        """外部学習器の所属・閾値・平均・MSEを全群の合成木と照合する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        offset = 3
        for z in (0, 1):
            for a in (0, 1):
                rows = [r for r in self.rows if r["features"][17] == z and int(np.float32(r["features"][0]) > 0) == a]
                independent = oracle(rows)
                x = np.asarray([r["features"][:17] for r in rows], dtype=np.float32)
                leaves, predictions, visits = independent.apply(x), independent.predict(x), independent.decision_path(x)
                partition = self.model["training"]["partition"][f"Z{z}_a{a}"]
                self.assertEqual((partition["root"], partition["direction_rows"], partition["policy"]), (offset, len(rows), "G0"))
                self.assertEqual(partition["fit_parameters"]["criterion"], "squared_error")
                for local in range(independent.tree_.node_count):
                    node = self.model["nodes"][offset + local]
                    selected = [rows[i] for i in visits[:, local].nonzero()[0].tolist()]
                    ids = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
                    self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
                    self.assertEqual(node["direction_rows"], int(independent.tree_.n_node_samples[local]))
                    self.assertEqual(node["total_weight"], float(independent.tree_.weighted_n_node_samples[local]))
                    self.assertEqual(node["regression_value"], float(independent.tree_.value[local, 0, 0]))
                    self.assertEqual(node["impurity"], float(independent.tree_.impurity[local]))
                    if node["feature"] >= 0:
                        self.assertEqual((node["feature"], node["threshold"]), (int(independent.tree_.feature[local]), float(independent.tree_.threshold[local])))
                for i, row in enumerate(rows):
                    leaf, _ = M.walk(self.model, row["features"])
                    self.assertEqual((leaf, self.model["nodes"][leaf]["regression_value"]), (offset + int(leaves[i]), float(predictions[i])))
                offset += independent.tree_.node_count
        self.assertEqual(offset, len(self.model["nodes"]))

    def test_固定三nodeと17列と最大深さ(self) -> None:
        """固定Z/DI段を保ち、F18を子へ入れずF01は残すことを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        nodes = self.model["nodes"]
        self.assertEqual([(n["id"], n["feature"], n["threshold"]) for n in nodes[:3]], [(0, 17, 0.5), (1, 0, 0.0), (2, 0, 0.0)])
        self.assertEqual((nodes[0]["left"], nodes[0]["right"]), (1, 2))
        self.assertTrue(all(n["feature"] < 17 for n in nodes[3:]))
        self.assertLessEqual(max(len(n["path"]) for n in nodes), 4)
        self.assertEqual(self.model["subtree_parameters"]["min_samples_leaf"], 60)
        self.assertNotIn("class_weight", self.model["subtree_parameters"])
        self.assertFalse(self.model["structure"]["fixed_mse_optimized"])
        for partition in self.model["training"]["partition"].values():
            self.assertEqual(partition["fit_parameters"]["max_depth"], 2)
            root = partition["root"]
            if self.model["nodes"][root]["left"] != -1:
                for node in nodes[root:root + partition["node_count"]]:
                    if node["left"] == node["right"] == -1:
                        self.assertGreaterEqual(node["direction_rows"], 60)

    def test_障壁率と回収統計とMSEの分離(self) -> None:
        """全nodeへ独立に所属行を集め、gini/scoreと回収額を別計算する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for node in self.model["nodes"]:
            selected = []
            for row in self.rows:
                leaf, path = M.walk(self.model, row["features"])
                if node["id"] in [p["node"] for p in path] + [leaf]:
                    selected.append(row)
            rate = sum(r["outcome"] == "250" for r in selected) / len(selected)
            values = [Decimal(r["pnl5"]) for r in selected]
            mean = sum(values) / len(values)
            mse = sum((v - mean) ** 2 for v in values) / len(values)
            self.assertEqual(node["score"], rate)
            self.assertEqual(node["barrier_gini"], 2 * rate * (1 - rate))
            self.assertEqual(Decimal(node["recovery"]["pnl5"]["sum"]), sum(values))
            self.assertEqual(node["recovery"]["pnl5"]["mean"], float(mean))
            self.assertEqual(Decimal(node["recovery_mse_decimal"]), mse)
            self.assertEqual(node["recovery_positive"], sum(values) > 0)
            self.assertEqual(node["total_weight"], len(selected) * 0.5)
            self.assertNotEqual(node["impurity"], node["barrier_gini"])

    def test_全負回収かつ一定障壁でも子木は分岐(self) -> None:
        """黒字フラグや障壁giniを分岐目的へ誤用した場合に失敗する教師を置く。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row.update(outcome="250", pnl0="-1", pnl5=str(-400 + 50 * row["features"][15]), pnl10="-1000")
        model = M.fit(rows, self.meta, "G0", "人工全負回収", EVALUATION)
        self.assertTrue(any(n["feature"] >= 0 for n in model["nodes"][3:]))
        self.assertTrue(all(n["score"] == 1 and n["barrier_gini"] == 0 and n["recovery_positive"] is False for n in model["nodes"]))
        self.assertTrue(any(n["impurity"] > 0 for n in model["nodes"]))

    def test_回収未知は群分割前pair除外し旧指紋を保持(self) -> None:
        """片側回収欠測と旧障壁不足を別stageで残し、双方だけを使用集合から除く。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        rows[0]["pnl5"] = None
        rows[2].update(outcome="不足", filled=False)
        used, training = M.prepare_rows(rows, EVALUATION)
        old_used, old = T54.M.prepare_rows(rows, EVALUATION)
        self.assertEqual((len(used), training["used_pairs"], training["excluded_pair_count"]), (796, 398, 2))
        self.assertEqual((training["barrier_excluded_pair_count"], training["recovery_excluded_pair_count"]), (1, 1))
        self.assertEqual({p["stage"] for p in training["excluded_pairs"]}, {"障壁", "回収"})
        self.assertEqual(training["recovery_missing_counts"], {"side1:pnl5": 1})
        self.assertEqual(training["barrier_fingerprints"], {k: old[k] for k in ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256")})
        self.assertEqual(training["barrier_used_pairs"], len(old_used) // 2)
        self.assertEqual(training["row_ids"], [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in used])
        excluded = {(r["session"], r["slot_id"]) for r in rows[:4]}
        self.assertTrue(all((r["session"], r["slot_id"]) not in excluded for r in used))

    def test_回収値だけの変更で新指紋だけが変わる(self) -> None:
        """旧障壁4指紋は同一、回収を含むinput/used/target指紋は別であることを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        _, original = M.prepare_rows(self.rows, EVALUATION)
        rows = deepcopy(self.rows)
        rows[0]["pnl5"] = "0.00000000000000000000000000000000001"
        used, changed = M.prepare_rows(rows, EVALUATION)
        self.assertEqual(changed["barrier_fingerprints"], original["barrier_fingerprints"])
        self.assertEqual(changed["row_ids_sha256"], original["row_ids_sha256"])
        for key in ("input_rows_sha256", "used_rows_sha256", "target_rows_sha256"):
            self.assertNotEqual(changed[key], original[key])
        self.assertEqual(set(used[0]), set(M.BARRIER_FIELDS) | {"entry_time", "entry_line", *M.MONEY_FIELDS, "recovery_end_time"})

    def test_未来回収と不正数値を拒否(self) -> None:
        """評価同秒や未来を欠測除外へ隠さず、NaN/Inf/boolも拒否する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for end in (EVALUATION, EVALUATION + 1, float("nan"), self.rows[0]["entry_time"] - 0.5):
            rows = deepcopy(self.rows)
            rows[0].update(pnl5=None, recovery_end_time=end)
            with self.assertRaises(ValueError):
                M.prepare_rows(rows, EVALUATION)
        for value in (True, float("nan"), "Infinity", "不正", "1e999", "1e-999"):
            rows = deepcopy(self.rows)
            rows[0]["pnl5"] = value
            with self.assertRaises(ValueError):
                M.prepare_rows(rows, EVALUATION)
        rows = deepcopy(self.rows)
        rows[0]["end_time"] = EVALUATION
        with self.assertRaises(ValueError):
            M.prepare_rows(rows, EVALUATION)
        with self.assertRaises(ValueError):
            M.prepare_rows(self.rows[:-1], EVALUATION)

    def test_空Zの内部固定nodeと未知leafを残す(self) -> None:
        """回帰でも空枝をゼロ利益やゼロ確率へ埋めず、一方未知なら両WAITとする。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][17] = 0
        model = M.fit(rows, self.meta, "G0", "人工空Z", EVALUATION)
        internal = model["nodes"][2]
        self.assertTrue(internal["data_absent"])
        self.assertEqual(internal["feature"], 0)
        for key in ("left", "right"):
            node = model["nodes"][internal[key]]
            self.assertEqual((node["score"], node["regression_value"], node["impurity"], node["recovery_positive"]), (None, None, None, None))
            self.assertEqual(node["recovery"]["pnl5"], {"sum": "0", "mean": None, "mean_decimal": None})
        values = {"1": deepcopy(rows[0]["features"]), "-1": deepcopy(rows[1]["features"])}
        values["-1"][17] = 1
        result = M.predict(model, values)
        self.assertEqual((result["side"], result["reason"]), (0, "未学習枝WAIT"))
        self.assertIsNone(result["scores"]["-1"])

    def test_DIのfloat32同値境界とZ定義域(self) -> None:
        """微小正DIが0へ写るときの群所属とwalkを一致させる。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][0] = row["side"] * 1e-46
        model = M.fit(rows, self.meta, "G0", "人工f32", EVALUATION)
        self.assertEqual(sum(p["direction_rows"] for k, p in model["training"]["partition"].items() if k.endswith("a1")), 0)
        vector = deepcopy(rows[0]["features"])
        for value, branch in ((-1e-46, "left"), (0.0, "left"), (1e-46, "left"), (float(np.nextafter(np.float32(0), np.float32(1))), "right")):
            vector[0] = value
            self.assertEqual(M.walk(model, vector)[1][1]["branch"], branch)
        for value in (0.5, math.nextafter(0.5, 0), True, 2, -1):
            vector[17] = value
            with self.assertRaises(ValueError):
                M.walk(model, vector)

    def test_障壁最高側だけを採用し回収側へ救済しない(self) -> None:
        """回帰平均と逆の障壁率を置いて、rankを障壁率から変えないことを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        model = deepcopy(self.model)
        values = {"1": deepcopy(self.rows[0]["features"]), "-1": deepcopy(self.rows[1]["features"])}
        high, _ = M.walk(model, values["1"])
        low, _ = M.walk(model, values["-1"])
        self.assertNotEqual(high, low)
        for leaf, score, mean in ((high, 0.8, -1000), (low, 0.4, 1000)):
            model["nodes"][leaf].update(score=score, unique_slots=60, days=6, sessions=10, regression_value=mean, recovery_positive=mean > 0)
        result = M.predict(model, values)
        self.assertEqual((result["side"], result["winner_side"]), (1, 1))
        model["nodes"][high]["unique_slots"] = 59
        rejected = M.predict(model, values)
        self.assertEqual((rejected["side"], rejected["winner_side"], rejected["scores"]), (0, 1, {"1": 0.8, "-1": 0.4}))
        model["nodes"][high].update(unique_slots=60, score=1 / 3)
        model["nodes"][low]["score"] = 0.1
        self.assertEqual(M.predict(model, values)["side"], 1)
        model["nodes"][high]["score"] = math.nextafter(1 / 3, 0)
        self.assertEqual(M.predict(model, values)["side"], 0)

    def test_鏡像と同点と未準備と旧予測完全一致(self) -> None:
        """同じ共通木の方向交換を照合し、旧54への純射影と全辞書を一致させる。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for i in range(0, len(self.rows), 2):
            values = {"1": self.rows[i]["features"], "-1": self.rows[i + 1]["features"]}
            actual = M.predict(self.model, values)
            expected = T54.M.predict({**self.model, "policy": "D0"}, values)
            reverse = M.predict(self.model, {"1": values["-1"], "-1": values["1"]})
            self.assertEqual(actual, expected)
            self.assertEqual((reverse["side"], reverse["winner_side"]), (-actual["side"], -actual["winner_side"]))
            self.assertEqual(reverse["scores"], {"1": actual["scores"]["-1"], "-1": actual["scores"]["1"]})
        values = self.rows[0]["features"]
        self.assertEqual(M.predict(self.model, {"1": values, "-1": values})["reason"], "同点WAIT")
        self.assertEqual(M.predict(self.model, {"1": [], "-1": []})["reason"], "特徴未準備WAIT")
        with self.assertRaises(ValueError):
            M.predict(self.model, {"1": [], "-1": values})

    def test_少数枝の支持と固定family(self) -> None:
        """非空1方向枝も回帰fitし、通常支持を満たさないため採用しない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][17] = 0
        rows[0]["features"][17] = 1
        model = M.fit(rows, self.meta, "G0", "人工少数", EVALUATION)
        partition = model["training"]["partition"]["Z1_a0"]
        node = model["nodes"][partition["root"]]
        self.assertTrue(partition["fit_performed"])
        self.assertEqual(node["direction_rows"], 1)
        self.assertTrue(node["method_support"])
        self.assertFalse(node["leaf_support"])
        self.assertEqual(node["families"], ["price", "trend"])

    def test_Decimal零近傍と相殺と重みの尺度(self) -> None:
        """浮動値の近似許容を回収正の旗へ流用せず、非重み合計を保持する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for values, sign in ((("1", "-1"), False), (("1", "-0.99999999999999999999999999999999999"), True), (("-1", "0.99999999999999999999999999999999999"), False)):
            rows = [{key: value for key in M.MONEY_FIELDS} for value in values]
            result = M.recovery_statistics(rows)
            self.assertIs(result["recovery_positive"], sign)
            with localcontext() as context:
                context.prec = 80
                total = sum(Decimal(v) for v in values)
            self.assertEqual(Decimal(result["recovery"]["pnl5"]["sum"]), total)
            self.assertEqual(result["recovery"]["pnl5"]["mean"], float(total / 2))
        tiny = deepcopy(self.rows)
        for row in tiny:
            row.update(pnl0="1e-35", pnl5="1e-35", pnl10="1e-35")
        model = M.fit(tiny, self.meta, "G0", "人工零近傍", EVALUATION)
        self.assertTrue(all(n["recovery_positive"] is True and n["recovery_mse_decimal"] == "0" for n in model["nodes"]))
        self.assertTrue(all(M.numeric_match(n["impurity"], 0.0, "mse", 1e-70) for n in model["nodes"]))
        self.assertEqual(Decimal(model["nodes"][0]["recovery"]["pnl5"]["sum"]), Decimal("8e-33"))

    def test_入力不変と政策metadataとJSON安全(self) -> None:
        """呼出し元や旧globalを変えず、G1別fitや列数違いを拒否する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows, meta = deepcopy(self.rows), deepcopy(self.meta)
        before, old_rules = deepcopy(rows), deepcopy(T54.M.RULES)
        M.prepare_rows(rows, EVALUATION)
        self.assertEqual(rows, before)
        self.assertEqual(meta, self.meta)
        self.assertEqual(T54.M.RULES, old_rules)
        json.dumps(self.model, ensure_ascii=False, allow_nan=False)
        for policy, values in (("G1", meta), ("G0", meta[:17])):
            with self.assertRaises(ValueError):
                M.fit(rows, values, policy, "人工不正", EVALUATION)


def run() -> dict:
    """このファイルの人工だけを実行し、実データ未使用の検査範囲を返す。

    引数: なし。
    返り値: dictは成功件数/出典。学習成果物・相場・本物教師は保存しない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArtificialTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun, "失敗数": len(result.failures), "エラー数": len(result.errors),
        "市場入力読取": False, "実モデル学習": False, "固定54人工factorySHA256": hashlib.sha256(OLD_TEST.read_bytes()).hexdigest(),
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["全件一致"] else 1)
