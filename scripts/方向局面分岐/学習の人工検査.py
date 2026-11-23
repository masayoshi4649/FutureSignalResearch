"""市場を読まず、固定二段と四群子木の合成・未知・数値境界を確認する。"""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest

import numpy as np
from sklearn.tree import DecisionTreeClassifier


HERE = Path(__file__).resolve().parent
OLD_TEST = HERE.parent / "局所帯分岐/学習の人工検査.py"
SPEC = importlib.util.spec_from_file_location("方向局面の固定53人工factory", OLD_TEST)
T53 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T53)
SPEC = importlib.util.spec_from_file_location("方向局面の新学習人工", HERE / "学習.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
EVALUATION = T53.EVALUATION


def oracle(rows: list[dict]) -> DecisionTreeClassifier:
    """四群の一つへ17列・深さ2の独立学習器を当てる。

    引数: rows(list[dict])は有効な群内方向行。
    返り値: DecisionTreeClassifierは比較専用。枝内pairは要求しない。
    """
    estimator = DecisionTreeClassifier(criterion="gini", splitter="best", max_depth=2,
        min_samples_leaf=60, random_state=51, class_weight=None, ccp_alpha=0.0, max_features=None)
    estimator.fit(np.asarray([r["features"][:17] for r in rows], dtype=np.float32),
        np.asarray([int(r["outcome"] == "250") for r in rows]), sample_weight=np.repeat(0.5, len(rows)))
    return estimator


class ArtificialTests(unittest.TestCase):
    """固定構造と再利用した採否規則を、小型の人工教師で照合する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """20人工場/400枠の18列で新候補を一度だけ作る。

        引数: cls(type)は検査クラス。
        返り値: None。本物教師や相場を読まない。
        """
        cls.rows, cls.meta = T53.training_rows(18), T53.metadata(18)
        cls.model = M.fit(cls.rows, cls.meta, "D0", "人工D0", EVALUATION)

    def test_四群独立子木と合成の全予測一致(self) -> None:
        """各群を別fitし、全体ID・葉率・全教師の走査を一致させる。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        offset = 3
        for z in (0, 1):
            for a in (0, 1):
                selected = [r for r in self.rows if r["features"][17] == z and int(np.float32(r["features"][0]) > 0) == a]
                independent = oracle(selected)
                values = np.asarray([r["features"][:17] for r in selected], dtype=np.float32)
                leaves, probabilities = independent.apply(values), independent.predict_proba(values)
                positive = np.flatnonzero(independent.classes_ == 1)
                p = self.model["training"]["partition"][f"Z{z}_a{a}"]
                self.assertEqual((p["root"], p["node_count"], p["direction_rows"], p["policy"]), (offset, independent.tree_.node_count, len(selected), "D0"))
                for i, row in enumerate(selected):
                    leaf, _ = M.walk(self.model, row["features"])
                    score = float(probabilities[i, positive[0]]) if len(positive) else 0.0
                    self.assertEqual((leaf, self.model["nodes"][leaf]["score"]), (offset + int(leaves[i]), score))
                offset += independent.tree_.node_count
        self.assertEqual(offset, len(self.model["nodes"]))

    def test_三固定nodeと全体深さと子17列(self) -> None:
        """根と両DI段が固定で、子にF18を戻さずF01は残すことを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        nodes = self.model["nodes"]
        self.assertEqual([(n["id"], n["feature"], n["threshold"]) for n in nodes[:3]], [(0, 17, 0.5), (1, 0, 0), (2, 0, 0)])
        self.assertEqual((nodes[0]["left"], nodes[0]["right"]), (1, 2))
        self.assertTrue(all(n["feature"] < 17 for n in nodes[3:]))
        self.assertEqual(self.model["subtree_parameters"]["max_depth"], 2)
        self.assertLessEqual(max(len(n["path"]) for n in nodes), 4)
        self.assertEqual(self.model["structure"]["child_features"], 17)
        self.assertFalse(self.model["structure"]["fixed_gini_optimized"])
        self.assertTrue(all(n["method_support"] for n in nodes if n["left"] == n["right"] == -1))
        for p in self.model["training"]["partition"].values():
            self.assertEqual(p["fit_parameters"]["max_features"], None)
            self.assertEqual(p["fit_parameters"]["max_depth"], 2)

    def test_全nodeの所属と支持とgini(self) -> None:
        """固定nodeを含めて全使用行からID指紋・重み・支持を再計数する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for node in self.model["nodes"]:
            selected = []
            for row in self.rows:
                leaf, path = M.walk(self.model, row["features"])
                if node["id"] in [p["node"] for p in path] + [leaf]:
                    selected.append(row)
            score = sum(r["outcome"] == "250" for r in selected) / len(selected)
            ids = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
            self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
            self.assertEqual((node["direction_rows"], node["total_weight"], node["score"], node["impurity"]), (len(selected), len(selected) / 2, score, 2 * score * (1 - score)))
            self.assertEqual(node["unique_slots"], len({(r["session"], r["slot_id"]) for r in selected}))

    def test_F01強さを子でも追加分割できる(self) -> None:
        """同じ正符号の中にある教師差をF01の強さだけへ置き、子が使えることを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            first, second = row["features"][:2]
            row["features"][0] = 1.0 if first > 0 and second > 0 else 2.0 if first > 0 else -1.0
            row["features"][1] = 0.0
        model = M.fit(rows, self.meta, "D0", "人工DI強さ", EVALUATION)
        self.assertTrue(any(n["feature"] == 0 for n in model["nodes"][3:]))
        self.assertTrue(any(n["feature"] == 0 and n["threshold"] > 0 for n in model["nodes"][3:]))

    def test_pair先除外と旧53教師指紋(self) -> None:
        """全pair除外が53と同じで、群内片側を不当に落とさないことを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        old_used, old_training = T53.M.prepare_rows(self.rows, EVALUATION, 18)
        used, training = M.prepare_rows(self.rows, EVALUATION)
        self.assertEqual((used, training), (old_used, old_training))
        rows = deepcopy(self.rows)
        rows[0].update(outcome="未約定", filled=False)
        rows[0].pop("entry_time")
        rows[0].pop("entry_line")
        model = M.fit(rows, self.meta, "D0", "人工pair除外", EVALUATION)
        self.assertEqual((model["training"]["used_pairs"], model["training"]["excluded_pair_count"], model["training"]["direction_rows"]), (399, 1, 798))
        self.assertEqual(sum(p["direction_rows"] for p in model["training"]["partition"].values()), 798)
        self.assertEqual({r["side"] for r in used if r["features"][17] == 0}, {-1})

    def test_空ZでもDI固定nodeと二未知leafを保持(self) -> None:
        """Z全体が空でも固定内部nodeを省かず、未知を0へ補完しない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][17] = 0
        model = M.fit(rows, self.meta, "D0", "人工空Z", EVALUATION)
        internal = model["nodes"][2]
        self.assertEqual((internal["feature"], internal["data_absent"], internal["score"], internal["impurity"]), (0, True, None, None))
        for branch in ("left", "right"):
            leaf = model["nodes"][internal[branch]]
            self.assertEqual((leaf["left"], leaf["right"], leaf["data_absent"], leaf["score"]), (-1, -1, True, None))
        for key in ("Z1_a0", "Z1_a1"):
            self.assertFalse(model["training"]["partition"][key]["fit_performed"])
        chosen = next(r["features"] for r in rows if r["outcome"] == "250")
        values = {"1": deepcopy(chosen), "-1": deepcopy(chosen)}
        values["-1"][17] = 1
        result = M.predict(model, values)
        self.assertEqual((result["side"], result["winner_side"], result["reason"]), (0, 0, "未学習枝WAIT"))
        self.assertIsNone(result["scores"]["-1"])
        self.assertIsNotNone(result["scores"]["1"])

    def test_DI区分もfloat32で同値左を使用(self) -> None:
        """極小正のDIがfloat32で0になる場合、fit所属とwalkがともに左へ入る。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][0] = row["side"] * 1e-46
        model = M.fit(rows, self.meta, "D0", "人工DI丸め", EVALUATION)
        self.assertEqual(model["training"]["partition"]["Z0_a1"]["direction_rows"], 0)
        self.assertEqual(model["training"]["partition"]["Z1_a1"]["direction_rows"], 0)
        values = deepcopy(rows[0]["features"])
        for raw, branch in ((1e-46, "left"), (-1e-46, "left"), (0.0, "left"), (float(np.nextafter(np.float32(0), np.float32(1))), "right")):
            values[0] = raw
            self.assertEqual(M.walk(model, values)[1][1]["branch"], branch)

    def test_方向交換と同点と最高側gate(self) -> None:
        """同じ共通木で売買を交換し、固定familyを数えても通常の支持を維持する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        adopted = 0
        for i in range(0, len(self.rows), 2):
            values = {"1": self.rows[i]["features"], "-1": self.rows[i + 1]["features"]}
            normal = M.predict(self.model, values)
            reverse = M.predict(self.model, {"1": values["-1"], "-1": values["1"]})
            self.assertEqual((reverse["side"], reverse["winner_side"]), (-normal["side"], -normal["winner_side"]))
            self.assertEqual(reverse["scores"], {"1": normal["scores"]["-1"], "-1": normal["scores"]["1"]})
            adopted += int(normal["side"] != 0)
        self.assertGreater(adopted, 0)
        row = next(r for r in self.rows if r["outcome"] == "250")
        other = next(r for r in self.rows if r["outcome"] == "125")
        values = {"1": row["features"], "-1": other["features"]}
        leaf, _ = M.walk(self.model, values["1"])
        altered = deepcopy(self.model)
        altered["nodes"][leaf]["unique_slots"] = 59
        result = M.predict(altered, values)
        self.assertEqual((result["side"], result["winner_side"]), (0, 1))
        self.assertEqual(result["scores"], {"1": 1.0, "-1": 0.0})
        self.assertEqual(M.predict(self.model, {"1": values["1"], "-1": values["1"]})["reason"], "同点WAIT")

    def test_少数非空群は通常支持で除外(self) -> None:
        """固定段で方向行1件となる枝もfitし、支持不足で採用しない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][17] = 0
        selected = next(r for r in rows if r["outcome"] == "250")
        selected["features"][17] = 1
        model = M.fit(rows, self.meta, "D0", "人工少数群", EVALUATION)
        p = model["training"]["partition"]["Z1_a1"]
        node = model["nodes"][p["root"]]
        self.assertTrue(p["fit_performed"])
        self.assertEqual((node["direction_rows"], node["data_absent"], node["score"], node["method_support"], node["leaf_support"]), (1, False, 1, True, False))

    def test_未知特徴とZ定義域と未来を拒否(self) -> None:
        """両空WAIT・片空拒否・厳密Zと評価同秒拒否を保持する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        self.assertEqual(M.predict(self.model, {"1": [], "-1": []})["reason"], "特徴未準備WAIT")
        with self.assertRaises(ValueError):
            M.predict(self.model, {"1": [], "-1": self.rows[0]["features"]})
        for z in (0.5, math.nextafter(0.5, 0), True, -1, 2):
            values = deepcopy(self.rows[0]["features"])
            values[17] = z
            with self.assertRaises(ValueError):
                M.walk(self.model, values)
        rows = deepcopy(self.rows)
        rows[0].update(end_time=EVALUATION, outcome="未約定", filled=False)
        with self.assertRaises(ValueError):
            M.fit(rows, self.meta, "D0", "人工未来", EVALUATION)
        with self.assertRaises(ValueError):
            M.fit(self.rows[:-1], self.meta, "D0", "人工片側", EVALUATION)
        with self.assertRaises(ValueError):
            M.feature_metadata(self.meta[:17], "D0")


def run() -> dict:
    """新規人工だけを実行し、旧factoryと新コードの範囲を返す。

    引数: なし。
    返り値: dictは成功件数と出典。市場・本物教師・モデル保存は無し。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArtificialTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun, "失敗数": len(result.failures), "エラー数": len(result.errors),
        "市場入力読取": False, "実モデル学習": False, "固定53人工factorySHA256": hashlib.sha256(OLD_TEST.read_bytes()).hexdigest(),
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["全件一致"] else 1)
