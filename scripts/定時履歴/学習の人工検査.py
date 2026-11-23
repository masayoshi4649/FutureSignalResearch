"""相場を読まず、基礎15列の51同値と追加25列のJSON木境界を確認する。"""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest

import numpy as np


HERE = Path(__file__).resolve().parent
OLD_TEST = HERE.parent / "技法分岐学習/学習の人工検査.py"
SPEC = importlib.util.spec_from_file_location("履歴学習の固定51人工factory", OLD_TEST)
T51 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T51)
SPEC = importlib.util.spec_from_file_location("履歴学習の新人工対象", HERE / "学習.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
EVALUATION = T51.EVALUATION


def metadata(count: int) -> list[dict]:
    """51の基礎metadataを保持し、履歴10列だけを後ろへ加える。

    引数: count(int)は15又は25。
    返り値: list[dict]は人工metadata。固定51の辞書は変更しない。
    """
    values = T51.metadata()
    if count == 25:
        methods = ["P06", "P03", "P09", "P10", "P10"] * 2
        values += [{"id": f"F{i + 16:02d}", "name": "人工履歴" + str(i + 1), "method": method, "family": "price", "scale": "m03+m30"}
            for i, method in enumerate(methods)]
    return values


def history_rows(force_history: bool = False) -> list[dict]:
    """基礎と同じpair/教師へ、欠測と区別する有限の人工履歴を加える。

    引数: force_history(bool)は二つ目の説明情報を追加列だけへ移す検査か。
    返り値: list[dict]は800人工方向行。0とage−1も正当な有限値として含む。
    """
    rows = T51.training_rows()
    for row in rows:
        second = row["features"][1]
        row["features"] += [second, 0.0, 0.0, 0.0, -1.0, -second, 0.0, 0.0, 0.0, -1.0]
        if force_history:
            row["features"][1] = 0.0
    return rows


def hand_model(high: float = 0.8, low: float = 0.5, first: int = 0) -> dict:
    """追加列F16を分岐へ使う7nodeの人工JSONを用意する。

    引数: high/low(float)は葉率、first(int)は最初の分岐列。
    返り値: dictはH0のJSON。51のfactory返り値だけを新規に変更する。
    """
    model = T51.hand_model((first, 1), high, low)
    meta = metadata(25)
    model.update(policy="H0", feature_meta=meta)
    for node in model["nodes"]:
        if node["feature"] == 1:
            node["feature"] = 15
        for step in node["path"]:
            if step["feature"] == 1:
                step.update(feature=15, feature_id="F16", method=meta[15]["method"], family="price")
    return model


def vectors(first: int = 0) -> dict:
    """F16と最初の分岐を鏡像方向へ置いた人工特徴を作る。

    引数: first(int)は最初の分岐列。
    返り値: dictは25列×両方向。物理的価格からの鏡像抽出は履歴担当で別検査する。
    """
    result = {"1": [0.0] * 25, "-1": [0.0] * 25}
    for key, direction in (("1", 1.0), ("-1", -1.0)):
        result[key][first], result[key][15] = direction, direction
        result[key][19] = result[key][24] = -1.0
    return result


class ArtificialTests(unittest.TestCase):
    """旧木の同値性と、追加列の寸法・支持・時間境界を検査する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """同じ400枠/800方向行の人工二候補を作る。

        引数: cls(type)は検査クラス。
        返り値: None。実市場のfitはしない。
        """
        cls.base, cls.history = T51.training_rows(), history_rows()
        cls.models = {"C0": M.fit(cls.base, metadata(15), "C0", "人工C0", EVALUATION),
            "H0": M.fit(cls.history, metadata(25), "H0", "人工H0", EVALUATION)}

    def test_C0と固定51Q1の全node同値(self) -> None:
        """同一15列・同一教師なら固定51Q1と全木が一致することを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        old = T51.M.fit(self.base, metadata(15), "Q1", "人工旧Q1", EVALUATION)
        new = self.models["C0"]
        self.assertEqual(new["nodes"], old["nodes"])
        self.assertEqual(new["parameters"], old["parameters"])
        self.assertEqual(new["feature_meta"], old["feature_meta"])
        for row in self.base:
            old_leaf, old_path = T51.M.walk(old, row["features"])
            new_leaf, new_path = M.walk(new, row["features"])
            self.assertEqual((new_leaf, new_path), (old_leaf, old_path))
            self.assertEqual(new["nodes"][new_leaf]["score"], old["nodes"][old_leaf]["score"])

    def test_両政策とsklearn全行一致(self) -> None:
        """15/25それぞれの全人工方向行を独立sklearnと照合する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for policy, rows in (("C0", self.base), ("H0", self.history)):
            independent = T51.oracle(rows, "Q1")
            values = np.asarray([r["features"] for r in rows], dtype=np.float32)
            leaves, probabilities = independent.apply(values), independent.predict_proba(values)[:, 1]
            model = json.loads(json.dumps(self.models[policy], ensure_ascii=False, allow_nan=False))
            for i, row in enumerate(rows):
                leaf, _ = M.walk(model, row["features"])
                self.assertEqual((leaf, model["nodes"][leaf]["score"]), (int(leaves[i]), float(probabilities[i])))
            self.assertEqual(model["parameters"]["max_depth"], 4)

    def test_15prefixと同教師pairを保持(self) -> None:
        """追加列の有無で入力の基礎値・教師・枠を変えないことを確認する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for base, history in zip(self.base, self.history):
            self.assertEqual(base["features"], history["features"][:15])
            self.assertEqual({k: v for k, v in base.items() if k != "features"}, {k: v for k, v in history.items() if k != "features"})
        a, b = self.models["C0"]["training"], self.models["H0"]["training"]
        self.assertEqual(a["row_ids_sha256"], b["row_ids_sha256"])
        self.assertEqual(a["period_sha256"], b["period_sha256"])
        self.assertNotEqual(a["used_rows_sha256"], b["used_rows_sha256"])
        self.assertEqual((a["total_weight"], b["total_weight"]), (400, 400))

    def test_履歴列だけの情報も分岐できる(self) -> None:
        """追加列に移した情報をF16以降のJSON分岐で保持する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = history_rows(True)
        model = M.fit(rows, metadata(25), "H0", "人工履歴だけ", EVALUATION)
        self.assertTrue(any(node["feature"] >= 15 for node in model["nodes"]))
        independent = T51.oracle(rows, "Q1")
        values = [r["features"] for r in rows]
        expected = independent.predict_proba(values)[:, 1]
        for i, row in enumerate(rows):
            leaf, _ = M.walk(model, row["features"])
            self.assertEqual(model["nodes"][leaf]["score"], float(expected[i]))

    def test_政策とmetadataとvectors長の不一致を拒否(self) -> None:
        """15/25の取り違えや不定長への暗黙対応をしない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for policy, count in (("C0", 25), ("H0", 15)):
            with self.assertRaises(ValueError):
                M.feature_metadata(metadata(count), policy)
            wrong = {"1": [0.0] * count, "-1": [0.0] * count}
            with self.assertRaises(ValueError):
                M.predict(self.models[policy], wrong)
        bad = metadata(25)
        bad[-1]["id"] = "F24"
        with self.assertRaises(ValueError):
            M.feature_metadata(bad, "H0")

    def test_履歴を新familyにしてgateを緩めない(self) -> None:
        """履歴と価格の二手法だけを異種familyの達成にしない。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        result = M.predict(hand_model(first=4), vectors(first=4))
        self.assertEqual(result["side"], 0)
        self.assertEqual(result["eligibility"]["1"]["families"], ["price"])
        self.assertEqual(M.predict(hand_model(), vectors())["side"], 1)
        bad = metadata(25)
        bad[15]["family"] = "history"
        with self.assertRaises(ValueError):
            M.feature_metadata(bad, "H0")

    def test_float32追加列の等号境界(self) -> None:
        """25番目までの走査にもfloat32化を先に適用する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        model, values = hand_model(), vectors()["1"]
        values[15] = 1e-46
        leaf, path = M.walk(model, values)
        self.assertGreater(values[15], 0)
        self.assertEqual((leaf, path[-1]["feature"], path[-1]["branch"]), (5, 15, "left"))
        values[15] = float(np.nextafter(np.float32(0), np.float32(1)))
        self.assertEqual(M.walk(model, values)[0], 6)

    def test_未発生ゼロage負一と未知を区別(self) -> None:
        """有効な0/−1は通し、未知の両空や非有限値を別にする。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        valid = vectors()
        self.assertEqual(M.float32(valid["1"], 25)[19], -1)
        M.predict(hand_model(), valid)
        result = M.predict(hand_model(), {"1": [], "-1": []})
        self.assertEqual((result["side"], result["scores"]), (0, {"1": None, "-1": None}))
        invalid = deepcopy(valid)
        invalid["1"][24] = float("nan")
        with self.assertRaises(ValueError):
            M.predict(hand_model(), invalid)
        with self.assertRaises(ValueError):
            M.predict(hand_model(), {"1": [], "-1": valid["-1"]})

    def test_方向交換と同点WAIT(self) -> None:
        """同一木に入る方向特徴を交換すれば選択も反転し、同点は待機する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        x = vectors()
        self.assertEqual(M.predict(hand_model(), {"1": x["-1"], "-1": x["1"]})["side"], -1)
        result = M.predict(hand_model(0.5, 0.5), x)
        self.assertEqual((result["side"], result["winner_side"], result["scores"]), (0, 0, {"1": 0.5, "-1": 0.5}))

    def test_最高側gateと下限等号(self) -> None:
        """葉支持不足の最高側から次点へ救済せず、1/3等号は認める。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        for field, value in (("unique_slots", 59), ("days", 5), ("sessions", 9)):
            model = hand_model()
            model["nodes"][6][field] = value
            result = M.predict(model, vectors())
            self.assertEqual((result["side"], result["winner_side"], result["scores"]), (0, 1, {"1": 0.8, "-1": 0.5}))
        self.assertEqual(M.predict(hand_model(1 / 3, 0.2), vectors())["side"], 1)
        self.assertEqual(M.predict(hand_model(math.nextafter(1 / 3, 0), 0.2), vectors())["side"], 0)

    def test_pair除外と重みと未来(self) -> None:
        """履歴付きでも片側未約定をpair除外し、未来同秒を拒否する。

        引数: self(ArtificialTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.history)
        rows[0].update(outcome="未約定", filled=False)
        rows[0].pop("entry_time")
        rows[0].pop("entry_line")
        model = M.fit(rows, metadata(25), "H0", "人工除外", EVALUATION)
        self.assertEqual((model["training"]["excluded_pair_count"], model["training"]["direction_rows"], model["training"]["total_weight"]), (1, 798, 399))
        self.assertEqual(model["training"]["excluded_pairs"][0]["outcomes"]["1"], "未約定")
        rows[0]["end_time"] = EVALUATION
        with self.assertRaises(ValueError):
            M.fit(rows, metadata(25), "H0", "人工未来", EVALUATION)
        with self.assertRaises(ValueError):
            M.fit(self.history[:-1], metadata(25), "H0", "人工片側", EVALUATION)


def run() -> dict:
    """人工検査だけを実行し、小型の日本語結果を返す。

    引数: なし。
    返り値: dictは成功数と固定fixture出典。市場や本物モデルを保存しない。
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
