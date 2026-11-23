"""同じ共通準備教師で61列と直近進行64列を支持付き厳密列挙する。"""

from copy import deepcopy
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
LEGACY_PATH = HERE.parent / "支持を満たす技法分割/学習.py"
LEGACY_SHA256 = "a6d35a48ee3db75295401b0e91ba832e82ad2fe00592dcb8d5f88455fa538cc0"


def load_fixed(path: Path, digest: str, name: str):
    """固定純補助を固有名で読み、旧globalを変更しない。

    引数: path(Path)は固定コード、digest/name(str)はSHAとmodule名。
    返り値: ModuleTypeは読込結果。本物入力や教師を読まない。
    """
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("固定72学習コードのSHA256差")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LEGACY = load_fixed(LEGACY_PATH, LEGACY_SHA256, "直近進行73の固定72支持列挙")
POLICIES = {"B0": 4, "Q0": 4}
FEATURE_COUNTS = {"B0": 61, "Q0": 64}
EXTRA_META = [
    {"id": "F62", "name": "直近一足集中率", "method": "P05", "family": "price", "scale": "m03"},
    {"id": "F63", "name": "直近方向効率", "method": "P05", "family": "price", "scale": "m03"},
    {"id": "F64", "name": "最大一足の方向", "method": "P05", "family": "price", "scale": "m03"},
]
FIXED_NODES, SIDES = deepcopy(LEGACY.FIXED_NODES), LEGACY.SIDES
CANONICAL_FIELDS, FINGERPRINT_FIELDS = LEGACY.CANONICAL_FIELDS, LEGACY.FINGERPRINT_FIELDS
MONEY_FIELDS, DECIMAL_PRECISION = LEGACY.MONEY_FIELDS, LEGACY.DECIMAL_PRECISION
NUMERIC_TOLERANCE = deepcopy(LEGACY.NUMERIC_TOLERANCE)
ALGORITHM, THRESHOLD_RULE, TIE_RULE, GAIN_RULE = LEGACY.ALGORITHM, LEGACY.THRESHOLD_RULE, LEGACY.TIE_RULE, LEGACY.GAIN_RULE
fingerprint, money, decimal_text = LEGACY.fingerprint, LEGACY.money, LEGACY.decimal_text
node_statistics, leaf_eligibility = LEGACY.node_statistics, LEGACY.leaf_eligibility
support, descendants = LEGACY.support, LEGACY.descendants
paths_for = LEGACY.LEGACY.paths_for
RULES = deepcopy(LEGACY.RULES)
RULES.update({"政策深さ": deepcopy(POLICIES), "政策特徴数": deepcopy(FEATURE_COUNTS),
    "教師": "旧69C可知pairへ当時の直近窓commonreadyを先にANDし、B61/Q64に同じpair・同じ順序を渡す",
    "回収教師": "確定無取引0を含む同じpnl5。全行重み0.5、scoreと約定支持は約定既知だけ",
    "追加指標": "Q0だけ直近公開3分5差分C/E/Jを追加。全P05/priceで独立技法票を増やさない",
    "未知": "6連続公開終値又はTV>0が成立しなければ両政策共通ready外。学習内で0補完・追加pair除外・片側追加をしない",
    "候補約定支持": {policy: "両子がfilled unique枠60・日6・場10を満たす候補だけ" for policy in POLICIES},
    "比較の限定": "同じ支持付き厳密列挙のB61対Q64。旧72Sは保存参考で、新commonreadyによる準備差を別に記録する",
    "旧指紋": "base61_fingerprintsは同commonready教師の旧61射影。Q64の全特徴指紋と同一視しない"})
RULES["共通固定段"].update(子特徴数={policy: count - 2 for policy, count in FEATURE_COUNTS.items()},
    子特徴列index={policy: {"D0": [i for i in range(count) if i not in (0, 25)],
        "D1": [i for i in range(count) if i not in (0, 19)]} for policy, count in FEATURE_COUNTS.items()})
PRUNING_RULES = deepcopy(LEGACY.PRUNING_RULES)
PRUNING_RULES.update({"入力": "新73のB0生木61列又はQ0生木64列。親統計と探索来歴を保持し剪定時学習0",
    "予測": "新73の政策別61/64列JSON walk/predict。旧globalと元辞書を変更せず、64列を旧61走査へ渡さない"})


