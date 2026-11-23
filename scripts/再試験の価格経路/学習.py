"""固定二段と同教師を保ち、再試験価格経路を加えた30特徴で回収を分岐する。"""

from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
import struct


HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / "方向局面分岐/学習.py"
SPEC = importlib.util.spec_from_file_location("回収目的の固定54学習純関数", SHARED)
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
LEGACY_SPEC = importlib.util.spec_from_file_location("再試験経路の固定56学習", HERE.parent / "回収目的分岐/学習.py")
LEGACY = importlib.util.module_from_spec(LEGACY_SPEC)
sys.modules[LEGACY_SPEC.name] = LEGACY
LEGACY_SPEC.loader.exec_module(LEGACY)
POLICIES, FEATURE_COUNTS = {"N0": 4}, {"N0": 30}
CHILD_FEATURE_INDICES = [*range(17), *range(18, 30)]
SIDES, LABELS, SKLEARN_VERSION = BASE.SIDES, BASE.LABELS, BASE.SKLEARN_VERSION
MONEY_FIELDS = ("pnl0", "pnl5", "pnl10")
BARRIER_FIELDS = ("slot_id", "session", "scheduled", "time", "line", "side", "features", "outcome", "filled", "end_time", "end_line")
DECIMAL_PRECISION = 80
NUMERIC_TOLERANCE = {"mean_abs": 1e-10, "mean_rel": 1e-12, "mse_abs": 1e-8, "mse_second_moment_rel": 1e-10}
RULES = deepcopy(BASE.RULES)
FIXED_RULE = RULES.pop("D0固定段")
FIXED_RULE.pop("gini最適固定段ではない")
FIXED_RULE["MSE最適固定段ではない"] = True
FIXED_RULE["子特徴数"] = 29
FIXED_RULE["子特徴列index"] = CHILD_FEATURE_INDICES
RULES.pop("class_weight")
RULES.update({"政策深さ": POLICIES, "政策特徴数": FEATURE_COUNTS, "criterion": "squared_error", "学習目的": "pnl5",
    "子学習器": "DecisionTreeRegressor", "回帰class_weight": "引数なし", "N0固定段": FIXED_RULE,
    "方向採点": "障壁250成功率のみ。回帰値で方向変更又は低い側救済をしない",
    "N1": "同一N0木を使用。回収支持と正の追加条件は後段の固定回収集計で判定",
    "回収教師": "旧障壁pair検査後、両方向pnl0/5/10と回収終了の既知を要求。欠測はpair全体除外",
    "未来回収": "非欠測のrecovery_end_timeは評価開始よりstrict前。同秒は拒否",
    "回収正": "Decimalのpnl5合計>0。epsilonなし", "Decimal平均精度": DECIMAL_PRECISION,
    "数値照合許容": NUMERIC_TOLERANCE})


def fingerprint(value: object) -> str:
    """旧54と同じ有限JSONの内容指紋を得る。

    引数: value(object)はJSONで表せる値。
    返り値: strは配列順を保つSHA256。
    """
    return BASE.fingerprint(value)


def feature_metadata(feature_meta: list[dict], policy: str) -> list[dict]:
    """旧18列と追加12列の順・役割・尺度を検査する。

    引数: feature_meta(list[dict])はF01..30、policy(str)はN0。
    返り値: list[dict]は深い複写。N1は同じ木を使う。
    """
    if policy != "N0" or not isinstance(feature_meta, list) or len(feature_meta) != 30:
        raise ValueError("N0の30特徴が必要")
    BASE.feature_metadata(feature_meta[:18], "D0")
    for index, meta in enumerate(feature_meta[18:], 18):
        method = "P05" if index in (22, 28) else "P10"
        if meta.get("id") != f"F{index + 1:02d}" or meta.get("family") != "price" or meta.get("method") != method or meta.get("scale") != "m03" or not isinstance(meta.get("name"), str) or not meta["name"]:
            raise ValueError("追加価格経路のmetadataが不正")
    return deepcopy(feature_meta)


