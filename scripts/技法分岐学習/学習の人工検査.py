"""実相場を読まず、共通木の学習・JSON予測・採否境界を人工で検査する。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest

import numpy as np
from sklearn.tree import DecisionTreeClassifier


SPEC = importlib.util.spec_from_file_location("技法分岐の人工用学習", Path(__file__).with_name("学習.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
JST = timezone(timedelta(hours=9))
EVALUATION = datetime(2026, 2, 1, tzinfo=JST).timestamp()


def metadata() -> list[dict]:
    """特徴担当と同じ列順・familyの人工metadataを作る。

    引数: なし。
    返り値: list[dict]は15特徴。実指標を計算しない。
    """
    methods = ["I08", "I07", "I07", "I09", "P03", "P06", "P05", "P01", "P01", "P01", "P02", "P02", "P01", "P01", "P01"]
    return [{"id": f"F{i + 1:02d}", "name": "人工特徴" + str(i + 1), "method": methods[i], "family": family, "scale": "m15" if i == 0 or i >= 12 else "m03"}
        for i, family in enumerate(M.EXPECTED_FAMILIES)]


def training_rows() -> list[dict]:
    """20人工場へ偏らない二特徴AND教師の方向ペアを配置する。

    引数: なし。
    返り値: list[dict]は400枠/800方向行。市場行は使用しない。
    """
    rows = []
    for i in range(400):
        session_index, pattern = i % 20, (i // 20) % 4
        day = datetime(2026, 1, 1, tzinfo=JST) + timedelta(days=session_index // 2)
        kind = "Day" if session_index % 2 == 0 else "Night"
        session = day.strftime("%Y-%m-%d") + "_" + kind
        scheduled = (day + timedelta(hours=10 if kind == "Day" else 18, minutes=15 * (i // 20))).timestamp()
        for side in (1, -1):
            values = [0.0] * 15
            values[0], values[1] = side * (1.0 if pattern & 1 else -1.0), side * (1.0 if pattern & 2 else -1.0)
            success = values[0] > 0 and values[1] > 0
            rows.append({"slot_id": "人工枠" + str(i), "session": session, "scheduled": scheduled, "time": scheduled,
                "line": i * 10 + 1, "side": side, "features": values, "outcome": "250" if success else "期限" if i % 3 == 0 else "125",
                "filled": True, "entry_time": scheduled + 1, "entry_line": i * 10 + 2, "end_time": scheduled + 61, "end_line": i * 10 + 3})
    return rows


def oracle(rows: list[dict], policy: str) -> DecisionTreeClassifier:
    """独立のscikit-learn呼出しへ人工入力をそのまま渡す。

    引数: rows(list[dict])は全件有効人工教師、policy(str)はQ0/Q1。
    返り値: DecisionTreeClassifierはJSONとの比較専用。
    """
    estimator = DecisionTreeClassifier(criterion="gini", splitter="best", max_depth=2 if policy == "Q0" else 4,
        min_samples_leaf=60, random_state=51, class_weight=None, ccp_alpha=0.0, max_features=None)
    estimator.fit(np.asarray([r["features"] for r in rows], dtype=np.float32),
        np.asarray([int(r["outcome"] == "250") for r in rows]), sample_weight=np.repeat(0.5, len(rows)))
    return estimator


def hand_model(features: tuple[int, int] = (0, 1), high: float = 0.8, low: float = 0.5) -> dict:
    """採否境界を独立に検査する、小さい手作りJSON木を用意する。

    引数: features(tuple[int,int])は二段分岐列、high/low(float)は比較score。
    返り値: dictは7node。fitや実相場から期待値を作らない。
    """
    meta, nodes = metadata(), []
    structure = {0: (features[0], 1, 4), 1: (features[1], 2, 3), 4: (features[1], 5, 6)}
    paths = {0: []}
    for node_id in (0, 1, 4):
        feature, left, right = structure[node_id]
        for child, branch, comparison in ((left, "left", "<="), (right, "right", ">")):
            paths[child] = paths[node_id] + [{"node": node_id, "feature": feature, "feature_id": meta[feature]["id"],
                "method": meta[feature]["method"], "family": meta[feature]["family"], "threshold": 0.0, "comparison": comparison, "branch": branch}]
    for i in range(7):
        feature, left, right = structure.get(i, (-2, -1, -1))
        nodes.append({"id": i, "feature": feature, "threshold": 0.0 if feature >= 0 else -2.0, "left": left, "right": right,
            "score": high if i == 6 else low, "unique_slots": 60, "days": 6, "sessions": 10, "path": paths[i]})
    return {"schema_version": 1, "policy": "Q0", "feature_meta": meta, "nodes": nodes}


def opposing_vectors(features: tuple[int, int] = (0, 1)) -> dict:
    """手作り木の左右両端へ到達する方向特徴を用意する。

    引数: features(tuple[int,int])は分岐特徴。
    返り値: dictは正側+1/負側−1の各15列。
    """
    positive, negative = [0.0] * 15, [0.0] * 15
    for index in features:
        positive[index], negative[index] = 1.0, -1.0
    return {"1": positive, "-1": negative}


class ArtificialTests(unittest.TestCase):
    """学習とJSON木の失敗しやすい境界を、相場なしで照合する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """固定した人工教師と二政策モデルを一度作る。

        引数: cls(type)は検査クラス。
        返り値: None。
        """
        cls.rows, cls.meta = training_rows(), metadata()
        cls.models = {p: M.fit(cls.rows, cls.meta, p, "人工_" + p, EVALUATION) for p in ("Q0", "Q1")}

    def test_jsonとsklearnの全予測(self) -> None:
        """全人工方向行の葉と成功率を完全一致で確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for policy, model in self.models.items():
            independent = oracle(self.rows, policy)
            values = np.asarray([r["features"] for r in self.rows], dtype=np.float32)
            leaves, probabilities = independent.apply(values), independent.predict_proba(values)[:, 1]
            restored = json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
            for i, row in enumerate(self.rows):
                leaf, _ = M.walk(restored, row["features"])
                self.assertEqual(leaf, int(leaves[i]))
                self.assertEqual(restored["nodes"][leaf]["score"], float(probabilities[i]))
            self.assertEqual(model["parameters"]["max_depth"], 2 if policy == "Q0" else 4)
            self.assertLessEqual(max(len(n["path"]) for n in model["nodes"]), model["parameters"]["max_depth"])

    def test_float32境界を先に変換(self) -> None:
        """生floatで右でもfloat32では等号左になる値を確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for model in self.models.values():
            root = model["nodes"][0]
            self.assertEqual(root["threshold"], 0.0)
            values = [1.0] * 15
            values[root["feature"]] = 1e-46
            leaf, path = M.walk(model, values)
            self.assertGreater(values[root["feature"]], root["threshold"])
            self.assertEqual(path[0]["branch"], "left")
            independent = oracle(self.rows, model["policy"])
            self.assertEqual(leaf, int(independent.apply([values])[0]))
            values[root["feature"]] = float(np.nextafter(np.float32(0), np.float32(1)))
            self.assertEqual(M.walk(model, values)[1][0]["branch"], "right")

    def test_pair除外と半分重み(self) -> None:
        """片側不足/未約定の相手を学習へ残さないことを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows)
        for number, side, outcome in ((1, 1, "不足"), (2, -1, "未約定")):
            extra = deepcopy(rows[:2])
            for row in extra:
                row["slot_id"] = "人工除外" + str(number)
                if row["side"] == side:
                    row["outcome"] = outcome
                    if outcome == "未約定":
                        row["filled"] = False
                        row.pop("entry_time")
                        row.pop("entry_line")
            rows.extend(extra)
        model = M.fit(rows, self.meta, "Q0", "人工除外", EVALUATION)
        self.assertEqual(model["training"]["excluded_pair_count"], 2)
        self.assertEqual(model["training"]["direction_rows"], 800)
        self.assertEqual(model["training"]["total_weight"], 400)
        self.assertEqual(model["nodes"][0]["weighted_rows"], 400)
        self.assertEqual(model["training"]["excluded_pairs"][1]["outcomes"]["-1"], "未約定")
        self.assertEqual(self.models["Q0"]["nodes"], model["nodes"])

    def test_片方向とペア時計不一致拒否(self) -> None:
        """両方向を別枠として加える事故を拒否する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for rows in (deepcopy(self.rows[:-1]), deepcopy(self.rows)):
            if len(rows) == len(self.rows):
                rows[1]["line"] += 1
            with self.assertRaises(ValueError):
                M.fit(rows, self.meta, "Q0", "不正ペア", EVALUATION)

    def test_未来教師と同秒を拒否(self) -> None:
        """評価開始と同秒・以後の教師終点を拒否する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for end in (EVALUATION, EVALUATION + 1):
            rows = deepcopy(self.rows)
            rows[0]["end_time"] = end
            with self.assertRaises(ValueError):
                M.fit(rows, self.meta, "Q0", "未来拒否", EVALUATION)

    def test_欠測と順番と重みを拒否(self) -> None:
        """特徴欠測/並替え/片側重み変更を拒否する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for value in (float("nan"), float("inf")):
            rows = deepcopy(self.rows)
            rows[0]["features"][0] = value
            with self.assertRaises(ValueError):
                M.fit(rows, self.meta, "Q0", "欠測拒否", EVALUATION)
        rows = deepcopy(self.rows)
        rows[0]["sample_weight"] = 1
        with self.assertRaises(ValueError):
            M.fit(rows, self.meta, "Q0", "重み拒否", EVALUATION)
        with self.assertRaises(ValueError):
            M.fit(self.rows, list(reversed(self.meta)), "Q0", "順番拒否", EVALUATION)

    def test_同点WAITと両score保持(self) -> None:
        """同点を買い/売り優先にせず、負け側も0へ変更しない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        result = M.predict(hand_model(high=0.5, low=0.5), opposing_vectors())
        self.assertEqual((result["side"], result["winner_side"], result["reason"]), (0, 0, "同点WAIT"))
        self.assertEqual(result["scores"], {"1": 0.5, "-1": 0.5})

    def test_score下限等号と直下(self) -> None:
        """三分の一等号を採用し、直下は最高側でもWAITにする。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        self.assertEqual(M.predict(hand_model(high=1 / 3, low=0.2), opposing_vectors())["side"], 1)
        result = M.predict(hand_model(high=math.nextafter(1 / 3, 0), low=0.2), opposing_vectors())
        self.assertEqual((result["side"], result["winner_side"]), (0, 1))

    def test_勝側支持不足は次点へ逃がさない(self) -> None:
        """最高側のunique枠/日/場の不足を個別にWAITへする。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for field, below in (("unique_slots", 59), ("days", 5), ("sessions", 9)):
            model = hand_model()
            model["nodes"][6][field] = below
            result = M.predict(model, opposing_vectors())
            self.assertEqual((result["side"], result["winner_side"]), (0, 1))
            self.assertEqual(result["scores"], {"1": 0.8, "-1": 0.5})
            self.assertTrue(all(result["eligibility"]["-1"][k] for k in ("score", "leaf_support", "method_support")))

    def test_family異種と必須系統(self) -> None:
        """同系統二分岐・価格と値幅だけを複数技法条件の達成にしない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for features, expected in (((0, 0), 0), ((4, 3), 0), ((0, 4), 1), ((1, 4), 1)):
            result = M.predict(hand_model(features), opposing_vectors(features))
            self.assertEqual(result["side"], expected)

    def test_売買方向の選択と未準備(self) -> None:
        """入力方向を交換すると売りが勝ち、両欠測はscore未定のWAITになる。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        vectors = opposing_vectors()
        result = M.predict(hand_model(), {"1": vectors["-1"], "-1": vectors["1"]})
        self.assertEqual(result["side"], -1)
        missing = M.predict(hand_model(), {"1": [], "-1": []})
        self.assertEqual(missing["scores"], {"1": None, "-1": None})
        self.assertEqual(missing["side"], 0)
        with self.assertRaises(ValueError):
            M.predict(hand_model(), {"1": [], "-1": vectors["-1"]})

    def test_単一classと根だけの木(self) -> None:
        """成功又は失敗しかない教師でもscoreを保ち、技法path不足を待機にする。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for outcome, expected in (("250", 1.0), ("期限", 0.0)):
            rows = deepcopy(self.rows)
            for row in rows:
                row["outcome"] = outcome
            model = M.fit(rows, self.meta, "Q0", "単一class", EVALUATION)
            self.assertEqual(len(model["nodes"]), 1)
            self.assertEqual(model["nodes"][0]["score"], expected)
            self.assertEqual(M.predict(model, opposing_vectors())["side"], 0)

    def test_使用教師とmetadataの指紋(self) -> None:
        """学習ID・期間・metadataをJSONで保全する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        model = self.models["Q0"]
        self.assertEqual(len(model["training"]["row_ids"]), 800)
        self.assertEqual(model["feature_meta"], self.meta)
        self.assertEqual(model["feature_meta_sha256"], M.fingerprint(self.meta))
        self.assertEqual(model["training"]["period_sha256"], M.fingerprint(model["training"]["period"]))
        self.assertLess(model["training"]["period"]["max_label_end_key"][0], EVALUATION)
        self.assertEqual(model["training"]["weight_per_direction"], 0.5)


def run() -> dict:
    """人工検査だけを実行し、日本語の小型要約を返す。

    引数: なし。
    返り値: dictは成功/失敗数。モデルや市場成果物を保存しない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ArtificialTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun, "失敗数": len(result.failures), "エラー数": len(result.errors),
        "市場入力読取": False, "実モデル学習": False, "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["全件一致"] else 1)
