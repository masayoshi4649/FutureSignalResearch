"""本物の結果・モデル・教師を開かず、64表示契約を人工で検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
R = None


def artificial_context(renderer) -> dict:
    """固定表示器の人工数値を六政策・二方向木の契約へ写す。

    引数: renderer(ModuleType)は64表示器。
    返り値: dictは人工文脈。実入力・モデル・結果を読み込まない。
    """
    c = deepcopy(renderer.BASE.artificial_context())
    result, originals = c["result"], c["models"]
    for phase, original in originals.items():
        for key in renderer.FINGERPRINT_KEYS:
            original["base"]["training"].setdefault(key, "人工_" + phase + "_" + key)
        for key in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints"):
            original["base"]["training"].setdefault(key, {name: "人工_" + phase + "_" + key + "_" + name for name in renderer.FINGERPRINT_KEYS})
    c["prior_models"] = deepcopy(originals)
    mapping = {"K0": "J0", "K1": "J1", "J0": "B0", "J1": "B1"}
    for field in ("候補", "役割別入口"):
        result[field] = {mapping[p]: value for p, value in result[field].items()}
        result[field].update({"Q0": deepcopy(result[field]["B0"]), "Q1": deepcopy(result[field]["B1"])})
    old_reasons = result["判断理由"]
    result["判断理由"] = {p: deepcopy(old_reasons["J0" if p.endswith("0") else "J1"]) for p in renderer.NEW}
    result.update(試行=64, 新運用数=184, 新回帰器fit=12,
        対照参照={"候補": ["J0", "J1"], "元試行": 63, "同じ評価46場": True, "市場再生": False})
    additions = [("対応b同時刻RVOL", "V01", "volume"), ("対応b同足進行対現在ATR", "P05", "price"),
        ("対応r同時刻RVOL", "V01", "volume"), ("対応r同足進行対現在ATR", "P05", "price"),
        ("対応b量価格ペア有効", "V01", "volume"), ("対応r量価格ペア有効", "V01", "volume")]
    metadata = c["metadata"] + [{"id": f"F{i + 55:02d}", "name": name, "method": method, "family": family, "scale": "m03"}
        for i, (name, method, family) in enumerate(additions)]
    c["metadata"], c["models"] = metadata, {}
    for policy in renderer.FIT:
        count = renderer.COUNTS[policy]
        for phase, original in originals.items():
            item = deepcopy(original)
            model = item["base"]
            identity = policy + "_" + phase
            model.update(policy=policy, model_id=identity, feature_meta=metadata[:count])
            model["structure"].update(kind="fixed_direction_only", child_depth=3, child_features=count - 1,
                child_feature_indices=list(range(1, count)), excluded_feature_indices=[0], feature_count=count)
            model["structure"]["fixed_nodes"] = [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0}]
            model["subtree_parameters"]["max_depth"] = 3
            model["nodes"][1]["feature"], model["nodes"][2]["feature"] = 17, 3
            model["nodes"][5]["feature"] = 58 if policy == "Q0" else 1
            for node in model["nodes"]:
                for part in node["path"]:
                    split = model["nodes"][part["node"]]
                    meta = metadata[split["feature"]]
                    part.update(feature=split["feature"], feature_id=meta["id"], method=meta["method"],
                        family=meta["family"], threshold=split["threshold"])
                node["families"] = sorted({part["family"] for part in node["path"]})
                node["method_support"] = len(node["families"]) >= 2 and bool(set(node["families"]) & {"trend", "osc"})
            model["training"]["partition"] = {f"D{d}": {"d": d, "route": "R" if d == 0 else "T", "policy": policy,
                "excluded_feature_indices": [0], "child_feature_indices": list(range(1, count)),
                "direction_rows": model["nodes"][1 + d]["direction_rows"],
                "pair_unique": model["nodes"][1 + d]["unique_slots"], "days": 6, "sessions": 10,
                "root": 1 + d, "node_count": 3 if d == 0 else 5, "fit_performed": True}
                for d in (0, 1)}
            model["training"]["base54_fingerprints"] = {key: original["base"]["training"].get(key) for key in renderer.FINGERPRINT_KEYS}
            item["base_path"] = renderer.STUDY / "models" / (identity + ".json")
            item["path"] = renderer.STUDY / "models" / ("回収_" + identity + ".json")
            item["entry"].update(id=identity, policy=policy, phase=phase, path=item["base_path"].relative_to(renderer.ROOT).as_posix())
            item["calibration"].update(model_id=identity, policy=policy, phase=phase,
                base_model_path=item["entry"]["path"], base_model_sha256="人工")
            c["models"][identity] = item
    result["経路支持"] = {identity: {str(n["id"]): {"方向行": n["direction_rows"],
        "T": renderer.BASE.empty_episode_counts(n["direction_rows"]), "R": renderer.BASE.empty_episode_counts(n["direction_rows"])}
        for n in item["base"]["nodes"] if n["left"] == -1} for identity, item in c["models"].items()}
    result["数量分布"] = {}
    for name, group in result["価格経路分布"].items():
        n = group["準備方向行"]
        result["数量分布"][name] = {**{k: group[k] for k in ("全枠", "準備枠", "未準備枠")},
            "方向行": n, "両ペア有効方向": 0,
            **{stage: {"段階あり": 0, "ペア有効": 0, "既知0量": 0, "理由": {"段階なし": n}, "基準足数": {}} for stage in ("b", "r")}}
    c["sources"] = [Path(renderer.__file__).resolve(), Path(__file__).resolve()]
    return c


def virtual_outputs(context: dict) -> set[Path]:
    """正式生成しない人工リンク先だけを明示する。

    引数: context(dict)は人工文脈。
    返り値: set[Path]は二MD・正本参照・六木・六回収集計の仮想出典。
    """
    paths = {R.STUDY / n for n in ("README.md", "設定と結果.md", "結果.json", "保存物確認.json", "検証計画.md", "条件.json", "一覧.resources.json")}
    for item in context["models"].values():
        paths.update((item["path"], item["base_path"]))
    return {p.resolve() for p in paths}


class RenderTests(unittest.TestCase):
    """表示の欠測・分母・全モデルと既存純補助への接続を検査する。"""

    def test_documents(self) -> None:
        """六木の全node・全60列・55×9・リンク・同byteを確認する。

        引数: なし。
        返り値: None。正式MDは作らない。
        """
        context = artificial_context(R)
        before = deepcopy(context)
        R.validate_result(context["result"])
        R.validate_episode_support(context["result"]["経路支持"], context["models"])
        for item in context["models"].values():
            R.validate_model(item["base"])
            R.R55.validate_calibration(item["calibration"], item["base"])
        a, b = R.documents(context), R.documents(context)
        self.assertEqual(a, b)
        self.assertEqual(context, before)
        self.assertGreater(R.validate_documents(a, virtual_outputs(context)), 50)
        self.assertIn("276資源", a["README.md"])
        self.assertIn("新6列はmaskのみ", a["設定と結果.md"])
        for identity, item in context["models"].items():
            self.assertIn(identity, a["設定と結果.md"])
            self.assertEqual(len(item["base"]["feature_meta"]), 54 if identity.startswith("B") else 60)

    def test_null_and_rates(self) -> None:
        """無取引率nullと品質注意nullを表示し、0補完を拒否する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        self.assertIn("null", R.documents(c)["設定と結果.md"])
        c["result"]["候補"]["J0"]["学習"]["運用"]["全体確定額円"]["5"] = 0
        with self.assertRaises(ValueError):
            R.validate_result(c["result"])

    def test_quantity_masks_and_denominators(self) -> None:
        """既知0を未知と分け、理由・基準足数・全方向行の差を拒否する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        coverage = c["result"]["価格経路分布"]
        rows = c["result"]["数量分布"]
        row = rows["時系列20場"]["b"]
        row.update(段階あり=2, ペア有効=1, 既知0量=1, 理由={"有効": 1, "基準不足": 1}, 基準足数={"5": 1, "4": 1})
        R.validate_quantity_distribution(rows, coverage)
        row["基準足数"]["11"] = 1
        with self.assertRaises(ValueError):
            R.validate_quantity_distribution(rows, coverage)

    def test_model_columns_and_only_di_root(self) -> None:
        """政策次元・二群・子投影と固定根の相違を検出する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        model = c["models"]["Q0_F40"]["base"]
        R.validate_model(model)
        model["structure"]["child_feature_indices"].remove(26)
        with self.assertRaises(ValueError):
            R.validate_model(model)
        model = deepcopy(c["models"]["B0_W20"]["base"])
        model["feature_meta"].append(deepcopy(c["metadata"][54]))
        with self.assertRaises(ValueError):
            R.validate_model(model)

    def test_method_gate_not_automatic(self) -> None:
        """DI根だけのnodeは非資格、maskだけの別familyは従来式で有資格とする。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        model = c["models"]["Q0_W20"]["base"]
        self.assertFalse(model["nodes"][1]["method_support"])
        self.assertTrue(model["nodes"][7]["method_support"])
        model["nodes"][1]["method_support"] = True
        with self.assertRaises(ValueError):
            R.validate_model(model)

    def test_episode_model_id_join(self) -> None:
        """同phaseのB/Qを混同せず全六木の空葉も照合する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        R.validate_episode_support(c["result"]["経路支持"], c["models"])
        c["result"]["経路支持"]["W20"] = c["result"]["経路支持"].pop("B0_W20")
        with self.assertRaises(ValueError):
            R.validate_episode_support(c["result"]["経路支持"], c["models"])

    def test_prior54_fingerprints(self) -> None:
        """旧54六指紋と既存射影の保持を新60canonicalから分離する。

        引数: なし。
        返り値: None。
        """
        c = artificial_context(R)
        prior = c["prior_models"]["F40"]["base"]
        model = c["models"]["Q0_F40"]["base"]
        R.validate_prior54(model, prior)
        model["training"]["base54_fingerprints"]["row_ids_sha256"] = "相違"
        with self.assertRaises(ValueError):
            R.validate_prior54(model, prior)


def run(renderer) -> dict:
    """表示器を明示注入して人工だけを一回実行する。

    引数: renderer(ModuleType)は64表示器。
    返り値: dictは成功とテスト件数。失敗時は終了1。
    """
    global R
    R = renderer
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    return {"成功": True, "テスト件数": result.testsRun, "実入力読取": False, "fit": 0, "市場再生": False}


if __name__ == "__main__":
    spec = importlib.util.spec_from_file_location("量価格64表示器の人工専用読込", HERE / "レポート.py")
    renderer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = renderer
    spec.loader.exec_module(renderer)
    print(json.dumps(run(renderer), ensure_ascii=False))
