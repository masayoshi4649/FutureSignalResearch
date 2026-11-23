"""71の再学習・支持剪定・取得位置の表示を、自己完結人工だけで検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest


R = None


def artificial_context(renderer) -> dict:
    """旧70人工辞書から60/61列の元六木・派生六木を手製で構成する。

    引数: renderer(ModuleType)は71表示器。
    返り値: dictは本物入力を読まない表示文脈。fit・剪定関数も呼ばない。
    """
    spec = importlib.util.spec_from_file_location("取得71表示の固定70人工材料", renderer.PREVIOUS.HERE / "レポートの人工検査.py")
    factory = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = factory
    spec.loader.exec_module(factory)
    prior = factory.artificial_context(renderer.PREVIOUS)
    result = deepcopy(prior["result"])
    for key in ("候補", "役割別入口"):
        result[key] = {p: deepcopy(prior["result"][key]["P" + p[-1]]) for p in renderer.POLICIES}
    result["条件段階"] = {p: deepcopy(prior["result"]["条件段階"]["P" + p[-1]]) for p in renderer.NEW}
    result["判断理由"] = {p: deepcopy(prior["result"]["判断理由"]["P" + p[-1]]) for p in renderer.NEW}
    result.update(試行=71, 新保存木数=12, 新元学習木数=6, 新派生木数=6, 新運用数=184,
        新回帰器fit=18, モデル=[], 元学習モデル=[], 回収集計=[], 剪定={}, 共通教師={},
        学習参照={"元試行": 69, "モデル政策": "C0", "同じ可知集合": True, "同じ条件教師": True,
            "基礎60投影同値": True, "新fit": True, "追加": deepcopy(renderer.POSITION_META), "無取引": "回収0・障壁対象外"},
        対照参照={"候補": ["P0", "P1"], "元試行": 70, "市場再生": False})
    raw_models, models = {}, {}
    fingerprints = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "used_barrier_rows_sha256", "period_sha256")
    for phase in renderer.PHASES:
        result["剪定"][phase] = {}
        common = prior["old"]["共通教師"][phase]
        result["共通教師"][phase] = {key: deepcopy(common[key]) for key in ("全予定枠", "共通可知枠", "共通方向行", "除外枠数", "使用分類", "共通ID同順序", "方向重み")}
        result["共通教師"][phase].update(旧69共通集合SHA256=renderer.fingerprint(common), 旧69結果path=(renderer.SOURCE / "結果.json").relative_to(renderer.ROOT).as_posix())
        for policy, count in (("B0", 60), ("G0", 61)):
            template = prior["models"]["P0_" + phase]
            source, model, cal = deepcopy(template["source"]), deepcopy(template["base"]), deepcopy(template["calibration"])
            raw_id, identity = policy + "_" + phase + "_学習", policy + "_" + phase
            source.update(model_id=raw_id, policy=policy)
            source["feature_meta"] = deepcopy(prior["metadata"]) + ([deepcopy(renderer.POSITION_META)] if count == 61 else [])
            source["structure"]["child_features"] = count - 2
            source["structure"]["child_feature_indices"] = {"D0": [i for i in range(count) if i not in (0, 25)], "D1": [i for i in range(count) if i not in (0, 19)]}
            source["training"]["base60_fingerprints"] = {key: source["training"].get(key, "人工基礎_" + key) for key in fingerprints}
            model.update(model_id=identity, policy=policy, source_model_id=raw_id, feature_meta=deepcopy(source["feature_meta"]),
                training=deepcopy(source["training"]), structure=deepcopy(source["structure"]))
            model["pruning"]["source_model_id"] = raw_id
            cal.update(model_id=identity, policy=policy)
            raw_path = renderer.STUDY / "models" / (raw_id + ".json")
            path = renderer.STUDY / "models" / (identity + ".json")
            cal_path = renderer.STUDY / "models" / ("回収_" + identity + ".json")
            raw_entry = {**template["entry"], "id": raw_id, "policy": policy, "特徴数": count, "path": raw_path.relative_to(renderer.ROOT).as_posix()}
            entry = {**raw_entry, "id": identity, "path": path.relative_to(renderer.ROOT).as_posix(), "元path": raw_entry["path"], "元SHA256": "a" * 64}
            result["元学習モデル"].append(raw_entry)
            result["モデル"].append(entry)
            result["回収集計"].append({"id": identity, "policy": policy, "phase": phase, "path": cal_path.relative_to(renderer.ROOT).as_posix(), "SHA256": "人工"})
            result["剪定"][phase][policy] = deepcopy(model["pruning"])
            raw_models[raw_id] = {"base": source, "calibration": None, "base_path": raw_path, "path": raw_path, "entry": raw_entry, "kind": "元学習"}
            models[identity] = {"base": model, "calibration": cal, "base_path": path, "path": cal_path, "entry": entry, "source": source, "source_path": raw_path, "kind": "支持剪定後"}
    result["新条件入口評価"] = sum(result["候補"][p][h]["入口"]["候補"] for p in renderer.NEW for h in renderer.PERIODS)
    return {"result": result, "proof": {"照合項目数": 123, "不一致数": 0}, "fixed": {}, "old": prior["result"], "teacher": prior["old"],
        "models": models, "raw_models": raw_models, "all_models": {**raw_models, **models}, "metadata": [*prior["metadata"], deepcopy(renderer.POSITION_META)],
        "sources": [renderer.HERE / "レポート.py", renderer.HERE / "レポートの人工検査.py"]}


def virtual_outputs(context: dict) -> set:
    """人工文脈だけのリンクを仮想生成集合へ登録する。

    引数: context(dict)は人工表示文脈。
    返り値: set[Path]は作成しない文書・モデル・回収の参照先。
    """
    paths = {R.STUDY / name for name in ("README.md", "設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json")}
    for folder in (R.OLD, R.SOURCE):
        paths.update(folder / name for name in ("結果.json", "設定と結果.md"))
    for item in context["all_models"].values():
        paths.update((item["base_path"], item["path"]))
    return {p.resolve() for p in paths}


# ----------------------------------------
class RenderTests(unittest.TestCase):
    """旧対照・新元木・派生木と二つの列数を人工で検査する。"""

    def test_full_documents_and_no_mutation(self) -> None:
        """全61・55×9・12木と六剪定・リンクと非変更を確認する。

        引数: self(RenderTests)は検査器。
        返り値: None。正式文書を書かない。
        """
        context = artificial_context(R)
        R.validate_result(context["result"])
        for item in context["models"].values():
            common = context["teacher"]["共通教師"][item["entry"]["phase"]]
            R.validate_fitted_model(item["source"], None, common)
            R.validate_model(item["base"], item["calibration"], item["source"], common)
        snapshot = deepcopy(context)
        output = R.documents(context)
        self.assertEqual(output, R.documents(context))
        self.assertEqual(context, snapshot)
        self.assertGreater(R.validate_documents(output, virtual_outputs(context)), 30)
        text = output["設定と結果.md"]
        for identity in context["all_models"]:
            self.assertIn(identity, text)
        for phrase in ("G専用追加", "元学習6木", "派生6木", "元子root", "新root", "新しい独立技法票", "E*は将来", "全無取引", "空回帰"):
            self.assertIn(phrase, text)
        self.assertNotIn("W20_可知0", text)

    def test_60_61_metadata_and_projections(self) -> None:
        """旧60同値・G末尾列と枝別58/59を確認し不整合を拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        b, g = context["models"]["B0_W20"], context["models"]["G0_W20"]
        self.assertEqual(b["base"]["feature_meta"], g["base"]["feature_meta"][:60])
        self.assertEqual(len(g["base"]["structure"]["child_feature_indices"]["D0"]), 59)
        g["base"]["structure"]["child_feature_indices"]["D0"].remove(60)
        with self.assertRaises(ValueError):
            R.validate_fitted_model(g["base"], g["calibration"], context["teacher"]["共通教師"]["W20"])

    def test_parent_statistics_and_new_geometry(self) -> None:
        """元fit配置と派生配置の違いを保持し、親統計の改変を拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        item = context["models"]["G0_F40"]
        self.assertEqual(item["base"]["training"]["partition"]["D0_V0"]["node_count"], 3)
        self.assertEqual(item["base"]["pruning"]["partitions"]["D0_V0"]["new_node_count"], 1)
        item["base"]["nodes"][3]["recovery"]["pnl5"]["sum"] = "1"
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], item["source"], context["teacher"]["共通教師"]["F40"])

    def test_unknown_zero_and_filled_support(self) -> None:
        """全無取引0と空未知、filled支持と回帰分母を区別する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        item = context["models"]["B0_W30"]
        self.assertEqual(item["base"]["nodes"][3]["recovery"]["pnl5"]["mean"], 0)
        self.assertIsNone(item["base"]["nodes"][3]["score"])
        self.assertIsNone(item["base"]["nodes"][4]["recovery"]["pnl5"]["mean"])
        item["calibration"]["leaves"]["5"]["mean_yen"]["5"] = 0.0
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], item["source"], context["teacher"]["共通教師"]["W30"])

    def test_quality_null_and_fit_count(self) -> None:
        """観測額を保ち品質nullと新元学習fit/剪定fit0を区別する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        o = context["result"]["候補"]["G0"][R.PERIODS[0]]["運用"]
        o["品質注意場"] = ["人工"]
        o["全体確定額円"] = {str(f): None for f in (0, 5, 10)}
        R.validate_result(context["result"])
        self.assertIn("null", R.documents(context)["設定と結果.md"])
        o["全体確定額円"]["5"] = 0
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])
        context = artificial_context(R)
        context["result"]["新独立計測"] = 1
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_six_nonfill_and_no_common_ids(self) -> None:
        """条件非fill全群を仮約定から除き、旧共通IDを再転記しない。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        p, h = "G1", R.PERIODS[0]
        e = context["result"]["候補"][p][h]["入口"]
        outcomes = {key: 1 for key in R.NONFILL}
        outcomes.update({"250": 1, "125": 1})
        e.update(候補=8, 約定=2, 結果別=outcomes, 率=0.5, **{"250": 1})
        context["result"]["条件段階"][p][h].update(純候補=8, 条件結果別=deepcopy(outcomes), 仮約定=2, 発動=3)
        context["result"]["新条件入口評価"] = sum(context["result"]["候補"][p][h]["入口"]["候補"] for p in R.NEW for h in R.PERIODS)
        R.validate_result(context["result"])
        self.assertNotIn("W20_可知0", R.common_table(context))
        e["約定"] = 3
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])


def run(renderer=None) -> dict:
    """表示の六人工だけを実行する。

    引数: renderer(ModuleType|None)は71表示器。
    返り値: dictは成功/テスト件数と本物・fit非実行の記録。
    """
    global R
    if renderer is None:
        spec = importlib.util.spec_from_file_location("取得位置71表示の人工対象", Path(__file__).with_name("レポート.py"))
        renderer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = renderer
        spec.loader.exec_module(renderer)
    R = renderer
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests))
    if not result.wasSuccessful():
        raise AssertionError("71表示人工に不一致")
    return {"成功": True, "テスト件数": result.testsRun, "fit": 0, "本物入力読取": False, "正式文書生成": False}


def self_test() -> dict:
    """公式人工へ表示六群の結果を返す。

    引数: なし。
    返り値: dictは人工結果。
    """
    return run()


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False))
