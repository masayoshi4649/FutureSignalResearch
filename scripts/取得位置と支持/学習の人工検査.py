"""架空の同条件教師だけで60/61学習・鏡像・支持剪定・選択接続を検査する。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
import io
import json
from pathlib import Path
import unittest

import numpy as np
from sklearn.tree import DecisionTreeRegressor


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(path: Path, name: str):
    """人工材料と純関数だけを固有名で読む。

    引数: path(Path)はコード、name(str)は固有module名。
    返り値: ModuleTypeは読込結果。本物モデル・教師・市場を開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load(HERE / "学習.py", "取得71人工の対象")
OLD = load(HERE.parent / "条件入口の教師/学習の人工検査.py", "取得71の固定69人工材料")
P70 = load(HERE.parent / "支持を保つ技法群/剪定の人工検査.py", "取得71の固定70人工材料")
CAL = load(HERE.parent / "条件入口の教師/検証.py", "取得71人工の固定69校正")
SELECTOR = load(HERE.parent / "適格方向の選択/選択.py", "取得71人工の固定66選択")
METADATA = deepcopy(OLD.METADATA)
META61 = [*deepcopy(METADATA), deepcopy(M.POSITION_META)]
EVALUATION = OLD.EVALUATION
SOURCE_SHA = "a" * 64


