"""新30列の射影・教師同一性・未来境界・売買鏡像を人工で検査する。"""

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import unittest

import numpy as np
from sklearn.tree import DecisionTreeRegressor


HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """市場へ触れない人工生成と対象コードを読む。

    引数: path(Path)はコード、name(str)は固有名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = load(HERE.parent / "回収目的分岐/学習の人工検査.py", "再試験の固定56人工")
M = load(HERE / "学習.py", "再試験学習の人工対象")
F = load(HERE / "特徴.py", "再試験の人工metadata")
EVALUATION = OLD.EVALUATION


def training_rows() -> list[dict]:
    """29番目の子特徴へ目的差を持つ人工教師を作る。

    引数: なし。
    返り値: list[dict]は旧800方向に追加12列を持つ人工。市場データではない。
    """
    rows = OLD.training_rows()
    for index, row in enumerate(rows):
        category = (index // 2) % 4
        row["features"] = [float(v) for v in row["features"]]
        row["features"][15] = 1.0
        row["features"] += [0., 0., 0., -1., 0., 0., 4., 1., 1., 0.2, 0., float(category)]
    return rows


class ArtificialTests(unittest.TestCase):
    """追加された列と既存基盤の接続を検査する。"""

    @classmethod
    def setUpClass(cls):
        """共通の人工木を一度作る。

        引数: cls(type)は検査クラス。
        返り値: None。本物fitをしない。
        """
        cls.rows = training_rows()
        cls.model = M.fit(cls.rows, F.FEATURES, "E0", "人工30列", EVALUATION)

    def test_子投影と全node所属(self):
        """局所列28が全体F30へ正しく戻ることを独立回帰器で確認する。

        引数: self(ArtificialTests)は検査器。
        返り値: None。
        """
        indexes = [*range(17), *range(18, 30)]
        self.assertEqual(self.model["structure"]["child_feature_indices"], indexes)
        self.assertEqual(self.model["structure"]["child_features"], 29)
        self.assertTrue(any(n["feature"] == 29 for n in self.model["nodes"]))
        self.assertTrue(all(n["feature"] != 17 for n in self.model["nodes"][3:]))
        for z in (0, 1):
            for a in (0, 1):
                rows = [r for r in self.rows if r["features"][17] == z and int(np.float32(r["features"][0]) > 0) == a]
                x = np.asarray([r["features"] for r in rows], dtype=np.float32)[:, indexes]
                target = np.asarray([float(r["pnl5"]) for r in rows])
                estimator = DecisionTreeRegressor(criterion="squared_error", splitter="best", max_depth=2,
                    min_samples_leaf=60, random_state=51, ccp_alpha=0.0, max_features=None)
                estimator.fit(x, target, sample_weight=np.repeat(.5, len(rows)))
                part = self.model["training"]["partition"][f"Z{z}_a{a}"]
                visits = estimator.decision_path(x)
                for local in range(estimator.tree_.node_count):
                    node = self.model["nodes"][part["root"] + local]
                    selected = [rows[i] for i in visits[:, local].nonzero()[0].tolist()]
                    ids = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
                    self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
                    self.assertEqual(node["regression_value"], float(estimator.tree_.value[local, 0, 0]))
                    self.assertEqual(node["impurity"], float(estimator.tree_.impurity[local]))
                    if node["feature"] >= 0:
                        self.assertEqual(node["feature"], indexes[estimator.tree_.feature[local]])
                for row, leaf in zip(rows, estimator.apply(x)):
                    self.assertEqual(M.walk(self.model, row["features"])[0], part["root"] + int(leaf))

    def test_旧18教師指紋と追加特徴(self):
        """新特徴だけの変更で目的や旧射影を変えない。

        引数: self(ArtificialTests)は検査器。
        返り値: None。
        """
        _, original = M.prepare_rows(self.rows, EVALUATION)
        projected = [{**r, "features": r["features"][:18]} for r in self.rows]
        _, old = OLD.M.prepare_rows(projected, EVALUATION)
        self.assertEqual(original["base18_fingerprints"], {k: old[k] for k in original["base18_fingerprints"]})
        rows = deepcopy(self.rows)
        rows[0]["features"][29] = 9.
        _, changed = M.prepare_rows(rows, EVALUATION)
        self.assertEqual(original["base18_fingerprints"], changed["base18_fingerprints"])
        self.assertEqual(original["target_rows_sha256"], changed["target_rows_sha256"])
        self.assertNotEqual(original["used_rows_sha256"], changed["used_rows_sha256"])

    def test_未形成不成立と不正値(self):
        """既知未形成を欠測除外せず、未来や不正状態を拒否する。

        引数: self(ArtificialTests)は検査器。
        返り値: None。
        """
        for index, value in ((18, 4), (19, True), (21, -.1), (29, -1), (22, float("inf")), (17, .5)):
            row = deepcopy(self.rows[0]["features"])
            row[index] = value
            with self.assertRaises(ValueError):
                M.float32(row)
        rows = deepcopy(self.rows)
        rows[0].update(pnl5=None, recovery_end_time=EVALUATION)
        with self.assertRaises(ValueError):
            M.prepare_rows(rows, EVALUATION)
        rows[0]["recovery_end_time"] = self.rows[0]["recovery_end_time"]
        used, training = M.prepare_rows(rows, EVALUATION)
        self.assertEqual((len(used), training["recovery_excluded_pair_count"]), (798, 1))

    def test_売買鏡像と空枝(self):
        """同一木の方向入替と未知枝の待機を検査する。

        引数: self(ArtificialTests)は検査器。
        返り値: None。
        """
        for index in range(0, 40, 2):
            vectors = {"1": self.rows[index]["features"], "-1": self.rows[index + 1]["features"]}
            normal = M.predict(self.model, vectors)
            reverse = M.predict(self.model, {"1": vectors["-1"], "-1": vectors["1"]})
            self.assertEqual(reverse["side"], -normal["side"])
            self.assertEqual(reverse["scores"], {"1": normal["scores"]["-1"], "-1": normal["scores"]["1"]})
        rows = deepcopy(self.rows)
        for row in rows:
            row["features"][17] = 0
        model = M.fit(rows, F.FEATURES, "E0", "人工空枝", EVALUATION)
        vector = deepcopy(rows[0]["features"])
        vector[17] = 1
        self.assertEqual(M.predict(model, {"1": vector, "-1": rows[1]["features"]})["reason"], "未学習枝WAIT")

    def test_回帰額で最高側を変更しない(self):
        """30列でも障壁最高側と支持条件を維持する。

        引数: self(ArtificialTests)は検査器。
        返り値: None。
        """
        model = deepcopy(self.model)
        vectors = {"1": self.rows[0]["features"], "-1": self.rows[1]["features"]}
        high, low = [M.walk(model, vectors[s])[0] for s in ("1", "-1")]
        self.assertNotEqual(high, low)
        for leaf, score, mean in ((high, .8, -1000), (low, .4, 1000)):
            model["nodes"][leaf].update(score=score, unique_slots=60, days=6, sessions=10, regression_value=mean)
        self.assertEqual(M.predict(model, vectors)["side"], 1)
        model["nodes"][high]["unique_slots"] = 59
        self.assertEqual(M.predict(model, vectors)["side"], 0)


def run() -> dict:
    """人工だけを実行する。

    引数: なし。
    返り値: dictは成否と件数。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArtificialTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun,
        "詳細": "" if result.wasSuccessful() else capture.getvalue(), "市場入力読取": False, "実モデル学習": False}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["全件一致"] else 1)
