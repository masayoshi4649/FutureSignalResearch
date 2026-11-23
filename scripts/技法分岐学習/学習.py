"""両方向を同じ浅い木へ学習し、保存JSONだけで方向の適否を判定する。"""

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


POLICIES = {"Q0": 2, "Q1": 4}
SIDES = ("1", "-1")
FEATURE_COUNT = 15
EXPECTED_FAMILIES = ["trend", "osc", "osc", "vol", *(["price"] * 11)]
LABELS = {"250": 1, "125": 0, "期限": 0}
OUTCOMES = set(LABELS) | {"未約定", "不足"}
SKLEARN_VERSION = "1.9.1"
RULES = {"政策深さ": POLICIES, "random_state": 51, "criterion": "gini", "splitter": "best",
    "min_samples_leaf": 60, "min_samples_split": 2, "class_weight": None, "ccp_alpha": 0.0,
    "max_features": None, "方向行重み": 0.5, "score下限": {"分子": 1, "分母": 3, "等号可": True},
    "葉支持": {"unique枠": 60, "日": 6, "場": 10}, "path異種family最低": 2,
    "path必須family候補": ["trend", "osc"], "方向差": "strict", "予測入力型": "float32"}


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


def feature_metadata(feature_meta: list[dict]) -> list[dict]:
    """15特徴の順・family契約を確認し、外部の辞書を変更せず保全する。

    引数: feature_meta(list[dict])は特徴担当のid/name/method/family/scale。
    返り値: list[dict]はJSONの深い複写。不足や並び替えは拒否する。
    """
    if not isinstance(feature_meta, list) or len(feature_meta) != FEATURE_COUNT:
        raise ValueError("特徴metadataは固定15列が必要")
    for index, meta in enumerate(feature_meta):
        if not isinstance(meta, dict) or any(not isinstance(meta.get(k), str) or not meta[k] for k in ("id", "name", "method", "family", "scale")):
            raise ValueError("特徴metadataの必須5項目が不正")
        if meta["id"] != f"F{index + 1:02d}" or meta["family"] != EXPECTED_FAMILIES[index]:
            raise ValueError("特徴の順又はfamilyを変更できない")
    return json.loads(json.dumps(feature_meta, ensure_ascii=False, allow_nan=False))


def vector(values: list) -> list[float]:
    """欠測を補完せず、15有限値の特徴列を検査する。

    引数: values(list)は方向正規化済み特徴。
    返り値: list[float]は元の順・符号を保つ値。
    """
    if not isinstance(values, list) or len(values) != FEATURE_COUNT or any(not finite(v) for v in values):
        raise ValueError("特徴は15個の有限値が必要。欠測補完はしない")
    return [float(v) for v in values]


def float32(values: list) -> list[float]:
    """scikit-learnと同じfloat32へ予測特徴を一度だけ写す。

    引数: values(list)は15有限値。
    返り値: list[float]はfloat32を正確に表せるPython float。桁あふれを拒否する。
    """
    result = []
    for value in vector(values):
        try:
            converted = struct.unpack("<f", struct.pack("<f", value))[0]
        except (OverflowError, struct.error) as exc:
            raise ValueError("特徴がfloat32範囲を超えた") from exc
        if not math.isfinite(converted):
            raise ValueError("float32化後の非有限特徴")
        result.append(converted)
    return result


