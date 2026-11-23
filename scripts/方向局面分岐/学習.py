"""ZとDI符号の二段を事前固定し、四群の17列子木を合成する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys


HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / "局所帯分岐/学習.py"
SPEC = importlib.util.spec_from_file_location("方向局面分岐の固定53学習純関数", SHARED)
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
POLICIES = {"D0": 4}
FEATURE_COUNTS = {"D0": 18}
SIDES, LABELS, SKLEARN_VERSION = BASE.SIDES, BASE.LABELS, BASE.SKLEARN_VERSION
RULES = deepcopy(BASE.RULES)
RULES.pop("F0強制root")
RULES.update({"政策深さ": POLICIES, "政策特徴数": FEATURE_COUNTS,
    "D0固定段": {"root": "F18<=0.5 / >0.5", "次段": "float32 F01<=0 / >0", "固定node数": 3,
        "固定node空でも保持": True, "子深さ": 2, "子特徴数": 17, "F01子分岐可": True,
        "群分割前pair除外": True, "枝内pair再要求": False, "gini最適固定段ではない": True}})


def fingerprint(value: object) -> str:
    """固定53と同じ有限JSON内容指紋を得る。

    引数: value(object)はJSON安全な値。
    返り値: strは配列順を保つSHA256。
    """
    return BASE.fingerprint(value)


def feature_metadata(feature_meta: list[dict], policy: str) -> list[dict]:
    """D0の18列順とfamilyを固定53契約で検査する。

    引数: feature_meta(list[dict])はF01..18、policy(str)はD0。
    返り値: list[dict]は深い複写。旧metadataやglobalを変更しない。
    """
    if policy != "D0":
        raise ValueError("政策はD0のみ")
    return BASE.feature_metadata(feature_meta, "F0")


def float32(values: list, feature_count: int = 18) -> list[float]:
    """群分割とJSON予測に共通のfloat32値を作る。

    引数: values(list)は18有限特徴、feature_count(int)は18固定。
    返り値: list[float]はfloat32を正確に表す値。Zは化前から0/1だけを許す。
    """
    if feature_count != 18:
        raise ValueError("D0は18列固定")
    return BASE.float32(values, 18)


def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 18) -> tuple[list[dict], dict]:
    """全pairを先に検査し、未知教師pair除外と未来境界を固定53と共通化する。

    引数: rows(list[dict])は両方向教師、evaluation_start(float)は評価開始秒、feature_count(int)は18。
    返り値: tuple[list[dict],dict]は使用方向行と全体教師指紋。群内pairは検査しない。
    """
    if feature_count != 18:
        raise ValueError("D0は18列固定")
    return BASE.prepare_rows(rows, evaluation_start, 18)


def walk(model: dict, values: list) -> tuple[int, list[dict]]:
    """D0を18列共通JSON走査へ射影し、元モデルを変更せず葉へ進む。

    引数: model(dict)はD0保存木、values(list)は18特徴。
    返り値: tuple[int,list[dict]]は全体葉IDとpath。閾値epsilonを加えない。
    """
    if model.get("policy") != "D0":
        raise ValueError("D0以外のモデル")
    return BASE.walk({**model, "policy": "F0"}, values)


def predict(model: dict, vectors: dict[str, list]) -> dict:
    """固定53の最高側・未知leaf・支持規則を同じ18列木へ適用する。

    引数: model(dict)はD0保存木、vectors(dict[str,list])は両方向特徴。
    返り値: dictはraw scores/leafs/side/reason。旧globalや保存policyは変更しない。
    """
    if model.get("policy") != "D0":
        raise ValueError("D0以外のモデル")
    return BASE.predict({**model, "policy": "F0"}, vectors)


def fit(rows: list[dict], feature_meta: list[dict], policy: str, model_id: str, evaluation_start: float) -> dict:
    """全pair除外後にZ×float32 DI符号の四群を学習し固定三nodeへ合成する。

    引数: rows(list[dict])は両方向教師、feature_meta(list[dict])は18特徴、policy(str)はD0、
        model_id(str)は成果物ID、evaluation_start(float)は評価開始秒。
    返り値: dictは全node/四群教師/全体指紋と構造を保持する純JSON。実市場のfitはroot担当。
    """
    if policy not in POLICIES or not isinstance(model_id, str) or not model_id:
        raise ValueError("政策又はmodel_idが不正")
    meta = feature_metadata(feature_meta, policy)
    used, training = prepare_rows(rows, evaluation_start)
    # ----------------------------------------
    # 学習時だけ固定版を読み、Zは二値のまま、DI符号はfloat32化後に区分する。
    import numpy as np
    import scipy
    import sklearn
    from sklearn.tree import DecisionTreeClassifier

    if sklearn.__version__ != SKLEARN_VERSION:
        raise RuntimeError("scikit-learnは固定1.9.1が必要")
    parameters, child_parameters = BASE.classifier_parameters(4), BASE.classifier_parameters(2)
    x = np.asarray([float32(r["features"]) for r in used], dtype=np.float32)
    target = np.asarray([LABELS[r["outcome"]] for r in used], dtype=np.int64)
    fixed = [{"id": 0, "feature": "F18", "index": 17, "threshold": 0.5},
        {"id": 1, "feature": "F01", "index": 0, "threshold": 0.0},
        {"id": 2, "feature": "F01", "index": 0, "threshold": 0.0}]
    nodes = [{"id": n["id"], "feature": n["index"], "feature_id": n["feature"], "family": meta[n["index"]]["family"],
        "threshold": n["threshold"], "left": 1 if n["id"] == 0 else None, "right": 2 if n["id"] == 0 else None}
        for n in fixed]
    training["partition"], fitted = {}, []
    for z in (0, 1):
        for a in (0, 1):
            indexes = [i for i in range(len(used)) if x[i, 17] == z and int(x[i, 0] > 0) == a]
            selected, offset, estimator = [used[i] for i in indexes], len(nodes), None
            if selected:
                estimator = DecisionTreeClassifier(**child_parameters)
                estimator.fit(x[indexes, :17], target[indexes], sample_weight=np.full(len(indexes), 0.5, dtype=np.float64))
                fitted.append((estimator, indexes, offset))
            child_nodes = BASE.tree_topology(estimator, offset, meta)
            nodes.extend(child_nodes)
            nodes[1 + z]["left" if a == 0 else "right"] = offset
            identities = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
            training["partition"][f"Z{z}_a{a}"] = {"z": z, "a": a, "policy": policy,
                "direction_rows": len(selected), "pair_unique": len({(r["session"], r["slot_id"]) for r in selected}),
                "days": len({r["session"][:10] for r in selected}), "sessions": len({r["session"] for r in selected}),
                "row_ids_sha256": fingerprint(identities), "fit_performed": estimator is not None,
                "root": offset, "node_count": len(child_nodes), "fit_parameters": deepcopy(child_parameters)}
    # ----------------------------------------
    # 固定段が空の場合も三nodeを残し、全使用行から全nodeの所属とginiを再計数する。
    paths = BASE.node_paths(nodes, meta)
    model = {"policy": policy, "feature_meta": meta, "nodes": nodes}
    membership = {n["id"]: [] for n in nodes}
    for i, row in enumerate(used):
        leaf, path = walk(model, row["features"])
        for node_id in [p["node"] for p in path] + [leaf]:
            membership[node_id].append(i)
    for node in nodes:
        selected = [used[i] for i in membership[node["id"]]]
        total_weight = len(selected) * 0.5
        success_weight = sum(LABELS[r["outcome"]] for r in selected) * 0.5
        score = success_weight / total_weight if total_weight else None
        path = paths[node["id"]]
        identities = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
        node.update({"path": path, "direction_rows": len(selected), "weighted_rows": total_weight,
            "success_weight": success_weight, "total_weight": total_weight, "score": score,
            "unique_slots": len({(r["session"], r["slot_id"]) for r in selected}),
            "days": len({r["session"][:10] for r in selected}), "sessions": len({r["session"] for r in selected}),
            "methods": sorted({p["method"] for p in path}), "families": sorted({p["family"] for p in path}),
            "training_ids_sha256": fingerprint(identities), "impurity": 2 * score * (1 - score) if score is not None else None,
            "data_absent": not selected})
        eligibility = BASE.leaf_eligibility(node, path)
        node.update(leaf_support=eligibility["leaf_support"], method_support=eligibility["method_support"])
    structure = {"kind": "fixed_root_and_direction", "fixed_nodes": fixed, "child_depth": 2,
        "child_features": 17, "max_depth": 4, "fixed_gini_optimized": False}
    model.update({"schema_version": 1, "model_id": model_id, "feature_meta_sha256": fingerprint(meta),
        "parameters": parameters, "subtree_parameters": child_parameters, "structure": structure, "rules": deepcopy(RULES),
        "versions": {"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "shared_source_sha256": {SHARED.relative_to(HERE.parents[1]).as_posix(): hashlib.sha256(SHARED.read_bytes()).hexdigest()},
        "training": training, "nodes": nodes,
        "interpretation": "Zとfloat32 DI符号の固定二段はgini最適分割ではない。各子木は17列の深さ2。固定price+trendをpathへ数えるが、未知枝/score/葉支持の基準は維持。葉率は将来確率ではない"})
    # ----------------------------------------
    # 全非空群の元学習器と全node所属・予測を照合し、17列投影や全体IDのずれを拒否する。
    for estimator, indexes, offset in fitted:
        projected = x[indexes, :17]
        tree, visits = estimator.tree_, estimator.decision_path(projected)
        positive = np.flatnonzero(estimator.classes_ == 1)
        for local in range(tree.node_count):
            expected = [indexes[i] for i in visits[:, local].nonzero()[0].tolist()]
            node = nodes[offset + local]
            expected_score = float(tree.value[local, 0, positive[0]]) if len(positive) else 0.0
            if membership[offset + local] != expected or node["score"] != expected_score or node["direction_rows"] != int(tree.n_node_samples[local]) or node["total_weight"] != float(tree.weighted_n_node_samples[local]):
                raise ValueError("合成木と群内学習木の所属/score/重みが不一致")
        leaves, probabilities = estimator.apply(projected), estimator.predict_proba(projected)
        for local_row, i in enumerate(indexes):
            leaf, _ = walk(model, used[i]["features"])
            expected_score = float(probabilities[local_row, positive[0]]) if len(positive) else 0.0
            if leaf != int(leaves[local_row]) + offset or nodes[leaf]["score"] != expected_score:
                raise ValueError("合成JSONと群内学習器の予測が不一致")
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
