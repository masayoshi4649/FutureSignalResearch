"""同じ54教師とDI固定根から、数量と価格進行を別列で回収学習する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import struct
import sys


HERE = Path(__file__).resolve().parent
LEGACY_PATH = HERE.parent / "局面強弱の複合確認/学習.py"
SPEC = importlib.util.spec_from_file_location("量と価格進行64が固定参照する63学習", LEGACY_PATH)
LEGACY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LEGACY
SPEC.loader.exec_module(LEGACY)
BASE = LEGACY.BASE
SHARED = HERE.parent / "方向局面分岐/学習.py"
POLICIES, FEATURE_COUNTS = {"B0": 4, "Q0": 4}, {"B0": 54, "Q0": 60}
SIDES, LABELS, SKLEARN_VERSION = LEGACY.SIDES, LEGACY.LABELS, LEGACY.SKLEARN_VERSION
MONEY_FIELDS, DECIMAL_PRECISION = LEGACY.MONEY_FIELDS, LEGACY.DECIMAL_PRECISION
NUMERIC_TOLERANCE = deepcopy(LEGACY.NUMERIC_TOLERANCE)
FINGERPRINT_FIELDS = LEGACY.FINGERPRINT_FIELDS
CHILD_FEATURE_INDICES = {policy: list(range(1, count)) for policy, count in FEATURE_COUNTS.items()}
RULES = deepcopy(LEGACY.RULES)
RULES.pop("J0固定段")
RULES.pop("J1")
RULES.update({"政策深さ": POLICIES, "政策特徴数": FEATURE_COUNTS,
    "固定DI根": {"根": {"feature": "F01", "index": 0, "threshold": 0.0},
        "群": ["D0", "D1"], "子深さ": 3, "子特徴数": {"B0": 53, "Q0": 59},
        "子特徴列index": CHILD_FEATURE_INDICES, "除外index": [0], "MSE最適固定段ではない": True},
    "B1": "同一B0木に従来の回収支持とstrict正額を後段追加",
    "Q1": "同一Q0木に従来の回収支持とstrict正額を後段追加",
    "群の意味": "float32 DI非正側D0と正側D1。k旗は子へ戻し、厳密DI0WAITは後段保持",
    "群の除外": "両方向群を残す。全pair除外は先に行い、枝内pair成立は要求しない",
    "複数技法": "固定根はtrendだけ。実pathのfamily2以上かつtrend又はoscを従来通り要求",
    "追加指標": "選択経路のb/rそれぞれのTOD RVOLと実方向終値差/現在ATRを別列、共同有効mask0なら両0",
    "mask限定": "新量maskもV01/volume。同じ資格関数だが新6列でmaskだけを使うpathは診断で別記",
    "比較の限定": "B0は旧54をDI一段根で再fit。Q0は同じ根/教師へ6列追加。量単独又は心理因果の証明ではない"})

# ----------------------------------------
# 固定63の純算術だけを直接再用する。
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
    """旧54と、数量/価格進行/共同maskの追加6列を政策別に検査する。

    引数: feature_meta(list[dict])は54又は60列、policy(str)はB0/Q0。
    返り値: list[dict]は深い複写。B1/Q1の別fitは許可しない。
    """
    count = FEATURE_COUNTS.get(policy)
    if count is None or not isinstance(feature_meta, list) or len(feature_meta) != count:
        raise ValueError("B0は54、Q0は60特徴が必要")
    LEGACY.feature_metadata(feature_meta[:54], "J0")
    for index, meta in enumerate(feature_meta[54:], 54):
        method, family = ("P05", "price") if index in (55, 57) else ("V01", "volume")
        if (meta.get("id") != f"F{index + 1:02d}" or meta.get("method") != method or meta.get("family") != family
                or meta.get("scale") != "m03" or not isinstance(meta.get("name"), str) or not meta["name"]):
            raise ValueError("追加数量/価格進行/maskのmetadataが不一致")
    return deepcopy(feature_meta)


# ----------------------------------------
def float32(values: list, feature_count: int = 60) -> list[float]:
    """旧54値と新6列のjoint maskを検査してfloat32へ写す。

    引数: values(list)は54又は60値、feature_count(int)は54/60、既定60。
    返り値: list[float]は有限値。B0ではfeature_count=54を明示する。
    """
    if feature_count not in (54, 60) or not isinstance(values, list) or len(values) != feature_count:
        raise ValueError("54又は60特徴が必要")
    result = LEGACY.float32(values[:54], 54)
    if feature_count == 54:
        return result
    for value in values[54:]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("新6列は有限実数が必要")
        try:
            rounded = struct.unpack("f", struct.pack("f", value))[0]
        except (OverflowError, struct.error) as exc:
            raise ValueError("新6列のfloat32範囲外") from exc
        if not math.isfinite(rounded):
            raise ValueError("新6列のfloat32範囲外")
        result.append(rounded)
    for quantity_index, progress_index, mask_index in ((54, 55, 58), (56, 57, 59)):
        if values[quantity_index] < 0 or values[mask_index] not in (0, 1):
            raise ValueError("TOD RVOLは非負、共同maskは0/1が必要")
        if values[mask_index] == 0 and (values[quantity_index] != 0 or values[progress_index] != 0):
            raise ValueError("共同mask0なら量と価格進行の両方が定義0であることが必要")
    return result


# ----------------------------------------
def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 60) -> tuple:
    """旧54射影でpairを確定し、同じ使用IDを政策の次元へ写す。

    引数: rows(list[dict])は54/60教師、evaluation_start(float)は評価開始、feature_count(int)は54/60、既定60。
    返り値: tuple[list[dict],dict]は使用canonicalと旧18/30/38/46/54指紋。
    """
    if feature_count not in (54, 60):
        raise ValueError("54又は60特徴が必要")
    projected = []
    for row in rows:
        float32(row["features"], feature_count)
        projected.append({**row, "features": row["features"][:54]})
    old_used, training = LEGACY.prepare_rows(projected, evaluation_start, 54)
    training["base54_fingerprints"] = {name: training[name] for name in FINGERPRINT_FIELDS}
    if feature_count == 54:
        training["feature_missing_handling"] = "旧63全54準備の同じ教師pair。基礎54の再fit、追加情報・追加除外なし"
        return old_used, training
    identities = {(row["session"], row["slot_id"], row["side"]) for row in old_used}
    canonical = []
    for original in rows:
        row = barrier_projection(original)
        row.update({key: None if original.get(key) is None else decimal_text(money(original[key])) for key in MONEY_FIELDS})
        row["recovery_end_time"] = original.get("recovery_end_time")
        canonical.append(row)
    used = [row for row in canonical if (row["session"], row["slot_id"], row["side"]) in identities]
    training.update(input_rows_sha256=fingerprint(canonical), used_rows_sha256=fingerprint(used),
        used_barrier_rows_sha256=fingerprint([barrier_projection(row) for row in used]),
        feature_missing_handling="旧63全54準備の同じ教師pair。追加6列は未知0＋共同有効mask、追加除外なし")
    return used, training


# ----------------------------------------
def walk(model: dict, values: list) -> tuple:
    """政策別の54/60列をfloat32化し、保存JSON木を左<=/右>へたどる。

    引数: model(dict)はB0/Q0木、values(list)は政策の特徴。
    返り値: tuple[int,list[dict]]は葉IDと全path。旧globalは変更しない。
    """
    count = FEATURE_COUNTS.get(model.get("policy"))
    if count is None or len(model.get("feature_meta", [])) != count:
        raise ValueError("政策と54/60列metadataが不一致")
    values, node_id, path, visited = float32(values, count), 0, [], set()
    nodes = model["nodes"]
    while True:
        if type(node_id) is not int or not 0 <= node_id < len(nodes) or node_id in visited:
            raise ValueError("JSON木の循環又は子ID不正")
        visited.add(node_id)
        node = nodes[node_id]
        if node["id"] != node_id:
            raise ValueError("JSON木のnode ID不一致")
        if node["left"] == -1 and node["right"] == -1:
            return node_id, path
        feature, threshold = node["feature"], node["threshold"]
        if type(feature) is not int or not 0 <= feature < count or isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
            raise ValueError("JSON木の分岐値不正")
        left, meta = values[feature] <= threshold, model["feature_meta"][feature]
        path.append({"node": node_id, "feature": feature, "feature_id": meta["id"], "method": meta["method"],
            "family": meta["family"], "threshold": threshold, "comparison": "<=" if left else ">", "branch": "left" if left else "right"})
        node_id = node["left"] if left else node["right"]


# ----------------------------------------
def predict(model: dict, vectors: dict) -> dict:
    """政策別の同じJSON木で障壁score最高側だけへ従来資格を課す。

    引数: model(dict)はB0/Q0保存木、vectors(dict)は両方向の政策列数又は両空list。
    返り値: dictはscores/leafs/side/reason/eligibility。未知や低い側を救済しない。
    """
    if model.get("schema_version") != 1 or not isinstance(model.get("nodes"), list) or not model["nodes"]:
        raise ValueError("保存モデルschemaが不正")
    feature_metadata(model["feature_meta"], model["policy"])
    if not isinstance(vectors, dict) or set(vectors) != set(SIDES):
        raise ValueError("両方向vectorsが必要")
    if vectors["1"] == [] and vectors["-1"] == []:
        return {"scores": {side: None for side in SIDES}, "leafs": {side: None for side in SIDES}, "side": 0,
            "winner_side": 0, "reason": "特徴未準備WAIT", "eligibility": {side: None for side in SIDES}}
    scores, leafs, eligibility = {}, {}, {}
    for side in SIDES:
        leaf, path = walk(model, vectors[side])
        node = model["nodes"][leaf]
        if node["path"] != path:
            raise ValueError("保存葉と実pathが不一致")
        absent = node.get("data_absent") is True
        if absent and (node["score"] is not None or node["direction_rows"] != 0):
            raise ValueError("未学習葉はscore未知/方向行0が必要")
        if not absent and (node["score"] is None or not isinstance(node["score"], (int, float))
                or isinstance(node["score"], bool) or not math.isfinite(node["score"]) or not 0 <= node["score"] <= 1):
            raise ValueError("学習済み葉scoreが不正")
        scores[side], leafs[side] = node["score"], leaf
        eligibility[side] = None if absent else leaf_eligibility(node, path)
    result = {"scores": scores, "leafs": leafs, "side": 0, "winner_side": 0, "reason": "同点WAIT", "eligibility": eligibility}
    if any(scores[side] is None for side in SIDES):
        result["reason"] = "未学習枝WAIT"
        return result
    if scores["1"] == scores["-1"]:
        return result
    winner = "1" if scores["1"] > scores["-1"] else "-1"
    result["winner_side"] = int(winner)
    failure = [text for key, text in (("score", "最高側score下限未達"), ("leaf_support", "最高側葉支持不足"),
        ("method_support", "最高側複数技法不足")) if not eligibility[winner][key]]
    result.update(side=0 if failure else int(winner), reason="/".join(failure) if failure else "採用")
    return result


# ----------------------------------------
def fit(rows: list[dict], feature_meta: list[dict], policy: str, model_id: str, evaluation_start: float) -> dict:
    """DIだけを固定根にして、両方向群の深さ3回帰木を合成する。

    引数: rows(list[dict])は過去教師、feature_meta(list[dict])は54/60列、policy(str)はB0/Q0、
        model_id(str)は保存ID、evaluation_start(float)は評価開始秒。
    返り値: dictは固定1node・空群を含む全node/支持/障壁率/回収/指紋の純JSON。
    """
    if policy not in POLICIES or not isinstance(model_id, str) or not model_id:
        raise ValueError("政策又はmodel_idが不正")
    meta = feature_metadata(feature_meta, policy)
    count, projection = FEATURE_COUNTS[policy], CHILD_FEATURE_INDICES[policy]
    used, training = prepare_rows(rows, evaluation_start, count)
    import numpy as np
    import scipy
    import sklearn
    from sklearn.tree import DecisionTreeRegressor

    if sklearn.__version__ != SKLEARN_VERSION:
        raise RuntimeError("scikit-learnは固定1.9.1が必要")
    parameters, child_parameters = regressor_parameters(4), regressor_parameters(3)
    x = np.asarray([float32(row["features"], count) for row in used], dtype=np.float32)
    target = np.asarray([float(money(row["pnl5"])) for row in used], dtype=np.float64)
    fixed = [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0}]
    nodes = [{"id": 0, "feature": 0, "feature_id": "F01", "family": meta[0]["family"],
        "threshold": 0.0, "left": None, "right": None}]
    training["partition"], fitted = {}, []
    for d in (0, 1):
        indexes = [i for i in range(len(used)) if int(x[i, 0] > 0.0) == d]
        selected, offset, estimator = [used[i] for i in indexes], len(nodes), None
        if selected:
            estimator = DecisionTreeRegressor(**child_parameters)
            estimator.fit(x[indexes][:, projection], target[indexes], sample_weight=np.full(len(indexes), .5, dtype=np.float64))
            fitted.append((estimator, indexes, offset, projection))
        child_nodes = BASE.BASE.tree_topology(estimator, offset, [meta[index] for index in projection])
        for child in child_nodes:
            if child["feature"] >= 0:
                child["feature"] = projection[child["feature"]]
        nodes.extend(child_nodes)
        nodes[0]["left" if d == 0 else "right"] = offset
        ids = [{"session": row["session"], "slot_id": row["slot_id"], "side": row["side"]} for row in selected]
        training["partition"][f"D{d}"] = {"d": d, "route": "R" if d == 0 else "T", "policy": policy,
            "excluded_feature_indices": [0], "child_feature_indices": list(projection),
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
    structure = {"kind": "fixed_direction_only", "fixed_nodes": fixed, "child_depth": 3,
        "child_features": count - 1, "child_feature_indices": list(projection), "excluded_feature_indices": [0],
        "feature_count": count, "max_depth": 4, "fixed_mse_optimized": False,
        "child_estimator": "DecisionTreeRegressor", "target": "pnl5"}
    sources = [SHARED, BASE.SHARED, HERE.parent / "回収目的分岐/学習.py", HERE.parent / "波の区間分離/学習.py",
        HERE.parent / "現行経路の状態分岐/学習.py", HERE.parent / "方向と再開確認/学習.py", LEGACY_PATH]
    model.update(schema_version=1, model_id=model_id, feature_meta_sha256=fingerprint(meta), parameters=parameters,
        subtree_parameters=child_parameters, structure=structure, rules=deepcopy(RULES),
        versions={"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        shared_source_sha256={path.relative_to(HERE.parents[1]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        training=training, nodes=nodes,
        interpretation="DI一段根で旧54を再fitするB0と、同教師へ量/価格進行/共同mask6列を足すQ0。子はpnl5回帰、方向順位は障壁率。kは子へ戻す。固定trendだけでは複数技法を自動充足せず、量maskのみ経由を診断で別記。旧準備・教師除外・出口を変更しない")
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