# ----------------------------------------
def child_indices(policy: str) -> dict:
    """政策列数から同じ固定DI枝の子候補列を作る。

    引数: policy(str)はB0又はQ0。
    返り値: dictはD0で0/25、D1で0/19を除く59又は62列。
    """
    if policy not in FEATURE_COUNTS:
        raise ValueError("政策はB0/Q0が必要")
    count = FEATURE_COUNTS[policy]
    return {"D0": [i for i in range(count) if i not in (0, 25)], "D1": [i for i in range(count) if i not in (0, 19)]}


def feature_metadata(meta: list[dict], policy: str) -> list[dict]:
    """旧61prefixと追加3項目の順・意味を厳密に確認する。

    引数: meta(list[dict])は61又は64項目、policy(str)はB0/Q0。
    返り値: list[dict]は深いコピー。新列を別familyへ数えない。
    """
    child_indices(policy)
    if not isinstance(meta, list) or len(meta) != FEATURE_COUNTS[policy]:
        raise ValueError("政策と61/64metadata長が異なる")
    LEGACY.feature_metadata(meta[:61], "S0")
    if policy == "Q0" and meta[61:] != EXTRA_META:
        raise ValueError("F62..64のmetadataが異なる")
    return deepcopy(meta)


def float32(values: list, feature_count: int = 64) -> list[float]:
    """旧61の制約を保持し、新C/E/Jを有限な同じfloat32へ写す。

    引数: values(list)は61又は64値、feature_count(int)は指定列数。
    返り値: list[float]は予測比較値。未知・bool・値域外を拒否し補完しない。
    """
    if type(feature_count) is not int or feature_count not in (61, 64) or not isinstance(values, list) or len(values) != feature_count:
        raise ValueError("特徴は指定どおり61又は64列が必要")
    result = LEGACY.float32(values[:61], 61)
    if feature_count == 64:
        extra = values[61:]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in extra):
            raise ValueError("C/E/Jは有限数値が必要")
        if not 0.2 <= extra[0] <= 1 or not -1 <= extra[1] <= 1 or extra[2] not in (-1, 0, 1):
            raise ValueError("C/E/Jの定義域が不正")
        result.extend(struct.unpack("!f", struct.pack("!f", float(v)))[0] for v in extra)
    return result


def barrier_projection(row: dict) -> dict:
    """全列canonicalから回収3値と終了時刻だけを除く。

    引数: row(dict)は正規化教師。
    返り値: dictは全61/64特徴を含む障壁指紋用辞書。
    """
    return LEGACY.barrier_projection(row)


def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 64) -> tuple:
    """同commonreadyの旧61pair検査を先行し、全列と旧射影の指紋を分ける。

    引数: rows(list[dict])は事前限定済みの同可知pair、evaluation_start(float)はstrict評価開始、feature_count(int)は61/64。
    返り値: tuple[list[dict],dict]は同順使用行と全列六指紋/base61/base60。学習内で追加除外しない。
    """
    if type(feature_count) is not int or feature_count not in (61, 64) or not isinstance(rows, list) or not rows:
        raise ValueError("空でない61/64教師が必要")
    projected = []
    for row in rows:
        if not isinstance(row, dict) or "features" not in row:
            raise ValueError("教師又はfeaturesが不正")
        float32(row["features"], feature_count)
        projected.append({**deepcopy(row), "features": deepcopy(row["features"][:61])})
    used61, old = LEGACY.prepare_rows(projected, evaluation_start, 61)
    if len(used61) != len(rows):
        raise ValueError("commonready後に旧validatorが行集合を変更した")
    used, training = deepcopy(used61), deepcopy(old)
    for item, origin in zip(used, rows):
        if any(item[k] != origin[k] for k in ("session", "slot_id", "side")):
            raise ValueError("教師の同順序が変化")
        item["features"] = [float(v) for v in origin["features"]]
    training.update(base61_fingerprints={key: old[key] for key in FINGERPRINT_FIELDS},
        input_rows_sha256=fingerprint(used), used_rows_sha256=fingerprint(used),
        used_barrier_rows_sha256=fingerprint([barrier_projection(row) for row in used]),
        feature_missing_handling="73の共通readyで先に両方向pairを限定。B61/Q64に同じ可知教師。学習内の追加除外・0補完なし")
    return used, training


def regressor_parameters(depth: int, policy: str = "B0") -> dict:
    """両政策へ同じ72S支持付き厳密列挙を保存する。

    引数: depth(int)は全体4又は子2、policy(str)はB0/Q0。
    返り値: dictは同アルゴリズム・乱数不使用・両子支持必須の引数。
    """
    child_indices(policy)
    return LEGACY.regressor_parameters(depth, "S0")


