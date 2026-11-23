"""同じ60特徴へ、共通可知pairの即時又は条件入口教師を接続する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys


HERE = Path(__file__).resolve().parent
LEGACY_PATH = HERE.parent / "現在状態と量価格/学習.py"
SPEC = importlib.util.spec_from_file_location("条件入口69が固定参照する65学習", LEGACY_PATH)
LEGACY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LEGACY
SPEC.loader.exec_module(LEGACY)
BASE = LEGACY.BASE
SHARED = HERE.parent / "方向局面分岐/学習.py"
POLICIES, FEATURE_COUNTS = {"I0": 4, "C0": 4}, {"I0": 60, "C0": 60}
CHILD_FEATURE_INDICES = deepcopy(LEGACY.CHILD_FEATURE_INDICES)
SIDES, LABELS, SKLEARN_VERSION = LEGACY.SIDES, LEGACY.LABELS, LEGACY.SKLEARN_VERSION
MONEY_FIELDS, DECIMAL_PRECISION = LEGACY.MONEY_FIELDS, LEGACY.DECIMAL_PRECISION
NUMERIC_TOLERANCE = deepcopy(LEGACY.NUMERIC_TOLERANCE)
FINGERPRINT_FIELDS = LEGACY.FINGERPRINT_FIELDS
CANONICAL_FIELDS = ("session", "slot_id", "side", "features", "filled", "outcome", "end_time",
    "recovery_end_time", "pnl0", "pnl5", "pnl10")
RULES = deepcopy(LEGACY.RULES)
RULES.pop("U0固定段")
RULES.pop("U1")
RULES.update({"政策深さ": POLICIES, "政策特徴数": FEATURE_COUNTS,
    "共通固定段": deepcopy(LEGACY.RULES["U0固定段"]),
    "回収教師": "rootで即時/条件の共通可知pairを用意。両側とも確定約定又は確定無取引を要求し、学習器で追加除外しない",
    "方向採点": "priorは約定後250成功率の最高側へ資格判定。最終の両側適格内選択は固定66が担当し、回帰平均で順位を変えない",
    "群の除外": "V0も四群に残す。rootで未知を含むpairを共通集合から除いた後、方向行を分割し枝内pairは要求しない",
    "追加指標": "旧64で追加済みの量価格6列を含む同60列。69では指標や数値列を追加しない",
    "mask限定": "旧60内の量maskもV01/volume。同じ資格関数を維持し、量maskだけのpathは独立した量の証拠としない",
    "教師": "I0は即時/C0は条件入口。rootで同じ両方向可知pairへそろえた後、同演算で別fit",
    "確定無取引": "filled=False/outcome=無取引/費用別回収すべて0。回帰へ含め、先着score分母へ含めない",
    "未知": "準備側で共通pair除外済み。不足/未解消/品質注意/Noneを学習器で0へ補完しない",
    "支持": "葉の60枠/6日/10場は約定既知だけ。全可知行の回帰min_samples_leaf=60と別",
    "回帰分母": "全可知方向行。無取引0を含むmean/MSE。全方向行の重み0.5",
    "先着分母": "filled=Trueの250/125/期限のみ。250件数/約定既知数。約定0ならscore=None",
    "標本なし": "data_absentは回帰行0、barrier_data_absentは約定既知行0。後者でも回帰平均0は既知になり得る",
    "予測": "両空/片側score未知/同点はWAIT。priorは旧65同型、適格方向の最終選択は固定66へ委ねる",
    "比較の限定": "I/Cは共通可知集合・同60情報・同構造/演算。教師契約だけを変え、現在setupや技法資格の改善は保証しない"})

# ----------------------------------------
# 既検証の数値・metadata・木の構成だけを読み、旧prepareは呼ばない。
fingerprint = LEGACY.fingerprint
money = LEGACY.money
decimal_text = LEGACY.decimal_text
recovery_statistics = LEGACY.recovery_statistics
regressor_parameters = LEGACY.regressor_parameters
numeric_match = LEGACY.numeric_match


def feature_metadata(feature_meta: list[dict], policy: str) -> list[dict]:
    """I0とC0へ旧65と同じ60列metadataを接続する。

    引数: feature_meta(list[dict])は60列、policy(str)はI0又はC0。
    返り値: list[dict]は旧65検査後の深い写し。元metadataを変更しない。
    """
    if policy not in POLICIES:
        raise ValueError("学習モデル政策はI0又はC0が必要")
    return LEGACY.feature_metadata(feature_meta, "U0")


def float32(values: list, feature_count: int = 60) -> list[float]:
    """旧65の有限値・共同mask検査を同じ60列へ適用する。

    引数: values(list)は60特徴、feature_count(int)は60のみ。
    返り値: list[float]は旧65と同じfloat32値。旧globalを変更しない。
    """
    if type(feature_count) is not int or feature_count != 60:
        raise ValueError("I0/C0は60特徴が必要")
    return LEGACY.float32(values, 60)


def barrier_projection(row: dict) -> dict:
    """回収3値と回収終了を分けた新しい障壁側の正規化列を作る。

    引数: row(dict)は新canonical方向行。
    返り値: dictはidentity/features/filled/outcome/end_time。旧即時canonicalと同値とはしない。
    """
    return {key: deepcopy(row[key]) for key in CANONICAL_FIELDS if key not in (*MONEY_FIELDS, "recovery_end_time")}


def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 60) -> tuple:
    """共通可知pairを再検査し、確定無取引を含む全方向行を正規化する。

    引数: rows(list[dict])は新11項目教師、evaluation_start(float)は評価開始、feature_count(int)は60。
    返り値: tuple[list[dict],dict]は使用行と件数/正規化/ID/終了の指紋。未知の除外や補完をここで追加しない。
    """
    if (isinstance(evaluation_start, bool) or not isinstance(evaluation_start, (int, float))
            or not math.isfinite(evaluation_start) or not isinstance(rows, list) or not rows):
        raise ValueError("評価開始は有限秒、教師は空でないlistが必要")
    if type(feature_count) is not int or feature_count != 60:
        raise ValueError("教師は60特徴が必要")
    canonical, pairs = [], {}
    for original in rows:
        if not isinstance(original, dict) or not set(CANONICAL_FIELDS) <= set(original):
            raise ValueError("共通可知教師の必須項目が不足")
        row = {key: deepcopy(original[key]) for key in CANONICAL_FIELDS}
        if (any(not isinstance(row[key], str) or not row[key] for key in ("session", "slot_id"))
                or type(row["side"]) is not int or row["side"] not in (-1, 1) or type(row["filled"]) is not bool):
            raise ValueError("教師identity/方向/filledが不正")
        float32(row["features"], feature_count)
        row["features"] = [float(value) for value in row["features"]]
        for key in ("end_time", "recovery_end_time"):
            value = row[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    or value < 0 or value >= evaluation_start):
                raise ValueError("障壁/条件終了と回収終了は有限非負かつ評価開始よりstrict前が必要")
            row[key] = float(value)
        for key in MONEY_FIELDS:
            row[key] = decimal_text(money(row[key]))
        if row["filled"]:
            if row["outcome"] not in LABELS:
                raise ValueError("約定既知は250/125/期限が必要。未知を学習へ入れない")
        elif row["outcome"] != "無取引" or any(money(row[key]) != 0 for key in MONEY_FIELDS):
            raise ValueError("確定無取引は無取引結果と費用別回収すべて0が必要")
        if "sample_weight" in original and original["sample_weight"] != 0.5:
            raise ValueError("方向重みは0.5固定")
        identity = row["session"], row["slot_id"]
        pair = pairs.setdefault(identity, {})
        if row["side"] in pair:
            raise ValueError("同じ枠/方向の教師が重複")
        pair[row["side"]] = row
        canonical.append(row)
    for pair in pairs.values():
        if set(pair) != {-1, 1}:
            raise ValueError("共通可知教師は両方向pairが必要")
    ids = [{key: row[key] for key in ("session", "slot_id", "side")} for row in canonical]
    period = {"sessions": list(dict.fromkeys(row["session"] for row in canonical)),
        "max_label_end_time": max(row["end_time"] for row in canonical),
        "max_recovery_end_time": max(row["recovery_end_time"] for row in canonical),
        "evaluation_start": float(evaluation_start), "same_second_allowed": False}
    targets = [{**identity, "pnl5": row["pnl5"]} for identity, row in zip(ids, canonical)]
    return canonical, {"evaluation_start": float(evaluation_start), "input_pairs": len(pairs), "used_pairs": len(pairs), "excluded_pair_count": 0,
        "excluded_pairs": [], "direction_rows": len(canonical), "weight_per_direction": 0.5,
        "total_weight": len(canonical) * 0.5, "filled_direction_rows": sum(row["filled"] for row in canonical),
        "unfilled_direction_rows": sum(not row["filled"] for row in canonical), "row_ids": ids,
        "input_rows_sha256": fingerprint(canonical), "used_rows_sha256": fingerprint(canonical),
        "row_ids_sha256": fingerprint(ids), "target_rows_sha256": fingerprint(targets),
        "used_barrier_rows_sha256": fingerprint([barrier_projection(row) for row in canonical]),
        "period": period, "period_sha256": fingerprint(period), "canonical_fields": list(CANONICAL_FIELDS),
        "target": "pnl5", "target_dtype": "float64", "unknown_handling": "rootで共通pair除外済み、ここでは未知を拒否",
        "feature_missing_handling": "旧65全60特徴・共通可知の両方向pair。確定無取引0を回帰へ含め、先着分母から分離"}


def leaf_eligibility(node: dict, path: list[dict]) -> dict:
    """約定既知の支持と従来の複数技法資格を別々に求める。

    引数: node(dict)は約定支持をunique_slots/days/sessionsへ保存したnode、path(list[dict])は通過分岐。
    返り値: dictは旧65同型のscore/leaf_support/method_support/families。標本なしscoreは不適格。
    """
    return LEGACY.leaf_eligibility({**node, "score": 0.0 if node["score"] is None else node["score"]}, path)


def node_statistics(rows: list[dict], path: list[dict]) -> dict:
    """全可知回帰統計と、約定既知の先着統計を異なる分母で計数する。

    引数: rows(list[dict])は当node所属の正規化行、path(list[dict])は当nodeまでの分岐。
    返り値: dictは全/約定件数・支持・先着score・全/約定回収・Decimal MSE。先着標本なしを空回帰と区別する。
    """
    filled = [row for row in rows if row["filled"]]
    statistics = recovery_statistics(rows)
    statistics.pop("second_moment")
    filled_statistics = recovery_statistics(filled)
    unique = len({(row["session"], row["slot_id"]) for row in filled})
    days, sessions = len({row["session"][:10] for row in filled}), len({row["session"] for row in filled})
    score = sum(row["outcome"] == "250" for row in filled) / len(filled) if filled else None
    result = {"direction_rows": len(rows), "weighted_rows": len(rows) * 0.5, "total_weight": len(rows) * 0.5,
        "filled_direction_rows": len(filled), "unfilled_direction_rows": len(rows) - len(filled),
        "barrier_total_weight": len(filled) * 0.5, "success_weight": sum(row["outcome"] == "250" for row in filled) * 0.5,
        "score": score, "fill_rate": len(filled) / len(rows) if rows else None,
        "unique_slots": unique, "days": days, "sessions": sessions,
        "filled_unique_slots": unique, "filled_days": days, "filled_sessions": sessions,
        "all_unique_slots": len({(row["session"], row["slot_id"]) for row in rows}),
        "all_days": len({row["session"][:10] for row in rows}), "all_sessions": len({row["session"] for row in rows}),
        "barrier_gini": 2 * score * (1 - score) if score is not None else None,
        "data_absent": not rows, "barrier_data_absent": not filled,
        "recovery_filled": filled_statistics["recovery"], **statistics}
    eligibility = leaf_eligibility(result, path)
    result.update(leaf_support=eligibility["leaf_support"], method_support=eligibility["method_support"])
    return result


# ----------------------------------------
def legacy_model(model: dict) -> dict:
    """旧65のJSON走査へ政策名だけを局所射影する。

    引数: model(dict)はI0/C0の保存モデル。
    返り値: dictはpolicy=U0の浅い複写。元モデルや旧globalを変更しない。
    """
    if model.get("policy") not in POLICIES or len(model.get("feature_meta", [])) != 60:
        raise ValueError("I0/C0モデルの政策又は60列metadataが不正")
    return {**model, "policy": "U0"}


def walk(model: dict, values: list) -> tuple:
    """固定三nodeと58列子を旧65と同じfloat32で走査する。

    引数: model(dict)はI0/C0木、values(list)は60特徴。
    返り値: tuple[int,list[dict]]は葉IDと通過path。fitを呼ばない。
    """
    return LEGACY.walk(legacy_model(model), values)


def predict(model: dict, vectors: dict) -> dict:
    """旧65同型のpriorを返し、無取引だけの葉もscore未知としてWAITする。

    引数: model(dict)はI0/C0木、vectors(dict)は両方向60列又は両空list。
    返り値: dictはscores/leafs/side/winner_side/reason/eligibility。固定66選択からそのまま利用できる。
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
        unknown = node["barrier_data_absent"]
        if type(unknown) is not bool or unknown != (node["filled_direction_rows"] == 0):
            raise ValueError("約定先着標本なしの旗が不正")
        if unknown and node["score"] is not None:
            raise ValueError("約定先着標本なしはscore=Noneが必要")
        if not unknown and (isinstance(node["score"], bool) or not isinstance(node["score"], (int, float))
                or not math.isfinite(node["score"]) or not 0 <= node["score"] <= 1):
            raise ValueError("約定先着scoreが不正")
        if type(node["data_absent"]) is not bool or node["data_absent"] != (node["direction_rows"] == 0):
            raise ValueError("回帰行なしの旗が不正")
        scores[side], leafs[side] = node["score"], leaf
        eligibility[side] = None if unknown else leaf_eligibility(node, path)
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
    """全pair検査後の方向行をDIと対応episode有効四群へ分け、58列深さ2の回帰木を合成する。

    引数: rows(list[dict])は過去教師、feature_meta(list[dict])は60特徴、policy(str)はI0/C0、
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
        path = paths[node["id"]]
        ids = [{"session": row["session"], "slot_id": row["slot_id"], "side": row["side"]} for row in selected]
        moments[node["id"]] = recovery_statistics(selected)["second_moment"]
        node.update(path=path, methods=sorted({part["method"] for part in path}),
            families=sorted({part["family"] for part in path}), training_ids_sha256=fingerprint(ids),
            impurity_kind="squared_error", **node_statistics(selected, path))
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
        HERE.parent / "方向と再開確認/学習.py", HERE.parent / "局面強弱の複合確認/学習.py", HERE.parent / "量と価格進行/学習.py", LEGACY_PATH]
    model.update(schema_version=1, model_id=model_id, feature_meta_sha256=fingerprint(meta), parameters=parameters,
        subtree_parameters=child_parameters, structure=structure, rules=deepcopy(RULES),
        versions={"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        shared_source_sha256={path.relative_to(HERE.parents[1]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        training=training, nodes=nodes,
        interpretation="同60特徴/65固定構造で共通可知pairの即時I0又は条件C0教師を学習。回帰は無取引0を含む全方向、scoreと支持は約定既知だけ。全無取引葉は回帰既知でも先着score未知。方向順位と資格/DI0WAITは従来契約で、現在setup成立や未見収益を証明しない")
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))
