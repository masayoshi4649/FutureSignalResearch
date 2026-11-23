"""手作り54/60特徴だけで、DI一段根・共同mask・教師再用を検査する。"""

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
    """固定人工工場と新学習だけを固有名で読む。

    引数: path(Path)はコード、name(str)はmodule名。
    返り値: ModuleTypeは読込結果。数量loadや本物入力は呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = load(HERE.parent / "局面強弱の複合確認/学習の人工検査.py", "量価格64の固定63人工材料")
M = load(HERE / "学習.py", "量と価格進行64の人工学習")
META54, EVALUATION = deepcopy(OLD.METADATA), OLD.EVALUATION
ADDED = [("登録足TOD RVOL", "V01", "volume"), ("登録足実方向終値変化", "P05", "price"),
    ("再試験足TOD RVOL", "V01", "volume"), ("再試験足実方向終値変化", "P05", "price"),
    ("登録足量価格共同有効", "V01", "volume"), ("再試験足量価格共同有効", "V01", "volume")]
META60 = [*deepcopy(META54), *[{"id": f"F{55 + i:02d}", "name": name, "method": method,
    "family": family, "scale": "m03"} for i, (name, method, family) in enumerate(ADDED)]]


# ----------------------------------------
def training_rows() -> list[dict]:
    """54列を方向枝内定数とし、新6列が回収差を持つ800行を作る。

    引数: なし。
    返り値: list[dict]は人工60列教師。実市場・数量・教師を使わない。
    """
    rows = OLD.training_rows()
    for index, row in enumerate(rows):
        pair, side_index = index // 2, index % 2
        d, a, b = (pair % 2) ^ side_index, (pair // 2) % 2, (pair // 4) % 2
        mb, mr = (pair // 8) % 2, (pair // 16) % 2
        values = [0.0] * 54
        values[0], values[15] = 1.0 if d else -1.0, 1.0
        values[18:24], values[24:30] = [3, 0, 0, .2, 0, 0], [4, 0, 0, .2, 0, 0]
        values[50:54] = [1, 1, 1, 1]
        values += [.5 + a if mb else 0, 2 * a - 1 if mb else 0,
            .5 + b if mr else 0, 2 * b - 1 if mr else 0, mb, mr]
        target = (200 if a else -200) if d == 0 else (250 if b else -250)
        row.update(features=values, outcome="250" if target > 0 else "125",
            pnl0=str(target + 100), pnl5=str(target), pnl10=str(target - 100))
    return rows


class QuantityPriceTests(unittest.TestCase):
    """二政策の次元・同教師・分岐・資格の責任を分ける。"""

    @classmethod
    def setUpClass(cls) -> None:
        """54と60の人工モデルを一度ずつ作る。

        引数: cls(type)は検査クラス。
        返り値: None。本物fitはしない。
        """
        cls.rows60 = training_rows()
        cls.rows54 = [{**row, "features": row["features"][:54]} for row in cls.rows60]
        cls.models = {"B0": M.fit(cls.rows54, META54, "B0", "人工64基礎", EVALUATION),
            "Q0": M.fit(cls.rows60, META60, "Q0", "人工64量価格", EVALUATION)}

    # ----------------------------------------
    def test_固定DI一段と政策別全node予測(self) -> None:
        """独立sklearnの両子と全node/重み/global index/予測を照合する。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。
        """
        for policy, count, rows in (("B0", 54, self.rows54), ("Q0", 60, self.rows60)):
            model, projection = self.models[policy], list(range(1, count))
            self.assertEqual(model["structure"]["kind"], "fixed_direction_only")
            self.assertEqual((model["structure"]["child_features"], model["structure"]["child_depth"], model["structure"]["max_depth"]), (count - 1, 3, 4))
            self.assertEqual(model["structure"]["child_feature_indices"], projection)
            self.assertEqual(model["structure"]["fixed_nodes"], [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0}])
            self.assertEqual(set(model["training"]["partition"]), {"D0", "D1"})
            self.assertIn(20, projection)
            self.assertIn(26, projection)
            self.assertEqual(model["nodes"][0]["direction_rows"], len(rows))
            for d in (0, 1):
                selected = [row for row in rows if int(np.float32(row["features"][0]) > 0) == d]
                x = np.asarray([row["features"] for row in selected], dtype=np.float32)[:, projection]
                y = np.asarray([float(row["pnl5"]) for row in selected], dtype=np.float64)
                estimator = DecisionTreeRegressor(**M.regressor_parameters(3)).fit(x, y, sample_weight=np.full(len(y), .5))
                part = model["training"]["partition"][f"D{d}"]
                self.assertEqual((part["d"], part["route"], part["policy"]), (d, "R" if d == 0 else "T", policy))
                self.assertEqual(part["child_feature_indices"], projection)
                self.assertEqual(part["excluded_feature_indices"], [0])
                visits = estimator.decision_path(x)
                for local in range(estimator.tree_.node_count):
                    node = model["nodes"][part["root"] + local]
                    members = [selected[i] for i in visits[:, local].nonzero()[0].tolist()]
                    ids = [{"session": row["session"], "slot_id": row["slot_id"], "side": row["side"]} for row in members]
                    self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
                    self.assertEqual((node["direction_rows"], node["total_weight"]), (len(members), len(members) * .5))
                    self.assertEqual(node["regression_value"], float(estimator.tree_.value[local, 0, 0]))
                    self.assertEqual(node["impurity"], float(estimator.tree_.impurity[local]))
                    if node["feature"] >= 0:
                        self.assertEqual(node["feature"], projection[estimator.tree_.feature[local]])
                for row, leaf, value in zip(selected, estimator.apply(x), estimator.predict(x)):
                    actual, path = M.walk(model, row["features"])
                    self.assertEqual(actual, part["root"] + int(leaf))
                    self.assertEqual(model["nodes"][actual]["regression_value"], float(value))
                    self.assertLessEqual(len(path), 4)
        self.assertTrue(any(node["feature"] >= 54 for node in self.models["Q0"]["nodes"]))

    # ----------------------------------------
    def test_base54六指紋と下位指紋を両政策保持(self) -> None:
        """Bのcanonicalは旧63同値、Qの使用IDは同じだが60指紋は別とする。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。
        """
        old_used, old = M.LEGACY.prepare_rows(self.rows54, EVALUATION, 54)
        base_used, base = M.prepare_rows(self.rows54, EVALUATION, 54)
        extended_used, extended = M.prepare_rows(self.rows60, EVALUATION, 60)
        self.assertEqual(old_used, base_used)
        self.assertEqual([row["features"][:54] for row in extended_used], [row["features"] for row in old_used])
        for training in (base, extended):
            self.assertEqual(training["base54_fingerprints"], {key: old[key] for key in M.FINGERPRINT_FIELDS})
            for name in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints", "row_ids", "row_ids_sha256", "target_rows_sha256", "period_sha256"):
                self.assertEqual(training[name], old[name])
        self.assertEqual(base["used_rows_sha256"], old["used_rows_sha256"])
        self.assertNotEqual(extended["used_rows_sha256"], old["used_rows_sha256"])
        self.assertEqual(extended["used_rows_sha256"], M.fingerprint(extended_used))

    # ----------------------------------------
    def test_jointmaskと既知零と次元不正(self) -> None:
        """数量0/進行0の既知と未知を旗で区別し、共同mask矛盾を拒否する。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。
        """
        unknown = deepcopy(self.rows60[0]["features"])
        unknown[54:] = [0] * 6
        known = deepcopy(unknown)
        known[58:] = [1, 1]
        self.assertEqual(M.float32(unknown)[54:58], M.float32(known)[54:58])
        self.assertNotEqual(M.float32(unknown)[58:], M.float32(known)[58:])
        for index, value in ((54, -1), (56, -1), (55, float("inf")), (58, .5), (59, True)):
            invalid = deepcopy(known)
            invalid[index] = value
            with self.assertRaises(ValueError):
                M.float32(invalid)
        for mask, field in ((58, 54), (58, 55), (59, 56), (59, 57)):
            invalid = deepcopy(known)
            invalid[mask], invalid[field] = 0, .1
            with self.assertRaises(ValueError):
                M.float32(invalid)
        independent = deepcopy(known)
        independent[58] = 0
        self.assertEqual(M.float32(independent)[59], 1)
        with self.assertRaises(ValueError):
            M.float32(self.rows54[0]["features"])
        with self.assertRaises(ValueError):
            M.feature_metadata(META60, "B0")
        for policy in ("B1", "Q1"):
            with self.assertRaises(ValueError):
                M.feature_metadata(META60, policy)

    # ----------------------------------------
    def test_全追加未知でも旧教師を除外しない(self) -> None:
        """新6列全部0でも旧54教師の使用数・targetを維持する。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows60)
        for row in rows:
            row["features"][54:] = [0] * 6
        used, training = M.prepare_rows(rows, EVALUATION)
        self.assertEqual(len(used), 800)
        self.assertEqual(training["recovery_excluded_pair_count"], 0)
        self.assertEqual(training["base54_fingerprints"], self.models["B0"]["training"]["base54_fingerprints"])

    # ----------------------------------------
    def test_pair先行除外と未来拒否(self) -> None:
        """一方向の未知回収を枝へ救済せず、終了同秒も拒否する。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows60)
        rows[0]["pnl5"] = None
        used, training = M.prepare_rows(rows, EVALUATION)
        self.assertEqual((len(used), training["recovery_excluded_pair_count"]), (798, 1))
        self.assertFalse(any(row["slot_id"] == rows[0]["slot_id"] for row in used))
        rows[0]["pnl5"] = "0"
        rows[0]["recovery_end_time"] = EVALUATION
        with self.assertRaises(ValueError):
            M.prepare_rows(rows, EVALUATION)

    # ----------------------------------------
    def test_DI根だけでは技法資格を満たさない(self) -> None:
        """子が分岐しない基礎木のtrendだけの葉は従来gateで落ちる。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。
        """
        leaves = [node for node in self.models["B0"]["nodes"] if node["left"] == -1]
        self.assertEqual(len(leaves), 2)
        self.assertTrue(all(node["families"] == ["trend"] and not node["method_support"] for node in leaves))

    # ----------------------------------------
    def test_量maskだけの分岐を独立した実数確認と呼ばない(self) -> None:
        """新値が全0でもV01maskは分割でき、従来family条件上は通り得る。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。ここで追加のgateを導入しない。
        """
        rows = deepcopy(self.rows60)
        for index, row in enumerate(rows):
            mask = (index // 4) % 2
            row["features"][54:] = [0, 0, 0, 0, mask, 0]
            target = 100 if mask else -100
            row.update(outcome="250" if mask else "125", pnl0=str(target + 100), pnl5=str(target), pnl10=str(target - 100))
        model = M.fit(rows, META60, "Q0", "人工64maskだけ", EVALUATION)
        leaves = [node for node in model["nodes"] if node["left"] == -1]
        for leaf in leaves:
            self.assertEqual({part["feature"] for part in leaf["path"] if part["feature"] >= 54}, {58})
            self.assertTrue(leaf["method_support"])
            self.assertEqual(leaf["families"], ["trend", "volume"])

    # ----------------------------------------
    def test_最高側不適格の低側救済禁止と同点(self) -> None:
        """回帰平均が良い下位側へ変更せず、支持59と同点をWAITにする。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。
        """
        model = deepcopy(self.models["Q0"])
        high = self.rows60[0]["features"]
        hi = M.walk(model, high)[0]
        low = next(row["features"] for row in self.rows60 if M.walk(model, row["features"])[0] != hi)
        lo = M.walk(model, low)[0]
        for leaf, score, mean in ((hi, .9, -1000), (lo, .5, 1000)):
            model["nodes"][leaf].update(score=score, regression_value=mean, unique_slots=60, days=6, sessions=10)
        model["nodes"][hi]["unique_slots"] = 59
        value = M.predict(model, {"1": high, "-1": low})
        self.assertEqual((value["side"], value["winner_side"]), (0, 1))
        self.assertEqual(value["scores"], {"1": .9, "-1": .5})
        self.assertIn("最高側葉支持不足", value["reason"])
        model["nodes"][hi]["score"] = .5
        self.assertEqual(M.predict(model, {"1": high, "-1": low})["reason"], "同点WAIT")

    # ----------------------------------------
    def test_空方向枝とfloat32零境界(self) -> None:
        """空枝をscore0にせず、微小正DIの零化も同じJSON比較で扱う。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows60)
        for row in rows:
            row["features"][0] = -1
        model = M.fit(rows, META60, "Q0", "人工64空方向", EVALUATION)
        self.assertEqual(len(model["structure"]["fixed_nodes"]), 1)
        self.assertFalse(model["training"]["partition"]["D1"]["fit_performed"])
        known, unknown = rows[0]["features"], deepcopy(rows[0]["features"])
        unknown[0] = 1
        value = M.predict(model, {"1": unknown, "-1": known})
        self.assertEqual((value["side"], value["reason"]), (0, "未学習枝WAIT"))
        self.assertIsNone(value["scores"]["1"])
        zero, tiny, positive = deepcopy(known), deepcopy(known), deepcopy(known)
        zero[0], tiny[0], positive[0] = 0.0, math.nextafter(0, math.inf), float(np.nextafter(np.float32(0), np.float32(1)))
        self.assertEqual(M.walk(model, zero), M.walk(model, tiny))
        self.assertEqual(M.walk(model, zero)[1][0]["branch"], "left")
        self.assertEqual(M.walk(model, positive)[1][0]["branch"], "right")

    # ----------------------------------------
    def test_売買交換と入力旧global保全(self) -> None:
        """同じ共通木の方向交換でscore/葉を交換し、入力や固定moduleを変えない。

        引数: self(QuantityPriceTests)は検査先。
        返り値: None。
        """
        before = deepcopy((self.rows60, M.LEGACY.RULES, self.models))
        for policy, rows in (("B0", self.rows54), ("Q0", self.rows60)):
            for i in range(0, 40, 2):
                a = M.predict(self.models[policy], {"1": rows[i]["features"], "-1": rows[i + 1]["features"]})
                b = M.predict(self.models[policy], {"1": rows[i + 1]["features"], "-1": rows[i]["features"]})
                self.assertEqual(b["side"], -a["side"])
                self.assertEqual(b["scores"], {"1": a["scores"]["-1"], "-1": a["scores"]["1"]})
                self.assertEqual(b["leafs"], {"1": a["leafs"]["-1"], "-1": a["leafs"]["1"]})
        self.assertEqual((self.rows60, M.LEGACY.RULES, self.models), before)
        for model in self.models.values():
            self.assertEqual(list(model["shared_source_sha256"]), ["scripts/方向局面分岐/学習.py", "scripts/局所帯分岐/学習.py",
                "scripts/回収目的分岐/学習.py", "scripts/波の区間分離/学習.py", "scripts/現行経路の状態分岐/学習.py",
                "scripts/方向と再開確認/学習.py", "scripts/局面強弱の複合確認/学習.py"])
            json.dumps(model, ensure_ascii=False, allow_nan=False)


# ----------------------------------------
def run() -> dict:
    """人工fitと独立sklearn比較だけを実行して範囲を返す。

    引数: なし。
    返り値: dictは成功/人工件数。本物入力・教師・数量loadを呼ばない。
    """
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(QuantityPriceTests))
    return {"全件一致": result.wasSuccessful(), "人工件数": result.testsRun, "人工fit_API": 4,
        "人工回帰器fit_対象": 7, "独立比較回帰器fit": 4, "市場入力読取": False,
        "本物fit": False, "数量load": False, "詳細": "" if result.wasSuccessful() else capture.getvalue()}


if __name__ == "__main__":
    value = run()
    print(json.dumps(value, ensure_ascii=False))
    raise SystemExit(0 if value["全件一致"] else 1)