def float32(values: list, feature_count: int = 30) -> list[float]:
    """同じfloat32へ写し、追加の段階・旗・経過・戻りの領域を検査する。

    引数: values(list)は30有限特徴、feature_count(int)は30。
    返り値: list[float]は分岐へ共通投入する数値。boolや桁あふれは拒否。
    """
    if feature_count != 30 or not isinstance(values, list) or len(values) != 30:
        raise ValueError("30特徴が必要")
    result = BASE.float32(values[:18], 18)
    for value in values[18:]:
        if not BASE.BASE.finite(value):
            raise ValueError("追加価格経路は有限数が必要")
        try:
            converted = struct.unpack("f", struct.pack("f", value))[0]
        except (OverflowError, struct.error) as exc:
            raise ValueError("追加価格経路のfloat32範囲外") from exc
        if not math.isfinite(converted):
            raise ValueError("追加価格経路のfloat32範囲外")
        result.append(converted)
    for start, maximum in ((18, 3), (24, 4)):
        stage, active, confirmed, age, progress, pullback = values[start:start + 6]
        if stage not in range(maximum + 1) or active not in (0, 1) or confirmed not in (0, 1) or age < -1 or -1 < age < 0 or pullback < 0:
            raise ValueError("追加価格経路の数値領域が不正")
        if stage < maximum and (age != -1 or progress != 0 or pullback != 0 or confirmed != 0):
            raise ValueError("未形成kの数値が不正")
        if stage == maximum and age < 0 or confirmed > active or stage == 0 and active:
            raise ValueError("k経過又は有効旗の不整合")
    return result



def decimal_text(value: Decimal) -> str:
    """Decimalを丸めず、不要な小数末尾だけ除いた文字列へ写す。

    引数: value(Decimal)は有限値。
    返り値: strは指数を使わない正本表現。負のゼロは0とする。
    """
    text = format(value, "f")
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return "0" if value == 0 else text


