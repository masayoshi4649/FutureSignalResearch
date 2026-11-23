"""69表示を、空葉・全無取引葉・約定葉を含む人工六木で検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
R = None


def model_for(renderer, metadata: list, policy: str, phase: str, common: dict) -> tuple:
    """fitなしで固定三nodeと四葉の小さな木・回収辞書を構成する。

    引数: renderer(ModuleType)は表示器、metadata(list)は人工60列、policy/phase(str)は識別、common(dict)は使用集合。
    返り値: tuple[dict,dict]は人工modelとcalibration。正式モデルは読まない。
    """
    model_id = policy + "_" + phase
    specs = [(0, 0, 1, 2, 0.0), (1, 25, 3, 4, 0.5), (2, 19, 5, 6, 0.5)]
    nodes = [{"id": i, "feature": f, "threshold": t, "left": left, "right": right} for i, f, left, right, t in specs]
    nodes += [{"id": i, "feature": -2, "threshold": -2.0, "left": -1, "right": -1} for i in range(3, 7)]
    paths = {0: []}
    for node in nodes[:3]:
        meta = metadata[node["feature"]]
        for child, sign in ((node["left"], "<="), (node["right"], ">")):
            paths[child] = [*paths[node["id"]], {"node": node["id"], "feature_id": meta["id"], "comparison": sign,
                "threshold": node["threshold"], "method": meta["method"], "family": meta["family"]}]
    amounts = {0: [0, 0, 300, -100, 0, 0], 1: [0, 0], 2: [300, -100, 0, 0], 3: [0, 0], 4: [], 5: [300, -100], 6: [0, 0]}
    fills = {0: 2, 1: 0, 2: 2, 3: 0, 4: 0, 5: 2, 6: 0}
    for node in nodes:
        i, filled = node["id"], fills[node["id"]]
        pnl, all_n = amounts[i], len(amounts[i])
        total = sum(pnl)
        recovery, recovery_filled = {}, {}
        for cost in (0, 5, 10):
            value = total + (5 - cost) * 20 * filled
            recovery["pnl" + str(cost)] = {"sum": str(value), "mean": value / all_n if all_n else None, "mean_decimal": str(value / all_n) if all_n else None}
            recovery_filled["pnl" + str(cost)] = {"sum": str(value), "mean": value / filled if filled else None, "mean_decimal": str(value / filled) if filled else None}
        mse = sum((x - total / all_n) ** 2 for x in pnl) / all_n if all_n else None
        node.update(path=paths[i], direction_rows=all_n, filled_direction_rows=filled, unfilled_direction_rows=all_n - filled,
            total_weight=all_n * 0.5, barrier_total_weight=filled * 0.5, success_weight=0.5 if filled else 0.0,
            score=0.5 if filled else None, fill_rate=filled / all_n if all_n else None,
            data_absent=not all_n, barrier_data_absent=not filled, unique_slots=1 if filled else 0,
            days=1 if filled else 0, sessions=1 if filled else 0, all_unique_slots=all_n // 2, all_days=1 if all_n else 0,
            all_sessions=1 if all_n else 0, leaf_support=False, method_support=i != 0,
            families=sorted({p["family"] for p in paths[i]}), recovery=recovery, recovery_filled=recovery_filled,
            recovery_positive=total > 0 if all_n else None, recovery_mse_decimal=str(mse) if all_n else None)
        if i >= 3:
            node.update(regression_value=total / all_n if all_n else None, impurity=mse)
    projection = {"D0": [i for i in range(60) if i not in (0, 25)], "D1": [i for i in range(60) if i not in (0, 19)]}
    partition = {}
    for d, v, leaf in ((0, 0, 3), (0, 1, 4), (1, 0, 5), (1, 1, 6)):
        n = nodes[leaf]["direction_rows"]
        partition[f"D{d}_V{v}"] = {"route": "R" if d == 0 else "T", "direction_rows": n,
            "pair_unique": n // 2, "days": 1 if n else 0, "sessions": 1 if n else 0,
            "root": leaf, "node_count": 1, "fit_performed": bool(n)}
    identities = [{**row, "side": side} for row in common["使用枠"] for side in (1, -1)]
    model = {"model_id": model_id, "policy": policy, "feature_meta": metadata, "nodes": nodes,
        "structure": {"kind": "fixed_direction_current_episode", "max_depth": 4, "child_depth": 2, "child_features": 58,
            "fixed_nodes": [{"id": i, "feature": metadata[f]["id"], "index": f, "threshold": t} for i, f, _, _, t in specs],
            "child_feature_indices": projection},
        "training": {"row_ids": identities, "direction_rows": 6, "input_pairs": 3, "evaluation_start": common["評価開始"],
            "period": {"same_second_allowed": False, "evaluation_start": common["評価開始"], "max_label_end_time": 500.0, "max_recovery_end_time": 600.0},
            "partition": partition, "row_ids_sha256": "人工共通ID_" + phase,
            "input_rows_sha256": "人工入力_" + model_id, "target_rows_sha256": "人工回収_" + model_id}}
    leaves = {}
    for node in nodes[3:]:
        leaves[str(node["id"])] = {"all_direction_rows": node["direction_rows"], "direction_rows": node["filled_direction_rows"],
            "unique_slots": node["unique_slots"], "days": node["days"], "sessions": node["sessions"], "support": False,
            "positive": bool(node["recovery_positive"]), "fill_rate": node["fill_rate"],
            "sum_yen": {str(c): node["recovery_filled"]["pnl" + str(c)]["sum"] for c in (0, 5, 10)},
            "mean_yen": {str(c): node["recovery_filled"]["pnl" + str(c)]["mean"] for c in (0, 5, 10)},
            "mean_all_yen": {str(c): node["recovery"]["pnl" + str(c)]["mean"] for c in (0, 5, 10)}}
    return model, {"model_id": model_id, "policy": policy, "evaluation_start": common["評価開始"], "leaves": leaves}


def artificial_context(renderer) -> dict:
    """旧表示の人工metadataと空運用を新六木・共通集合へ写す。

    引数: renderer(ModuleType)は69表示器。
    返り値: dictは自己完結人工文脈。本物結果・モデル・教師を開かない。
    """
    spec = importlib.util.spec_from_file_location("教師表示69が使う固定68人工", renderer.PREVIOUS.HERE / "レポートの人工検査.py")
    previous = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = previous
    spec.loader.exec_module(previous)
    base = previous.artificial_context(renderer.PREVIOUS)
    result = base["result"]
    for field in ("候補", "役割別入口", "判断理由"):
        old = result[field]
        result[field] = {p: deepcopy(old["N1" if p.endswith("1") else "N0"]) for p in renderer.POLICIES}
    old_stages = deepcopy(result["条件段階"])
    result["条件段階"] = {p: deepcopy(old_stages["N1" if p.endswith("1") else "N0"]) for p in renderer.NEW}
    result.update(試行=69, 新分類器fit=0, 新保存木数=6, 参照モデル数=3, 新運用数=184,
        新回帰器fit=18, 新独立計測=16, 新条件入口評価=976,
        学習参照=deepcopy(renderer.LEARNING), 対照参照={"候補": ["N0", "N1"], "元試行": 68, "市場再生": False},
        入力検査={"人工接続": 1}, 検査={"独立方向数": 16, "同一条件実仮新規一致": 0, "同一条件実独立完結一致": 0},
        独立教師分類={"確定無取引": 10, "確定約定": 4, "未知": 2}, 共通教師={}, モデル=[], 回収集計=[], 採用=[])
    models = {}
    for phase in renderer.PHASES:
        ids = [{"session": "人工Day", "slot_id": f"{phase}_可知{i}"} for i in range(3)]
        common = {"phase": phase, "評価開始": 1000.0, "全予定枠": 4, "共通可知枠": 3, "共通方向行": 6,
            "使用枠": ids, "除外枠数": 1, "除外": [{"session": "人工Day", "slot_id": phase + "_未知", "理由": {"条件-1": "入口又は障壁の観測不足"}}],
            "全測定分類": {s: {"確定無取引": 4, "確定約定": 2, "未知": 2} for s in ("即時", "条件")},
            "使用分類": {p: {"無取引": 4, "250": 1, "125": 1} for p in renderer.MODEL_POLICIES}, "共通ID同順序": True, "方向重み": 0.5}
        result["共通教師"][phase] = common
        for policy in renderer.MODEL_POLICIES:
            model, cal = model_for(renderer, base["metadata"], policy, phase, common)
            identity = model["model_id"]
            path = renderer.STUDY / "models" / (identity + ".json")
            cal_path = renderer.STUDY / "models" / ("回収_" + identity + ".json")
            entry = {"id": identity, "policy": policy, "phase": phase, "path": path.relative_to(renderer.ROOT).as_posix(), "SHA256": "人工",
                "学習場": ["人工過去"], "評価場": ["人工評価"]}
            result["モデル"].append(entry)
            result["回収集計"].append({"id": identity, "policy": policy, "phase": phase, "path": cal_path.relative_to(renderer.ROOT).as_posix(), "SHA256": "人工"})
            models[identity] = {"base": model, "calibration": cal, "base_path": path, "path": cal_path, "entry": entry}
    return {"result": result, "proof": {"照合項目数": 123, "不一致数": 0}, "fixed": {}, "metadata": base["metadata"], "models": models,
        "sources": [Path(renderer.__file__), Path(__file__)]}


def virtual_outputs(context: dict) -> set[Path]:
    """人工だけの参照先を仮想出力集合にする。

    引数: context(dict)は人工表示文脈。
    返り値: set[Path]は作成しない正本・文書・モデル参照。
    """
    paths = {R.STUDY / name for name in ("README.md", "設定と結果.md", "検証計画.md", "条件.json", "結果.json", "保存物確認.json", "一覧.resources.json")}
    for item in context["models"].values():
        paths.update((item["base_path"], item["path"]))
    return {p.resolve() for p in paths}


# ----------------------------------------
# 表示の分母・null・全六木を、教師計測やfitなしに検査する。


class RenderTests(unittest.TestCase):
    """新教師契約へ旧分母を混入させない表示人工を行う。"""

    def test_full_documents_and_no_mutation(self) -> None:
        """全60・55×9・全六木・ID・除外理由と非変更を検査する。

        引数: self(RenderTests)は検査器。
        返り値: None。正式文書を書かない。
        """
        context = artificial_context(R)
        R.validate_result(context["result"])
        for item in context["models"].values():
            R.validate_model(item["base"], item["calibration"], context["result"]["共通教師"][item["entry"]["phase"]])
        snapshot = deepcopy(context)
        output = R.documents(context)
        self.assertEqual(output, R.documents(context))
        self.assertEqual(context, snapshot)
        self.assertGreater(R.validate_documents(output, virtual_outputs(context)), 20)
        text = output["設定と結果.md"]
        for identity in context["models"]:
            self.assertIn(identity, text)
        for phrase in ("全無取引", "空回帰", "filled平均", "無取引0", "旧N→新I", "I→C", "条件-1", "W20_可知0", "独立教材の重複建玉合算"):
            self.assertIn(phrase, text)
        self.assertNotIn("新fit0", text)

    def test_all_no_trade_is_known_zero_not_empty(self) -> None:
        """全無取引葉と空葉を別旗・別平均で表示する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        item = context["models"]["C0_F40"]
        all_zero, absent = item["base"]["nodes"][3:5]
        self.assertEqual((all_zero["direction_rows"], all_zero["filled_direction_rows"], all_zero["recovery"]["pnl5"]["mean"], all_zero["score"]), (2, 0, 0.0, None))
        self.assertIsNone(absent["recovery"]["pnl5"]["mean"])
        self.assertIn("全無取引・回帰0既知/先着未知", R.model_tables(context, R.STUDY / "設定と結果.md"))
        all_zero["score"] = 0.0
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], context["result"]["共通教師"]["F40"])

    def test_filled_denominator_and_calibration(self) -> None:
        """全平均とfilled平均及びscore分母の混同を拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        item = context["models"]["I0_W20"]
        root = item["base"]["nodes"][0]
        self.assertEqual(root["score"], 0.5)
        self.assertEqual(root["recovery_filled"]["pnl5"]["mean"], 100.0)
        self.assertAlmostEqual(root["recovery"]["pnl5"]["mean"], 200 / 6)
        root["score"] = 1 / 6
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], context["result"]["共通教師"]["W20"])
        context = artificial_context(R)
        item = context["models"]["I0_W20"]
        item["base"]["training"]["period"]["max_recovery_end_time"] = 1000.0
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], context["result"]["共通教師"]["W20"])
        context = artificial_context(R)
        item = context["models"]["I0_W20"]
        item["calibration"]["leaves"]["3"]["mean_yen"]["5"] = 0.0
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], context["result"]["共通教師"]["W20"])
        context = artificial_context(R)
        item = context["models"]["I0_W20"]
        item["calibration"]["leaves"]["3"]["positive"] = not item["calibration"]["leaves"]["3"]["positive"]
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], context["result"]["共通教師"]["W20"])
        context = artificial_context(R)
        item = context["models"]["I0_W20"]
        item["base"]["nodes"][0]["leaf_support"] = True
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], context["result"]["共通教師"]["W20"])

    def test_common_ids_exclusions_and_clock(self) -> None:
        """使用と除外の重複・方向行差・モデル可知時計差を拒否する。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        for field in ("共通可知枠", "共通方向行", "除外枠数"):
            context = artificial_context(R)
            context["result"]["共通教師"]["W20"][field] += 1
            with self.assertRaises(ValueError):
                R.validate_result(context["result"])
        context = artificial_context(R)
        context["result"]["共通教師"]["W20"]["除外"][0].update(context["result"]["共通教師"]["W20"]["使用枠"][0])
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])
        context = artificial_context(R)
        item = context["models"]["I0_W20"]
        item["base"]["training"]["evaluation_start"] += 1
        with self.assertRaises(ValueError):
            R.validate_model(item["base"], item["calibration"], context["result"]["共通教師"]["W20"])

    def test_new_training_and_policies(self) -> None:
        """新六木・四政策・184運用を旧参照三木前提へ戻さない。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        for key, value in (("新保存木数", 0), ("新分類器fit", 1), ("新運用数", 92), ("新回帰器fit", 25)):
            context = artificial_context(R)
            context["result"][key] = value
            with self.assertRaises(ValueError):
                R.validate_result(context["result"])
        context = artificial_context(R)
        context["result"]["学習参照"]["無取引"] = "125敗北"
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])

    def test_condition_conservative_and_quality_null(self) -> None:
        """六政策の条件非fillと品質nullを旧即時分母で表示しない。

        引数: self(RenderTests)は検査器。
        返り値: None。
        """
        context = artificial_context(R)
        self.assertIn("対象なし（分母0）", R.main_tables(context["result"])[0])
        operation = context["result"]["候補"]["C0"]["学習"]["運用"]
        operation["品質注意場"] = ["人工品質場"]
        operation["全体確定額円"] = {"0": None, "5": None, "10": None}
        R.validate_result(context["result"])
        self.assertIn("null（品質注意）", R.main_tables(context["result"])[1])
        operation["全体確定額円"]["5"] = 0
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])
        context = artificial_context(R)
        context["result"]["候補"]["I0"]["条件選択"]["運用"]["待ち率保守上限"] = 0
        with self.assertRaises(ValueError):
            R.validate_result(context["result"])


def run(renderer) -> dict:
    """表示器を注入し人工の成功と件数を返す。

    引数: renderer(ModuleType)は69表示器。
    返り値: dictは成功・テスト件数・実入力なしの記録。
    """
    global R
    R = renderer
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenderTests))
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    return {"成功": True, "テスト件数": outcome.testsRun, "実入力読取": False, "fit": 0, "市場再生": False}


if __name__ == "__main__":
    spec = importlib.util.spec_from_file_location("条件教師69の人工用表示器", HERE / "レポート.py")
    renderer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = renderer
    spec.loader.exec_module(renderer)
    print(json.dumps(run(renderer), ensure_ascii=False))
