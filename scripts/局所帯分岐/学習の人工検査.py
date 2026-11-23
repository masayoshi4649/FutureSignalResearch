"""相場を読まず、Z固定root・17列子木・未知枝の採否境界を検査する。"""

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
OLD_TEST = HERE.parent / "技法分岐学習/学習の人工検査.py"
SPEC = importlib.util.spec_from_file_location("局所帯学習の固定51人工factory", OLD_TEST)
T51 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T51)
SPEC = importlib.util.spec_from_file_location("局所帯学習の新人工対象", HERE / "学習.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
EVALUATION = T51.EVALUATION


def metadata(count: int) -> list[dict]:
    """旧15特徴の順を保ち、局所帯幅・距離・Zの人工metadataを付ける。

    引数: count(int)は17又は18。
    返り値: list[dict]は人工の特徴定義。相場指標は計算しない。
    """
    values = T51.metadata()
    values += [{"id": "F16", "name": "人工局所幅", "method": "P03", "family": "price", "scale": "m03"},
        {"id": "F17", "name": "人工局所距離", "method": "P06", "family": "price", "scale": "m03"}]
    if count == 18:
        values.append({"id": "F18", "name": "人工Z", "method": "P10", "family": "price", "scale": "m03"})
    return values


def training_rows(count: int = 18) -> list[dict]:
    """同じ教師pairへ局所値を加え、Z枝を片方向ずつへ分ける。

    引数: count(int)は17又は18。
    返り値: list[dict]は400人工枠/800方向行。Z枝内のpair再要求を検出できる。
    """
    rows = T51.training_rows()
    for row in rows:
        row["features"] += [2.0, row["side"] * 0.25]
        if count == 18:
            row["features"].append(int(row["side"] == 1))
    return rows


def oracle(rows: list[dict], depth: int, count: int = 17) -> DecisionTreeClassifier:
    """独立のscikit-learnへ明示した列数だけを渡す。

    引数: rows(list[dict])は有効人工方向行、depth(int)は最大深さ、count(int)は入力列数。
    返り値: DecisionTreeClassifierは期待値専用。主学習のパラメータ関数を呼ばない。
    """
    estimator = DecisionTreeClassifier(criterion="gini", splitter="best", max_depth=depth,
        min_samples_leaf=60, random_state=51, class_weight=None, ccp_alpha=0.0, max_features=None)
    estimator.fit(np.asarray([r["features"][:count] for r in rows], dtype=np.float32),
        np.asarray([int(r["outcome"] == "250") for r in rows]), sample_weight=np.repeat(0.5, len(rows)))
    return estimator


def hand_model(high: float = 0.8, low: float = 0.5, first: int = 0) -> dict:
    """fitを使わない採否検査用の17列木を用意する。

    引数: high/low(float)は葉率、first(int)は一段目の分岐列。
    返り値: dictはB0形式の人工木。
    """
    model = T51.hand_model((first, 1), high, low)
    model.update(policy="B0", feature_meta=metadata(17))
    return model


def vectors(first: int = 0) -> dict:
    """手作り木の両端へ入る17列の方向特徴を作る。

    引数: first(int)は一段目の分岐列。
    返り値: dictは両方向。追加列を新familyにはしない。
    """
    values = T51.opposing_vectors((first, 1))
    return {s: v + [2.0, int(s) * 0.25] for s, v in values.items()}


class ArtificialTests(unittest.TestCase):
    """固定rootを含む木の変換と、教師・予測の失敗しやすい境界を確認する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """人工二候補と独立の自由木・Z別子木を一度作る。

        引数: cls(type)は検査クラス。
        返り値: None。実教師又は市場ファイルを読まない。
        """
        cls.base, cls.fixed = training_rows(17), training_rows(18)
        cls.models = {"B0": M.fit(cls.base, metadata(17), "B0", "人工B0", EVALUATION),
            "F0": M.fit(cls.fixed, metadata(18), "F0", "人工F0", EVALUATION)}

    def test_B0とsklearn全方向一致(self) -> None:
        """自由17列木の全葉ID・確率・構造を独立学習器と照合する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        independent, model = oracle(self.base, 4), self.models["B0"]
        x = np.asarray([r["features"] for r in self.base], dtype=np.float32)
        leaves, scores = independent.apply(x), independent.predict_proba(x)[:, 1]
        for i, row in enumerate(self.base):
            leaf, _ = M.walk(model, row["features"])
            self.assertEqual((leaf, model["nodes"][leaf]["score"]), (int(leaves[i]), float(scores[i])))
        self.assertEqual(model["structure"], {"kind": "free", "max_depth": 4, "features": 17})
        self.assertIsNone(model["training"]["partition"])
        self.assertEqual([n["feature"] for n in model["nodes"]], independent.tree_.feature.tolist())

    def test_F0とZ別17列子木の全方向一致(self) -> None:
        """Zの各枝を独立fitし、全体IDへ写した葉と確率が一致することを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        model, offset = self.models["F0"], 1
        for z in (0, 1):
            selected = [r for r in self.fixed if r["features"][17] == z]
            independent = oracle(selected, 3)
            x = np.asarray([r["features"][:17] for r in selected], dtype=np.float32)
            leaves, scores = independent.apply(x), independent.predict_proba(x)[:, 1]
            partition = model["training"]["partition"][str(z)]
            self.assertEqual((partition["root"], partition["node_count"], partition["direction_rows"]), (offset, independent.tree_.node_count, 400))
            self.assertTrue(partition["fit_performed"])
            for i, row in enumerate(selected):
                leaf, _ = M.walk(model, row["features"])
                self.assertEqual((leaf, model["nodes"][leaf]["score"]), (offset + int(leaves[i]), float(scores[i])))
            offset += independent.tree_.node_count
        self.assertEqual(offset, len(model["nodes"]))

    def test_強制rootと深さと子列投影(self) -> None:
        """Zに関係なくrootが存在し、子でF18を再選択しないことを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        model = self.models["F0"]
        self.assertEqual((model["nodes"][0]["feature"], model["nodes"][0]["threshold"]), (17, 0.5))
        self.assertTrue(all(n["feature"] < 17 for n in model["nodes"][1:]))
        self.assertLessEqual(max(len(n["path"]) for n in model["nodes"]), 4)
        self.assertEqual(model["subtree_parameters"]["max_depth"], 3)
        self.assertFalse(model["structure"]["root_gini_optimized"])
        self.assertEqual(model["nodes"][0]["families"], [])
        for node in model["nodes"][1:]:
            self.assertEqual(node["path"][0]["feature_id"], "F18")
            self.assertIn("price", node["families"])

    def test_全node支持をglobal使用行から照合(self) -> None:
        """全nodeの所属ID・0.5重み・unique支持を別走査で確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for policy, rows in (("B0", self.base), ("F0", self.fixed)):
            model = self.models[policy]
            for node in model["nodes"]:
                selected = []
                for row in rows:
                    leaf, path = M.walk(model, row["features"])
                    if node["id"] in [p["node"] for p in path] + [leaf]:
                        selected.append(row)
                ids = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
                score = sum(r["outcome"] == "250" for r in selected) / len(selected)
                self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
                self.assertEqual((node["direction_rows"], node["weighted_rows"], node["score"]), (len(selected), len(selected) / 2, score))
                self.assertEqual(node["unique_slots"], len({(r["session"], r["slot_id"]) for r in selected}))
                self.assertEqual(node["impurity"], 2 * score * (1 - score))

    def test_pair除外はZ分割前で枝片側も可(self) -> None:
        """片側未約定を相手も除外し、残った枝内でpairを再要求しない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.fixed)
        rows[0].update(outcome="未約定", filled=False)
        rows[0].pop("entry_time")
        rows[0].pop("entry_line")
        model = M.fit(rows, metadata(18), "F0", "人工pair先除外", EVALUATION)
        training = model["training"]
        self.assertEqual((training["used_pairs"], training["excluded_pair_count"], training["direction_rows"], training["total_weight"]), (399, 1, 798, 399))
        self.assertEqual([training["partition"][z]["direction_rows"] for z in ("0", "1")], [399, 399])
        self.assertTrue(all(r["side"] == (-1 if z == 0 else 1) for z in (0, 1) for r in self.fixed if r["features"][17] == z))
        self.assertEqual(self.models["B0"]["training"]["row_ids_sha256"], self.models["F0"]["training"]["row_ids_sha256"])

    def test_空枝は未知nullで両方向WAIT(self) -> None:
        """空枝を学習せず、既知側の得点を保持しても低い側へ救済しない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.fixed)
        for row in rows:
            row["features"][17] = 0
        model = M.fit(rows, metadata(18), "F0", "人工空枝", EVALUATION)
        empty = model["nodes"][model["nodes"][0]["right"]]
        self.assertEqual((empty["data_absent"], empty["score"], empty["impurity"], empty["direction_rows"]), (True, None, None, 0))
        self.assertFalse(model["training"]["partition"]["1"]["fit_performed"])
        values = {"1": deepcopy(rows[0]["features"]), "-1": deepcopy(rows[1]["features"])}
        values["-1"][17] = 1
        result = M.predict(model, values)
        self.assertEqual((result["side"], result["winner_side"], result["reason"]), (0, 0, "未学習枝WAIT"))
        self.assertIsNone(result["scores"]["-1"])
        self.assertIsNotNone(result["scores"]["1"])
        self.assertIsNone(result["eligibility"]["-1"])
        json.dumps(model, ensure_ascii=False, allow_nan=False)

    def test_非空少数枝もfitして通常支持で待つ(self) -> None:
        """方向行1件の枝を未知とせず、通常の葉支持・技法条件で退ける。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.fixed)
        for row in rows:
            row["features"][17] = 0
        selected = next(r for r in rows if r["outcome"] == "250")
        selected["features"][17] = 1
        model = M.fit(rows, metadata(18), "F0", "人工少数枝", EVALUATION)
        branch = model["training"]["partition"]["1"]
        leaf = model["nodes"][branch["root"]]
        self.assertTrue(branch["fit_performed"])
        self.assertEqual((leaf["data_absent"], leaf["direction_rows"], leaf["score"]), (False, 1, 1))
        other = next(r for r in rows if r["outcome"] == "125")
        values = {"1": deepcopy(selected["features"]), "-1": deepcopy(other["features"])}
        result = M.predict(model, values)
        self.assertEqual((result["side"], result["winner_side"]), (0, 1))
        self.assertFalse(result["eligibility"]["1"]["leaf_support"])
        self.assertEqual(result["eligibility"]["1"]["families"], ["price"])

    def test_Zは0or1だけで境界付近を補正しない(self) -> None:
        """0と1はrootの別枝へ入り、0.5や近傍値を二値化しない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        model, values = self.models["F0"], deepcopy(self.fixed[0]["features"])
        for z, expected in ((0, "left"), (1, "right")):
            values[17] = z
            self.assertEqual(M.walk(model, values)[1][0]["branch"], expected)
        for invalid in (0.5, math.nextafter(0.5, 0), math.nextafter(0.5, 1), -1, 2, True, None, float("nan")):
            values[17] = invalid
            with self.assertRaises(ValueError):
                M.walk(model, values)

    def test_政策とmetadata列数の誤りを拒否(self) -> None:
        """17/18列を暗黙変換せず、F18の技法やfamilyを保つ。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for policy, wrong in (("B0", 18), ("F0", 17)):
            with self.assertRaises(ValueError):
                M.fit(training_rows(wrong), metadata(wrong), policy, "人工誤列", EVALUATION)
        for key, value in (("family", "trend"), ("method", "P03"), ("id", "F17")):
            meta = metadata(18)
            meta[-1][key] = value
            with self.assertRaises(ValueError):
                M.feature_metadata(meta, "F0")

    def test_F0も両方向交換で同じ木を使う(self) -> None:
        """Zを含む方向ベクトルを交換し、scoresと選択が対称に変わることを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。実OHLCからのZ反射は特徴側人工の責任。
        """
        adopted = 0
        for index in range(0, len(self.fixed), 2):
            values = {"1": self.fixed[index]["features"], "-1": self.fixed[index + 1]["features"]}
            original = M.predict(self.models["F0"], values)
            reflected = M.predict(self.models["F0"], {"1": values["-1"], "-1": values["1"]})
            self.assertEqual(reflected["scores"], {"1": original["scores"]["-1"], "-1": original["scores"]["1"]})
            self.assertEqual((reflected["side"], reflected["winner_side"]), (-original["side"], -original["winner_side"]))
            adopted += int(original["side"] != 0)
        self.assertGreater(adopted, 0)

    def test_float32閾値前後と未知特徴(self) -> None:
        """学習列の極小正値もfloat32化し、両空と片空を区別する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        model, values = hand_model(), vectors()["1"]
        values[1] = 1e-46
        self.assertEqual(M.walk(model, values)[0], 5)
        values[1] = float(np.nextafter(np.float32(0), np.float32(1)))
        self.assertEqual(M.walk(model, values)[0], 6)
        self.assertEqual(M.predict(model, {"1": [], "-1": []})["reason"], "特徴未準備WAIT")
        with self.assertRaises(ValueError):
            M.predict(model, {"1": [], "-1": values})

    def test_方向交換と同点と最高側だけの採否(self) -> None:
        """同じ木で方向を交換し、同点WAIT・最高側不適格時の救済禁止を確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        values = vectors()
        self.assertEqual(M.predict(hand_model(), {"1": values["-1"], "-1": values["1"]})["side"], -1)
        self.assertEqual(M.predict(hand_model(0.5, 0.5), values)["reason"], "同点WAIT")
        for field, bad in (("unique_slots", 59), ("days", 5), ("sessions", 9)):
            model = hand_model()
            model["nodes"][6][field] = bad
            result = M.predict(model, values)
            self.assertEqual((result["side"], result["winner_side"], result["scores"]), (0, 1, {"1": 0.8, "-1": 0.5}))
        self.assertEqual(M.predict(hand_model(1 / 3, 0.2), values)["side"], 1)
        self.assertEqual(M.predict(hand_model(math.nextafter(1 / 3, 0), 0.2), values)["side"], 0)
        model, price_values = hand_model(first=4), vectors(first=4)
        for node in model["nodes"]:
            if node["feature"] == 1:
                node["feature"] = 15
            for step in node["path"]:
                if step["feature"] == 1:
                    step.update(feature=15, feature_id="F16", method="P03", family="price")
        for s in ("1", "-1"):
            price_values[s][15] = int(s)
        self.assertFalse(M.predict(model, price_values)["eligibility"]["1"]["method_support"])

    def test_未来教師とpair不一致と不正重みを拒否(self) -> None:
        """除外候補でも未来同秒を拒否し、片側追加や重み変更を認めない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for mutate in ("future", "unfilled_future", "clock", "weight"):
            rows = deepcopy(self.fixed)
            if mutate in ("future", "unfilled_future"):
                rows[0]["end_time"] = EVALUATION
                if mutate == "unfilled_future":
                    rows[0].update(outcome="未約定", filled=False)
            elif mutate == "clock":
                rows[0]["line"] += 1
            else:
                rows[0]["sample_weight"] = 1
            with self.assertRaises(ValueError):
                M.fit(rows, metadata(18), "F0", "人工不正", EVALUATION)
        with self.assertRaises(ValueError):
            M.fit(self.fixed[:-1], metadata(18), "F0", "人工片側", EVALUATION)


def run() -> dict:
    """人工検査を実行し、市場未使用と成功件数を返す。

    引数: なし。
    返り値: dictは人工結果と固定fixture出典。モデル成果物や本物教師を保存しない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArtificialTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun, "失敗数": len(result.failures), "エラー数": len(result.errors),
        "市場入力読取": False, "実モデル学習": False, "固定51人工factorySHA256": hashlib.sha256(OLD_TEST.read_bytes()).hexdigest(),
        "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["全件一致"] else 1)
