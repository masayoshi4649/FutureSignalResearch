"""70の表示だけを架空の元木・剪定木で検査する。"""

from copy import deepcopy
import importlib.util
import sys
import unittest


R = None


def artificial_context(renderer) -> dict:
    """固定69の人工factoryを純再用し、手製の支持統合例を構成する。

    引数: renderer(ModuleType)は70表示器。
    返り値: dictは本物モデル・結果・教師を読まない自己完結文脈。
    """
    spec = importlib.util.spec_from_file_location("支持表示70の固定69人工factory", renderer.PREVIOUS.HERE / "レポートの人工検査.py")
    factory = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = factory
    spec.loader.exec_module(factory)
    original = factory.artificial_context(renderer.PREVIOUS)
    old = original["result"]
    result = deepcopy(old)
    for field in ("候補", "役割別入口"):
        result[field] = {p: deepcopy(old[field]["C" + p[-1]]) for p in renderer.POLICIES}
    result["条件段階"] = {p: deepcopy(old["条件段階"]["C" + p[-1]]) for p in renderer.NEW}
    result["判断理由"] = {p: deepcopy(old["判断理由"]["C" + p[-1]]) for p in renderer.NEW}
    result.update(試行=70, 新分類器fit=0, 新回帰器fit=0, 新保存木数=3, 新派生木数=3,
        参照モデル数=3, 新運用数=92, 新独立計測=0, 参照独立測定=4092,
        学習参照=deepcopy(renderer.LEARNING), 対照参照={"候補": ["C0", "C1"], "元試行": 69, "市場再生": False},
        モデル=[], 回収集計=[], 剪定={}, 採用=[])
    for name in ("共通教師", "独立教師分類"):
        result.pop(name, None)
    models = {}
    for phase in renderer.PHASES:
        source_item = original["models"]["C0_" + phase]
        source, cal = deepcopy(source_item["base"]), deepcopy(source_item["calibration"])
        for node in source["nodes"]:
            node.update(feature_id=source["feature_meta"][node["feature"]]["id"] if node["left"] != -1 else None,
                family=source["feature_meta"][node["feature"]]["family"] if node["left"] != -1 else None)
        derived = deepcopy(source)
        # ----------------------------------------
        # 元node3の弱い両葉7/8を統合し、元親の統計だけをそのまま残す。
        source["nodes"][3].update(feature=1, feature_id="F02", family="osc", threshold=0.0, left=7, right=8)
        for index, template, comparison in ((7, 3, "<="), (8, 4, ">")):
            child = deepcopy(derived["nodes"][template])
            child["id"] = index
            child["path"] = [*source["nodes"][3]["path"], {"node": 3, "feature_id": "F02", "comparison": comparison, "threshold": 0.0, "method": "I07", "family": "osc"}]
            source["nodes"].append(child)
        source["training"]["partition"]["D0_V0"]["node_count"] = 3
        derived["training"] = deepcopy(source["training"])
        identity, source_sha = "P0_" + phase, "a" * 64
        derived.update(model_id=identity, policy="P0", source_model_id=source["model_id"], source_model_sha256=source_sha)
        for node in derived["nodes"]:
            node["source_node_id"] = node["id"]
        details = [{"source_node_id": i, "unique_slots": 0, "days": 0, "sessions": 0, "supported": False} for i in (7, 8)]
        partitions = {key: {"source_root": item["root"], "source_node_count": item["node_count"], "new_root": item["root"], "new_node_count": 1} for key, item in source["training"]["partition"].items()}
        pruning = {"rules": {"人工": "支持だけで両側統合"}, "source_model_id": source["model_id"], "source_model_sha256": source_sha,
            "source_node_count": 9, "new_node_count": 7, "fit_count": 0,
            "source_to_new": {str(i): i if i < 7 else None for i in range(9)}, "new_to_source": {str(i): i for i in range(7)},
            "partitions": partitions, "decisions": [{"source_node_id": 3, "action": "両側統合", "terminal_source_ids": [7, 8],
                "terminal_support": details, "result_terminal_source_ids": [3], "retained_in_final": True,
                "split_retained_in_final": False, "reason": "約定支持不足の両側を親へ統合"}]}
        derived["pruning"] = pruning
        cal.update(model_id=identity, policy="P0")
        path = renderer.STUDY / "models" / (identity + ".json")
        cal_path = renderer.STUDY / "models" / ("回収_" + identity + ".json")
        source_path = renderer.OLD / "models" / (source["model_id"] + ".json")
        entry = {**source_item["entry"], "id": identity, "policy": "P0", "path": path.relative_to(renderer.ROOT).as_posix(),
            "元path": source_path.relative_to(renderer.ROOT).as_posix(), "元SHA256": source_sha}
        result["モデル"].append(entry)
        result["回収集計"].append({"id": identity, "policy": "P0", "phase": phase, "path": cal_path.relative_to(renderer.ROOT).as_posix(), "SHA256": "人工"})
        result["剪定"][phase] = deepcopy(pruning)
        models[identity] = {"base": derived, "calibration": cal, "base_path": path, "path": cal_path, "entry": entry, "source": source, "source_path": source_path}
    result["新条件入口評価"] = sum(result["候補"][p][h]["入口"]["候補"] for p in renderer.NEW for h in renderer.PERIODS)
    return {"result": result, "old": old, "proof": {"照合項目数": 123, "不一致数": 0}, "fixed": {}, "metadata": original["metadata"],
        "models": models, "sources": [renderer.HERE / "レポート.py", renderer.HERE / "レポートの人工検査.py"]}


