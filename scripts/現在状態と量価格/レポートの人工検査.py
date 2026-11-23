"""65の表示を人工文脈だけで検査し、本物入力・モデルを開かない。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
R = None


def artificial_context(renderer) -> dict:
    """固定63の人工数値を同60列・対応episode有効四群へ写す。

    引数: renderer(ModuleType)は65表示器。
    返り値: dictは人工文脈。実際の教師・モデル・結果を読まない。
    """
    c = deepcopy(renderer.R63.artificial_context())
    result = c["result"]
    mapping = {"K0": "Q0", "K1": "Q1", "J0": "U0", "J1": "U1"}
    for field in ("候補", "役割別入口", "判断理由"):
        result[field] = {mapping[p]: v for p, v in result[field].items()}
    result.update(試行=65, 対照参照={"候補": ["Q0", "Q1"], "元試行": 64, "同じ評価46場": True, "市場再生": False})
    additions = [("対応b同時刻RVOL", "V01", "volume"), ("対応b同足進行対現在ATR", "P05", "price"),
        ("対応r同時刻RVOL", "V01", "volume"), ("対応r同足進行対現在ATR", "P05", "price"),
        ("対応b量価格ペア有効", "V01", "volume"), ("対応r量価格ペア有効", "V01", "volume")]
    c["metadata"] += [{"id": f"F{i + 55:02d}", "name": name, "method": method, "family": family, "scale": "m03"}
        for i, (name, method, family) in enumerate(additions)]
    keys = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")
    c["prior_models"] = {}
    result["状態分布"] = {}
    for phase, item in c["models"].items():
        model = item["base"]
        model.update(policy="U0", model_id="U0_" + phase, feature_meta=c["metadata"])
        model["structure"].update(kind="fixed_direction_current_episode", child_features=58, feature_count=60,
            child_feature_indices=renderer.CHILD_FEATURE_INDICES, excluded_feature_indices={"D0": [0, 25], "D1": [0, 19]})
        model["structure"]["fixed_nodes"] = [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0},
            {"id": 1, "feature": "F26", "index": 25, "threshold": .5}, {"id": 2, "feature": "F20", "index": 19, "threshold": .5}]
        model["nodes"][1]["feature"], model["nodes"][2]["feature"] = 25, 19
        for node in model["nodes"]:
            for step in node["path"]:
                split = model["nodes"][step["node"]]
                meta = c["metadata"][split["feature"]]
                step.update(feature=split["feature"], feature_id=meta["id"], method=meta["method"], family=meta["family"], threshold=split["threshold"])
            node["families"] = sorted({step["family"] for step in node["path"]})
            node["method_support"] = len(node["families"]) >= 2 and bool(set(node["families"]) & {"trend", "osc"})
        original = model["training"]["partition"]
        parts = {}
        result["状態分布"][phase] = {}
        for d in (0, 1):
            target = "R" if d == 0 else "T"
            for v in (0, 1):
                part = deepcopy(original[f"D{d}_K{v}"])
                part.pop("k")
                part.update(d=d, v=v, route=target, policy="U0", excluded_feature_indices=[0, 25] if d == 0 else [0, 19],
                    child_feature_indices=renderer.CHILD_FEATURE_INDICES[f"D{d}"])
                name = f"D{d}_V{v}"
                parts[name] = part
                n = part["direction_rows"]
                group = {"方向枝": "DI非正" if d == 0 else "DI正", "対象経路": target, "episode有効": v,
                    "方向行": n, "unique枠": part["pair_unique"], "日数": part["days"], "場数": part["sessions"],
                    "対象現在段階": {"b有効" if v else "b取消": n} if n else {}}
                for role in ("T", "R"):
                    formed = n if role == target else 0
                    group[role] = {"形成あり": formed, "形成なし": n - formed, "取消あり": formed if not v else 0,
                        "episode有効": formed if v else 0, "bあり": formed, "fあり": 0, "rあり": 0, "kあり": 0, "k有効": 0,
                        "形成ID数": formed // 2, "最大反復": 2 if formed else 0, "段階": {"1" if formed else "0": n} if n else {}}
                result["状態分布"][phase][name] = group
        model["training"]["partition"] = parts
        for key in keys:
            model["training"].setdefault(key, "人工_" + phase + "_" + key)
        for key in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints", "base54_fingerprints"):
            model["training"].setdefault(key, {name: "人工_" + phase + "_" + key + "_" + name for name in keys})
        model["training"]["base60_fingerprints"] = {key: model["training"][key] for key in keys}
        c["prior_models"][phase] = deepcopy(model)
        c["prior_models"][phase]["policy"] = "Q0"
        item["base_path"] = renderer.STUDY / "models" / (model["model_id"] + ".json")
        item["path"] = renderer.STUDY / "models" / ("回収_" + phase + ".json")
        item["entry"].update(id=model["model_id"], policy="U0", phase=phase)
        item["calibration"].update(model_id=model["model_id"], policy="U0", phase=phase)
    result["経路支持"] = {"U0_" + phase: v for phase, v in result["経路支持"].items()}
    result["数量分布"] = {name: {**{k: group[k] for k in ("全枠", "準備枠", "未準備枠")},
        "方向行": group["準備方向行"], "両ペア有効方向": 0,
        **{stage: {"段階あり": 0, "ペア有効": 0, "既知0量": 0, "理由": {"段階なし": group["準備方向行"]}, "基準足数": {}} for stage in ("b", "r")}}
        for name, group in result["価格経路分布"].items()}
    result["検査"]["旧64特徴保存一致"] = 3404
    c["sources"] = [Path(renderer.__file__).resolve(), Path(__file__).resolve()]
    return c


def virtual_outputs(context: dict) -> set[Path]:
    """正式出力を作らず、人工でだけ未作成参照を明示する。

    引数: context(dict)は人工文脈。
    返り値: set[Path]は二MDと正本・新木・回収の仮想リンク先。
    """
    paths = {R.STUDY / n for n in ("README.md", "設定と結果.md", "結果.json", "保存物確認.json", "検証計画.md", "条件.json", "一覧.resources.json")}
    for item in context["models"].values():
        paths.update((item["base_path"], item["path"]))
    return {p.resolve() for p in paths}


class RenderTests(unittest.TestCase):
    """同60・現在有効・数量・品質の表示を人工で確認する。"""

    def test_documents(self) -> None:
        """全60/55×9・全node・同byte・リンクと入力非変更を確認する。

        引数: なし。
        返り値: None。正式入力を開かない。
        """
        c = artificial_context(R)
        R.validate_result(c["result"])
        R.validate_state_distribution(c["result"]["状態分布"], c["models"])
        R.validate_episode_support(c["result"]["経路支持"], c["models"])
        for item in c["models"].values():
            R.validate_model(item["base"])
            R.R55.validate_calibration(item["calibration"], item["base"])
        before = deepcopy(c)
        a, b = R.documents(c), R.documents(c)
        self.assertEqual(a, b)
        self.assertEqual(c, before)
        self.assertGreater(R.validate_documents(a, virtual_outputs(c)), 50)
        for phrase in ("同じ全60", "V1はb", "旧64Q0/Q1", "184資源", "次点救済なし"):
            self.assertIn(phrase, a["README.md"] + a["設定と結果.md"])

    def test_valid_from_birth_without_k(self) -> None:
        """V1の未r/kとV0の取消を混同せず、対応有効の変造を拒否する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        R.validate_state_distribution(c["result"]["状態分布"], c["models"])
        row = c["result"]["状態分布"]["F40"]["D1_V1"]
        self.assertGreater(row["T"]["episode有効"], 0)
        self.assertEqual(row["T"]["kあり"], 0)
        row["T"]["episode有効"] = 0
        with self.assertRaises(ValueError):
            R.validate_state_distribution(c["result"]["状態分布"], c["models"])

    def test_current_not_k_roots(self) -> None:
        """固定根の対応episode列・58投影を検査し、k列置換を拒否する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        model = c["models"]["F40"]["base"]
        R.validate_model(model)
        model["nodes"][1]["feature"] = 26
        with self.assertRaises(ValueError):
            R.validate_model(model)

    def test_full60_fingerprints(self) -> None:
        """旧60canonicalと既存射影の完全保持を確認する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        model, prior = c["models"]["F40"]["base"], c["prior_models"]["F40"]
        R.validate_prior60(model, prior)
        model["training"]["used_rows_sha256"] = "差"
        with self.assertRaises(ValueError):
            R.validate_prior60(model, prior)

    def test_episode_model_id_and_quantity(self) -> None:
        """modelid経路支持と、量の段階なし・既知0・理由分母を確認する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        R.validate_episode_support(c["result"]["経路支持"], c["models"])
        R.R64.validate_quantity_distribution(c["result"]["数量分布"], c["result"]["価格経路分布"])
        c["result"]["経路支持"]["F40"] = c["result"]["経路支持"].pop("U0_F40")
        with self.assertRaises(ValueError):
            R.validate_episode_support(c["result"]["経路支持"], c["models"])

    def test_null_and_method_gate(self) -> None:
        """品質nullと、二段pathの技法資格・空scoreを確認する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        model = c["models"]["F40"]["base"]
        self.assertTrue(model["nodes"][3]["method_support"])
        self.assertIsNone(model["nodes"][4]["score"])
        c["result"]["候補"]["Q0"]["学習"]["運用"]["全体確定額円"]["5"] = 0
        with self.assertRaises(ValueError):
            R.validate_result(c["result"])


def run(renderer) -> dict:
    """表示器を注入し、人工件数と成功を正式記録へ返す。

    引数: renderer(ModuleType)は65表示器。
    返り値: dictは成功とテスト件数、実入力・fit・再生0。失敗時終了1。
    """
    global R
    R = renderer
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests))
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    return {"成功": True, "テスト件数": outcome.testsRun, "実入力読取": False, "fit": 0, "市場再生": False}


if __name__ == "__main__":
    spec = importlib.util.spec_from_file_location("現在状態65人工用表示器", HERE / "レポート.py")
    renderer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = renderer
    spec.loader.exec_module(renderer)
    print(json.dumps(run(renderer), ensure_ascii=False))