# ----------------------------------------
def walk(model: dict, values: list) -> tuple:
    """政策に対応するfloat32と保存閾値で生木/派生木を走査する。

    引数: model(dict)はB0/Q0木、values(list)は同61/64特徴。
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
    """従来同型priorを返し、生木と支持剪定後の木を同じ資格で扱う。

    引数: model(dict)はB0/Q0木、vectors(dict)は両方向61/64列又は両空list。
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
    """同じ四群と支持付き列挙で、61対64特徴だけを比較する。

    引数: rows(list[dict])は過去教師、feature_meta(list[dict])は61又は64metadata、evaluation_start(float)は評価開始、
        policy(str)はB0/Q0、model_id(str)は生木ID。
    返り値: dictはschema1の全node/探索記録/支持/回収/同教師指紋。sklearn.fitは呼ばない。
    """
    if policy not in POLICIES or not isinstance(model_id, str) or not model_id:
        raise ValueError("政策又はmodel_idが不正")
    meta = feature_metadata(feature_meta, policy)
    used, training = prepare_rows(rows, evaluation_start, FEATURE_COUNTS[policy])
    x = [float32(row["features"], FEATURE_COUNTS[policy]) for row in used]
    targets, scale = LEGACY.target_integers(used)
    nodes = [{"id": item["id"], "feature": item["index"], "feature_id": item["feature"],
        "family": meta[item["index"]]["family"], "threshold": item["threshold"],
        "left": 1 if item["id"] == 0 else None, "right": 2 if item["id"] == 0 else None,
        "split_search": None} for item in FIXED_NODES]
    membership = {0: list(range(len(used))), 1: [], 2: []}

    def build(indexes: list[int], projection: list[int], depth: int) -> int:
        """一つの学習子を深さ優先で作り、各停止理由も保存する。

        引数: indexes/projection(list[int])は所属行/候補列、depth(int)は子内深さ。
        返り値: intは追加した子木の根ID。元行順と同点順を保持する。
        """
        index = len(nodes)
        search, left, right = LEGACY.choose_split(used, x, targets, scale, indexes, projection, depth, "S0", meta)
        node = {"id": index, "feature": -2, "feature_id": None, "family": None,
            "threshold": -2.0, "left": -1, "right": -1, "split_search": search}
        nodes.append(node)
        membership[index] = indexes
        if search["selected"] is not None:
            selected = search["selected"]
            feature = selected["feature"]
            node.update(feature=feature, feature_id=meta[feature]["id"], family=meta[feature]["family"], threshold=selected["threshold"])
            node.update(left=build(left, projection, depth + 1), right=build(right, projection, depth + 1))
        return index

    training["partition"] = {}
    child_parameters = regressor_parameters(2, policy)
    for d in (0, 1):
        route, flag = ("R", 25) if d == 0 else ("T", 19)
        projection = child_indices(policy)[f"D{d}"]
        membership[1 + d] = [i for i in range(len(used)) if int(x[i][0] > 0.0) == d]
        for v in (0, 1):
            indexes = [i for i in membership[1 + d] if int(x[i][flag] > 0.5) == v]
            offset = build(indexes, projection, 0)
            nodes[1 + d]["left" if v == 0 else "right"] = offset
            ids = [{key: used[i][key] for key in ("session", "slot_id", "side")} for i in indexes]
            training["partition"][f"D{d}_V{v}"] = {"d": d, "v": v, "route": route, "policy": policy,
                "excluded_feature_indices": [0, flag], "child_feature_indices": list(projection),
                "direction_rows": len(indexes), "pair_unique": len({(used[i]["session"], used[i]["slot_id"]) for i in indexes}),
                "days": len({used[i]["session"][:10] for i in indexes}), "sessions": len({used[i]["session"] for i in indexes}),
                "row_ids_sha256": fingerprint(ids), "fit_performed": bool(indexes), "root": offset,
                "node_count": len(nodes) - offset, "fit_parameters": deepcopy(child_parameters)}
    paths = paths_for(nodes, meta)
    for node in nodes:
        selected = [used[i] for i in membership[node["id"]]]
        path = paths[node["id"]]
        ids = [{key: row[key] for key in ("session", "slot_id", "side")} for row in selected]
        node.update(path=path, methods=sorted({part["method"] for part in path}), families=sorted({part["family"] for part in path}),
            training_ids_sha256=fingerprint(ids), impurity_kind="squared_error", **node_statistics(selected, path))
    structure = {"kind": "fixed_direction_current_episode", "fixed_nodes": deepcopy(FIXED_NODES), "child_depth": 2,
        "child_features": FEATURE_COUNTS[policy] - 2, "child_feature_indices": child_indices(policy),
        "excluded_feature_indices": {"D0": [0, 25], "D1": [0, 19]}, "feature_count": FEATURE_COUNTS[policy],
        "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": ALGORITHM, "target": "pnl5"}
    training.update(target_dtype="Decimal金額の厳密10進整数", independent_regression_count=sum(bool(g["fit_performed"]) for g in training["partition"].values()),
        sklearn_fit_count=0)
    result = {"schema_version": 1, "policy": policy, "model_id": model_id, "feature_meta": meta,
        "feature_meta_sha256": fingerprint(meta), "parameters": regressor_parameters(4, policy),
        "subtree_parameters": child_parameters, "structure": structure, "rules": deepcopy(RULES),
        "versions": {"Python": platform.python_version(), "学習器": ALGORITHM, "算術": "整数/既約有理数", "sklearn.fit": 0},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "shared_source_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in [LEGACY_PATH]},
        "training": training, "nodes": nodes,
        "interpretation": "同commonready可知pair・同容量・同72S候補支持のB61対Q64。追加3列は同じ価格加工で独立技法票ではない。旧72全準備との同値や未知利益を主張しない"}
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