def money(value: object) -> Decimal:
    """有限の回収値をDecimalへ変換し、学習用float64範囲も確認する。

    引数: value(object)はint/float/Decimal又は数値文字列。bool/欠測は不可。
    返り値: Decimalはstr経由の値。非有限・float64の桁あふれ/非零の桁落ちは拒否する。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise ValueError("回収値は有限数又は数値文字列が必要")
    try:
        result = Decimal(str(value))
        converted = float(result)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ValueError("回収値の数値表現が不正") from exc
    if not result.is_finite() or not math.isfinite(converted) or result != 0 and converted == 0:
        raise ValueError("回収値は有限のfloat64で扱える値が必要")
    return result


def barrier_projection(row: dict) -> dict:
    """旧検査済み行から旧54のcanonical列だけを再構成する。

    引数: row(dict)は旧54の全pair検査を通った入力行。
    返り値: dictは旧11必須列とentry2列。回収値を混ぜない指紋に用いる。
    """
    result = {key: deepcopy(row[key]) for key in BARRIER_FIELDS}
    result["features"] = [float(v) for v in row["features"]]
    result.update(entry_time=row.get("entry_time"), entry_line=row.get("entry_line"))
    return result


def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 30) -> tuple[list[dict], dict]:
    """18列射影で旧全pair検査を完了し、同じ使用集合を30列へ写す。

    引数: rows(list[dict])は30特徴と障壁/回収教師、evaluation_start(float)は評価開始、feature_count(int)は30。
    返り値: tuple[list[dict],dict]は全特徴canonical使用行と旧18指紋を含む指紋/除外。
    """
    if feature_count != 30:
        raise ValueError("30特徴が必要")
    projected = []
    for row in rows:
        float32(row["features"])
        projected.append({**row, "features": row["features"][:18]})
    old_used, training = LEGACY.prepare_rows(projected, evaluation_start, 18)
    identities = {(r["session"], r["slot_id"], r["side"]) for r in old_used}
    canonical = []
    for original in rows:
        row = barrier_projection(original)
        row.update({key: None if original.get(key) is None else decimal_text(money(original[key])) for key in MONEY_FIELDS})
        row["recovery_end_time"] = original.get("recovery_end_time")
        canonical.append(row)
    used = [r for r in canonical if (r["session"], r["slot_id"], r["side"]) in identities]
    training["base18_fingerprints"] = {key: training[key] for key in
        ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")}
    training.update(input_rows_sha256=fingerprint(canonical), used_rows_sha256=fingerprint(used),
        used_barrier_rows_sha256=fingerprint([barrier_projection(r) for r in used]),
        feature_missing_handling="旧18準備の同一pair。未形成/取消の価格経路は既知状態、追加除外なし")
    return used, training



def recovery_statistics(rows: list[dict]) -> dict:
    """所属方向行の費用別合計/平均とpnl5のMSEを別々に算出する。

    引数: rows(list[dict])は回収既知の方向行。全行の重みは等しく0.5。
    返り値: dictはDecimal正本と表示float。合計は重みを掛けない方向行の単純和、平均/MSEは80桁。
    """
    if not rows:
        return {"recovery": {key: {"sum": "0", "mean": None, "mean_decimal": None} for key in MONEY_FIELDS},
            "recovery_positive": None, "recovery_mse_decimal": None, "regression_value": None, "impurity": None, "second_moment": None}
    result, n, target = {}, len(rows), []
    for key in MONEY_FIELDS:
        values = [money(r[key]) for r in rows]
        integer_digits = max(max(1, v.adjusted() + 1) for v in values)
        scale = max(max(0, -v.as_tuple().exponent) for v in values)
        precision = max(DECIMAL_PRECISION, integer_digits + scale + len(str(n)) + 4)
        with localcontext() as context:
            context.prec = precision
            context.rounding = ROUND_HALF_EVEN
            total = sum(values, Decimal(0))
        with localcontext() as context:
            context.prec = DECIMAL_PRECISION
            context.rounding = ROUND_HALF_EVEN
            mean = total / n
        result[key] = {"sum": decimal_text(total), "mean": float(mean), "mean_decimal": decimal_text(mean)}
        if key == "pnl5":
            target, target_sum, target_precision = values, total, precision
    # ----------------------------------------
    # 展開した二乗差の分子を十分な桁で正確に作り、最後の除算だけ80桁へ丸める。
    with localcontext() as context:
        context.prec = 2 * target_precision + len(str(n)) + 4
        context.rounding = ROUND_HALF_EVEN
        squares = sum((v * v for v in target), Decimal(0))
        numerator = n * squares - target_sum * target_sum
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        context.rounding = ROUND_HALF_EVEN
        mse, second = numerator / (n * n), squares / n
    if mse < 0 or not math.isfinite(float(mse)) or not math.isfinite(float(second)):
        raise ValueError("回収MSEの数値範囲が不正")
    return {"recovery": result, "recovery_positive": target_sum > 0,
        "recovery_mse_decimal": decimal_text(mse), "regression_value": result["pnl5"]["mean"],
        "impurity": float(mse), "second_moment": float(second)}


def regressor_parameters(depth: int) -> dict:
    """旧54の分岐・支持ハイパーパラメータを回帰木へ適応する。

    引数: depth(int)は全体上限4又は実際の子上限2。
    返り値: dictはDecisionTreeRegressor引数。回帰に存在しないclass_weightを渡さない。
    """
    parameters = BASE.BASE.classifier_parameters(depth)
    parameters.pop("class_weight")
    parameters["criterion"] = "squared_error"
    return parameters


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
        if type(feature) is not int or not 0 <= feature < count or not BASE.BASE.finite(threshold):
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

    引数: model(dict)はfitのJSON木、vectors(dict[str,list])は'1'/'-1'の30特徴。
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
        if not absent and (not BASE.BASE.finite(node["score"]) or not 0 <= node["score"] <= 1):
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


def numeric_match(actual: float, expected: float, kind: str, second_moment: float = 0.0) -> bool:
    """学習器の演算順による平均/MSEだけを明示許容で照合する。

    引数: actual/expected(float)は生学習器/Decimal再算値、kind(str)はmean又はmse、second_moment(float)はE[pnl5²]。
    返り値: boolは一致可否。score/支持/回収正/予測閾値にこの許容を使わない。
    """
    if not math.isfinite(actual) or not math.isfinite(expected):
        return False
    if kind == "mean":
        return math.isclose(actual, expected, rel_tol=NUMERIC_TOLERANCE["mean_rel"], abs_tol=NUMERIC_TOLERANCE["mean_abs"])
    if kind != "mse":
        raise ValueError("数値照合の種類が不正")
    tolerance = NUMERIC_TOLERANCE["mse_abs"] + NUMERIC_TOLERANCE["mse_second_moment_rel"] * max(1.0, abs(second_moment))
    return abs(actual - expected) <= tolerance


def fit(rows: list[dict], feature_meta: list[dict], policy: str, model_id: str, evaluation_start: float) -> dict:
    """回収既知pairを固定四群へ分け、29列深さ2のpnl5回帰木を合成する。

    引数: rows(list[dict])は障壁/回収教師、feature_meta(list[dict])は30特徴、policy(str)はN0、
        model_id(str)は保存ID、evaluation_start(float)は評価開始秒。
    返り値: dictは全node/障壁率/回収統計/支持/指紋の純JSON。本物fitはrootだけが実行する。
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
    x = np.asarray([float32(r["features"]) for r in used], dtype=np.float32)
    target = np.asarray([float(money(r["pnl5"])) for r in used], dtype=np.float64)
    fixed = [{"id": 0, "feature": "F18", "index": 17, "threshold": 0.5},
        {"id": 1, "feature": "F01", "index": 0, "threshold": 0.0},
        {"id": 2, "feature": "F01", "index": 0, "threshold": 0.0}]
    nodes = [{"id": n["id"], "feature": n["index"], "feature_id": n["feature"], "family": meta[n["index"]]["family"],
        "threshold": n["threshold"], "left": 1 if n["id"] == 0 else None, "right": 2 if n["id"] == 0 else None} for n in fixed]
    training["partition"], fitted = {}, []
    for z in (0, 1):
        for a in (0, 1):
            indexes = [i for i in range(len(used)) if x[i, 17] == z and int(x[i, 0] > 0) == a]
            selected, offset, estimator = [used[i] for i in indexes], len(nodes), None
            if selected:
                estimator = DecisionTreeRegressor(**child_parameters)
                estimator.fit(x[indexes][:, CHILD_FEATURE_INDICES], target[indexes], sample_weight=np.full(len(indexes), 0.5, dtype=np.float64))
                fitted.append((estimator, indexes, offset))
            child_nodes = BASE.BASE.tree_topology(estimator, offset, [meta[i] for i in CHILD_FEATURE_INDICES])
            for child in child_nodes:
                if child["feature"] >= 0:
                    child["feature"] = CHILD_FEATURE_INDICES[child["feature"]]
            nodes.extend(child_nodes)
            nodes[1 + z]["left" if a == 0 else "right"] = offset
            ids = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
            training["partition"][f"Z{z}_a{a}"] = {"z": z, "a": a, "policy": policy, "direction_rows": len(selected),
                "pair_unique": len({(r["session"], r["slot_id"]) for r in selected}), "days": len({r["session"][:10] for r in selected}),
                "sessions": len({r["session"] for r in selected}), "row_ids_sha256": fingerprint(ids),
                "fit_performed": estimator is not None, "root": offset, "node_count": len(child_nodes), "fit_parameters": deepcopy(child_parameters)}
    # ----------------------------------------
    # 固定段を含め全使用行から全nodeを再計数し、障壁率と回収目的を別々に保存する。
    paths = BASE.BASE.node_paths(nodes, meta)
    model = {"policy": policy, "feature_meta": meta, "nodes": nodes}
    membership = {node["id"]: [] for node in nodes}
    for i, row in enumerate(used):
        leaf, path = walk(model, row["features"])
        for node_id in [p["node"] for p in path] + [leaf]:
            membership[node_id].append(i)
    moments = {}
    for node in nodes:
        selected = [used[i] for i in membership[node["id"]]]
        total_weight, success_weight = len(selected) * 0.5, sum(LABELS[r["outcome"]] for r in selected) * 0.5
        score = success_weight / total_weight if total_weight else None
        path = paths[node["id"]]
        ids = [{"session": r["session"], "slot_id": r["slot_id"], "side": r["side"]} for r in selected]
        statistics = recovery_statistics(selected)
        moments[node["id"]] = statistics.pop("second_moment")
        node.update({"path": path, "direction_rows": len(selected), "weighted_rows": total_weight,
            "success_weight": success_weight, "total_weight": total_weight, "score": score,
            "unique_slots": len({(r["session"], r["slot_id"]) for r in selected}),
            "days": len({r["session"][:10] for r in selected}), "sessions": len({r["session"] for r in selected}),
            "methods": sorted({p["method"] for p in path}), "families": sorted({p["family"] for p in path}),
            "training_ids_sha256": fingerprint(ids), "barrier_gini": 2 * score * (1 - score) if score is not None else None,
            "impurity_kind": "squared_error", "data_absent": not selected, **statistics})
        eligibility = BASE.BASE.leaf_eligibility(node, path)
        node.update(leaf_support=eligibility["leaf_support"], method_support=eligibility["method_support"])
    # ----------------------------------------
    # 元回帰器の全node所属・重み・平均・MSEと全方向予測を合成JSONへ接続する。
    for estimator, indexes, offset in fitted:
        projected, tree = x[indexes][:, CHILD_FEATURE_INDICES], estimator.tree_
        visits = estimator.decision_path(projected)
        for local in range(tree.node_count):
            expected = [indexes[i] for i in visits[:, local].nonzero()[0].tolist()]
            node = nodes[offset + local]
            value, impurity = float(tree.value[local, 0, 0]), float(tree.impurity[local])
            if membership[node["id"]] != expected or node["direction_rows"] != int(tree.n_node_samples[local]) or node["total_weight"] != float(tree.weighted_n_node_samples[local]):
                raise ValueError("合成回帰木の所属/件数/重みが不一致")
            if not numeric_match(value, node["recovery"]["pnl5"]["mean"], "mean") or not numeric_match(impurity, float(Decimal(node["recovery_mse_decimal"])), "mse", moments[node["id"]]):
                raise ValueError("合成回帰木の平均/MSEが独立Decimal算術と不一致")
            node.update(regression_value=value, impurity=impurity)
        leafs, predictions = estimator.apply(projected), estimator.predict(projected)
        for local_row, index in enumerate(indexes):
            leaf, _ = walk(model, used[index]["features"])
            if leaf != int(leafs[local_row]) + offset or nodes[leaf]["regression_value"] != float(predictions[local_row]):
                raise ValueError("合成JSONと元回帰器の所属/予測が不一致")
    structure = {"kind": "fixed_root_and_direction", "fixed_nodes": fixed, "child_depth": 2,
        "child_features": 29, "child_feature_indices": CHILD_FEATURE_INDICES, "feature_count": 30, "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"}
    sources = [SHARED, BASE.SHARED, HERE.parent / "回収目的分岐/学習.py"]
    model.update({"schema_version": 1, "model_id": model_id, "feature_meta_sha256": fingerprint(meta),
        "parameters": parameters, "subtree_parameters": child_parameters, "structure": structure, "rules": deepcopy(RULES),
        "versions": {"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "shared_source_sha256": {path.relative_to(HERE.parents[1]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        "training": training, "nodes": nodes,
        "interpretation": "旧18技法へ再試験経路12を追加し、pnl5平均の二乗誤差で分割。固定二段はMSE最適分割ではない。方向rank/資格は障壁率のまま。回収合算は同時実行可能な運用損益ではない。回帰平均は将来利益の保証ではない"})
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
