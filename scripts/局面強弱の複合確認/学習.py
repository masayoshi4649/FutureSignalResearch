"""旧46特徴と同じ回収教師へ、方向不変なADX/BB値と有効maskを追加する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
import struct
from pathlib import Path
import platform
import sys


HERE = Path(__file__).resolve().parent
LEGACY_PATH = HERE.parent / "方向と再開確認/学習.py"
SPEC = importlib.util.spec_from_file_location("局面強弱63が固定参照する62学習", LEGACY_PATH)
LEGACY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LEGACY
SPEC.loader.exec_module(LEGACY)
BASE = LEGACY.BASE
SHARED = HERE.parent / "方向局面分岐/学習.py"
POLICIES, FEATURE_COUNTS = {"J0": 4}, {"J0": 54}
CHILD_FEATURE_INDICES = {"D0": [index for index in range(54) if index not in (0, 26)],
    "D1": [index for index in range(54) if index not in (0, 20)]}
SIDES, LABELS, SKLEARN_VERSION = LEGACY.SIDES, LEGACY.LABELS, LEGACY.SKLEARN_VERSION
MONEY_FIELDS, DECIMAL_PRECISION = LEGACY.MONEY_FIELDS, LEGACY.DECIMAL_PRECISION
NUMERIC_TOLERANCE = deepcopy(LEGACY.NUMERIC_TOLERANCE)
FINGERPRINT_FIELDS = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256",
    "period_sha256", "used_barrier_rows_sha256")
RULES = deepcopy(LEGACY.RULES)
RULES.pop("K0固定段")
RULES.pop("K1")
RULES.update({"政策深さ": POLICIES, "政策特徴数": FEATURE_COUNTS,
    "J0固定段": {"根": {"feature": "F01", "index": 0, "threshold": 0.0},
        "第二段": {"D0": {"feature": "F27", "index": 26, "threshold": 0.5, "route": "R"},
            "D1": {"feature": "F21", "index": 20, "threshold": 0.5, "route": "T"}},
        "群": ["D0_K0", "D0_K1", "D1_K0", "D1_K1"], "子深さ": 2,
        "子特徴数": 52, "子特徴列index": CHILD_FEATURE_INDICES, "MSE最適固定段ではない": True},
    "J1": "同一J0木を使用。従来の回収支持と正額追加条件を後段で判定",
    "群の意味": "固定62と同じfloat32 DI非正側R k/正側T k。追加ADX/BBとmaskは両方向へ同値",
    "群の除外": "k0も四群に残し即WAITにしない。pair除外は全体で先に行い、枝内pair成立を要求しない",
    "複数技法": "固定DI根trendと対応k旗priceで有効pathは従来条件を構造的に満たす。gate自体は変更しない",
    "追加指標": "ADX現/現前差・絶対BB幅/同差を現在ATR3で正規化。未知は0＋有効mask、旧readyを変えない",
    "比較の限定": "同じ固定根/教師への8列追加。準備不足も既知maskで入力し追加除外しない"})

# ----------------------------------------
# 数値・教師・支持・回収統計は固定61の純関数を直接再用する。
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
    """旧46列とADX/BB・有効maskの8列を検査する。

    引数: feature_meta(list[dict])はF01..54、policy(str)はJ0。
    返り値: list[dict]は深い複写。J1は同じ木を使用する。
    """
    if policy not in POLICIES or not isinstance(feature_meta, list) or len(feature_meta) != 54:
        raise ValueError("J0の54特徴が必要")
    LEGACY.feature_metadata(feature_meta[:46], "K0")
    for index, meta in enumerate(feature_meta[46:], 46):
        method, family = ("I08", "trend") if index in (46, 47, 50, 51) else ("I05", "vol")
        if (meta.get("id") != f"F{index + 1:02d}" or meta.get("method") != method or meta.get("family") != family
                or meta.get("scale") != "m15" or not isinstance(meta.get("name"), str) or not meta["name"]):
            raise ValueError("追加ADX/BB/maskのmetadataが不一致")
    return deepcopy(feature_meta)


# ----------------------------------------
def float32(values: list, feature_count: int = 54) -> list[float]:
    """旧46列と追加値/maskの整合を検査してfloat32へ写す。

    引数: values(list)は54特徴、feature_count(int)は54。
    返り値: list[float]は有限の学習/JSON走査用値。未知0を追加除外しない。
    """
    if feature_count != 54 or not isinstance(values, list) or len(values) != 54:
        raise ValueError("54特徴が必要")
    result = LEGACY.float32(values[:46], 46)
    for value in values[46:]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("追加値/maskは有限実数が必要")
        try:
            rounded = struct.unpack("f", struct.pack("f", value))[0]
        except (OverflowError, struct.error) as exc:
            raise ValueError("追加値のfloat32範囲外") from exc
        if not math.isfinite(rounded):
            raise ValueError("追加値のfloat32範囲外")
        result.append(rounded)
    if not 0 <= values[46] <= 1 or not -1 <= values[47] <= 1 or values[48] < 0:
        raise ValueError("ADX水準/差又はBB絶対幅の領域が不正")
    for index in range(4):
        mask = values[50 + index]
        if mask not in (0, 1) or mask == 0 and values[46 + index] != 0:
            raise ValueError("有効maskと未知0が不整合")
    if values[51] > values[50] or values[53] > values[52]:
        raise ValueError("現前差有効には現在有効が必要")
    return result


# ----------------------------------------
def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 54) -> tuple:
    """旧46射影で全pairを確定して同じ使用集合を54canonicalへ写す。

    引数: rows(list[dict])は54特徴と障壁/回収、evaluation_start(float)は評価開始、feature_count(int)は54。
    返り値: tuple[list[dict],dict]は54使用行と旧18/30/38/46の六指紋。
    """
    if feature_count != 54:
        raise ValueError("54特徴が必要")
    projected = []
    for row in rows:
        float32(row["features"])
        projected.append({**row, "features": row["features"][:46]})
    old_used, training = LEGACY.prepare_rows(projected, evaluation_start, 46)
    base46 = {name: training[name] for name in FINGERPRINT_FIELDS}
    if training["base46_fingerprints"] != base46:
        raise ValueError("旧62の全46指紋継承が不一致")
    identities = {(row["session"], row["slot_id"], row["side"]) for row in old_used}
    canonical = []
    for original in rows:
        row = barrier_projection(original)
        row.update({key: None if original.get(key) is None else decimal_text(money(original[key])) for key in MONEY_FIELDS})
        row["recovery_end_time"] = original.get("recovery_end_time")
        canonical.append(row)
    used = [row for row in canonical if (row["session"], row["slot_id"], row["side"]) in identities]
    training["base46_fingerprints"] = base46
    training.update(input_rows_sha256=fingerprint(canonical), used_rows_sha256=fingerprint(used),
        used_barrier_rows_sha256=fingerprint([barrier_projection(row) for row in used]),
        feature_missing_handling="旧62全46準備の同じ教師pair。追加8指標は未知0＋有効mask、追加除外なし")
    return used, training


# ----------------------------------------
def walk(model: dict, values: list) -> tuple:
    """新54列をfloat32化し、保存JSON木を左<=/右>へたどる。

    引数: model(dict)はJ0木、values(list)は54特徴。
    返り値: tuple[int,list[dict]]は葉IDと全path。旧globalは変更しない。
    """
    if model.get("policy") not in POLICIES or len(model.get("feature_meta", [])) != 54:
        raise ValueError("J0木と54列metadataが必要")
    values, node_id, path, visited = float32(values), 0, [], set()
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
        if type(feature) is not int or not 0 <= feature < 54 or isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
            raise ValueError("JSON木の分岐値不正")
        left, meta = values[feature] <= threshold, model["feature_meta"][feature]
        path.append({"node": node_id, "feature": feature, "feature_id": meta["id"], "method": meta["method"],
            "family": meta["family"], "threshold": threshold, "comparison": "<=" if left else ">", "branch": "left" if left else "right"})
        node_id = node["left"] if left else node["right"]


# ----------------------------------------
def predict(model: dict, vectors: dict) -> dict:
    """同じ54列JSON木で障壁score最高側だけへ従来資格を課す。

    引数: model(dict)はJ0保存木、vectors(dict)は両方向54列又は両空list。
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
    """全pair検査後の方向行をDIと対応k四群へ分け、52列深さ2の回帰木を合成する。

    引数: rows(list[dict])は過去教師、feature_meta(list[dict])は54特徴、policy(str)はJ0、
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
        "child_features": 52, "child_feature_indices": deepcopy(CHILD_FEATURE_INDICES),
        "excluded_feature_indices": {"D0": [0, 26], "D1": [0, 20]}, "feature_count": 54,
        "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"}
    sources = [SHARED, BASE.SHARED, HERE.parent / "回収目的分岐/学習.py",
        HERE.parent / "波の区間分離/学習.py", HERE.parent / "現行経路の状態分岐/学習.py", LEGACY_PATH]
    model.update(schema_version=1, model_id=model_id, feature_meta_sha256=fingerprint(meta), parameters=parameters,
        subtree_parameters=child_parameters, structure=structure, rules=deepcopy(RULES),
        versions={"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        shared_source_sha256={path.relative_to(HERE.parents[1]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        training=training, nodes=nodes,
        interpretation="固定62と同じ46prefix/教師/DI→対応kを保持し、ADX/BBの値4＋有効mask4を追加。未知0と既知0を分け追加除外なし。子52列はpnl5回帰、方向順位は障壁率。同一価格由来の特徴を独立票又は収益原因にしない")
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
