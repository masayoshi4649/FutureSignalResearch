"""架空の固定四群だけで、支持剪定・両側統合・連番と予測接続を検査する。"""

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(path: Path, name: str):
    """人工材料と純関数を固有名で読む。

    引数: path(Path)はコード、name(str)はmodule名。
    返り値: ModuleTypeは読込結果。保存モデルや市場入力を開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load(HERE / "剪定.py", "支持70人工の対象")
F = load(ROOT / "scripts/量と価格進行/特徴.py", "支持70人工の固定60metadata")
SELECTOR = load(ROOT / "scripts/適格方向の選択/選択.py", "支持70人工の固定66選択")
SOURCE_SHA = "a" * 64


# ----------------------------------------
def vector(direction: int = 1, valid: int = 0) -> list[float]:
    """DI枝と対応episode旗だけを指定する合法60値を作る。

    引数: direction(int)は±1、valid(int)は0/1。
    返り値: list[float]は架空特徴。価格・教師・モデルの値は使わない。
    """
    values = [0.0] * 60
    values[0], values[15] = float(direction), 1.0
    values[18:24] = [1, valid if direction > 0 else 0, 0, -1, 0, 0]
    values[24:30] = [1, valid if direction <= 0 else 0, 0, -1, 0, 0]
    return values


def source_paths(nodes: list[dict], metadata: list[dict]) -> dict:
    """対象のpath生成を呼ばず、手作り木の元pathを構成する。

    引数: nodes(list[dict])は人工構造、metadata(list[dict])は固定60列。
    返り値: dictは旧node番号からpath。人工入力の構成にだけ使う。
    """
    result = {0: []}
    for node in nodes:
        if node["left"] < 0:
            continue
        feature, index = metadata[node["feature"]], node["id"]
        for branch, comparison in (("left", "<="), ("right", ">")):
            result[node[branch]] = [*result[index], {"node": index, "feature": node["feature"],
                "feature_id": feature["id"], "method": feature["method"], "family": feature["family"],
                "threshold": node["threshold"], "comparison": comparison, "branch": branch}]
    return result


def source_factory(case: str = "nested", overrides: dict | None = None) -> dict:
    """fitなしで固定四群と二段の学習子を持つ人工C0木を作る。

    引数: case(str)はnested/keep/local_merge/fixed_insufficient/all_no_trade/empty_group、overrides(dict|None)は葉別filled/日/場。
    返り値: dictは自己完結のschema1元モデル。正式モデルも教師も読まない。
    """
    metadata = deepcopy(F.FEATURES)
    specs = [(0, 0, 1, 2, 0.), (1, 25, 3, 10, .5), (2, 19, 11, 12, .5),
        (3, 2, 4, 7, 0.), (4, 6, 5, 6, 0.), (7, 7, 8, 9, 0.)]
    by_id = {i: {"id": i, "feature": f, "feature_id": metadata[f]["id"], "family": metadata[f]["family"],
        "threshold": threshold, "left": left, "right": right} for i, f, left, right, threshold in specs}
    for index in (5, 6, 8, 9, 10, 11, 12):
        by_id[index] = {"id": index, "feature": -2, "feature_id": None, "family": None, "threshold": -2., "left": -1, "right": -1}
    nodes = [by_id[index] for index in range(13)]
    paths = source_paths(nodes, metadata)
    counts = {5: 60, 6: 10, 8: 40, 9: 10, 10: 60, 11: 60, 12: 60}
    if case == "keep":
        counts.update({key: 60 for key in counts})
    elif case == "local_merge":
        counts.update({5: 30, 6: 30, 8: 60, 9: 60})
    elif case == "fixed_insufficient":
        counts.update({5: 10, 6: 10, 8: 10, 9: 10})
    elif case == "all_no_trade":
        counts.update({key: 0 for key in counts})
    elif case == "empty_group":
        counts[10] = 0
    elif case != "nested":
        raise ValueError("人工ケースが不明")
    leaf_rows = {}
    for leaf, count in counts.items():
        setting = (overrides or {}).get(leaf, {})
        count = setting.get("filled", count)
        days, sessions = setting.get("days", 6), setting.get("sessions", 10)
        pool = [f"2026-01-{1 + i:02d}Day" for i in range(days)]
        pool += [f"2026-01-{1 + i % days:02d}Night" for i in range(sessions - days)]
        leaf_rows[leaf] = []
        for i in range(count + (0 if case == "empty_group" and leaf == 10 else 4)):
            filled = i < count
            leaf_rows[leaf].append({"session": pool[i % len(pool)], "slot_id": f"人工_{leaf}_{i}", "side": 1,
                "filled": filled, "outcome": "250" if filled and i % 10 < (6 if leaf == 11 else 5) else "125" if filled else "無取引",
                "pnl0": "110" if filled else "0", "pnl5": "10" if filled else "0", "pnl10": "-90" if filled else "0"})
    membership = {}
    for node in reversed(nodes):
        index = node["id"]
        membership[index] = leaf_rows[index] if index in leaf_rows else membership[node["left"]] + membership[node["right"]]
    for node in nodes:
        path = paths[node["id"]]
        node.update(path=path, methods=sorted({p["method"] for p in path}), families=sorted({p["family"] for p in path}),
            impurity_kind="squared_error", **P.LEGACY.node_statistics(membership[node["id"]], path))
    partition = {}
    for d, v, index in ((0, 0, 3), (0, 1, 10), (1, 0, 11), (1, 1, 12)):
        partition[f"D{d}_V{v}"] = {"d": d, "v": v, "route": "T" if d else "R", "policy": "C0",
            "root": index, "node_count": 7 if index == 3 else 1, "direction_rows": len(membership[index]),
            "pair_unique": len(membership[index]), "days": 6, "sessions": 10, "fit_performed": bool(membership[index])}
    return {"schema_version": 1, "model_id": "C0_人工", "policy": "C0", "feature_meta": metadata,
        "feature_meta_sha256": P.LEGACY.fingerprint(metadata), "nodes": nodes,
        "parameters": {"人工": "学習済み構造の教材でありfitなし"}, "subtree_parameters": {"max_depth": 2},
        "structure": {"kind": "fixed_direction_current_episode", "fixed_nodes": deepcopy(P.FIXED_NODES),
            "feature_count": 60, "max_depth": 4, "child_depth": 2, "child_features": 58,
            "child_feature_indices": deepcopy(P.LEGACY.CHILD_FEATURE_INDICES)},
        "training": {"evaluation_start": 10000., "partition": partition, "人工元学習ID": "変更禁止"},
        "versions": {"人工": True}, "rules": {"元学習規約": True}, "source_sha256": "b" * 64}


class PruningTests(unittest.TestCase):
    """閾値を保ち、支持だけで構造を決定する境界を確認する。"""

    def test_約定支持の三境界(self) -> None:
        """60枠・6日・10場のいずれか不足ならFalse、等号ならTrueとする。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        good = {"unique_slots": 60, "days": 6, "sessions": 10}
        self.assertTrue(P.support(good)["supported"])
        for key in good:
            self.assertFalse(P.support({**good, key: good[key] - 1})["supported"])
        with self.assertRaises(ValueError):
            P.support({**good, "unique_slots": True})

    def test_両側まとめて祖先も再統合(self) -> None:
        """一側だけ救わず、不足が残る場合は上の親も統合する。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        old = source_factory()
        model = P.prune(old, "P0_人工", SOURCE_SHA)
        self.assertEqual([n["source_node_id"] for n in model["nodes"]], [0, 1, 2, 3, 10, 11, 12])
        decisions = {d["source_node_id"]: d for d in model["pruning"]["decisions"]}
        self.assertEqual(decisions[3]["terminal_source_ids"], [4, 7])
        self.assertEqual(decisions[3]["action"], "両側統合")
        self.assertEqual(decisions[4]["result_terminal_source_ids"], [4])
        self.assertFalse(decisions[4]["retained_in_final"])
        self.assertFalse(decisions[7]["retained_in_final"])
        self.assertTrue(decisions[3]["retained_in_final"])
        self.assertEqual(model["nodes"][3]["recovery"], old["nodes"][3]["recovery"])
        self.assertEqual((model["nodes"][3]["feature"], model["nodes"][3]["left"], model["nodes"][3]["threshold"]), (-2, -1, -2.))

    def test_下位統合後に全終端支持なら上は保持(self) -> None:
        """元葉の不足ではなく、下位剪定後の有効終端を判定する。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        model = P.prune(source_factory("local_merge"), "P0_人工", SOURCE_SHA)
        d = {x["source_node_id"]: x for x in model["pruning"]["decisions"]}
        self.assertEqual(d[3]["terminal_source_ids"], [4, 8, 9])
        self.assertEqual(d[3]["action"], "保持")
        self.assertTrue(d[3]["split_retained_in_final"])
        self.assertTrue(d[4]["retained_in_final"])
        self.assertFalse(d[4]["split_retained_in_final"])
        self.assertEqual(model["pruning"]["new_node_count"], 11)

    def test_全支持なら全構造保持(self) -> None:
        """全終端が等号で支持を満たす木は分割を残す。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        model = P.prune(source_factory("keep"), "P0_人工", SOURCE_SHA)
        self.assertEqual(len(model["nodes"]), 13)
        self.assertTrue(all(x["action"] == "保持" for x in model["pruning"]["decisions"]))
        self.assertEqual(model["pruning"]["source_to_new"], {str(i): i for i in range(13)})

    def test_固定四群不足でも固定段を越えない(self) -> None:
        """固定群に不足が残ってもDI/episode根を統合しない。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        model = P.prune(source_factory("fixed_insufficient"), "P0_人工", SOURCE_SHA)
        self.assertEqual([n["feature"] for n in model["nodes"][:3]], [0, 25, 19])
        self.assertFalse(model["nodes"][3]["leaf_support"])
        self.assertEqual(model["nodes"][3]["unique_slots"], 40)
        self.assertEqual(len([n for n in model["nodes"] if n["left"] == -1]), 4)

    def test_価格とscoreを変えても剪定構造不変(self) -> None:
        """利益・確率・MSEを入れ替えても支持だけで同じ剪定を行う。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        original = source_factory()
        changed = deepcopy(original)
        for n in changed["nodes"]:
            n.update(score=.99, regression_value=999999., impurity=123., recovery_positive=True)
            n["recovery"]["pnl5"].update(sum="999999", mean=999999., mean_decimal="999999")
        a, b = P.prune(original, "P0_人工", SOURCE_SHA), P.prune(changed, "P0_人工", SOURCE_SHA)
        keys = ("id", "source_node_id", "left", "right", "feature", "threshold", "path")
        self.assertEqual([{k: n[k] for k in keys} for n in a["nodes"]], [{k: n[k] for k in keys} for n in b["nodes"]])
        self.assertEqual(a["pruning"]["decisions"], b["pruning"]["decisions"])

    def test_元全文不変と統計の直接継承(self) -> None:
        """元モデル・metadata・trainingを変えず、残存nodeは親統計を直接持つ。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        old = source_factory()
        before = P.LEGACY.fingerprint(old)
        model = P.prune(old, "P0_人工", SOURCE_SHA)
        self.assertEqual(before, P.LEGACY.fingerprint(old))
        for key in set(old) - {"model_id", "policy", "nodes"}:
            self.assertEqual(model[key], old[key])
        ignored = {"id", "source_node_id", "left", "right", "feature", "feature_id", "family", "threshold", "path"}
        for n in model["nodes"]:
            source = old["nodes"][n["source_node_id"]]
            self.assertEqual({k: v for k, v in n.items() if k not in ignored}, {k: v for k, v in source.items() if k not in ignored})
        self.assertEqual(model["pruning"]["partitions"]["D0_V1"], {"source_root": 10, "source_node_count": 1, "new_root": 4, "new_node_count": 1})

    def test_全pathの新ID再割当(self) -> None:
        """元pathの分岐内容を保ち、node参照だけを連番対応へ移す。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        old = source_factory("local_merge")
        model = P.prune(old, "P0_人工", SOURCE_SHA)
        mapping = model["pruning"]["source_to_new"]
        for n in model["nodes"]:
            expected = [{**part, "node": mapping[str(part["node"])]} for part in old["nodes"][n["source_node_id"]]["path"]]
            self.assertEqual(n["path"], expected)
            self.assertEqual(model["pruning"]["new_to_source"][str(n["id"])], n["source_node_id"])
        self.assertIsNone(mapping["5"])
        self.assertIsNone(mapping["6"])

    def test_不正構造と版を拒否(self) -> None:
        """policy・元SHA・固定段・重複親・元pathの破損を拒否する。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        for case in ("policy", "固定", "重複親", "path", "支持旗"):
            old = source_factory()
            if case == "policy":
                old["policy"] = "I0"
            elif case == "固定":
                old["nodes"][1]["threshold"] = 0.25
            elif case == "重複親":
                old["nodes"][4]["right"] = old["nodes"][4]["left"]
            elif case == "path":
                old["nodes"][5]["path"] = []
            else:
                old["nodes"][5]["leaf_support"] = False
            with self.assertRaises(ValueError):
                P.prune(old, "P0_人工", SOURCE_SHA)
        with self.assertRaises(ValueError):
            P.prune(source_factory(), "P0_人工", "不正SHA")

    def test_未知葉と空群を維持(self) -> None:
        """全無取引・空回帰の区別を保持し、scoreを0へ補わない。

        引数: self(PruningTests)は検査先。
        返り値: None。
        """
        model = P.prune(source_factory("all_no_trade"), "P0_人工", SOURCE_SHA)
        prior = P.predict(model, {"1": vector(1), "-1": vector(-1)})
        self.assertEqual((prior["side"], prior["reason"]), (0, "未学習枝WAIT"))
        self.assertTrue(all(n["barrier_data_absent"] and not n["data_absent"] for n in model["nodes"]))
        empty = P.prune(source_factory("empty_group"), "P0_人工", SOURCE_SHA)
        self.assertTrue(empty["nodes"][4]["data_absent"])
        self.assertEqual(empty["nodes"][4]["recovery"]["pnl5"]["mean"], None)

    def test_69calと66selectorと主slotの接続(self) -> None:
        """fit0の剪定木を69cal・66選択・新主P0/P1へ架空入力で接続する。

        引数: self(PruningTests)は検査先。
        返り値: None。主run・本物特徴・原板は呼ばない。
        """
        main = load(HERE / "検証.py", "支持70人工の主純接続")
        model = P.prune(source_factory(), "P0_人工", SOURCE_SHA)
        cal = main.PREVIOUS.calibration_for(model)
        vectors = {"1": vector(1), "-1": vector(-1)}
        source = {"session": "2026-01-01Day", "slot_id": "人工定時", "scheduled": 100., "time": 101., "line": 1}
        feature = {"ready": True, "reason": "人工", "background_direction": 1, "atr": 10, "D": 10, "vectors": vectors}
        for policy in ("P0", "P1"):
            expected = SELECTOR.predict(model, cal, vectors, P, "E0" if policy == "P0" else "E1")
            actual = main.slots_for({"slots": [source]}, {source["slot_id"]: feature}, model, cal, P, SELECTOR, policy, "人工")[0]
            self.assertEqual(actual["prediction"], expected)
            self.assertEqual(actual["side"], expected["side"])
            self.assertEqual((actual["policy"], actual["model_id"]), (policy, "P0_人工"))
        self.assertEqual(P.predict(model, {"1": [], "-1": []})["reason"], "特徴未準備WAIT")


# ----------------------------------------
def self_test() -> dict:
    """人工の剪定と純接続だけを実行して公式集約へ返す。

    引数: なし。
    返り値: dictは成功・テスト件数・不一致。人工fitも本物fitも0。
    """
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PruningTests))
    return {"成功": result.wasSuccessful(), "テスト件数": result.testsRun,
        "不一致": output.getvalue() if not result.wasSuccessful() else [],
        "本物入力読取": False, "人工fit": 0, "本物fit": 0, "実モデル剪定": 0, "市場再生": False}


def run() -> dict:
    """人工の公開APIを旧集約形式へそろえる。

    引数: なし。
    返り値: dictはself_testの結果。
    """
    return self_test()


if __name__ == "__main__":
    proof = self_test()
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    raise SystemExit(0 if proof["成功"] else 1)
