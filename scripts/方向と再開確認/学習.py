"""同じ46特徴と回収教師を、DIと対応経路のk有効の固定二段から分岐する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys


HERE = Path(__file__).resolve().parent
LEGACY_PATH = HERE.parent / "現行経路の状態分岐/学習.py"
SPEC = importlib.util.spec_from_file_location("方向と再開確認が固定参照する61学習", LEGACY_PATH)
LEGACY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LEGACY
SPEC.loader.exec_module(LEGACY)
BASE = LEGACY.BASE
SHARED = HERE.parent / "方向局面分岐/学習.py"
POLICIES, FEATURE_COUNTS = {"K0": 4}, {"K0": 46}
CHILD_FEATURE_INDICES = {"D0": [index for index in range(46) if index not in (0, 26)],
    "D1": [index for index in range(46) if index not in (0, 20)]}
SIDES, LABELS, SKLEARN_VERSION = LEGACY.SIDES, LEGACY.LABELS, LEGACY.SKLEARN_VERSION
MONEY_FIELDS, DECIMAL_PRECISION = LEGACY.MONEY_FIELDS, LEGACY.DECIMAL_PRECISION
NUMERIC_TOLERANCE = deepcopy(LEGACY.NUMERIC_TOLERANCE)
FINGERPRINT_FIELDS = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256",
    "period_sha256", "used_barrier_rows_sha256")
RULES = deepcopy(LEGACY.RULES)
RULES.pop("A0固定段")
RULES.pop("A1")
RULES.update({"政策深さ": POLICIES, "政策特徴数": FEATURE_COUNTS,
    "K0固定段": {"根": {"feature": "F01", "index": 0, "threshold": 0.0},
        "第二段": {"D0": {"feature": "F27", "index": 26, "threshold": 0.5, "route": "R"},
            "D1": {"feature": "F21", "index": 20, "threshold": 0.5, "route": "T"}},
        "群": ["D0_K0", "D0_K1", "D1_K0", "D1_K1"], "子深さ": 2,
        "子特徴数": 44, "子特徴列index": CHILD_FEATURE_INDICES, "MSE最適固定段ではない": True},
    "K1": "同一K0木を使用。従来の回収支持と正額追加条件を後段で判定",
    "群の意味": "float32 DI非正側はR k有効、正側はT k有効。微小値の零化で厳密DI/運用roleとの一致は保証しない",
    "群の除外": "k0も四群に残し即WAITにしない。pair除外は全体で先に行い、枝内pair成立を要求しない",
    "複数技法": "固定DI根trendと対応k旗priceで有効pathは従来条件を構造的に満たす。gate自体は変更しない",
    "比較の限定": "分割順・枝別44列投影・学習容量配分の変更。k旗だけの単独効果ではない"})

# ----------------------------------------
# 数値・教師・支持・回収統計は固定61の純関数を直接再用する。
fingerprint = LEGACY.fingerprint
float32 = LEGACY.float32
money = LEGACY.money
decimal_text = LEGACY.decimal_text
barrier_projection = LEGACY.barrier_projection
recovery_statistics = LEGACY.recovery_statistics
regressor_parameters = LEGACY.regressor_parameters
numeric_match = LEGACY.numeric_match
leaf_eligibility = LEGACY.leaf_eligibility

# ----------------------------------------
def feature_metadata(feature_meta: list[dict], policy: str) -> list[dict]:
    """K0へ同じ46特徴のmetadataを接続する。

    引数: feature_meta(list[dict])は固定61と同じ46列、policy(str)はK0。
    返り値: list[dict]は旧61検査後の深い複写。K1は同じ木を使う。
    """
    if policy not in POLICIES:
        raise ValueError("学習モデル政策はK0が必要")
    return LEGACY.feature_metadata(feature_meta, "A0")

# ----------------------------------------
def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 46) -> tuple:
    """全pair・既知回収・過去境界を旧61で検査し、同じcanonicalを保持する。

    引数: rows(list[dict])は46特徴と障壁/回収教師、evaluation_start(float)は評価開始、feature_count(int)は46。
    返り値: tuple[list[dict],dict]は旧61と同じ使用行及び旧18/30/38/46指紋。
    """
    used, training = LEGACY.prepare_rows(rows, evaluation_start, feature_count)
    if training["base46_fingerprints"] != {name: training[name] for name in FINGERPRINT_FIELDS}:
        raise ValueError("継承した全46教師指紋が不一致")
    training["feature_missing_handling"] = "旧61全46特徴・同じ教師pair。追加情報・追加除外なし"
    return used, training

# ----------------------------------------
def legacy_model(model: dict) -> dict:
    """旧61の汎用JSON走査へ、政策名だけを局所射影する。

    引数: model(dict)は新K0モデル。
    返り値: dictはpolicy=A0の浅い複写。旧globalや元モデルへ代入しない。
    """
    if model.get("policy") not in POLICIES or len(model.get("feature_meta", [])) != 46:
        raise ValueError("K0モデルの政策又は46列metadataが不正")
    return {**model, "policy": "A0"}

# ----------------------------------------
def walk(model: dict, values: list) -> tuple:
    """新しい固定段を含むJSON木を、旧61のfloat32汎用走査でたどる。

    引数: model(dict)はK0保存木、values(list)は46特徴。
    返り値: tuple[int,list[dict]]は葉IDと通過path。fitを呼ばない。
    """
    return LEGACY.walk(legacy_model(model), values)

# ----------------------------------------
def predict(model: dict, vectors: dict) -> dict:
    """同じ木の障壁率最高側に、従来の支持・複数技法gateを課す。

    引数: model(dict)はK0保存木、vectors(dict)は両方向46列又は両空list。
    返り値: dictは旧61同型のscores/leafs/side/reason。未知枝/同点/最高側不適格はWAIT。
    """
    feature_metadata(model["feature_meta"], model["policy"])
    return LEGACY.predict(legacy_model(model), vectors)

# ----------------------------------------
def fit(rows: list[dict], feature_meta: list[dict], policy: str, model_id: str, evaluation_start: float) -> dict:
    """全pair検査後の方向行をDIと対応k四群へ分け、44列深さ2の回帰木を合成する。

    引数: rows(list[dict])は過去教師、feature_meta(list[dict])は46特徴、policy(str)はK0、
        model_id(str)は保存ID、evaluation_start(float)は評価開始秒。
    返り値: dictは固定三node・空群を含む全node/支持/障壁率/回収/指紋の純JSON。
        本物fitはrootだけが実行する。
    """
    if policy not in POLICIES or not isinstance(model_id, str) or not model_id:
        raise ValueError("政策又はmodel_idが不正")
    meta = feature_metadata(feature_meta, policy)
    used, training = prepare_rows(rows, evaluation_start)
    import numpy as np
    import scipy
    import sklearn
    from sklearn.tree import DecisionTreeRegressor

    if sklearn.__version__ != SKLEARN_VERSION:
        raise RuntimeError("scikit-learnは固定1.9.1が必要")
    parameters, child_parameters = regressor_parameters(4), regressor_parameters(2)
    x = np.asarray([float32(row["features"]) for row in used], dtype=np.float32)
    target = np.asarray([float(money(row["pnl5"])) for row in used], dtype=np.float64)
    fixed = [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0},
        {"id": 1, "feature": "F27", "index": 26, "threshold": 0.5},
        {"id": 2, "feature": "F21", "index": 20, "threshold": 0.5}]
    nodes = [{"id": node["id"], "feature": node["index"], "feature_id": node["feature"],
        "family": meta[node["index"]]["family"], "threshold": node["threshold"],
        "left": 1 if node["id"] == 0 else None, "right": 2 if node["id"] == 0 else None} for node in fixed]
    training["partition"], fitted = {}, []
    for d in (0, 1):
        route, flag = ("R", 26) if d == 0 else ("T", 20)
        projection = CHILD_FEATURE_INDICES[f"D{d}"]
        for k in (0, 1):
            indexes = [i for i in range(len(used)) if int(x[i, 0] > 0.0) == d and int(x[i, flag] > 0.5) == k]
            selected, offset, estimator = [used[i] for i in indexes], len(nodes), None
            if selected:
                estimator = DecisionTreeRegressor(**child_parameters)
                estimator.fit(x[indexes][:, projection], target[indexes], sample_weight=np.full(len(indexes), 0.5, dtype=np.float64))
                fitted.append((estimator, indexes, offset, projection))
            child_nodes = BASE.BASE.tree_topology(estimator, offset, [meta[index] for index in projection])
            for child in child_nodes:
                if child["feature"] >= 0:
                    child["feature"] = projection[child["feature"]]
            nodes.extend(child_nodes)
            nodes[1 + d]["left" if k == 0 else "right"] = offset
            ids = [{"session": row["session"], "slot_id": row["slot_id"], "side": row["side"]} for row in selected]
            training["partition"][f"D{d}_K{k}"] = {"d": d, "k": k, "route": route, "policy": policy,
                "excluded_feature_indices": [0, flag], "child_feature_indices": list(projection),
                "direction_rows": len(selected), "pair_unique": len({(row["session"], row["slot_id"]) for row in selected}),
                "days": len({row["session"][:10] for row in selected}), "sessions": len({row["session"] for row in selected}),
                "row_ids_sha256": fingerprint(ids), "fit_performed": estimator is not None, "root": offset,
                "node_count": len(child_nodes), "fit_parameters": deepcopy(child_parameters)}
    # ----------------------------------------
    # 固定段を含む全nodeの所属・障壁率・回収を、同じ使用方向行から再計数する。
    paths = BASE.BASE.node_paths(nodes, meta)
    model = {"policy": policy, "feature_meta": meta, "nodes": nodes}
    membership = {node["id"]: [] for node in nodes}
    for i, row in enumerate(used):
        leaf, path = walk(model, row["features"])
        for node_id in [part["node"] for part in path] + [leaf]:
            membership[node_id].append(i)
    moments = {}
    for node in nodes:
        selected = [used[i] for i in membership[node["id"]]]
        total_weight = len(selected) * 0.5
        success_weight = sum(LABELS[row["outcome"]] for row in selected) * 0.5
        score = success_weight / total_weight if total_weight else None
        path = paths[node["id"]]
        ids = [{"session": row["session"], "slot_id": row["slot_id"], "side": row["side"]} for row in selected]
        statistics = recovery_statistics(selected)
        moments[node["id"]] = statistics.pop("second_moment")
        node.update(path=path, direction_rows=len(selected), weighted_rows=total_weight,
            success_weight=success_weight, total_weight=total_weight, score=score,
            unique_slots=len({(row["session"], row["slot_id"]) for row in selected}),
            days=len({row["session"][:10] for row in selected}), sessions=len({row["session"] for row in selected}),
            methods=sorted({part["method"] for part in path}), families=sorted({part["family"] for part in path}),
            training_ids_sha256=fingerprint(ids), barrier_gini=2 * score * (1 - score) if score is not None else None,
            impurity_kind="squared_error", data_absent=not selected, **statistics)
        eligibility = leaf_eligibility(node, path)
        node.update(leaf_support=eligibility["leaf_support"], method_support=eligibility["method_support"])
    # ----------------------------------------
    # 元回帰器の全node所属・値・MSE・全予測と、global ID/特徴indexの合成を照合する。
    for estimator, indexes, offset, projection in fitted:
        projected, tree = x[indexes][:, projection], estimator.tree_
        visits = estimator.decision_path(projected)
        for local in range(tree.node_count):
            expected = [indexes[i] for i in visits[:, local].nonzero()[0].tolist()]
            node = nodes[offset + local]
            value, impurity = float(tree.value[local, 0, 0]), float(tree.impurity[local])
            if (membership[node["id"]] != expected or node["direction_rows"] != int(tree.n_node_samples[local])
                    or node["total_weight"] != float(tree.weighted_n_node_samples[local])):
                raise ValueError("合成回帰木の所属/件数/重みが不一致")
            if (not numeric_match(value, node["recovery"]["pnl5"]["mean"], "mean")
                    or not numeric_match(impurity, float(Decimal(node["recovery_mse_decimal"])), "mse", moments[node["id"]])):
                raise ValueError("合成回帰木の平均/MSEがDecimal算術と不一致")
            node.update(regression_value=value, impurity=impurity)
        leaves, predictions = estimator.apply(projected), estimator.predict(projected)
        for local_row, index in enumerate(indexes):
            leaf, _ = walk(model, used[index]["features"])
            if leaf != int(leaves[local_row]) + offset or nodes[leaf]["regression_value"] != float(predictions[local_row]):
                raise ValueError("合成JSONと元回帰器の所属/予測が不一致")
    structure = {"kind": "fixed_direction_confirmation", "fixed_nodes": fixed, "child_depth": 2,
        "child_features": 44, "child_feature_indices": deepcopy(CHILD_FEATURE_INDICES),
        "excluded_feature_indices": {"D0": [0, 26], "D1": [0, 20]}, "feature_count": 46,
        "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"}
    sources = [SHARED, BASE.SHARED, HERE.parent / "回収目的分岐/学習.py",
        HERE.parent / "波の区間分離/学習.py", LEGACY_PATH]
    model.update(schema_version=1, model_id=model_id, feature_meta_sha256=fingerprint(meta), parameters=parameters,
        subtree_parameters=child_parameters, structure=structure, rules=deepcopy(RULES),
        versions={"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        shared_source_sha256={path.relative_to(HERE.parents[1]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        training=training, nodes=nodes,
        interpretation="旧61と全46特徴・教師は同じ。float32 DI非正側R/正側Tの現在k有効で分け、k0も残す。厳密DI0WAITは後段維持。固定trend+priceで従来技法gateを構造的に満たすがgateは同じ。子はpnl5回帰、方向順位は障壁率。分割順/枝別投影/容量配分の比較で単独効果ではない")
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
