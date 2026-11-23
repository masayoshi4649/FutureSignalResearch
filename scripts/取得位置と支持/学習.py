"""同じ条件教師を60列/取得位置61列で学習し、約定支持だけで剪定する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import re
import struct
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEGACY_PATH = HERE.parent / "条件入口の教師/学習.py"
LEGACY_SHA256 = "f0569e4d25834b038caba57929f941367e22e397a64d8306a14406f41fef77de"
PRUNING_PATH = HERE.parent / "支持を保つ技法群/剪定.py"
PRUNING_SHA256 = "0584e185a87d3cc58f19aad464ecf7f81bfb9a7e04a4ea5ff6cea9be927a485c"


def load_fixed(path: Path, digest: str, name: str):
    """固定された旧純補助を固有名で読み込む。

    引数: path(Path)はコード、digest/name(str)は固定SHAと固有module名。
    返り値: ModuleTypeは旧globalを変更しない読込結果。
    """
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("旧純補助の固定SHA差:" + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LEGACY = load_fixed(LEGACY_PATH, LEGACY_SHA256, "取得位置71の固定69学習")
PRUNING = load_fixed(PRUNING_PATH, PRUNING_SHA256, "取得位置71の固定70支持規約")
BASE = LEGACY.BASE
POLICIES = {"B0": 4, "G0": 4}
FEATURE_COUNTS = {"B0": 60, "G0": 61}
POSITION_META = {"id": "F61", "name": "取得位置と上位端", "method": "P01", "family": "price", "scale": "m15"}
FIXED_NODES = deepcopy(PRUNING.FIXED_NODES)
SIDES, LABELS, SKLEARN_VERSION = LEGACY.SIDES, LEGACY.LABELS, LEGACY.SKLEARN_VERSION
MONEY_FIELDS, DECIMAL_PRECISION = LEGACY.MONEY_FIELDS, LEGACY.DECIMAL_PRECISION
CANONICAL_FIELDS, FINGERPRINT_FIELDS = LEGACY.CANONICAL_FIELDS, LEGACY.FINGERPRINT_FIELDS
NUMERIC_TOLERANCE = deepcopy(LEGACY.NUMERIC_TOLERANCE)
fingerprint, money, decimal_text = LEGACY.fingerprint, LEGACY.money, LEGACY.decimal_text
recovery_statistics, regressor_parameters, numeric_match = LEGACY.recovery_statistics, LEGACY.regressor_parameters, LEGACY.numeric_match
leaf_eligibility, node_statistics = LEGACY.leaf_eligibility, LEGACY.node_statistics
support, descendants = PRUNING.support, PRUNING.descendants
SHARED_SOURCE_PATHS = [ROOT / name for name in (
    "scripts/方向局面分岐/学習.py", "scripts/局所帯分岐/学習.py", "scripts/回収目的分岐/学習.py",
    "scripts/波の区間分離/学習.py", "scripts/現行経路の状態分岐/学習.py", "scripts/方向と再開確認/学習.py",
    "scripts/局面強弱の複合確認/学習.py", "scripts/量と価格進行/学習.py", "scripts/現在状態と量価格/学習.py")]
SHARED_SOURCE_PATHS += [LEGACY_PATH, PRUNING_PATH]
RULES = deepcopy(LEGACY.RULES)
RULES.update({"政策深さ": deepcopy(POLICIES), "政策特徴数": deepcopy(FEATURE_COUNTS),
    "回収教師": "固定69で作成済みの即時/条件共通可知pairからC条件教師を再用。新しいpair選別・追加除外なし",
    "教師": "固定69C条件教師の同一可知pair。B0/G0とも新fitし、B1/G1は同木の回収strict正条件",
    "追加指標": "G0だけF61=g=s*(M-E*)/D。買M=当時上位high/E*=ask、売M=low/E*=bid。計算はroot入力側",
    "未知": "旧60準備と共通可知pairを保持。取得位置の入力欠落/不一致はpreflight停止し、0補完・mask・clip・余分な符号gateなし",
    "取得位置の限定": "F61はP01/priceであり既存価格の加工と重なる。独立技法票や反転確認としない",
    "比較の限定": "B0は旧60の同演算、G0は同容量の子候補へF61だけを追加。同じ支持剪定で比較し未見利益を保証しない"})
RULES["共通固定段"].update(子特徴数={"B0": 58, "G0": 59},
    子特徴列index={policy: {"D0": [i for i in range(count) if i not in (0, 25)],
        "D1": [i for i in range(count) if i not in (0, 19)]} for policy, count in FEATURE_COUNTS.items()})
PRUNING_RULES = deepcopy(PRUNING.RULES)
PRUNING_RULES.update({"入力": "新71のB0生木60列又はG0生木61列。同政策の派生木へ変換し、剪定時fit0",
    "予測": "新71の同政策・同列数のJSON walk/predictで生木と派生木を扱う。旧globalや元辞書を変更しない"})


# ----------------------------------------
def child_indices(policy: str) -> dict:
    """政策の列数からDI枝別の子候補列を確定する。

    引数: policy(str)はB0又はG0。
    返り値: dict[str,list[int]]はD0で0/25、D1で0/19を除く58又は59列。
    """
    if policy not in FEATURE_COUNTS:
        raise ValueError("政策はB0/G0が必要")
    count = FEATURE_COUNTS[policy]
    return {"D0": [i for i in range(count) if i not in (0, 25)],
        "D1": [i for i in range(count) if i not in (0, 19)]}


def feature_metadata(feature_meta: list[dict], policy: str) -> list[dict]:
    """旧60metadataを保持し、G0だけ末尾の取得位置を厳密検査する。

    引数: feature_meta(list[dict])は60又は61項目、policy(str)はB0/G0。
    返り値: list[dict]は深いコピー。F61を別familyや独立技法へ数えない。
    """
    if policy not in POLICIES or not isinstance(feature_meta, list) or len(feature_meta) != FEATURE_COUNTS[policy]:
        raise ValueError("政策と60/61metadataの差")
    base = LEGACY.feature_metadata(feature_meta[:60], "C0")
    if policy == "G0":
        if feature_meta[60] != POSITION_META:
            raise ValueError("F61の5項目metadataが不一致")
        base.append(deepcopy(POSITION_META))
    return base


def float32(values: list, feature_count: int = 60) -> list[float]:
    """旧60の値域/共同maskと追加gの有限float32を確認する。

    引数: values(list)は60又は61値、feature_count(int)は政策の列数。
    返り値: list[float]はfloat32値。gをclipせず未知やoverflowを拒否する。
    """
    if type(feature_count) is not int or feature_count not in (60, 61) or not isinstance(values, list) or len(values) != feature_count:
        raise ValueError("特徴は指定どおり60又は61列が必要")
    result = LEGACY.float32(values[:60], 60)
    if feature_count == 61:
        g = values[60]
        if isinstance(g, bool) or not isinstance(g, (int, float)) or not math.isfinite(g):
            raise ValueError("取得位置gは有限数が必要")
        try:
            value = struct.unpack("!f", struct.pack("!f", float(g)))[0]
        except (OverflowError, struct.error) as exc:
            raise ValueError("取得位置gのfloat32表示範囲外") from exc
        if not math.isfinite(value):
            raise ValueError("取得位置gのfloat32有限値不成立")
        result.append(value)
    return result


def barrier_projection(row: dict) -> dict:
    """政策列数を保った障壁側canonicalを作る。

    引数: row(dict)は正規化された全60又は61教師行。
    返り値: dictは回収3値と回収終了だけを除いた列。
    """
    return {key: deepcopy(row[key]) for key in CANONICAL_FIELDS if key not in (*MONEY_FIELDS, "recovery_end_time")}


def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 60) -> tuple:
    """旧60投影を69で検査し、同じ可知pairの60/61canonicalを保存する。

    引数: rows(list[dict])は過去の条件教師、evaluation_start(float)は評価開始、feature_count(int)は60/61。
    返り値: tuple[list[dict],dict]は同順使用行と六指紋/base60六指紋。追加除外しない。
    """
    if type(feature_count) is not int or feature_count not in (60, 61) or not isinstance(rows, list) or not rows:
        raise ValueError("空でない60/61教師listが必要")
    projected = []
    for original in rows:
        if not isinstance(original, dict) or "features" not in original:
            raise ValueError("教師又は特徴が不正")
        float32(original["features"], feature_count)
        projected.append({**deepcopy(original), "features": deepcopy(original["features"][:60])})
    used60, old_training = LEGACY.prepare_rows(projected, evaluation_start, 60)
    used, training = deepcopy(used60), deepcopy(old_training)
    for row, original in zip(used, rows):
        row["features"] = [float(value) for value in original["features"]]
    training.update(base60_fingerprints={key: old_training[key] for key in FINGERPRINT_FIELDS},
        input_rows_sha256=fingerprint(used), used_rows_sha256=fingerprint(used),
        used_barrier_rows_sha256=fingerprint([barrier_projection(row) for row in used]),
        feature_missing_handling="旧69C共通可知の同pair。B60/G61とも追加除外なし、g欠測は拒否")
    return used, training


def walk(model: dict, values: list) -> tuple:
    """政策に対応するfloat32と保存閾値で生木/派生木を走査する。

    引数: model(dict)はB0/G0木、values(list)は同60/61特徴。
    返り値: tuple[int,list[dict]]は到達葉と根からの全path。fitしない。
    """
    policy = model.get("policy")
    metadata = feature_metadata(model["feature_meta"], policy)
    x = float32(values, FEATURE_COUNTS[policy])
    nodes, index, path, visited = model["nodes"], 0, [], set()
    while True:
        if type(index) is not int or not 0 <= index < len(nodes) or index in visited:
            raise ValueError("JSON木の範囲又は循環が不正")
        visited.add(index)
        node = nodes[index]
        if node["id"] != index:
            raise ValueError("JSON木の連番差")
        if node["left"] == node["right"] == -1:
            return index, path
        f, threshold = node["feature"], node["threshold"]
        if (type(f) is not int or not 0 <= f < len(metadata) or isinstance(threshold, bool)
                or not isinstance(threshold, (int, float)) or not math.isfinite(threshold)):
            raise ValueError("保存分割特徴又は閾値が不正")
        meta = metadata[f]
        if node["feature_id"] != meta["id"] or node["family"] != meta["family"]:
            raise ValueError("分割metadata差")
        branch = "left" if x[f] <= threshold else "right"
        path.append({"node": index, "feature": f, "feature_id": meta["id"], "method": meta["method"],
            "family": meta["family"], "threshold": threshold, "comparison": "<=" if branch == "left" else ">", "branch": branch})
        index = node[branch]


def predict(model: dict, vectors: dict) -> dict:
    """旧69同型priorを返し、生木と支持剪定後の木を同じ資格で扱う。

    引数: model(dict)はB0/G0木、vectors(dict)は両方向60/61列又は両空list。
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
def fit(rows: list[dict], feature_meta: list[dict], evaluation_start: float, policy: str, model_id: str) -> dict:
    """同条件pairをDIと対応episode四群へ分け、60/61入力の子深さ2を学習する。

    引数: rows(list[dict])は過去教師、feature_meta(list[dict])は60/61特徴、policy(str)はB0/G0、
        model_id(str)は保存ID、evaluation_start(float)は評価開始秒。
    返り値: dictは固定三node・空群を含む全node/支持/障壁率/回収/指紋の純JSON。
        本物fitはrootだけが実行する。
    """
    if policy not in POLICIES or not isinstance(model_id, str) or not model_id:
        raise ValueError("政策又はmodel_idが不正")
    meta = feature_metadata(feature_meta, policy)
    count = FEATURE_COUNTS[policy]
    used, training = prepare_rows(rows, evaluation_start, count)
    import numpy as np
    import scipy
    import sklearn
    from sklearn.tree import DecisionTreeRegressor

    if sklearn.__version__ != SKLEARN_VERSION:
        raise RuntimeError("scikit-learnは固定1.9.1が必要")
    parameters, child_parameters = regressor_parameters(4), regressor_parameters(2)
    x = np.asarray([float32(row["features"], count) for row in used], dtype=np.float32)
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
        projection = child_indices(policy)[f"D{d}"]
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
        "child_features": count - 2, "child_feature_indices": child_indices(policy),
        "excluded_feature_indices": {"D0": [0, 25], "D1": [0, 19]}, "feature_count": count,
        "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"}
    sources = SHARED_SOURCE_PATHS
    model.update(schema_version=1, model_id=model_id, feature_meta_sha256=fingerprint(meta), parameters=parameters,
        subtree_parameters=child_parameters, structure=structure, rules=deepcopy(RULES),
        versions={"Python": platform.python_version(), "scikit-learn": sklearn.__version__, "NumPy": np.__version__, "SciPy": scipy.__version__},
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        shared_source_sha256={path.relative_to(HERE.parents[1]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        training=training, nodes=nodes,
        interpretation="同69C条件教師・同固定段でB60と取得位置G61を別fit。回帰は無取引0込み、先着scoreと支持は約定既知だけ。gは既存P01/priceで独立票とせず、同支持剪定後の経済的優位は未検証")
    return json.loads(json.dumps(model, ensure_ascii=False, allow_nan=False))


# ----------------------------------------
def paths_for(nodes: list[dict], metadata: list[dict]) -> dict:
    """親子構造だけから全残存pathを生成し、IDとmetadataを対応させる。

    引数: nodes(list[dict])は昇順連番の木、metadata(list[dict])は同60/61列。
    返り値: dict[int,list[dict]]は各nodeの根からのpath。多重親や循環を拒否する。
    """
    paths = {0: []}
    for index, node in enumerate(nodes):
        if type(node.get("id")) is not int or node["id"] != index or index not in paths:
            raise ValueError("node順・連番又は到達性が不正")
        left, right = node.get("left"), node.get("right")
        if type(left) is not int or type(right) is not int:
            raise ValueError("子IDはintが必要")
        if left == right == -1:
            if (node["feature"], node["feature_id"], node["family"], node["threshold"]) != (-2, None, None, -2.0):
                raise ValueError("葉のsentinelが不正")
            continue
        feature, threshold = node.get("feature"), node.get("threshold")
        if (type(feature) is not int or not 0 <= feature < len(metadata) or isinstance(threshold, bool)
                or not isinstance(threshold, (int, float)) or not math.isfinite(threshold)):
            raise ValueError("分割特徴又は閾値が不正")
        meta = metadata[feature]
        if node["feature_id"] != meta["id"] or node["family"] != meta["family"]:
            raise ValueError("分割metadataが不一致")
        for branch, comparison in (("left", "<="), ("right", ">")):
            child = node[branch]
            if not index < child < len(nodes) or child in paths:
                raise ValueError("子ID順・多重親又は循環が不正")
            paths[child] = [*paths[index], {"node": index, "feature": feature, "feature_id": meta["id"],
                "method": meta["method"], "family": meta["family"], "threshold": threshold,
                "comparison": comparison, "branch": branch}]
    if set(paths) != set(range(len(nodes))):
        raise ValueError("到達しないnodeがある")
    return paths


def validate_source(model: dict) -> dict:
    """新71の生木と固定三node・元path・約定支持の整合を確認する。

    引数: model(dict)は読み込んだ元の保存木。
    返り値: dict[int,list[dict]]は元path。利益・scoreを剪定前の選別に使わない。
    """
    if not isinstance(model, dict) or model.get("schema_version") != 1 or model.get("policy") not in POLICIES or "pruning" in model:
        raise ValueError("剪定元は新71の未剪定B0/G0/schema1が必要")
    policy = model["policy"]
    count = FEATURE_COUNTS[policy]
    metadata = feature_metadata(model["feature_meta"], policy)
    structure, nodes = model["structure"], model["nodes"]
    if (not isinstance(nodes, list) or len(nodes) < 7 or structure["kind"] != "fixed_direction_current_episode"
            or structure["fixed_nodes"] != FIXED_NODES or structure["feature_count"] != count
            or structure["max_depth"] != 4 or structure["child_depth"] != 2 or structure["child_features"] != count - 2
            or structure["child_feature_indices"] != child_indices(policy)):
        raise ValueError("剪定元の65同型固定段と子58/59列の構造差")
    paths = paths_for(nodes, metadata)
    if (nodes[0]["left"], nodes[0]["right"]) != (1, 2):
        raise ValueError("固定根の両子は1/2が必要")
    for index, node in enumerate(nodes):
        if node["path"] != paths[index] or len(paths[index]) > 4:
            raise ValueError("元path又は全深さ4が不正")
        counts = support(node)
        if type(node["leaf_support"]) is not bool or node["leaf_support"] != counts["supported"]:
            raise ValueError("元の約定支持旗と件数が不一致")
        if index < 3:
            fixed = FIXED_NODES[index]
            if (node["feature"], node["threshold"]) != (fixed["index"], fixed["threshold"]) or node["left"] == -1:
                raise ValueError("固定三nodeの分割が必要")
        elif node["left"] != -1:
            branch = "D1" if paths[index][0]["branch"] == "right" else "D0"
            if node["feature"] not in child_indices(policy)[branch]:
                raise ValueError("旧学習子の特徴投影差")
    groups = model["training"]["partition"]
    if set(groups) != {f"D{d}_V{v}" for d in (0, 1) for v in (0, 1)}:
        raise ValueError("元の四学習群が必要")
    for d in (0, 1):
        for v in (0, 1):
            group = groups[f"D{d}_V{v}"]
            root = nodes[1 + d]["right" if v else "left"]
            if group["root"] != root or group["node_count"] != len(descendants(nodes, root)):
                raise ValueError("元trainingの子root又はnode数が不一致")
    return paths


# ----------------------------------------
def prune(model: dict, model_id: str, source_sha256: str) -> dict:
    """約定支持のみで下から両側統合し、残存IDと判断履歴を保存する。

    引数: model(dict)は新71のB0/G0生木、model_id(str)は同政策の派生保存名、source_sha256(str)は呼出側が照合した元JSON byte SHA。
    返り値: dictはschema1の同政策派生木。親統計と元trainingを保持し、旧新対応・剪定理由・新pathを付加する。
    """
    if not isinstance(model_id, str) or not model_id or not isinstance(source_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None:
        raise ValueError("新model IDと元JSONの64桁SHA256が必要")
    validate_source(model)
    source_nodes, collapsed, decisions = model["nodes"], set(), []

    def reduce(index: int) -> list[int]:
        """子を先に簡約し、支持不足の終端があれば両側を親へまとめる。

        引数: index(int)は元node番号。
        返り値: list[int]は当該子木の剪定後終端旧ID。固定段は統合しない。
        """
        node = source_nodes[index]
        if node["left"] == -1:
            return [index]
        terminals = sorted([*reduce(node["left"]), *reduce(node["right"])])
        if index < 3:
            return terminals
        details = [{"source_node_id": leaf, **support(source_nodes[leaf])} for leaf in terminals]
        keep = all(item["supported"] for item in details)
        if not keep:
            collapsed.add(index)
        result = terminals if keep else [index]
        decisions.append({"source_node_id": index, "action": "保持" if keep else "両側統合",
            "terminal_source_ids": terminals, "terminal_support": details,
            "result_terminal_source_ids": result,
            "reason": "剪定後の両側全終端が約定支持を満たす" if keep else "剪定後の終端に約定支持不足があるため両側を親へ統合"})
        return result

    reduce(0)
    reachable, stack = set(), [0]
    while stack:
        index = stack.pop()
        reachable.add(index)
        node = source_nodes[index]
        if node["left"] != -1 and index not in collapsed:
            stack.extend((node["left"], node["right"]))
    retained = sorted(reachable)
    mapping = {old: new for new, old in enumerate(retained)}
    result, nodes = deepcopy(model), []
    for old in retained:
        node = deepcopy(source_nodes[old])
        node.update(id=mapping[old], source_node_id=old)
        if old in collapsed:
            node.update(feature=-2, feature_id=None, family=None, threshold=-2.0, left=-1, right=-1)
        elif node["left"] != -1:
            node.update(left=mapping[node["left"]], right=mapping[node["right"]])
        nodes.append(node)
    paths = paths_for(nodes, result["feature_meta"])
    for node in nodes:
        node["path"] = paths[node["id"]]
    for item in decisions:
        old = item["source_node_id"]
        item.update(retained_in_final=old in reachable, split_retained_in_final=old in reachable and old not in collapsed)
    partitions = {}
    for key, original in model["training"]["partition"].items():
        members = descendants(source_nodes, original["root"])
        partitions[key] = {"source_root": original["root"], "source_node_count": original["node_count"],
            "new_root": mapping[original["root"]], "new_node_count": sum(index in reachable for index in members)}
    result.update(model_id=model_id, policy=model["policy"], source_model_id=model["model_id"], source_model_sha256=source_sha256,
        nodes=nodes, pruning={"rules": deepcopy(PRUNING_RULES), "source_model_id": model["model_id"],
            "source_model_sha256": source_sha256, "source_model_content_sha256": LEGACY.fingerprint(model),
            "source_node_count": len(source_nodes), "new_node_count": len(nodes),
            "source_to_new": {str(old): mapping.get(old) for old in range(len(source_nodes))},
            "new_to_source": {str(new): old for old, new in mapping.items()},
            "decisions": sorted(decisions, key=lambda item: item["source_node_id"]), "partitions": partitions,
            "fit_count": 0, "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "shared_source_sha256": {LEGACY_PATH.relative_to(ROOT).as_posix(): LEGACY_SHA256, PRUNING_PATH.relative_to(ROOT).as_posix(): PRUNING_SHA256}})
    return result


