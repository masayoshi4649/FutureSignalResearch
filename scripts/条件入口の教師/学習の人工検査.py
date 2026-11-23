"""共通pair・無取引0・約定先着分母・固定四群を架空教師だけで検査する。"""

from copy import deepcopy
from decimal import Decimal, localcontext
import importlib.util
import io
import json
from pathlib import Path
import unittest

import numpy as np
from sklearn.tree import DecisionTreeRegressor


HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工工場・純学習・純選択を固有名で読む。

    引数: path(Path)はPython、name(str)はmodule名。
    返り値: ModuleTypeは読込結果。保存モデル・教師・原板を開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = load(HERE.parent / "現在状態と量価格/学習の人工検査.py", "条件入口69の固定65人工材料")
M = load(HERE / "学習.py", "条件入口69の人工対象")
SELECTOR = load(HERE.parent / "適格方向の選択/選択.py", "条件入口69の固定66選択接続")
METADATA, EVALUATION = deepcopy(OLD.METADATA), OLD.EVALUATION


# ----------------------------------------
def training_rows(conditional: bool = False) -> list[dict]:
    """同じ800方向へ即時全約定又は条件片側無取引の人工教師を作る。

    引数: conditional(bool)は各pairの一側だけを確定約定にする指定。
    返り値: list[dict]は新canonical11項目。未来・モデル・実入力を参照しない。
    """
    result = []
    for index, original in enumerate(OLD.training_rows()):
        row = {key: deepcopy(original[key]) for key in M.CANONICAL_FIELDS}
        if conditional and row["side"] != (1 if index // 2 % 3 else -1):
            row.update(filled=False, outcome="無取引", pnl0="0", pnl5="0", pnl10="0")
        result.append(row)
    return result


def independent_walk(model: dict, vector: list) -> tuple:
    """numpy float32と子番号だけで期待所属を独立走査する。

    引数: model(dict)は人工木、vector(list)は人工60値。
    返り値: tuple[int,list[int]]は到達葉と全訪問node番号。対象walkは呼ばない。
    """
    values, index, visits = np.asarray(vector, dtype=np.float32), 0, []
    while True:
        node = model["nodes"][index]
        visits.append(index)
        if node["left"] == -1:
            return index, visits
        index = node["left"] if values[node["feature"]] <= node["threshold"] else node["right"]


class EntryTeacherTests(unittest.TestCase):
    """旧構造を保ちながら、教師契約と評価分母を変える責務を検査する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """二種類の人工教師だけで対象モデルを一度ずつ作る。

        引数: cls(type)は検査クラス。
        返り値: None。本物fit・市場・原板は使わない。
        """
        cls.immediate, cls.conditional = training_rows(), training_rows(True)
        cls.models = {"I0": M.fit(cls.immediate, METADATA, "I0", "人工69即時", EVALUATION),
            "C0": M.fit(cls.conditional, METADATA, "C0", "人工69条件", EVALUATION)}

    # ----------------------------------------
    def test_新canonicalと共通ID(self) -> None:
        """全pairを保持し、契約の異なる回収を同じidentityへ結ぶ。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        a, pa = M.prepare_rows(self.immediate, EVALUATION)
        b, pb = M.prepare_rows(self.conditional, EVALUATION)
        self.assertEqual(len(a), 800)
        self.assertEqual(pa["row_ids"], pb["row_ids"])
        self.assertEqual(pa["row_ids_sha256"], pb["row_ids_sha256"])
        self.assertEqual((pa["input_pairs"], pb["used_pairs"], pb["excluded_pair_count"]), (400, 400, 0))
        self.assertEqual((pb["filled_direction_rows"], pb["unfilled_direction_rows"]), (400, 400))
        self.assertNotEqual(pa["target_rows_sha256"], pb["target_rows_sha256"])
        self.assertEqual(set(a[0]), set(M.CANONICAL_FIELDS))
        self.assertEqual(pb["used_rows_sha256"], M.fingerprint(b))
        self.assertEqual(pb["total_weight"], 400)

    def test_未知と不正pairを拒否(self) -> None:
        """片側欠落・重複・未知・無取引費用・未来同秒を補完せず拒否する。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        cases = []
        cases.append(self.conditional[1:])
        cases.append(self.conditional + [self.conditional[0]])
        for key, value in (("filled", 1), ("outcome", "不足"), ("pnl5", None),
                ("end_time", EVALUATION), ("recovery_end_time", EVALUATION),
                ("end_time", float("nan")), ("side", True), ("pnl0", "NaN")):
            rows = deepcopy(self.conditional)
            rows[0][key] = value
            cases.append(rows)
        for index, rows in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises((ValueError, TypeError)):
                    M.prepare_rows(rows, EVALUATION)
        for key, value in (("pnl5", "1"), ("outcome", "250"), ("filled", True)):
            rows = deepcopy(self.conditional)
            target = next(row for row in rows if not row["filled"])
            target[key] = value
            with self.assertRaises(ValueError):
                M.prepare_rows(rows, EVALUATION)

    def test_60次元maskと正規化の拒否境界(self) -> None:
        """旧60次元の数値・jointmask契約を全教師に要求する。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        for mutation in ("次元", "非有限", "mask矛盾", "boolmask"):
            rows = deepcopy(self.conditional)
            if mutation == "次元":
                rows[0]["features"].pop()
            elif mutation == "非有限":
                rows[0]["features"][2] = float("inf")
            elif mutation == "mask矛盾":
                rows[0]["features"][58] = 0
                rows[0]["features"][54] = 1
            else:
                rows[0]["features"][58] = True
            with self.assertRaises(ValueError):
                M.prepare_rows(rows, EVALUATION)
        with self.assertRaises(ValueError):
            M.prepare_rows(self.conditional, EVALUATION, 54)

    # ----------------------------------------
    def test_全nodeの独立所属と二つの分母(self) -> None:
        """回帰は全方向・先着は約定だけとして、Decimalと独立所属で照合する。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        for policy, rows in (("I0", self.immediate), ("C0", self.conditional)):
            model = self.models[policy]
            for node in model["nodes"]:
                members = [row for row in rows if node["id"] in independent_walk(model, row["features"])[1]]
                filled = [row for row in members if row["filled"]]
                ids = [{key: row[key] for key in ("session", "slot_id", "side")} for row in members]
                self.assertEqual(node["training_ids_sha256"], M.fingerprint(ids))
                self.assertEqual((node["direction_rows"], node["total_weight"], node["weighted_rows"]),
                    (len(members), len(members) * .5, len(members) * .5))
                self.assertEqual(node["barrier_total_weight"], len(filled) * .5)
                self.assertEqual(node["score"], sum(r["outcome"] == "250" for r in filled) / len(filled) if filled else None)
                self.assertEqual(node["unique_slots"], len({(r["session"], r["slot_id"]) for r in filled}))
                self.assertEqual(node["all_unique_slots"], len({(r["session"], r["slot_id"]) for r in members}))
                self.assertEqual(node["fill_rate"], len(filled) / len(members) if members else None)
                for scope, key in ((members, "recovery"), (filled, "recovery_filled")):
                    for cost in (0, 5, 10):
                        values = [Decimal(row[f"pnl{cost}"]) for row in scope]
                        with localcontext() as context:
                            context.prec = 80
                            mean = sum(values) / len(values) if values else None
                        self.assertEqual(Decimal(node[key][f"pnl{cost}"]["sum"]), sum(values))
                        self.assertEqual(node[key][f"pnl{cost}"]["mean_decimal"], M.decimal_text(mean) if mean is not None else None)
                if members:
                    values = [Decimal(row["pnl5"]) for row in members]
                    with localcontext() as context:
                        context.prec = 80
                        mse = (len(values) * sum(v * v for v in values) - sum(values) ** 2) / len(values) ** 2
                    self.assertEqual(Decimal(node["recovery_mse_decimal"]), mse)
                self.assertEqual(node["recovery"]["pnl5"]["sum"], node["recovery_filled"]["pnl5"]["sum"])

    def test_固定四群と独立sklearn各子(self) -> None:
        """枝内pairを要求せず、58列深さ2の四回帰器へ別実装で照合する。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        model = self.models["C0"]
        self.assertEqual(model["structure"]["kind"], "fixed_direction_current_episode")
        self.assertEqual(model["structure"]["child_features"], 58)
        self.assertEqual([n["feature"] for n in model["nodes"][:3]], [0, 25, 19])
        for d in (0, 1):
            flag, projection = (25 if d == 0 else 19), [i for i in range(60) if i not in (0, 25 if d == 0 else 19)]
            for v in (0, 1):
                members = [row for row in self.conditional if int(np.float32(row["features"][0]) > 0) == d
                    and int(np.float32(row["features"][flag]) > .5) == v]
                part = model["training"]["partition"][f"D{d}_V{v}"]
                self.assertEqual(part["child_feature_indices"], projection)
                x = np.asarray([r["features"] for r in members], dtype=np.float32)[:, projection]
                y = np.asarray([float(r["pnl5"]) for r in members])
                estimator = DecisionTreeRegressor(**M.regressor_parameters(2)).fit(x, y, sample_weight=np.full(len(y), .5))
                visits = estimator.decision_path(x)
                for local in range(estimator.tree_.node_count):
                    node = model["nodes"][part["root"] + local]
                    self.assertEqual(node["direction_rows"], len(visits[:, local].nonzero()[0]))
                    self.assertEqual(node["regression_value"], float(estimator.tree_.value[local, 0, 0]))
                    self.assertEqual(node["impurity"], float(estimator.tree_.impurity[local]))
                    if node["feature"] >= 0:
                        self.assertEqual(node["feature"], projection[estimator.tree_.feature[local]])
                for row, leaf in zip(members, estimator.apply(x)):
                    actual, path = M.walk(model, row["features"])
                    self.assertEqual(actual, part["root"] + int(leaf))
                    self.assertLessEqual(len(path), 4)

    def test_同教師ならIとCの演算同値(self) -> None:
        """政策名で回帰や分母を変えず、教師だけが差になることを確認する。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        model = M.fit(self.immediate, METADATA, "C0", "人工69同教師", EVALUATION)
        self.assertEqual(model["nodes"], self.models["I0"]["nodes"])
        self.assertEqual(model["parameters"], self.models["I0"]["parameters"])
        for row in self.immediate[::40]:
            vectors = {"1": row["features"], "-1": self.immediate[self.immediate.index(row) + 1]["features"]}
            self.assertEqual(M.predict(model, vectors), M.predict(self.models["I0"], vectors))

    def test_全約定なら旧65の全nodeと予測同値(self) -> None:
        """時計列以外の教師が同じ全約定例では、旧65の木構造と採点を保つ。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        old = OLD.M.fit(OLD.training_rows(), METADATA, "U0", "人工旧65対照", EVALUATION)
        model = self.models["I0"]
        for a, b in zip(model["nodes"], old["nodes"]):
            for key in ("feature", "threshold", "left", "right", "direction_rows", "total_weight", "score",
                    "unique_slots", "days", "sessions", "recovery", "recovery_mse_decimal", "impurity", "regression_value"):
                self.assertEqual(a[key], b[key])
        for index in range(0, len(self.immediate), 40):
            vectors = {"1": self.immediate[index]["features"], "-1": self.immediate[index + 1]["features"]}
            self.assertEqual(M.predict(model, vectors), OLD.M.predict(old, vectors))

    # ----------------------------------------
    def test_無取引で先着支持を水増ししない(self) -> None:
        """全可知件数を増やしても、filled59と60の支持境界を保つ。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        rows = []
        for index in range(300):
            rows.append({"session": f"2026-01-{1 + index % 6:02d}" + ("Day" if index // 6 % 2 else "Night"),
                "slot_id": str(index), "filled": index < 60, "outcome": "250" if index < 20 else "125" if index < 60 else "無取引",
                "pnl0": "3" if index < 60 else "0", "pnl5": "2" if index < 60 else "0", "pnl10": "1" if index < 60 else "0"})
        path = [{"family": "trend"}, {"family": "price"}]
        node = M.node_statistics(rows, path)
        self.assertEqual((node["score"], node["fill_rate"], node["leaf_support"]), (1 / 3, .2, True))
        self.assertEqual(node["recovery"]["pnl5"]["mean"], .4)
        self.assertEqual(node["recovery_filled"]["pnl5"]["mean"], 2)
        rows[59].update(filled=False, outcome="無取引", pnl0="0", pnl5="0", pnl10="0")
        self.assertFalse(M.node_statistics(rows, path)["leaf_support"])
        self.assertFalse(M.leaf_eligibility({**node, "unique_slots": 59}, path)["leaf_support"])
        self.assertFalse(M.leaf_eligibility(node, [{"family": "price"}, {"family": "vol"}])["method_support"])

    def test_全無取引葉は回帰既知と先着未知(self) -> None:
        """無取引0の学習行を消さず、scoreNoneで両方向WAITする。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.conditional)
        for row in rows:
            row.update(filled=False, outcome="無取引", pnl0="0", pnl5="0", pnl10="0")
        model = M.fit(rows, METADATA, "C0", "人工全無取引", EVALUATION)
        node = model["nodes"][0]
        self.assertFalse(node["data_absent"])
        self.assertTrue(node["barrier_data_absent"])
        self.assertEqual((node["direction_rows"], node["filled_direction_rows"], node["score"]), (800, 0, None))
        self.assertEqual((node["recovery"]["pnl5"]["mean"], node["recovery_mse_decimal"]), (0, "0"))
        prediction = M.predict(model, {"1": rows[0]["features"], "-1": rows[1]["features"]})
        self.assertEqual((prediction["side"], prediction["winner_side"], prediction["reason"]), (0, 0, "未学習枝WAIT"))
        self.assertEqual(prediction["eligibility"], {"1": None, "-1": None})

    def test_空群も固定三nodeを保持(self) -> None:
        """全行が一群でも固定DI/episode nodeを残し、空葉率を未知にする。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.immediate)
        for row in rows:
            row["features"][0], row["features"][19] = 1.0, 0
        model = M.fit(rows, METADATA, "I0", "人工空四群", EVALUATION)
        self.assertEqual([node["feature"] for node in model["nodes"][:3]], [0, 25, 19])
        empty = [node for node in model["nodes"] if node["data_absent"]]
        self.assertTrue(empty)
        for node in empty:
            self.assertEqual((node["direction_rows"], node["score"], node["impurity"], node["regression_value"]), (0, None, None, None))

    def test_旧priorと66両側選択の接続(self) -> None:
        """先着最高側の支持拒否・他側救済・回収正での逆選択を独立期待へ照合する。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        model = deepcopy(self.models["I0"])
        vectors = {"1": self.immediate[0]["features"], "-1": self.immediate[1]["features"]}
        ids = {side: M.walk(model, vector)[0] for side, vector in vectors.items()}
        self.assertNotEqual(ids["1"], ids["-1"])
        for side in ("1", "-1"):
            model["nodes"][ids[side]].update(score=.5 if side == "1" else .4, unique_slots=60, days=6, sessions=10)
        cal = {"model_id": model["model_id"], "leaves": {str(node["id"]): {"leaf": node["id"], "support": True,
            "positive": node["id"] == ids["-1"], "mean_yen": {"5": 1 if node["id"] == ids["-1"] else -1}}
            for node in model["nodes"] if node["left"] == -1}}
        a = SELECTOR.predict(model, cal, vectors, M, "E0")
        b = SELECTOR.predict(model, cal, vectors, M, "E1")
        self.assertEqual((a["side"], b["side"], b["rescued"]), (1, -1, True))
        model["nodes"][ids["1"]]["unique_slots"] = 59
        self.assertEqual(M.predict(model, vectors)["side"], 0)
        self.assertEqual(SELECTOR.predict(model, cal, vectors, M, "E0")["side"], -1)
        model["nodes"][ids["-1"]]["score"] = .5
        self.assertEqual(SELECTOR.predict(model, cal, vectors, M, "E0")["ranking_block_reason"], "同点WAIT")

    def test_両空と片側未知の先行WAIT(self) -> None:
        """特徴未準備・score片側未知・raw同点を資格差で解消しない。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        model = deepcopy(self.models["I0"])
        self.assertEqual(M.predict(model, {"1": [], "-1": []})["reason"], "特徴未準備WAIT")
        with self.assertRaises(ValueError):
            M.predict(model, {"1": [], "-1": self.immediate[1]["features"]})
        vectors = {"1": self.immediate[0]["features"], "-1": self.immediate[1]["features"]}
        leaf = M.walk(model, vectors["-1"])[0]
        model["nodes"][leaf].update(score=None, filled_direction_rows=0, barrier_data_absent=True)
        self.assertEqual(M.predict(model, vectors)["reason"], "未学習枝WAIT")

    def test_float32境界と元入力不変(self) -> None:
        """最小正doubleの零化と正float32を区別し、元辞書・旧globalを変えない。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。
        """
        model = self.models["I0"]
        vector = deepcopy(self.immediate[0]["features"])
        vector[0] = 5e-324
        self.assertEqual(M.walk(model, vector)[1][0]["branch"], "left")
        vector[0] = float(np.nextafter(np.float32(0), np.float32(1)))
        self.assertEqual(M.walk(model, vector)[1][0]["branch"], "right")
        before = M.fingerprint([self.conditional, METADATA, OLD.M.RULES])
        M.prepare_rows(self.conditional, EVALUATION)
        M.predict(model, {"1": self.immediate[0]["features"], "-1": self.immediate[1]["features"]})
        self.assertEqual(before, M.fingerprint([self.conditional, METADATA, OLD.M.RULES]))

    def test_主calibrationと純slotの人工接続(self) -> None:
        """root主のcalibrationから固定66選択・純判断へ実データなしで接続する。

        引数: self(EntryTeacherTests)は検査先。
        返り値: None。主のrun/入力読取/市場は呼ばず、公開純関数だけを使う。
        """
        main = load(HERE / "検証.py", "条件入口69の人工接続用主純関数")
        for model_policy, model in self.models.items():
            cal = main.calibration_for(model)
            self.assertEqual(cal["evaluation_start"], EVALUATION)
            for node in model["nodes"]:
                if node["left"] != -1:
                    continue
                item = cal["leaves"][str(node["id"])]
                self.assertEqual(item["support"], node["leaf_support"])
                self.assertEqual(item["positive"], bool(node["recovery_positive"]))
                self.assertEqual(item["mean_yen"]["5"], node["recovery_filled"]["pnl5"]["mean"])
                self.assertEqual(item["mean_all_yen"]["5"], node["recovery"]["pnl5"]["mean"])
            vectors = {"1": self.immediate[0]["features"], "-1": self.immediate[1]["features"]}
            source = {"session": "2026-01-01Day", "slot_id": "人工主接続", "scheduled": 100.0, "time": 101.0, "line": 1}
            feature = {"ready": True, "reason": "人工", "vectors": vectors, "background_direction": 1, "atr": 10, "D": 10}
            before = M.fingerprint([model, cal, source, feature])
            for suffix in ("0", "1"):
                policy = model_policy[0] + suffix
                expected = SELECTOR.predict(model, cal, vectors, M, "E" + suffix)
                actual = main.slots_for({"slots": [source]}, {source["slot_id"]: feature}, model, cal, M, SELECTOR, policy, "人工")[0]
                self.assertEqual(actual["prediction"], expected)
                self.assertEqual(actual["side"], expected["side"])
                self.assertEqual(actual["role"], "順行" if expected["side"] == 1 else "反転" if expected["side"] else "待機")
            self.assertEqual(before, M.fingerprint([model, cal, source, feature]))
            unknown = {**feature, "ready": False, "reason": "人工未準備", "vectors": {"1": [], "-1": []}}
            actual = main.slots_for({"slots": [source]}, {source["slot_id"]: unknown}, model, cal, M, SELECTOR, model_policy, "人工")[0]
            self.assertEqual((actual["side"], actual["prediction"], actual["reason"]), (0, None, "人工未準備"))


# ----------------------------------------
def self_test() -> dict:
    """人工unittestを明示起動してrootの正式集約へ結果を返す。

    引数: なし。
    返り値: dictは成功・テスト件数・失敗・本物fit0。人工のsklearn fitだけを行う。
    """
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EntryTeacherTests))
    return {"成功": result.wasSuccessful(), "テスト件数": result.testsRun,
        "不一致": output.getvalue() if not result.wasSuccessful() else [],
        "本物入力読取": False, "本物fit": 0, "対象fitAPI": 5, "旧対照fitAPI": 1, "独立比較子": 4, "市場再生": False}


def run() -> dict:
    """人工結果を旧人工CLIと同じ入口で返す。

    引数: なし。
    返り値: dictはself_testの結果。実入力は読まない。
    """
    return self_test()


if __name__ == "__main__":
    proof = self_test()
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    raise SystemExit(0 if proof["成功"] else 1)
