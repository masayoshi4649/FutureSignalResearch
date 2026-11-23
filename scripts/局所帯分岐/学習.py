"""局所帯17列の自由木と、Zで根を固定した18列の合成木を学習する。"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import platform
import struct


POLICIES = {"B0": 4, "F0": 4}
FEATURE_COUNTS = {"B0": 17, "F0": 18}
SIDES = ("1", "-1")
BASE_FAMILIES = ["trend", "osc", "osc", "vol", *(["price"] * 11)]
EXPECTED_FAMILIES = {17: BASE_FAMILIES + ["price"] * 2, 18: BASE_FAMILIES + ["price"] * 3}
LABELS = {"250": 1, "125": 0, "期限": 0}
OUTCOMES = set(LABELS) | {"未約定", "不足"}
SKLEARN_VERSION = "1.9.1"
RULES = {"政策深さ": POLICIES, "政策特徴数": FEATURE_COUNTS, "random_state": 51, "criterion": "gini", "splitter": "best",
    "min_samples_leaf": 60, "min_samples_split": 2, "class_weight": None, "ccp_alpha": 0.0,
    "max_features": None, "方向行重み": 0.5, "score下限": {"分子": 1, "分母": 3, "等号可": True},
    "葉支持": {"unique枠": 60, "日": 6, "場": 10}, "path異種family最低": 2,
    "path必須family候補": ["trend", "osc"], "方向差": "strict", "予測入力型": "float32",
    "F0強制root": {"feature": "F18", "index": 17, "threshold": 0.5, "child_depth": 3, "child_features": 17,
        "Z定義域": [0, 1], "gini最適分割ではない": True}, "未知leaf": "両方向のどちらか到達なら未学習枝WAIT。scoreを0補完しない"}


def fingerprint(value: object) -> str:
    """配列順と値を保持したJSON指紋を得る。

    引数: value(object)は有限JSONで表せる値。
    返り値: strはキーを整列したUTF-8内容のSHA256。
    """
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def finite(value: object) -> bool:
    """boolと非有限値を除外する。

    引数: value(object)は検査値。
    返り値: boolは有限の実数か。
    """
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def feature_metadata(feature_meta: list[dict], policy: str) -> list[dict]:
    """政策の17/18特徴順・family契約を確認し、外部辞書を保全する。

    引数: feature_meta(list[dict])は特徴担当のid/name/method/family/scale、policy(str)はB0/F0。
    返り値: list[dict]はJSONの深い複写。不足や並び替えは拒否する。
    """
    if policy not in FEATURE_COUNTS or not isinstance(feature_meta, list) or len(feature_meta) != FEATURE_COUNTS[policy]:
        raise ValueError("特徴metadataはB0の17列又はF0の18列が必要")
    families = EXPECTED_FAMILIES[len(feature_meta)]
    for index, meta in enumerate(feature_meta):
        if not isinstance(meta, dict) or any(not isinstance(meta.get(k), str) or not meta[k] for k in ("id", "name", "method", "family", "scale")):
            raise ValueError("特徴metadataの必須5項目が不正")
        if meta["id"] != f"F{index + 1:02d}" or meta["family"] != families[index]:
            raise ValueError("特徴の順又はfamilyを変更できない")
    if policy == "F0" and feature_meta[17]["method"] != "P10":
        raise ValueError("F18強制partitionはP10/priceが必要")
    return json.loads(json.dumps(feature_meta, ensure_ascii=False, allow_nan=False))


def vector(values: list, feature_count: int) -> list[float]:
    """欠測を補完せず17/18有限値を検査し、F18を厳密な0/1へ制限する。

    引数: values(list)は方向正規化済み特徴、feature_count(int)は政策列数。
    返り値: list[float]は元の順・符号を保つ値。
    """
    if feature_count not in (17, 18) or not isinstance(values, list) or len(values) != feature_count or any(not finite(v) for v in values):
        raise ValueError("特徴は明示した17又は18個の有限値が必要。欠測補完はしない")
    if feature_count == 18 and values[17] not in (0, 1):
        raise ValueError("Zはfloat32化前から厳密な0又は1が必要")
    return [float(v) for v in values]


def float32(values: list, feature_count: int) -> list[float]:
    """scikit-learnと同じfloat32へ予測特徴を一度だけ写す。

    引数: values(list)は有限特徴、feature_count(int)は政策の17/18列数。
    返り値: list[float]はfloat32を正確に表せるPython float。桁あふれを拒否する。
    """
    result = []
    for value in vector(values, feature_count):
        try:
            converted = struct.unpack("<f", struct.pack("<f", value))[0]
        except (OverflowError, struct.error) as exc:
            raise ValueError("特徴がfloat32範囲を超えた") from exc
        if not math.isfinite(converted):
            raise ValueError("float32化後の非有限特徴")
        result.append(converted)
    return result


def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int) -> tuple[list[dict], dict]:
    """方向ペアを検査し、未約定・不足は双方を学習から除く。

    引数: rows(list[dict])は共通準備の両方向教師、evaluation_start(float)は評価開始秒、feature_count(int)は17/18列数。
    返り値: tuple[list[dict],dict]は使用方向行と除外/時間/ID指紋。未来教師は拒否する。
    """
    if not finite(evaluation_start) or not isinstance(rows, list) or not rows:
        raise ValueError("評価開始は有限秒、学習入力は空でないlistが必要")
    required = {"slot_id", "session", "scheduled", "time", "line", "side", "features", "outcome", "filled", "end_time", "end_line"}
    pairs, canonical = {}, []
    for original in rows:
        if not isinstance(original, dict) or not required <= set(original):
            raise ValueError("学習方向行の必須項目が不足")
        row = {k: deepcopy(original[k]) for k in required}
        if any(not isinstance(row[k], str) or not row[k] for k in ("slot_id", "session")) or type(row["side"]) is not int or row["side"] not in (-1, 1):
            raise ValueError("学習ID/場/方向が不正")
        if any(not finite(row[k]) for k in ("scheduled", "time", "end_time")) or any(type(row[k]) is not int or row[k] < 0 for k in ("line", "end_line")):
            raise ValueError("学習の時計又は原行が不正")
        if row["scheduled"] > row["time"] or row["time"] > row["end_time"] or row["end_time"] >= evaluation_start:
            raise ValueError("未来教師又は逆順時計。終了秒は評価開始よりstrict前が必要")
        if row["outcome"] not in OUTCOMES or type(row["filled"]) is not bool:
            raise ValueError("教師の結果又はfilledが不正")
        row["features"] = vector(row["features"], feature_count)
        float32(row["features"], feature_count)
        if "sample_weight" in original and original["sample_weight"] != 0.5:
            raise ValueError("方向行の重みは0.5固定")
        for key in ("entry_time", "entry_line"):
            row[key] = original.get(key)
        if row["outcome"] in LABELS:
            if row["filled"] is not True or not finite(row["entry_time"]) or type(row["entry_line"]) is not int:
                raise ValueError("使用教師は仮約定の時計/原行が必要")
            if (row["entry_time"], row["entry_line"]) < (row["time"], row["line"]) or (row["end_time"], row["end_line"]) < (row["entry_time"], row["entry_line"]):
                raise ValueError("教師の仮約定/終了keyが逆順")
        elif row["outcome"] == "未約定" and row["filled"] is not False:
            raise ValueError("未約定とfilledが不整合")
        identity = row["session"], row["slot_id"]
        pair = pairs.setdefault(identity, {})
        if row["side"] in pair:
            raise ValueError("同じ枠/方向の教師が重複")
        pair[row["side"]] = row
        canonical.append(row)
    excluded, eligible = [], set()
    for identity, pair in pairs.items():
        if set(pair) != {-1, 1}:
            raise ValueError("片方向だけの学習は禁止")
        for field in ("slot_id", "session", "scheduled", "time", "line"):
            if pair[1][field] != pair[-1][field]:
                raise ValueError("両方向の同枠出典が不一致: " + field)
        if all(pair[s]["outcome"] in LABELS for s in (1, -1)):
            eligible.add(identity)
        else:
            excluded.append({"session": identity[0], "slot_id": identity[1], "reason": "未約定又は不足を含むpair全体除外",
                "outcomes": {str(s): pair[s]["outcome"] for s in (1, -1)}, "filled": {str(s): pair[s]["filled"] for s in (1, -1)}})
    used = [row for row in canonical if (row["session"], row["slot_id"]) in eligible]
    if not used:
        raise ValueError("使用できる両方向教師pairがない")
    ids = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in used]
    sessions = list(dict.fromkeys(r["session"] for r in used))
    period = {"sessions": sessions, "first_scheduled": min(r["scheduled"] for r in used),
        "last_scheduled": max(r["scheduled"] for r in used), "max_label_end_key": list(max((r["end_time"], r["end_line"]) for r in used)),
        "max_input_label_end_key": list(max((r["end_time"], r["end_line"]) for r in canonical)), "evaluation_start": float(evaluation_start), "same_second_allowed": False}
    return used, {"input_pairs": len(pairs), "used_pairs": len(eligible), "excluded_pair_count": len(excluded),
        "excluded_pairs": excluded, "excluded_outcome_counts": dict(Counter("1=" + p["outcomes"]["1"] + ";-1=" + p["outcomes"]["-1"] for p in excluded)),
        "direction_rows": len(used), "weight_per_direction": 0.5, "total_weight": len(used) * 0.5,
        "row_ids": ids, "input_rows_sha256": fingerprint(canonical), "used_rows_sha256": fingerprint(used),
        "row_ids_sha256": fingerprint(ids), "period": period, "period_sha256": fingerprint(period), "feature_missing_handling": "rootが同一局所帯readyなpairのみ入力。ここでは補完しない"}


def walk(model: dict, values: list) -> tuple[int, list[dict]]:
    """float32化した特徴でJSON木を左<=/右>へたどる。

    引数: model(dict)は保存木、values(list)は方向特徴。
    返り値: tuple[int,list[dict]]は葉IDと通過分岐。学習器やjoblibを使わない。
    """
    count = FEATURE_COUNTS.get(model.get("policy"))
    if count is None or len(model["feature_meta"]) != count:
        raise ValueError("モデル政策と特徴列数が不整合")
    values, node_id, path = float32(values, count), 0, []
    nodes = model["nodes"]
    visited = set()
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
        if type(feature) is not int or not 0 <= feature < count or not finite(threshold):
            raise ValueError("JSON木の分岐値不正")
        left = values[feature] <= threshold
        meta = model["feature_meta"][feature]
        path.append({"node": node_id, "feature": feature, "feature_id": meta["id"], "method": meta["method"],
            "family": meta["family"], "threshold": threshold, "comparison": "<=" if left else ">", "branch": "left" if left else "right"})
        node_id = node["left"] if left else node["right"]


def leaf_eligibility(node: dict, path: list[dict]) -> dict:
    """勝者側へ適用するscore・葉支持・異種技法の条件を算定する。

    引数: node(dict)は到達葉、path(list[dict])は実際の通過分岐。
    返り値: dictは別々の適否。負け側を救済選択しない。
    """
    families = sorted({p["family"] for p in path})
    return {"score": node["score"] is not None and node["score"] >= 1 / 3, "leaf_support": node["unique_slots"] >= 60 and node["days"] >= 6 and node["sessions"] >= 10,
        "method_support": len(families) >= 2 and bool(set(families) & {"trend", "osc"}), "families": families}


def predict(model: dict, vectors: dict[str, list]) -> dict:
    """同じJSON木で両方向を採点し、高い側だけに採用資格を課す。

    引数: model(dict)はfitのJSON木、vectors(dict[str,list])は'1'/'-1'の政策別17/18特徴。
    返り値: dictはscores/leafs/side/reasonと資格。両空は未準備、未知leaf到達は未学習枝WAIT。
    """
    if model.get("schema_version") != 1 or model.get("policy") not in POLICIES or not isinstance(model.get("nodes"), list) or not model["nodes"]:
        raise ValueError("保存モデルのschemaが不正")
    feature_metadata(model["feature_meta"], model["policy"])
    if not isinstance(vectors, dict) or set(vectors) != set(SIDES):
        raise ValueError("予測は両方向vectorsが必要")
    if vectors["1"] == [] and vectors["-1"] == []:
        return {"scores": {s: None for s in SIDES}, "leafs": {s: None for s in SIDES}, "side": 0, "winner_side": 0, "reason": "特徴未準備WAIT", "eligibility": {s: None for s in SIDES}}
    scores, leafs, eligibility = {}, {}, {}
    for side in SIDES:
        leaf_id, path = walk(model, vectors[side])
        node = model["nodes"][leaf_id]
        if node["path"] != path:
            raise ValueError("保存葉score/pathが不整合")
        absent = node.get("data_absent") is True
        if absent and (node["score"] is not None or node["direction_rows"] != 0):
            raise ValueError("未学習葉は0方向行/score未定が必要")
        if not absent and (not finite(node["score"]) or not 0 <= node["score"] <= 1):
            raise ValueError("学習済み葉scoreが不正")
        scores[side], leafs[side] = node["score"], leaf_id
        eligibility[side] = None if absent else leaf_eligibility(node, path)
    result = {"scores": scores, "leafs": leafs, "side": 0, "winner_side": 0, "reason": "同点WAIT", "eligibility": eligibility}
    if any(scores[s] is None for s in SIDES):
        result["reason"] = "未学習枝WAIT"
        return result
    if scores["1"] == scores["-1"]:
        return result
    winner = "1" if scores["1"] > scores["-1"] else "-1"
    result["winner_side"] = int(winner)
    failure = [label for key, label in (("score", "最高側score下限未達"), ("leaf_support", "最高側葉支持不足"), ("method_support", "最高側複数技法不足")) if not eligibility[winner][key]]
    result.update(side=0 if failure else int(winner), reason="/".join(failure) if failure else "採用")
    return result


def classifier_parameters(depth: int) -> dict:
    """自由木又は子木へ渡す固定ハイパーパラメータを返す。

    引数: depth(int)は自由木4又は子木3の最大深さ。
    返り値: dictはscikit-learnへ渡す引数。方向行数のmin_samples_leafと重みを混同しない。
    """
    return {"criterion": "gini", "splitter": "best", "max_depth": depth, "min_samples_split": 2,
        "min_samples_leaf": 60, "min_weight_fraction_leaf": 0.0, "max_features": None, "random_state": 51,
        "max_leaf_nodes": None, "min_impurity_decrease": 0.0, "class_weight": None, "ccp_alpha": 0.0, "monotonic_cst": None}


def tree_topology(estimator: object | None, offset: int, meta: list[dict]) -> list[dict]:
    """子木の局所IDを全体IDへ写し、空枝には未知leafを一つ作る。

    引数: estimator(object|None)は学習器又は空枝、offset(int)は先頭全体ID、meta(list[dict])は全特徴。
    返り値: list[dict]は分岐構造だけのnode。支持とscoreは後から全使用教師で再計数する。
    """
    if estimator is None:
        return [{"id": offset, "feature": -2, "feature_id": None, "family": None, "threshold": -2.0, "left": -1, "right": -1}]
    tree, result = estimator.tree_, []
    for local in range(tree.node_count):
        feature = int(tree.feature[local])
        result.append({"id": offset + local, "feature": feature, "feature_id": meta[feature]["id"] if feature >= 0 else None,
            "family": meta[feature]["family"] if feature >= 0 else None, "threshold": float(tree.threshold[local]),
            "left": int(tree.children_left[local]) + offset if tree.children_left[local] >= 0 else -1,
            "right": int(tree.children_right[local]) + offset if tree.children_right[local] >= 0 else -1})
    return result


def node_paths(nodes: list[dict], meta: list[dict]) -> dict[int, list[dict]]:
    """合成後のrootから全nodeまでの分岐列を構築する。

    引数: nodes(list[dict])は全体IDの木、meta(list[dict])は特徴metadata。
    返り値: dict[int,list[dict]]は各nodeのpath。固定rootもprice familyとして含む。
    """
    paths, stack = {0: []}, [0]
    while stack:
        node_id = stack.pop()
        node = nodes[node_id]
        if node["left"] == node["right"] == -1:
            continue
        feature = node["feature"]
        for branch, comparison in (("left", "<="), ("right", ">")):
            child = node[branch]
            if child in paths:
                raise ValueError("合成木の子IDが重複又は循環")
            paths[child] = paths[node_id] + [{"node": node_id, "feature": feature, "feature_id": meta[feature]["id"],
                "method": meta[feature]["method"], "family": meta[feature]["family"], "threshold": node["threshold"],
                "comparison": comparison, "branch": branch}]
            stack.append(child)
    if len(paths) != len(nodes):
        raise ValueError("合成木に到達不能nodeがある")
    return paths


def fit(rows: list[dict], feature_meta: list[dict], policy: str, model_id: str, evaluation_start: float) -> dict:
    """全pairの除外後、自由木又はZ固定rootと二つの子木を学習する。

    引数: rows(list[dict])は両方向教師、feature_meta(list[dict])はB0の17又はF0の18特徴、policy(str)はB0/F0、
        model_id(str)は成果物ID、evaluation_start(float)は次の評価開始秒。
    返り値: dictは合成後の全node・葉/支持/出典/期間/ID指紋。実市場での呼出しはroot担当。
    """
    if policy not in POLICIES or not isinstance(model_id, str) or not model_id:
        raise ValueError("政策又はmodel_idが不正")
    meta = feature_metadata(feature_meta, policy)
    used, training = prepare_rows(rows, evaluation_start, FEATURE_COUNTS[policy])
    # ----------------------------------------
    # 学習時だけ固定版を読み、正規化済み特徴へ変換・標準化を追加しない。
    import numpy as np
    import scipy
    import sklearn
    from sklearn.tree import DecisionTreeClassifier

    if sklearn.__version__ != SKLEARN_VERSION:
        raise RuntimeError("scikit-learnは固定1.9.1が必要")
    parameters = classifier_parameters(4)
    x = np.asarray([float32(r["features"], FEATURE_COUNTS[policy]) for r in used], dtype=np.float32)
    target = np.asarray([LABELS[r["outcome"]] for r in used], dtype=np.int64)
    fitted = []
    if policy == "B0":
        estimator = DecisionTreeClassifier(**parameters)
        estimator.fit(x, target, sample_weight=np.full(len(used), 0.5, dtype=np.float64))
        nodes = tree_topology(estimator, 0, meta)
        fitted.append((estimator, list(range(len(used))), 0))
        training["partition"] = None
        structure = {"kind": "free", "max_depth": 4, "features": 17}
    else:
        nodes = [{"id": 0, "feature": 17, "feature_id": "F18", "family": "price", "threshold": 0.5, "left": 1, "right": None}]
        training["partition"] = {}
        structure = {"kind": "fixed_root", "feature": "F18", "index": 17, "threshold": 0.5,
            "child_depth": 3, "child_features": 17, "max_depth": 4, "root_gini_optimized": False}
        for z in (0, 1):
            indexes = [i for i, row in enumerate(used) if row["features"][17] == z]
            selected = [used[i] for i in indexes]
            offset = len(nodes)
            estimator = None
            if selected:
                estimator = DecisionTreeClassifier(**classifier_parameters(3))
                estimator.fit(x[indexes, :17], target[indexes], sample_weight=np.full(len(indexes), 0.5, dtype=np.float64))
                fitted.append((estimator, indexes, offset))
            child_nodes = tree_topology(estimator, offset, meta)
            nodes.extend(child_nodes)
            nodes[0]["left" if z == 0 else "right"] = offset
            identities = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
            training["partition"][str(z)] = {"direction_rows": len(selected),
                "pair_unique": len({(r["session"], r["slot_id"]) for r in selected}),
                "days": len({r["session"][:10] for r in selected}), "sessions": len({r["session"] for r in selected}),
                "row_ids_sha256": fingerprint(identities), "fit_performed": estimator is not None,
                "root": offset, "node_count": len(child_nodes), "fit_parameters": classifier_parameters(3)}
    # ----------------------------------------
    # 合成後の木へ全使用教師を通し、枝内pairを再要求せず全nodeの所属と支持を数え直す。
    paths = node_paths(nodes, meta)
    model = {"policy": policy, "feature_meta": meta, "nodes": nodes}
    membership = {n["id"]: [] for n in nodes}
    for i, row in enumerate(used):
        leaf_id, path = walk(model, row["features"])
        for node_id in [p["node"] for p in path] + [leaf_id]:
            membership[node_id].append(i)
    for node in nodes:
        node_id = node["id"]
        indexes = membership[node_id]
        selected = [used[i] for i in indexes]
        successful = sum(LABELS[r["outcome"]] for r in selected)
        total_weight, success_weight = len(selected) * 0.5, successful * 0.5
        score = success_weight / total_weight if total_weight else None
        path = paths[node_id]
        identities = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
        node.update({"path": path,
            "direction_rows": len(selected), "weighted_rows": total_weight, "success_weight": success_weight, "total_weight": total_weight,
            "score": score, "unique_slots": len({(r["session"], r["slot_id"]) for r in selected}),
            "days": len({r["session"][:10] for r in selected}), "sessions": len({r["session"] for r in selected}),
            "methods": sorted({p["method"] for p in path}), "families": sorted({p["family"] for p in path}),
            "training_ids_sha256": fingerprint(identities), "impurity": 2 * score * (1 - score) if score is not None else None,
            "data_absent": not selected})
        eligibility = leaf_eligibility(node, path)
        node.update(leaf_support=eligibility["leaf_support"], method_support=eligibility["method_support"])
    model.update({"schema_version": 1, "model_id": model_id, "feature_meta_sha256": fingerprint(meta),
        "parameters": parameters, "subtree_parameters": classifier_parameters(3) if policy == "F0" else None,
        "structure": structure, "rules": deepcopy(RULES), "versions": {"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "training": training, "nodes": nodes,
        "interpretation": "同じ局所帯準備の両方向125/250/期限教師。B0は17列の自由木。F0のF18固定rootはgini最適分割ではなく、各子木は基礎17列だけで学習。葉率は未来確率又は局面分岐の因果効果を保証しない"})
    # ----------------------------------------
    # 非空子木だけを元学習器と全node/全方向で照合し、JSON変換時の投影・IDずれを拒否する。
    for estimator, indexes, offset in fitted:
        projected = x[indexes, :17]
        tree, visits = estimator.tree_, estimator.decision_path(projected)
        positive = np.flatnonzero(estimator.classes_ == 1)
        for local in range(tree.node_count):
            expected = [indexes[i] for i in visits[:, local].nonzero()[0].tolist()]
            node = nodes[offset + local]
            expected_score = float(tree.value[local, 0, positive[0]]) if len(positive) else 0.0
            if membership[offset + local] != expected or node["score"] != expected_score or node["direction_rows"] != int(tree.n_node_samples[local]) or node["total_weight"] != float(tree.weighted_n_node_samples[local]):
                raise ValueError("合成木と学習子木の所属/score/重みが不一致")
        actual_leafs, actual_probabilities = estimator.apply(projected), estimator.predict_proba(projected)
        for local_row, i in enumerate(indexes):
            leaf_id, _ = walk(model, used[i]["features"])
            expected_score = float(actual_probabilities[local_row, positive[0]]) if len(positive) else 0.0
            if leaf_id != int(actual_leafs[local_row]) + offset or nodes[leaf_id]["score"] != expected_score:
                raise ValueError("JSON木とscikit-learn予測が不一致")
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