def training_rows(extended: bool = False) -> list[dict]:
    """gだけが四群内で回収を分ける、同じ800方向の架空教師を作る。

    引数: extended(bool)は61列を要求する指定。
    返り値: list[dict]は同じ条件教師。実入力・実モデルの成績を使わない。
    """
    rows = OLD.training_rows()
    for index, row in enumerate(rows):
        pair, side = index // 2, row["side"]
        valid = pair % 2
        row["session"] = f"2026-01-{1 + (pair // 4) % 10:02d}_" + ("Day" if (pair // 40) % 2 else "Night")
        g_buy = 3.0 if (pair // 2) % 2 else -1.0
        g = g_buy if side == 1 else 2.0 - g_buy
        row["features"] = P70.vector(side, valid)
        if extended:
            row["features"].append(g)
        value = 500 if g > 0 else -500
        row.update(outcome="250" if value > 0 else "125", filled=True,
            pnl0=str(value + 100), pnl5=str(value), pnl10=str(value - 100))
    return rows


def independent_walk(model: dict, values: list) -> tuple:
    """対象walkを使わずnumpy float32と保存左右だけで所属を求める。

    引数: model(dict)は人工木、values(list)は同60又は61特徴。
    返り値: tuple[int,list[int]]は到達葉と訪問した全node。
    """
    x, index, visits = np.asarray(values, dtype=np.float32), 0, []
    while True:
        node = model["nodes"][index]
        visits.append(index)
        if node["left"] == -1:
            return index, visits
        index = node["left"] if x[node["feature"]] <= node["threshold"] else node["right"]


def projected_source(policy: str, case: str) -> dict:
    """固定70の架空木を新政策の列数へ写し、剪定算法比較に使う。

    引数: policy(str)はB0/G0、case(str)は固定70の人工ケース。
    返り値: dictは生木の人工辞書。実保存モデルを読まない。
    """
    model = P70.source_factory(case)
    model.update(policy=policy, model_id=policy + "_人工_学習")
    if policy == "G0":
        model["feature_meta"].append(deepcopy(M.POSITION_META))
    model["feature_meta_sha256"] = M.fingerprint(model["feature_meta"])
    model["structure"].update(feature_count=M.FEATURE_COUNTS[policy], child_features=M.FEATURE_COUNTS[policy] - 2,
        child_feature_indices=M.child_indices(policy))
    for group in model["training"]["partition"].values():
        group["policy"] = policy
    return model


# ----------------------------------------
class PositionTests(unittest.TestCase):
    """同集合の情報追加と、利益を見ない支持剪定の責任を確認する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """架空の同教師で60/61と旧69対照を一回ずつ学習する。

        引数: cls(type)は検査クラス。
        返り値: None。本物fit・市場・原板は使わない。
        """
        cls.rows60, cls.rows61 = training_rows(), training_rows(True)
        cls.old = M.LEGACY.fit(cls.rows60, METADATA, "C0", "C0_人工_学習", EVALUATION)
        cls.models = {"B0": M.fit(cls.rows60, METADATA, EVALUATION, "B0", "B0_人工_学習"),
            "G0": M.fit(cls.rows61, META61, EVALUATION, "G0", "G0_人工_学習")}

    def test_政策とmetadataは厳密(self) -> None:
        """B60/G61と同priceのF61だけを許し、列や技法名の変更を拒否する。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        self.assertEqual(M.feature_metadata(METADATA, "B0"), METADATA)
        self.assertEqual(M.feature_metadata(META61, "G0"), META61)
        self.assertEqual([len(M.child_indices(p)["D0"]) for p in M.POLICIES], [58, 59])
        self.assertEqual(M.RULES["共通固定段"]["子特徴数"], {"B0": 58, "G0": 59})
        for policy in M.POLICIES:
            self.assertEqual(M.RULES["共通固定段"]["子特徴列index"][policy], M.child_indices(policy))
        for meta, policy in ((META61, "B0"), (METADATA, "G0"), (META61, "G1")):
            with self.assertRaises(ValueError):
                M.feature_metadata(meta, policy)
        for key, value in (("id", "F62"), ("family", "volume"), ("method", "V01")):
            meta = deepcopy(META61); meta[-1][key] = value
            with self.assertRaises(ValueError):
                M.feature_metadata(meta, "G0")

    def test_float32と旧60maskを保つ(self) -> None:
        """g有限値・表示最大・零化を扱い、旧共同maskも緩めない。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        base = self.rows60[0]["features"]
        self.assertEqual(M.float32([*base, 0.0], 61)[:60], M.LEGACY.float32(base, 60))
        self.assertEqual(M.float32([*base, 1e-50], 61)[60], 0.0)
        maximum = float(np.finfo(np.float32).max)
        self.assertEqual(M.float32([*base, maximum], 61)[60], maximum)
        for value in (None, True, float("nan"), float("inf"), -float("inf"), 1e100):
            with self.assertRaises(ValueError):
                M.float32([*base, value], 61)
        for count in (59, 62, True):
            with self.assertRaises(ValueError):
                M.float32(base, count)
        broken = [*base, 0.0]; broken[58] = True
        with self.assertRaises(ValueError):
            M.float32(broken, 61)

    def test_canonicalと同六指紋(self) -> None:
        """情報追加だけでID・回収目標・可知集合を変えない。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        old_rows, old = M.LEGACY.prepare_rows(self.rows60, EVALUATION)
        a, ta = M.prepare_rows(self.rows60, EVALUATION)
        b, tb = M.prepare_rows(self.rows61, EVALUATION, 61)
        self.assertEqual(a, old_rows)
        self.assertEqual([{**r, "features": r["features"][:60]} for r in b], a)
        for key in M.FINGERPRINT_FIELDS:
            self.assertEqual(ta[key], old[key])
            self.assertEqual(ta["base60_fingerprints"][key], old[key])
            self.assertEqual(tb["base60_fingerprints"][key], old[key])
        for key in ("row_ids_sha256", "target_rows_sha256", "period_sha256"):
            self.assertEqual(tb[key], ta[key])
        self.assertNotEqual(tb["used_rows_sha256"], ta["used_rows_sha256"])
        self.assertEqual((tb["input_pairs"], tb["used_pairs"], tb["excluded_pair_count"]), (400, 400, 0))

    def test_pairと未来と未知を拒否(self) -> None:
        """片側不足・重複・不足結果・同秒未来・無取引不整合を追加補完しない。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        cases = [self.rows61[1:], self.rows61 + [self.rows61[0]]]
        for key, value in (("filled", 1), ("outcome", "不足"), ("pnl5", None), ("end_time", EVALUATION),
                ("recovery_end_time", EVALUATION), ("sample_weight", 1.0)):
            rows = deepcopy(self.rows61); rows[0][key] = value; cases.append(rows)
        rows = deepcopy(self.rows61); rows[0].update(filled=False, outcome="無取引"); cases.append(rows)
        rows = deepcopy(self.rows61); rows[0]["features"][60] = None; cases.append(rows)
        for rows in cases:
            with self.assertRaises((ValueError, TypeError)):
                M.prepare_rows(rows, EVALUATION, 61)

    def test_B0全演算は旧69同値(self) -> None:
        """政策識別を除き元の全親統計・分岐・閾値と生予測を保持する。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        model = self.models["B0"]
        self.assertEqual(model["nodes"], self.old["nodes"])
        for key in ("structure", "parameters", "subtree_parameters", "feature_meta", "versions"):
            self.assertEqual(model[key], self.old[key])
        for row in self.rows60[::41]:
            self.assertEqual(M.walk(model, row["features"]), M.LEGACY.walk(self.old, row["features"]))
        for group in model["training"]["partition"].values():
            self.assertEqual(group["policy"], "B0")

    def test_G0四子を別sklearnで比較(self) -> None:
        """gだけが変わる人工で59列子を独立学習し、全node所属と予測を確認する。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        model = self.models["G0"]
        used, _ = M.prepare_rows(self.rows61, EVALUATION, 61)
        x = np.asarray([r["features"] for r in used], dtype=np.float32)
        y = np.asarray([float(r["pnl5"]) for r in used], dtype=np.float64)
        self.assertEqual(model["structure"]["child_features"], 59)
        self.assertTrue(any(n["feature"] == 60 for n in model["nodes"]))
        for d in (0, 1):
            flag = 25 if d == 0 else 19
            projection = [i for i in range(61) if i not in (0, flag)]
            for valid in (0, 1):
                ids = [i for i in range(len(used)) if int(x[i, 0] > 0) == d and int(x[i, flag] > .5) == valid]
                group = model["training"]["partition"][f"D{d}_V{valid}"]
                estimator = DecisionTreeRegressor(**M.regressor_parameters(2)).fit(x[ids][:, projection], y[ids], sample_weight=np.full(len(ids), .5))
                self.assertEqual(group["node_count"], estimator.tree_.node_count)
                self.assertEqual(group["child_feature_indices"], projection)
                for local, i in enumerate(ids):
                    leaf, visits = independent_walk(model, used[i]["features"])
                    actual, path = M.walk(model, used[i]["features"])
                    self.assertEqual((actual, [p["node"] for p in path] + [actual]), (leaf, visits))
                    self.assertEqual(leaf, int(estimator.apply(x[i:i+1, projection])[0]) + group["root"])
                    self.assertEqual(model["nodes"][leaf]["regression_value"], float(estimator.predict(x[i:i+1, projection])[0]))

    def test_G0閾値はfloat32等号を左(self) -> None:
        """F61分岐の等号と次の表現値で左右を分け、doubleだけの微差は補わない。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        model = self.models["G0"]
        for n in model["nodes"]:
            if n["feature"] != 60:
                continue
            group = next(g for g in model["training"]["partition"].values() if g["root"] == n["id"])
            vector = P70.vector(1 if group["d"] else -1, group["v"])
            threshold = n["threshold"]
            left = [*vector, threshold]
            right = [*vector, float(np.nextafter(np.float32(threshold), np.float32(np.inf))) ]
            self.assertEqual(M.walk(model, left)[0], n["left"])
            self.assertEqual(M.walk(model, right)[0], n["right"])
            tiny = [*vector, threshold + 1e-12]
            self.assertEqual(M.walk(model, tiny)[0], n["left"])

    def test_売買鏡像と取得位置の意味(self) -> None:
        """価格反射でgは不変、方向vector交換で予測の側だけを交換する。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        high, low, bid, ask, distance, offset = map(Fraction, (110, 90, 99, 101, 5, 1000))
        buy, sell = (high-ask)/distance, (bid-low)/distance
        reflected_buy = ((offset-low)-(offset-bid))/distance
        reflected_sell = ((offset-ask)-(offset-high))/distance
        self.assertEqual((reflected_buy, reflected_sell), (sell, buy))
        self.assertEqual(buy+sell, (high-low-(ask-bid))/distance)
        for model in self.models.values():
            count = len(model["feature_meta"])
            plus = P70.vector(1, 0) + ([3.] if count == 61 else [])
            minus = P70.vector(-1, 0) + ([-1.] if count == 61 else [])
            a = M.predict(model, {"1": plus, "-1": minus})
            b = M.predict(model, {"1": minus, "-1": plus})
            self.assertEqual(a["scores"], {"1": b["scores"]["-1"], "-1": b["scores"]["1"]})
            self.assertEqual(a["side"], -b["side"])
            self.assertEqual(a["winner_side"], -b["winner_side"])

    def test_両政策剪定と元辞書不変(self) -> None:
        """60/61でも固定三node・祖先再統合・元親統計・旧新配置を同じ規約で保つ。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        for policy in M.POLICIES:
            for case in ("nested", "keep", "local_merge", "fixed_insufficient"):
                source = projected_source(policy, case)
                before = M.fingerprint(source)
                result = M.prune(source, policy+"_人工", SOURCE_SHA)
                expected = P70.P.prune(P70.source_factory(case), "P0_人工", SOURCE_SHA)
                self.assertEqual(result["policy"], policy)
                self.assertEqual(result["training"], source["training"])
                self.assertEqual(M.fingerprint(source), before)
                self.assertEqual(result["nodes"], expected["nodes"])
                for key in ("decisions", "source_to_new", "new_to_source", "partitions"):
                    self.assertEqual(result["pruning"][key], expected["pruning"][key])
                self.assertEqual(result["pruning"]["fit_count"], 0)

    def test_剪定は利益やscoreを使わない(self) -> None:
        """取得位置側も利益・score・MSEを変えて剪定集合が不変になる。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        source = projected_source("G0", "nested")
        changed = deepcopy(source)
        for n in changed["nodes"]:
            n.update(score=.99, regression_value=999999., impurity=999999., recovery_positive=True)
        a, b = M.prune(source, "G0_人工", SOURCE_SHA), M.prune(changed, "G0_人工", SOURCE_SHA)
        self.assertEqual(a["pruning"]["decisions"], b["pruning"]["decisions"])
        self.assertEqual(a["pruning"]["source_to_new"], b["pruning"]["source_to_new"])
        with self.assertRaises(ValueError):
            M.prune(a, "G0_二回", SOURCE_SHA)
        with self.assertRaises(ValueError):
            M.prune(source, "G0_人工", "不正")

    def test_無取引と空群は別(self) -> None:
        """無取引0を約定支持へ数えず、空群は固定三nodeとnullを残す。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        rows = deepcopy(self.rows61)
        for row in rows:
            row.update(filled=False, outcome="無取引", pnl0="0", pnl5="0", pnl10="0")
            row["features"][19] = row["features"][25] = 0
        raw = M.fit(rows, META61, EVALUATION, "G0", "G0_無取引_学習")
        model = M.prune(raw, "G0_無取引", SOURCE_SHA)
        self.assertEqual(len(model["nodes"]), 7)
        self.assertTrue(all(n["barrier_data_absent"] and n["score"] is None and not n["leaf_support"] for n in model["nodes"]))
        self.assertTrue(any(n["data_absent"] and n["recovery"]["pnl5"]["mean"] is None for n in model["nodes"]))
        self.assertTrue(any(not n["data_absent"] and n["recovery"]["pnl5"]["mean"] == 0 for n in model["nodes"]))
        self.assertEqual(M.predict(model, {"1": rows[0]["features"], "-1": rows[1]["features"]})["reason"], "未学習枝WAIT")

    def test_69calと66選択へ接続(self) -> None:
        """同政策の派生木を旧校正と適格内選択へ渡して全葉参照を確認する。

        引数: self(PositionTests)は検査先。
        返り値: None。新主・本物入力は呼ばない。
        """
        for policy, raw in self.models.items():
            model = M.prune(raw, policy+"_人工", SOURCE_SHA)
            cal = CAL.calibration_for(model)
            count = M.FEATURE_COUNTS[policy]
            vectors = {"1": P70.vector(1, 0) + ([3.] if count == 61 else []),
                "-1": P70.vector(-1, 0) + ([-1.] if count == 61 else [])}
            for variant in ("E0", "E1"):
                actual = SELECTOR.predict(model, cal, vectors, M, variant)
                self.assertEqual(actual["prior"], M.predict(model, vectors))
                if actual["side"]:
                    self.assertEqual(actual["recovery_leaf"], actual["prior"]["leafs"][str(actual["side"])])
            self.assertEqual(M.predict(model, {"1": [], "-1": []})["reason"], "特徴未準備WAIT")

    def test_入力と旧globalは変更しない(self) -> None:
        """学習・剪定・走査が旧規約と入力辞書を変更しないことを確認する。

        引数: self(PositionTests)は検査先。
        返り値: None。
        """
        self.assertEqual(self.rows60, training_rows())
        self.assertEqual(self.rows61, training_rows(True))
        self.assertEqual(M.LEGACY.POLICIES, {"I0": 4, "C0": 4})
        self.assertEqual(M.PRUNING.POLICIES, ("P0",))
        self.assertEqual(M.LEGACY.FEATURE_COUNTS, {"I0": 60, "C0": 60})
        self.assertEqual(M.feature_metadata(META61, "G0"), META61)

    def test_新主四政策slotsと旧70対照へ接続(self) -> None:
        """架空モデルで71主四政策を呼び、基礎側の予測は旧70とも一致させる。

        引数: self(PositionTests)は検査先。
        返り値: None。新主run・本物入力・保存モデルは呼ばない。
        """
        main = load(HERE / "検証.py", "取得71人工の新主純slots")
        old_main = load(HERE.parent / "支持を保つ技法群/検証.py", "取得71人工の固定70純slots")
        origin = {"session": "2026-01-01_Day", "slot_id": "人工取得定時", "scheduled": 100., "time": 101., "line": 1}
        block = {"slots": [origin]}
        for base_policy, raw in self.models.items():
            model = M.prune(raw, base_policy+"_人工", SOURCE_SHA)
            cal = main.calibration_for(model)
            count = M.FEATURE_COUNTS[base_policy]
            feature = {"ready": True, "reason": "人工", "background_direction": 1, "atr": 10., "D": 10,
                "vectors": {"1": P70.vector(1, 0) + ([3.] if count == 61 else []),
                    "-1": P70.vector(-1, 0) + ([-1.] if count == 61 else [])}}
            for variant in ("0", "1"):
                policy = base_policy[0] + variant
                actual = main.slots_for(block, {origin["slot_id"]: feature}, model, cal, M, SELECTOR, policy, "人工")[0]
                expected = SELECTOR.predict(model, cal, feature["vectors"], M, "E" + variant)
                self.assertEqual(actual["prediction"], expected)
                self.assertEqual((actual["policy"], actual["model_id"], actual["side"]), (policy, model["model_id"], expected["side"]))
                if base_policy == "B0":
                    previous = P70.P.prune(self.old, "P0_人工", SOURCE_SHA)
                    old_cal = old_main.PREVIOUS.calibration_for(previous)
                    old_slot = old_main.slots_for(block, {origin["slot_id"]: feature}, previous, old_cal, P70.P,
                        SELECTOR, "P"+variant, "人工")[0]
                    self.assertEqual(actual["prediction"], old_slot["prediction"])


# ----------------------------------------
def self_test() -> dict:
    """人工fitと支持剪定だけを公式集約へ返す。

    引数: なし。
    返り値: dictは成功・テスト件数・不一致と人工範囲。本物fit/剪定/市場は0。
    """
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PositionTests))
    return {"成功": result.wasSuccessful(), "テスト件数": result.testsRun,
        "不一致": [] if result.wasSuccessful() else stream.getvalue(), "実入力読取": False,
        "対象人工fitAPI": 3, "旧69対照fitAPI": 1, "独立子比較": 4, "本物fit": 0, "実モデル剪定": 0, "市場再生": False}


def run() -> dict:
    """人工の公開呼出しを統一する。

    引数: なし。
    返り値: dictはself_testの結果。
    """
    return self_test()


if __name__ == "__main__":
    proof = self_test()
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    raise SystemExit(0 if proof["成功"] else 1)