# ----------------------------------------
def validate_source(model: dict) -> dict:
    """新73の生木と固定三node・元path・約定支持の整合を確認する。

    引数: model(dict)は読み込んだ元の保存木。
    返り値: dict[int,list[dict]]は元path。利益・scoreを剪定前の選別に使わない。
    """
    if not isinstance(model, dict) or model.get("schema_version") != 1 or model.get("policy") not in POLICIES or "pruning" in model:
        raise ValueError("剪定元は新73の未剪定B0/Q0/schema1が必要")
    policy = model["policy"]
    count = FEATURE_COUNTS[policy]
    metadata = feature_metadata(model["feature_meta"], policy)
    structure, nodes = model["structure"], model["nodes"]
    if (not isinstance(nodes, list) or len(nodes) < 7 or structure["kind"] != "fixed_direction_current_episode"
            or structure["fixed_nodes"] != FIXED_NODES or structure["feature_count"] != count
            or structure["max_depth"] != 4 or structure["child_depth"] != 2 or structure["child_features"] != count - 2
            or structure["child_feature_indices"] != child_indices(policy)):
        raise ValueError("剪定元の65同型固定段と子59/62列の構造差")
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

    引数: model(dict)は新73のB0/Q0生木、model_id(str)は同政策の派生保存名、source_sha256(str)は呼出側が照合した元JSON byte SHA。
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
            "source_model_sha256": source_sha256, "source_model_content_sha256": fingerprint(model),
            "source_node_count": len(source_nodes), "new_node_count": len(nodes),
            "source_to_new": {str(old): mapping.get(old) for old in range(len(source_nodes))},
            "new_to_source": {str(new): old for old, new in mapping.items()},
            "decisions": sorted(decisions, key=lambda item: item["source_node_id"]), "partitions": partitions,
            "fit_count": 0, "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "shared_source_sha256": {LEGACY_PATH.relative_to(ROOT).as_posix(): LEGACY_SHA256}})
    return result