def virtual_outputs(context: dict) -> set:
    """実際には作成しない人工参照をリンク検査へ渡す。

    引数: context(dict)は人工表示文脈。
    返り値: set[Path]は仮想的な同時出力とモデル参照。
    """
    paths = {R.STUDY / name for name in ("README.md", "設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json")}
    paths.update(R.OLD / name for name in ("結果.json", "設定と結果.md"))
    for item in context["models"].values():
        paths.update((item["base_path"], item["path"], item["source_path"]))
    return {p.resolve() for p in paths}


# ----------------------------------------
class RenderTests(unittest.TestCase):
    """数値・支持分母と元統計の出所を表示人工で確認する。"""

    def test_documents_and_no_mutation(self) -> None:
        """全60・55×9・全剪定判断・リンクと非改変を確認する。

        引数: self(RenderTests)は検査器。
        返り値: None。正式MDを書かない。
        """
        context = artificial_context(R)
        R.validate_result(context["result"])
        for item in context["models"].values():
            R.validate_model(item["base"], item["calibration"], item["source"], context["old"]["共通教師"][item["entry"]["phase"]])
        before = deepcopy(context)
        documents = R.documents(context)
        self.assertEqual(documents, R.documents(context))
        self.assertEqual(context, before)
        self.assertGreater(R.validate_documents(documents, virtual_outputs(context)), 20)
        text = documents["設定と結果.md"]
        for phrase in ("新fit0", "元子root", "元node数", "source_node_id", "両側統合", "全無取引", "空回帰", "filled平均", "元保存MSE", "同じ全60特徴"):
            self.assertIn(phrase, text)
        self.assertNotIn("W20_可知0", text)
        for identity in context["models"]:
            self.assertIn(identity, text)

    def test_source_statistics_and_mapping_guards(self) -> None:
        """利益統計・元学習証拠・ID対応の変更を拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        mutations = (("stat", "元保存統計"), ("map", "ID圧縮"), ("training", "元配置"), ("fixed", "固定段"), ("fit", "fit0"))
        for kind, label in mutations:
            with self.subTest(label=label):
                context = artificial_context(R)
                item = context["models"]["P0_W20"]
                model = item["base"]
                if kind == "stat":
                    model["nodes"][3]["recovery"]["pnl5"]["sum"] = "999"
                elif kind == "map":
                    model["pruning"]["source_to_new"]["7"] = 6
                elif kind == "training":
                    model["training"]["partition"]["D0_V0"]["node_count"] = 1
                elif kind == "fixed":
                    model["nodes"][0]["threshold"] = 1.0
                else:
                    model["pruning"]["fit_count"] = 1
                with self.assertRaises(ValueError):
                    R.validate_model(model, item["calibration"], item["source"], context["old"]["共通教師"]["W20"])

    def test_support_and_original_layout(self) -> None:
        """元の三節点から新一葉への配置と支持だけの判断を区別する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        item = context["models"]["P0_F40"]
        self.assertEqual(item["base"]["training"]["partition"]["D0_V0"]["node_count"], 3)
        self.assertEqual(item["base"]["pruning"]["partitions"]["D0_V0"]["new_node_count"], 1)
        item["base"]["pruning"]["decisions"][0]["action"] = "保持"
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], item["source"], context["old"]["共通教師"]["F40"])

    def test_unknown_zero_and_filled_denominator(self) -> None:
        """全無取引0・空未知・条件付きscoreを混同しない。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        item = context["models"]["P0_W20"]
        self.assertEqual(item["base"]["nodes"][3]["recovery"]["pnl5"]["mean"], 0.0)
        self.assertIsNone(item["base"]["nodes"][3]["score"])
        self.assertIsNone(item["base"]["nodes"][4]["recovery"]["pnl5"]["mean"])
        item["calibration"]["leaves"]["5"]["mean_yen"]["5"] = 0.0
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], item["source"], context["old"]["共通教師"]["W20"])

    def test_quality_null_and_no_fit(self) -> None:
        """品質注意は観測額を残して確定null、新fitの増加は拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        result = context["result"]
        o = result["候補"]["P0"][R.PERIODS[0]]["運用"]
        o["品質注意場"] = ["人工注意"]
        o["全体確定額円"] = {str(f): None for f in (0, 5, 10)}
        R.validate_result(result)
        self.assertIn("null", R.documents(context)["設定と結果.md"])
        o["全体確定額円"]["5"] = 0
        with self.assertRaises(ValueError):
            R.validate_result(result)
        context = artificial_context(R)
        context["result"]["新回帰器fit"] = 1
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_all_six_nonfill_and_activity(self) -> None:
        """非fill六群を仮約定から除外し、条件未約定を活動へ含める。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        result = context["result"]
        p, h = "P0", R.PERIODS[0]
        e, stage = result["候補"][p][h]["入口"], result["条件段階"][p][h]
        outcomes = {key: 1 for key in R.NONFILL}
        outcomes.update({"250": 1, "125": 1})
        e.update(候補=8, 約定=2, 結果別=outcomes, 率=0.5, **{"250": 1})
        stage.update(純候補=8, 条件結果別=deepcopy(outcomes), 仮約定=2, 発動=3)
        result["新条件入口評価"] = sum(result["候補"][q][period]["入口"]["候補"] for q in R.NEW for period in R.PERIODS)
        R.validate_result(result)
        e["約定"] = 3
        with self.assertRaises(ValueError):
            R.validate_result(result)


def run(renderer=None) -> dict:
    """人工表示六群だけを実行し、rootの公式記録へ結果を返す。

    引数: renderer(ModuleType|None)は70表示器。省略時は固有名で読込む。
    返り値: dictは成功/テスト件数/fit0。正式入力・モデル・文書へ触れない。
    """
    global R
    if renderer is None:
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("支持表示70人工の対象", Path(__file__).with_name("レポート.py"))
        renderer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = renderer
        spec.loader.exec_module(renderer)
    R = renderer
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests))
    if not result.wasSuccessful():
        raise AssertionError("70の表示人工に不一致")
    return {"成功": True, "テスト件数": result.testsRun, "fit": 0, "本物入力読取": False, "正式文書生成": False}


def self_test() -> dict:
    """単独CLIと公式人工から同じ人工六群を呼ぶ。

    引数: なし。
    返り値: dictは人工の成功記録。
    """
    return run()


if __name__ == "__main__":
    import json
    print(json.dumps(self_test(), ensure_ascii=False))
