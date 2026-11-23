"""固定69の条件教師木を、訓練の約定支持だけで下から剪定する。"""

from copy import deepcopy
import hashlib
import importlib.util
import math
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
LEGACY_PATH = HERE.parent / "条件入口の教師/学習.py"
LEGACY_SHA256 = "f0569e4d25834b038caba57929f941367e22e397a64d8306a14406f41fef77de"
if hashlib.sha256(LEGACY_PATH.read_bytes()).hexdigest() != LEGACY_SHA256:
    raise ValueError("固定69学習コードのSHA256差")
SPEC = importlib.util.spec_from_file_location("支持剪定70が固定参照する69学習", LEGACY_PATH)
LEGACY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LEGACY
SPEC.loader.exec_module(LEGACY)
POLICIES = ("P0",)
FIXED_NODES = [{"id": 0, "feature": "F01", "index": 0, "threshold": 0.0},
    {"id": 1, "feature": "F26", "index": 25, "threshold": 0.5},
    {"id": 2, "feature": "F20", "index": 19, "threshold": 0.5}]
RULES = {
    "入力": "固定69のC0保存木だけ。全60特徴・教師・親統計を保持し、新fit0",
    "約定支持": {"unique枠": 60, "日": 6, "場": 10},
    "固定段": "旧node0/1/2は分割を維持。四つのDI×対応episode群を統合しない",
    "順序": "各子木を下から先に剪定し、その結果の全終端葉を判定する",
    "保持": "剪定後の両側すべての終端葉が約定支持を満たす場合だけ学習分割を保持",
    "統合": "一つでも約定支持不足なら両側を親へ統合。片側だけ残さず、祖先でも再判定する",
    "固定群不足": "四群の親自身が支持不足でも固定段を越えて統合しない。従来の支持不足WAITを維持",
    "決定へ不使用": ["score", "回収額", "回収平均", "MSE", "評価到達", "評価成績", "技法資格"],
    "統計": "統合先の旧親統計を再用。子葉平均の平均や教師再生成を行わない",
    "新ID": "残存旧IDの昇順を0から連番。旧0/1/2は新0/1/2を維持",
    "旧学習証拠": "trainingとparameters/structureは元の学習証拠。新配置はpruning.partitionsと対応表を参照",
    "予測": "局所policy=C0の複写で固定69walk/predictへ委譲。旧globalや元辞書を変更しない",
    "維持": "先着1/3・約定60枠6日10場・複数技法・過去主回収strict正・66選択・68入口・O49出口を緩めない",
}


# ----------------------------------------
def support(node: dict) -> dict:
    """訓練の約定unique枠・日・場だけで支持を確認する。

    引数: node(dict)は固定69の統計を持つnode。
    返り値: dictはunique_slots/days/sessions/supported。scoreや利益を読まない。
    """
    counts = {key: node[key] for key in ("unique_slots", "days", "sessions")}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("約定支持の件数は非負intが必要")
    return {**counts, "supported": counts["unique_slots"] >= 60 and counts["days"] >= 6 and counts["sessions"] >= 10}


def paths_for(nodes: list[dict], metadata: list[dict]) -> dict:
    """親子構造だけから全残存pathを生成し、IDとmetadataを対応させる。

    引数: nodes(list[dict])は昇順連番の木、metadata(list[dict])は同60列。
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
        if (type(feature) is not int or not 0 <= feature < 60 or isinstance(threshold, bool)
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


def descendants(nodes: list[dict], root: int) -> list[int]:
    """旧子木の全IDを構造から取得する。

    引数: nodes(list[dict])は検査済み木、root(int)は子木の根。
    返り値: list[int]は旧ID昇順。統計や予測値を参照しない。
    """
    stack, result = [root], []
    while stack:
        index = stack.pop()
        result.append(index)
        if nodes[index]["left"] != -1:
            stack.extend((nodes[index]["left"], nodes[index]["right"]))
    return sorted(result)


def validate_source(model: dict) -> dict:
    """固定69の全60C0木と固定三node・元path・約定支持の整合を確認する。

    引数: model(dict)は読み込んだ元の保存木。
    返り値: dict[int,list[dict]]は元path。利益・scoreを剪定前の選別に使わない。
    """
    if not isinstance(model, dict) or model.get("schema_version") != 1 or model.get("policy") != "C0":
        raise ValueError("剪定元は固定69のC0/schema1が必要")
    metadata = LEGACY.feature_metadata(model["feature_meta"], "C0")
    structure, nodes = model["structure"], model["nodes"]
    if (not isinstance(nodes, list) or len(nodes) < 7 or structure["kind"] != "fixed_direction_current_episode"
            or structure["fixed_nodes"] != FIXED_NODES or structure["feature_count"] != 60
            or structure["max_depth"] != 4 or structure["child_depth"] != 2 or structure["child_features"] != 58
            or structure["child_feature_indices"] != LEGACY.CHILD_FEATURE_INDICES):
        raise ValueError("剪定元の65同型固定段と子58列の構造差")
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
            if node["feature"] not in LEGACY.CHILD_FEATURE_INDICES[branch]:
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

    引数: model(dict)は固定69C0木、model_id(str)はP0の保存名、source_sha256(str)は呼出側が照合した元JSON byte SHA。
    返り値: dictはschema1/P0木。親統計と元trainingを保持し、旧新対応・剪定理由・新pathを付加する。
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
    result.update(model_id=model_id, policy="P0", source_model_id=model["model_id"], source_model_sha256=source_sha256,
        nodes=nodes, pruning={"rules": deepcopy(RULES), "source_model_id": model["model_id"],
            "source_model_sha256": source_sha256, "source_model_content_sha256": LEGACY.fingerprint(model),
            "source_node_count": len(source_nodes), "new_node_count": len(nodes),
            "source_to_new": {str(old): mapping.get(old) for old in range(len(source_nodes))},
            "new_to_source": {str(new): old for old, new in mapping.items()},
            "decisions": sorted(decisions, key=lambda item: item["source_node_id"]), "partitions": partitions,
            "fit_count": 0, "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "shared_source_sha256": {LEGACY_PATH.relative_to(HERE.parents[1]).as_posix(): LEGACY_SHA256}})
    return result


def legacy_model(model: dict) -> dict:
    """新P0を固定69C0の純予測へ局所射影する。

    引数: model(dict)は剪定後のP0木。
    返り値: dictはpolicyだけC0の浅い写し。元モデルと旧globalは変更しない。
    """
    if not isinstance(model, dict) or model.get("policy") not in POLICIES:
        raise ValueError("剪定後policyはP0が必要")
    return {**model, "policy": "C0"}


def walk(model: dict, values: list) -> tuple:
    """残存pathを固定69と同じfloat32規約で走査する。

    引数: model(dict)はP0木、values(list)は60特徴。
    返り値: tuple[int,list[dict]]は新IDの到達葉と全path。
    """
    return LEGACY.walk(legacy_model(model), values)


def predict(model: dict, vectors: dict) -> dict:
    """剪定後の同統計と従来資格から固定66互換priorを返す。

    引数: model(dict)はP0木、vectors(dict)は両方向60列又は両空list。
    返り値: dictは固定69同型prior。支持/score/未知/同点の閾値を変更しない。
    """
    return LEGACY.predict(legacy_model(model), vectors)