# ----------------------------------------
def synthetic_inputs() -> tuple:
    """既存の架空pairだけから同じ61教師と追加64教師を作る。

    引数: なし。
    返り値: tupleはB行/Q行/61meta/64meta/評価開始。実データ・本物モデル・成績は使わない。
    """
    rows, meta, evaluation, _ = LEGACY.synthetic_inputs()
    baseline, augmented = [], []
    for index, origin in enumerate(rows):
        row = deepcopy(origin)
        row["features"][60] = 1.0
        concentration = 0.75 if (index // 4) % 2 else 0.25
        value = 500 if row["side"] == 1 and concentration == 0.75 else -500
        row.update(outcome="250" if value > 0 else "125", filled=True,
            pnl0=str(value + 100), pnl5=str(value), pnl10=str(value - 100))
        baseline.append(deepcopy(row))
        row["features"].extend([concentration, row["side"] * 0.5, row["side"]])
        augmented.append(row)
    return baseline, augmented, meta, [*deepcopy(meta), *deepcopy(EXTRA_META)], evaluation


def self_test() -> dict:
    """架空教師だけで旧S再現・新列・型境界・支持と互換採否を検査する。

    引数: なし。
    返り値: dictは成功/テスト件数/照合数/不一致。旧コード又は本物入力を変更しない。
    """
    count, failures, cases = 0, [], []

    def check(condition: bool, title: str) -> None:
        """人工の一条件を記録する。

        引数: condition(bool)は成立、title(str)は説明。
        返り値: None。不一致は後でまとめて返す。
        """
        nonlocal count
        count += 1
        if not condition:
            failures.append(title)

    def rejects(function, title: str) -> None:
        """不正な人工入力が明示拒否されることを検査する。

        引数: function(Callable)は引数を閉じた処理、title(str)は説明。
        返り値: None。未知の0補完を成功扱いにしない。
        """
        try:
            function()
        except (ValueError, TypeError, KeyError):
            check(True, title)
        else:
            check(False, title)

    rows_b, rows_q, meta_b, meta_q, evaluation = synthetic_inputs()
    before = fingerprint([rows_b, rows_q, meta_b, meta_q])
    old = LEGACY.fit(rows_b, meta_b, evaluation, "S0", "旧72S_人工")
    base = fit(rows_b, meta_b, evaluation, "B0", "B0_人工_学習")
    augmented = fit(rows_q, meta_q, evaluation, "Q0", "Q0_人工_学習")
    check(base["nodes"] == old["nodes"], "同61教師で旧72S全node再現")
    check(base["parameters"] == old["parameters"] and base["subtree_parameters"] == old["subtree_parameters"], "同じ支持法・列挙引数")
    check(base["feature_meta"] == old["feature_meta"], "同61metadata")
    cases.append("旧SとBの同61再現")
    used_b, training_b = prepare_rows(rows_b, evaluation, 61)
    used_q, training_q = prepare_rows(rows_q, evaluation, 64)
    check(training_b["base61_fingerprints"] == training_q["base61_fingerprints"], "同commonreadyの61六hash")
    check(training_b["row_ids_sha256"] == training_q["row_ids_sha256"] and training_b["target_rows_sha256"] == training_q["target_rows_sha256"], "同教師IDと目的")
    check(training_b["input_rows_sha256"] != training_q["input_rows_sha256"], "全64と61の入力hashは別")
    check(training_b["base60_fingerprints"] == training_q["base60_fingerprints"], "旧60射影の指紋も保持")
    check(all({**row, "features": row["features"][:61]} == prior for row, prior in zip(used_q, used_b)), "全64canonicalの61射影一致")
    cases.append("同教師と全列指紋の分離")
    check(any(node["feature"] >= 61 for node in augmented["nodes"] if node["left"] >= 0), "新列を子の候補から選択")
    for model in (base, augmented):
        expected = 59 if model["policy"] == "B0" else 62
        check(model["structure"]["child_features"] == expected, "政策別子候補列数")
        for node in model["nodes"][3:]:
            search = node["split_search"]
            check(search["support_required"] is True, "両政策の候補支持は必須")
            if search["selected"]:
                check(search["selected"]["left"]["supported"] and search["selected"]["right"]["supported"], "両子filled支持")
        check(all(len(node["path"]) <= 4 for node in model["nodes"]), "全体深さ4")
    cases.append("新64列の選択と両子支持")
    for index, value in ((61, 0.199999), (61, 1.00001), (62, -1.01), (62, 1.01), (63, 0.5), (63, True), (61, None), (62, float("nan"))):
        values = deepcopy(rows_q[0]["features"])
        values[index] = value
        rejects(lambda values=values: float32(values, 64), "新列未知又は値域外拒否")
    rejects(lambda: float32(rows_b[0]["features"], 64), "61を64へ0補完しない")
    rejects(lambda: feature_metadata(meta_q, "B0"), "政策とmetadata長を混ぜない")
    rejects(lambda: feature_metadata([*meta_b, *reversed(EXTRA_META)], "Q0"), "新metadata順を保持")
    check(float32([*rows_b[0]["features"], 0.2, -1, 0], 64)[-3:] == [struct.unpack("!f", struct.pack("!f", 0.2))[0], -1.0, 0.0], "定義域の等号")
    check(float32([*rows_b[0]["features"], 0.2, 1e-50, 0], 64)[62] == 0.0, "float32零化と未知を分離")
    cases.append("新値域・未知拒否・float32")
    rejects(lambda: prepare_rows(rows_q[:-1], evaluation, 64), "片側教師を追加しない")
    future = deepcopy(rows_q)
    future[0]["recovery_end_time"] = evaluation
    rejects(lambda: prepare_rows(future, evaluation, 64), "回収確定のstrict過去境界")
    cases.append("pairと未来教師境界")
    # ----------------------------------------
    # 実装のwalkを期待値へ流用せず、Pythonの数値比較だけで保存木を別走査する。
    for model, rows in ((base, rows_b), (augmented, rows_q)):
        for row in rows:
            x, index = float32(row["features"], len(model["feature_meta"])), 0
            while model["nodes"][index]["left"] != -1:
                node = model["nodes"][index]
                index = node["left" if x[node["feature"]] <= node["threshold"] else "right"]
            actual, path = walk(model, row["features"])
            check(actual == index and path == model["nodes"][index]["path"], "全方向のJSON所属とpath")
    cases.append("全61/64方向の独立walk")
    source_digest = "a" * 64
    derived = {"B0": prune(base, "B0_人工", source_digest), "Q0": prune(augmented, "Q0_人工", source_digest)}
    old_derived = LEGACY.prune(old, "旧72S_派生人工", source_digest)
    check(derived["B0"]["nodes"] == old_derived["nodes"], "同61の支持剪定も旧Sと一致")
    for policy, model in derived.items():
        source = base if policy == "B0" else augmented
        check(model["training"] == source["training"], "元training証拠を保持")
        for node in model["nodes"]:
            prior = source["nodes"][node["source_node_id"]]
            for key in ("score", "recovery", "recovery_filled", "split_search", "filled_direction_rows", "regression_value", "impurity"):
                check(node[key] == prior[key], "派生の親統計と探索来歴保持")
    cases.append("61/64支持剪定と旧新ID")
    selector_path = HERE.parent / "適格方向の選択/選択.py"
    spec = importlib.util.spec_from_file_location("直近73人工の固定66選択", selector_path)
    selector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(selector)
    cal_path = HERE.parent / "条件入口の教師/検証.py"
    spec = importlib.util.spec_from_file_location("直近73人工の固定69回収集計", cal_path)
    calibration_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(calibration_module)
    for policy, model in derived.items():
        rows = rows_b if policy == "B0" else rows_q
        calibration = calibration_module.calibration_for(model)
        for offset in (0, 4):
            vectors = {"1": rows[offset]["features"], "-1": rows[offset + 1]["features"]}
            for mode in ("E0", "E1"):
                chosen = selector.predict(model, calibration, vectors, sys.modules[__name__], mode)
                reflected = selector.predict(model, calibration, {"1": vectors["-1"], "-1": vectors["1"]}, sys.modules[__name__], mode)
                check(chosen["side"] == -reflected["side"], "選択器の売買交換")
        check(predict(model, {"1": [], "-1": []})["reason"] == "特徴未準備WAIT", "両空は未知WAIT")
    cases.append("66選択と鏡像")
    unknown_rows = deepcopy(rows_q)
    for row in unknown_rows:
        if row["side"] == -1:
            row.update(filled=False, outcome="無取引", pnl0="0", pnl5="0", pnl10="0")
    unknown = fit(unknown_rows, meta_q, evaluation, "Q0", "Q0_片側未知人工")
    unknown_prior = predict(unknown, {"1": rows_q[4]["features"], "-1": rows_q[5]["features"]})
    check(unknown_prior["reason"] == "未学習枝WAIT" and unknown_prior["scores"]["-1"] is None, "片側score未知を0補完又は救済しない")
    cases.append("無取引と片側未知")
    check(before == fingerprint([rows_b, rows_q, meta_b, meta_q]), "元の教師/metadataを変更しない")
    cases.append("入力の深い独立性")
    return {"成功": not failures, "人工成功": not failures, "テスト件数": len(cases), "テスト群": cases,
        "照合項目数": count, "不一致数": len(failures), "不一致": failures,
        "新人工独自学習API": 3, "旧人工独自学習API": 1,
        "新人工独自子学習": sum(group["fit_performed"] for model in (base, augmented, unknown) for group in model["training"]["partition"].values()),
        "sklearnfit": 0, "分類器fit": 0, "本物入力読取": False, "本物fit": 0, "市場再生": False}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, allow_nan=False, indent=2))


