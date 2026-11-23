"""同じ60特徴と回収教師を、DIと対応経路の現在episode有効から分岐する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys


HERE = Path(__file__).resolve().parent
LEGACY_PATH = HERE.parent / "量と価格進行/学習.py"
SPEC = importlib.util.spec_from_file_location("現在状態と量価格65が固定参照する64学習", LEGACY_PATH)
LEGACY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LEGACY
SPEC.loader.exec_module(LEGACY)
BASE = LEGACY.BASE
SHARED = HERE.parent / "方向局面分岐/学習.py"
POLICIES, FEATURE_COUNTS = {"U0": 4}, {"U0": 60}
CHILD_FEATURE_INDICES = {"D0": [index for index in range(60) if index not in (0, 25)],
    "D1": [index for index in range(60) if index not in (0, 19)]}
SIDES, LABELS, SKLEARN_VERSION = LEGACY.SIDES, LEGACY.LABELS, LEGACY.SKLEARN_VERSION
MONEY_FIELDS, DECIMAL_PRECISION = LEGACY.MONEY_FIELDS, LEGACY.DECIMAL_PRECISION
NUMERIC_TOLERANCE = deepcopy(LEGACY.NUMERIC_TOLERANCE)
FINGERPRINT_FIELDS = LEGACY.FINGERPRINT_FIELDS
RULES = deepcopy(LEGACY.RULES)
RULES.pop("固定DI根")
RULES.pop("B1")
RULES.pop("Q1")
RULES.update({"政策深さ": POLICIES, "政策特徴数": FEATURE_COUNTS,
    "U0固定段": {"根": {"feature": "F01", "index": 0, "threshold": 0.0},
        "第二段": {"D0": {"feature": "F26", "index": 25, "threshold": 0.5, "route": "R"},
            "D1": {"feature": "F20", "index": 19, "threshold": 0.5, "route": "T"}},
        "群": ["D0_V0", "D0_V1", "D1_V0", "D1_V1"], "子深さ": 2,
        "子特徴数": 58, "子特徴列index": CHILD_FEATURE_INDICES, "MSE最適固定段ではない": True},
    "U1": "同一U0木を使用。従来の回収支持とstrict正額追加条件を後段で判定",
    "群の意味": "float32 DI非正側はR/正側はTの現在episode有効。Rも出生bから真で、f/r/k成立とは別",
    "群の除外": "V0も四群に残し即WAITにしない。全pair除外は分割前に行い、枝内pair成立を要求しない",
    "複数技法": "固定DI根trendと対応episode旗priceが有効pathへ入る。従来gateは変更せず構造的に充足する",
    "比較の限定": "同60情報/教師。固定順・枝別58列投影・深さ3から2への容量配分と技法資格自動充足を含み、flagや量の単独効果ではない"})

# ----------------------------------------
# 数値・教師・支持・回収統計は固定64の純関数を直接再用する。
fingerprint = LEGACY.fingerprint
money = LEGACY.money
decimal_text = LEGACY.decimal_text
barrier_projection = LEGACY.barrier_projection
recovery_statistics = LEGACY.recovery_statistics
regressor_parameters = LEGACY.regressor_parameters
numeric_match = LEGACY.numeric_match
leaf_eligibility = LEGACY.leaf_eligibility

# ----------------------------------------
def feature_metadata(feature_meta: list[dict], policy: str) -> list[dict]:
    """U0へ固定64Q0と同じ60特徴metadataを接続する。

    引数: feature_meta(list[dict])は60列、policy(str)はU0。
    返り値: list[dict]は旧64検査後の深い写し。U1の別fitは許可しない。
    """
    if policy not in POLICIES:
        raise ValueError("学習モデル政策はU0が必要")
    return LEGACY.feature_metadata(feature_meta, "Q0")


# ----------------------------------------
def float32(values: list, feature_count: int = 60) -> list[float]:
    """固定64の数値・共同mask検査を、同じ60列へ適用する。

    引数: values(list)は60特徴、feature_count(int)は60のみ。
    返り値: list[float]は旧64と同じfloat32値。列を追加・補間しない。
    """
    if feature_count != 60:
        raise ValueError("U0は60特徴が必要")
    return LEGACY.float32(values, feature_count)


# ----------------------------------------
def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 60) -> tuple:
    """旧64の全pair検査を先に行い、同じ60canonical六指紋を保持する。

    引数: rows(list[dict])は60特徴と障壁/回収教師、evaluation_start(float)は評価開始、feature_count(int)は60。
    返り値: tuple[list[dict],dict]は同じ使用行とbase18/30/38/46/54/60指紋。
    """
    if feature_count != 60:
        raise ValueError("U0は60特徴が必要")
    used, training = LEGACY.prepare_rows(rows, evaluation_start, feature_count)
    training["base60_fingerprints"] = {name: training[name] for name in FINGERPRINT_FIELDS}
    training["feature_missing_handling"] = "旧64全60特徴・同じ教師pair。追加情報・追加除外なし"
    return used, training


# ----------------------------------------
def legacy_model(model: dict) -> dict:
    """旧64の汎用JSON走査へ、政策名だけを局所射影する。

    引数: model(dict)は新U0モデル。
    返り値: dictはpolicy=Q0の浅い複写。旧globalや元モデルへ代入しない。
    """
    if model.get("policy") not in POLICIES or len(model.get("feature_meta", [])) != 60:
        raise ValueError("U0モデルの政策又は60列metadataが不正")
    return {**model, "policy": "Q0"}

# ----------------------------------------
def walk(model: dict, values: list) -> tuple:
    """新しい固定段を含むJSON木を、旧64のfloat32汎用走査でたどる。

    引数: model(dict)はU0保存木、values(list)は60特徴。
    返り値: tuple[int,list[dict]]は葉IDと通過path。fitを呼ばない。
    """
    return LEGACY.walk(legacy_model(model), values)

# ----------------------------------------
def predict(model: dict, vectors: dict) -> dict:
    """同じ木の障壁率最高側に、従来の支持・複数技法gateを課す。

    引数: model(dict)はU0保存木、vectors(dict)は両方向60列又は両空list。
    返り値: dictは旧64同型のscores/leafs/side/reason。未知枝/同点/最高側不適格はWAIT。
    """
    feature_metadata(model["feature_meta"], model["policy"])
    return LEGACY.predict(legacy_model(model), vectors)

# ----------------------------------------
def fit(rows: list[dict], feature_meta: list[dict], policy: str, model_id: str, evaluation_start: float) -> dict:
    """全pair検査後の方向行をDIと対応episode有効四群へ分け、58列深さ2の回帰木を合成する。

    引数: rows(list[dict])は過去教師、feature_meta(list[dict])は60特徴、policy(str)はU0、
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
        {"id": 1, "feature": "F26", "index": 25, "threshold": 0.5},
        {"id": 2, "feature": "F20", "index": 19, "threshold": 0.5}]
    nodes = [{"id": node["id"], "feature": node["index"], "feature_id": node["feature"],
        "family": meta[node["index"]]["family"], "threshold": node["threshold"],
        "left": 1 if node["id"] == 0 else None, "right": 2 if node["id"] == 0 else None} for node in fixed]
    training["partition"], fitted = {}, []
    for d in (0, 1):
        route, flag = ("R", 25) if d == 0 else ("T", 19)
        projection = CHILD_FEATURE_INDICES[f"D{d}"]
        for v in (0, 1):
            indexes = [i for i in range(len(used)) if int(x[i, 0] > 0.0) == d and int(x[i, flag] > 0.5) == v]
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
            nodes[1 + d]["left" if v == 0 else "right"] = offset
            ids = [{"session": row["session"], "slot_id": row["slot_id"], "side": row["side"]} for row in selected]
            training["partition"][f"D{d}_V{v}"] = {"d": d, "v": v, "route": route, "policy": policy,
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
    structure = {"kind": "fixed_direction_current_episode", "fixed_nodes": fixed, "child_depth": 2,
        "child_features": 58, "child_feature_indices": deepcopy(CHILD_FEATURE_INDICES),
        "excluded_feature_indices": {"D0": [0, 25], "D1": [0, 19]}, "feature_count": 60,
        "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"}
    sources = [SHARED, BASE.SHARED, HERE.parent / "回収目的分岐/学習.py",
        HERE.parent / "波の区間分離/学習.py", HERE.parent / "現行経路の状態分岐/学習.py",
        HERE.parent / "方向と再開確認/学習.py", HERE.parent / "局面強弱の複合確認/学習.py", LEGACY_PATH]
    model.update(schema_version=1, model_id=model_id, feature_meta_sha256=fingerprint(meta), parameters=parameters,
        subtree_parameters=child_parameters, structure=structure, rules=deepcopy(RULES),
        versions={"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        shared_source_sha256={path.relative_to(HERE.parents[1]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        training=training, nodes=nodes,
        interpretation="旧64Q0と全60特徴・教師は同じ。float32 DI非正側R/正側Tの現在episode有効で分け、V0も残す。Rも出生bから有効でf/r/k成立とは別。厳密DI0WAITは後段維持。固定trend+priceで従来技法gateを構造的に満たすがgateは同じ。子はpnl5回帰、方向順位は障壁率。固定順/枝別58列投影/容量配分/資格自動充足の構造比較で、flag又は量の単独効果ではない")
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