def prepare_rows(rows: list[dict], evaluation_start: float) -> tuple[list[dict], dict]:
    """方向ペアを検査し、未約定・不足は双方を学習から除く。

    引数: rows(list[dict])は特徴readyな両方向教師、evaluation_start(float)は評価開始秒。
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
        row["features"] = vector(row["features"])
        float32(row["features"])
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
        "row_ids_sha256": fingerprint(ids), "period": period, "period_sha256": fingerprint(period), "feature_missing_handling": "rootがreadyなpairのみ入力。ここでは補完しない"}


def walk(model: dict, values: list) -> tuple[int, list[dict]]:
    """float32化した特徴でJSON木を左<=/右>へたどる。

    引数: model(dict)は保存木、values(list)は方向特徴。
    返り値: tuple[int,list[dict]]は葉IDと通過分岐。学習器やjoblibを使わない。
    """
    values, node_id, path = float32(values), 0, []
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
        if type(feature) is not int or not 0 <= feature < FEATURE_COUNT or not finite(threshold):
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
    return {"score": node["score"] >= 1 / 3, "leaf_support": node["unique_slots"] >= 60 and node["days"] >= 6 and node["sessions"] >= 10,
        "method_support": len(families) >= 2 and bool(set(families) & {"trend", "osc"}), "families": families}


def predict(model: dict, vectors: dict[str, list]) -> dict:
    """同じJSON木で両方向を採点し、高い側だけに採用資格を課す。

    引数: model(dict)はfitのJSON木、vectors(dict[str,list])は'1'/'-1'の15特徴。
    返り値: dictはscores/leafs/side/reasonと資格。両空は未準備WAIT、片側欠測は拒否。
    """
    if model.get("schema_version") != 1 or model.get("policy") not in POLICIES or not isinstance(model.get("nodes"), list) or not model["nodes"]:
        raise ValueError("保存モデルのschemaが不正")
    feature_metadata(model["feature_meta"])
    if not isinstance(vectors, dict) or set(vectors) != set(SIDES):
        raise ValueError("予測は両方向vectorsが必要")
    if vectors["1"] == [] and vectors["-1"] == []:
        return {"scores": {s: None for s in SIDES}, "leafs": {s: None for s in SIDES}, "side": 0, "winner_side": 0, "reason": "特徴未準備WAIT", "eligibility": {s: None for s in SIDES}}
    scores, leafs, eligibility = {}, {}, {}
    for side in SIDES:
        leaf_id, path = walk(model, vectors[side])
        node = model["nodes"][leaf_id]
        if not finite(node["score"]) or not 0 <= node["score"] <= 1 or node["path"] != path:
            raise ValueError("保存葉score/pathが不整合")
        scores[side], leafs[side] = node["score"], leaf_id
        eligibility[side] = leaf_eligibility(node, path)
    result = {"scores": scores, "leafs": leafs, "side": 0, "winner_side": 0, "reason": "同点WAIT", "eligibility": eligibility}
    if scores["1"] == scores["-1"]:
        return result
    winner = "1" if scores["1"] > scores["-1"] else "-1"
    result["winner_side"] = int(winner)
    failure = [label for key, label in (("score", "最高側score下限未達"), ("leaf_support", "最高側葉支持不足"), ("method_support", "最高側複数技法不足")) if not eligibility[winner][key]]
    result.update(side=0 if failure else int(winner), reason="/".join(failure) if failure else "採用")
    return result


def fit(rows: list[dict], feature_meta: list[dict], policy: str, model_id: str, evaluation_start: float) -> dict:
    """固定ハイパーパラメータの共通木を学習し、純JSONの全構造へ展開する。

    引数: rows(list[dict])は両方向教師、feature_meta(list[dict])は固定15特徴、policy(str)はQ0/Q1、
        model_id(str)は成果物ID、evaluation_start(float)は次の評価開始秒。
    返り値: dictは全node・葉/出典/期間/ID指紋。実市場での呼出しはroot担当。
    """
    if policy not in POLICIES or not isinstance(model_id, str) or not model_id:
        raise ValueError("政策又はmodel_idが不正")
    meta = feature_metadata(feature_meta)
    used, training = prepare_rows(rows, evaluation_start)
    # ----------------------------------------
    # 学習時だけ固定版を読み、正規化済み特徴へ変換・標準化を追加しない。
    import numpy as np
    import scipy
    import sklearn
    from sklearn.tree import DecisionTreeClassifier

    if sklearn.__version__ != SKLEARN_VERSION:
        raise RuntimeError("scikit-learnは固定1.9.1が必要")
    parameters = {"criterion": "gini", "splitter": "best", "max_depth": POLICIES[policy], "min_samples_split": 2,
        "min_samples_leaf": 60, "min_weight_fraction_leaf": 0.0, "max_features": None, "random_state": 51,
        "max_leaf_nodes": None, "min_impurity_decrease": 0.0, "class_weight": None, "ccp_alpha": 0.0, "monotonic_cst": None}
    x = np.asarray([float32(r["features"]) for r in used], dtype=np.float32)
    target = np.asarray([LABELS[r["outcome"]] for r in used], dtype=np.int64)
    estimator = DecisionTreeClassifier(**parameters)
    estimator.fit(x, target, sample_weight=np.full(len(used), 0.5, dtype=np.float64))
    tree, memberships = estimator.tree_, estimator.decision_path(x)
    paths = {0: []}
    for node_id in range(tree.node_count):
        if tree.children_left[node_id] == -1:
            continue
        index, threshold = int(tree.feature[node_id]), float(tree.threshold[node_id])
        for branch, child, comparison in (("left", int(tree.children_left[node_id]), "<="), ("right", int(tree.children_right[node_id]), ">")):
            paths[child] = paths[node_id] + [{"node": node_id, "feature": index, "feature_id": meta[index]["id"], "method": meta[index]["method"],
                "family": meta[index]["family"], "threshold": threshold, "comparison": comparison, "branch": branch}]
    # ----------------------------------------
    # 全nodeの所属方向行を保存教師から数え、葉支持はユニーク枠/日/場で別判定する。
    nodes = []
    for node_id in range(tree.node_count):
        indexes = memberships[:, node_id].nonzero()[0].tolist()
        selected = [used[i] for i in indexes]
        successful = sum(LABELS[r["outcome"]] for r in selected)
        total_weight, success_weight = len(selected) * 0.5, successful * 0.5
        score = success_weight / total_weight
        class_one = np.flatnonzero(estimator.classes_ == 1)
        sklearn_score = float(tree.value[node_id, 0, class_one[0]]) if len(class_one) else 0.0
        if score != sklearn_score or int(tree.n_node_samples[node_id]) != len(selected) or float(tree.weighted_n_node_samples[node_id]) != total_weight:
            raise ValueError("学習木の重み/方向行/成功率の不整合")
        path, index = paths[node_id], int(tree.feature[node_id])
        identities = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
        node = {"id": node_id, "feature": index, "feature_id": meta[index]["id"] if index >= 0 else None,
            "family": meta[index]["family"] if index >= 0 else None, "threshold": float(tree.threshold[node_id]),
            "left": int(tree.children_left[node_id]), "right": int(tree.children_right[node_id]), "path": path,
            "direction_rows": len(selected), "weighted_rows": total_weight, "success_weight": success_weight, "total_weight": total_weight,
            "score": score, "unique_slots": len({(r["session"], r["slot_id"]) for r in selected}),
            "days": len({r["session"][:10] for r in selected}), "sessions": len({r["session"] for r in selected}),
            "methods": sorted({p["method"] for p in path}), "families": sorted({p["family"] for p in path}),
            "training_ids_sha256": fingerprint(identities), "impurity": float(tree.impurity[node_id])}
        eligibility = leaf_eligibility(node, path)
        node.update(leaf_support=eligibility["leaf_support"], method_support=eligibility["method_support"])
        nodes.append(node)
    model = {"schema_version": 1, "model_id": model_id, "policy": policy, "feature_meta": meta, "feature_meta_sha256": fingerprint(meta),
        "parameters": parameters, "rules": deepcopy(RULES), "versions": {"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "training": training, "nodes": nodes,
        "interpretation": "両方向の125/250/期限教師。価格T/Rを教師にせず、葉の学習成功率は未来確率又は一般化性能を保証しない"}
    actual_leafs, actual_probabilities = estimator.apply(x), estimator.predict_proba(x)
    positive = np.flatnonzero(estimator.classes_ == 1)
    for i, row in enumerate(used):
        leaf_id, _ = walk(model, row["features"])
        expected_score = float(actual_probabilities[i, positive[0]]) if len(positive) else 0.0
        if leaf_id != int(actual_leafs[i]) or nodes[leaf_id]["score"] != expected_score:
            raise ValueError("JSON木とscikit-learn予測が不一致")
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
