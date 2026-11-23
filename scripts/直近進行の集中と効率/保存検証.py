"""73の共通準備・直近進行・支持付き厳密分割と保存運用を独立照合する。"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import struct
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00073_直近の集中と方向効率を組み合わせる"
WORK = ROOT / "work/直近進行の集中と効率/00073"
OLD = ROOT / "study/00072_分割候補から約定支持を確保する"
OLDWORK = ROOT / "work/支持を満たす技法分割/00072"
LEDGER = ROOT / "work/支持を満たす技法分割/72完了記録.json"
LEDGER_SHA = "2ded91aa2154f6a6202bfcc224126f88433f013498d49ab9a7dfb7850945fe1a"
POLICIES, CONTROLS = ("B0", "B1", "Q0", "Q1"), ("S0", "S1")
MODEL_POLICIES = ("B0", "Q0")
COUNTS = {"B0": 61, "Q0": 64}
PERIODS = ("学習", "条件選択", "後続検査")


def load_fixed(path: Path, name: str, digest: str | None = None):
    """固定純補助だけを固有名で読み、大域値を変更しない。

    引数: path(Path)は固定コード、name(str)はmodule名、digest(str|None)は必要なSHA。
    返り値: ModuleTypeは読込結果。新主・学習・Engineを正式期待値へ読み込まない。
    """
    if digest is not None and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("固定監査コードの変更:" + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R71 = load_fixed(HERE.parent / "取得位置と支持/保存検証.py", "支持候補72の固定71監査",
    "ff00114e24c905fb35f8c2d94e9a2b31ef4552a3d767f150321247e09866bfe9")
R70, R69, R68, R66, R65 = R71.R70, R71.R69, R71.R68, R71.R66, R71.R65
A, P, R55, R56 = R71.A, R71.P, R71.R55, R71.R56
fingerprint = R71.fingerprint
BINDING = R71.BINDING
TEACHER_STUDY, TEACHER_WORK = R71.TEACHER_STUDY, R71.TEACHER_WORK


# ----------------------------------------
R72 = load_fixed(HERE.parent / "支持を満たす技法分割/保存検証.py", "直近73の固定72監査", "0f980f7e628881e69c7c70702e257488112caddcab4977e45d1f9e074280fa1b")
INPUT_AUDIT = load_fixed(HERE / "入力監査.py", "直近73の独立入力監査", "4e2fbe0500df8ca76f0744ce7850847a78af317b80c5cb33e880a44babc86507")
FINGERPRINT_FIELDS = R71.FINGERPRINT_FIELDS
OLD_L_PATH = ROOT / "scripts/支持を満たす技法分割/学習.py"
OLD_L_SHA = "a6d35a48ee3db75295401b0e91ba832e82ad2fe00592dcb8d5f88455fa538cc0"
EXTRA_META = [{"id": f"F{i}", "name": name, "method": "P05", "family": "price", "scale": "m03"}
    for i, name in ((62, "直近一足集中率"), (63, "直近方向効率"), (64, "最大一足の方向"))]


def metadata(policy: str = "B0") -> list[dict]:
    """旧61の独立定数と新3項目を政策の列数へ組み合わせる。

    引数: policy(str)はB0/Q0。
    返り値: list[dict]は61又は64metadata。新I/Lから取得しない。
    """
    if policy not in COUNTS:
        raise ValueError("政策はB0/Q0が必要")
    return R71.metadata("G0") + (deepcopy(EXTRA_META) if policy == "Q0" else [])


def float32(values: list, count: int) -> list[float]:
    """旧61とC/E/Jの定義域を検査して独立float32へ写す。

    引数: values(list)は特徴、count(int)は61/64。
    返り値: list[float]は比較値。未知の0補完やclipを行わない。
    """
    if count not in (61, 64) or type(count) is not int or not isinstance(values, list) or len(values) != count:
        raise ValueError("61/64特徴長が不正")
    result = R71.float32(values[:61], 61)
    if count == 64:
        c, e, j = values[61:]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (c, e, j)):
            raise ValueError("直近特徴は有限数値が必要")
        if not .2 <= c <= 1 or not -1 <= e <= 1 or j not in (-1, 0, 1):
            raise ValueError("直近特徴の値域が不正")
        result.extend(struct.unpack("!f", struct.pack("!f", float(v)))[0] for v in (c, e, j))
    return result



# ----------------------------------------
def walk(model: dict, values: list) -> tuple:
    """61/64列をfloat32で独立走査し、保存pathと全所属nodeを返す。

    引数: model(dict)はraw又は派生保存木、values(list)は対応列数。
    返り値: tuple[int,list,list]はleaf/path/全訪問ID。新walkやpredictは呼ばない。
    """
    count = len(model["feature_meta"])
    values, index, path, visited = float32(values, count), 0, [], []
    while True:
        if type(index) is not int or not 0 <= index < len(model["nodes"]) or index in visited:
            raise ValueError("保存木の循環又は範囲外")
        node = model["nodes"][index]
        if node["id"] != index:
            raise ValueError("保存node ID差")
        visited.append(index)
        if node["left"] == node["right"] == -1:
            return index, path, visited
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < count or not A.finite(node["threshold"]):
            raise ValueError("分割値が不正")
        branch = "left" if values[feature] <= node["threshold"] else "right"
        meta = model["feature_meta"][feature]
        path.append({"node": index, "feature": feature, "feature_id": meta["id"], "method": meta["method"], "family": meta["family"],
            "threshold": node["threshold"], "comparison": "<=" if branch == "left" else ">", "branch": branch})
        index = node[branch]


# ----------------------------------------
def support_of(rows: list[dict]) -> dict:
    """約定方向行だけで三種類の支持を数える。

    引数: rows(list[dict])は独立canonical教師の部分集合。
    返り値: dictは全方向行とfilled unique枠/日/場・支持旗。無取引は支持に足さない。
    """
    filled = [row for row in rows if row["filled"]]
    slots = len({(row["session"], row["slot_id"]) for row in filled})
    days = len({row["session"][:10] for row in filled})
    sessions = len({row["session"] for row in filled})
    return {"direction_rows": len(rows), "unique_slots": slots, "days": days, "sessions": sessions,
        "supported": slots >= 60 and days >= 6 and sessions >= 10}


# ----------------------------------------
def fraction_dict(value: Fraction) -> dict:
    """厳密なMSE改善をJSON用の整数文字列へ直す。

    引数: value(Fraction)は約分済み改善値。
    返り値: dict[str,str]はnumerator/denominator。epsilonや丸めを使わない。
    """
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


# ----------------------------------------
def candidate_search(rows: list[dict], columns: list[int], required: bool, depth: int) -> dict:
    """float32水準別の別集計から全境界を独立列挙し、厳密最良分割を返す。

    引数: rows(list[dict])はnode所属、columns(list[int])は59又は62子列、required(bool)は両子支持制約、depth(int)は子内深さ。
    返り値: dictは全候補数・適格数・停止理由・選択。新Lの列挙器又はfitを呼ばない。
    """
    result = {"candidate_count": 0, "row_eligible_count": 0, "support_eligible_count": 0,
        "selectable_count": 0, "support_required": required, "stop_reason": "", "selected": None}
    n = len(rows)
    targets = [Fraction(str(row["pnl5"])) for row in rows]
    # ----------------------------------------
    # 共通分母の整数化は候補のgain比較を厳密に保ち、全行の重み0.5は相殺する。
    if not rows:
        result["stop_reason"] = "空"
        return result
    if depth >= 2:
        result["stop_reason"] = "最大深さ"
        return result
    if n < 120:
        result["stop_reason"] = "全行例数不足"
        return result
    if len(set(targets)) == 1:
        result["stop_reason"] = "目的純粋"
        return result
    denominator = math.lcm(*(value.denominator for value in targets))
    values = [value.numerator * (denominator // value.denominator) for value in targets]
    total = sum(values)
    vectors = [float32(row["features"], len(row["features"])) for row in rows]
    filled = [row["filled"] for row in rows]
    keys = [[(row["session"], row["slot_id"]), row["session"][:10], row["session"]] for row in rows]
    best_gain = Fraction(0)
    for feature in sorted(columns):
        # 値別bucketを作り、同値方向行は同時に左右へ移す。行単位の候補は作らない。
        buckets = defaultdict(list)
        for index, vector in enumerate(vectors):
            buckets[vector[feature]].append(index)
        levels = sorted(buckets)
        result["candidate_count"] += max(0, len(levels) - 1)
        left_count = left_sum = 0
        left_support = [Counter(), Counter(), Counter()]
        right_support = [Counter(keys[i][part] for i in range(n) if filled[i]) for part in range(3)]
        for position, level in enumerate(levels[:-1]):
            for index in buckets[level]:
                left_count += 1
                left_sum += values[index]
                if filled[index]:
                    for part in range(3):
                        key = keys[index][part]
                        left_support[part][key] += 1
                        right_support[part][key] -= 1
                        if right_support[part][key] == 0:
                            del right_support[part][key]
            right_count = n - left_count
            if min(left_count, right_count) < 60:
                continue
            result["row_eligible_count"] += 1
            left_counts, right_counts = [len(c) for c in left_support], [len(c) for c in right_support]
            supported = all(counts[0] >= 60 and counts[1] >= 6 and counts[2] >= 10 for counts in (left_counts, right_counts))
            result["support_eligible_count"] += int(supported)
            if required and not supported:
                continue
            result["selectable_count"] += 1
            # Σy²は親子で相殺できる。正改善と同点を分数のまま比較する。
            improvement = (Fraction(left_sum * left_sum, left_count) + Fraction((total - left_sum) ** 2, right_count)
                - Fraction(total * total, n)) / (n * denominator * denominator)
            if improvement <= best_gain:
                continue
            threshold = (level + levels[position + 1]) / 2.0
            best_gain = improvement
            def description(count: int, counts: list[int]) -> dict:
                """現在の左右集計器から候補支持の保存形を作る。

                引数: count(int)は全方向行、counts(list[int])はfilled枠/日/場。
                返り値: dictは候補左右支持。統計を教師行として再生成しない。
                """
                return {"direction_rows": count, "unique_slots": counts[0], "days": counts[1], "sessions": counts[2],
                    "supported": counts[0] >= 60 and counts[1] >= 6 and counts[2] >= 10}
            result["selected"] = {"feature": feature, "feature_id": f"F{feature + 1:02d}", "threshold": threshold,
                "gain": fraction_dict(improvement), "left": description(left_count, left_counts), "right": description(right_count, right_counts)}
    if result["row_eligible_count"] == 0:
        result["stop_reason"] = "全行適格候補なし"
    elif required and result["support_eligible_count"] == 0:
        result["stop_reason"] = "支持適格候補なし"
    elif result["selected"] is None:
        result["stop_reason"] = "正改善なし"
    else:
        result["stop_reason"] = "分割採用"
    return result


# ----------------------------------------
def check_optimality(model: dict, used: list[dict], audit) -> dict:
    """全node所属を独立JSON走査し、全候補最適性と終端理由を照合する。

    引数: model(dict)は保存元木、used(list[dict])は独立教師、audit(Audit)は照合器。
    返り値: dictは小型の候補総数。全候補一覧はproofへ転記しない。
    """
    members = defaultdict(list)
    for row in used:
        _, _, visits = walk(model, row["features"])
        for index in visits:
            members[index].append(row)
    total = Counter()
    for node in model["nodes"]:
        if node["id"] < 3:
            audit.check("固定段は候補探索なし", node["split_search"], None)
            continue
        branch = node["path"][0]["branch"]
        columns = [index for index in range(COUNTS[model["policy"]]) if index not in (0, 19 if branch == "right" else 25)]
        expected = candidate_search(members[node["id"]], columns, True, len(node["path"]) - 2)
        audit.check(model["model_id"] + str(node["id"]) + ":全候補最良", node["split_search"], expected)
        if expected["selected"] is not None:
            audit.check("最良候補の実分割", (node["feature"], node["threshold"], node["left"] >= 0),
                (expected["selected"]["feature"], expected["selected"]["threshold"], True))
        else:
            audit.check("不成立候補は終端", (node["left"], node["right"]), (-1, -1))
        for key in ("candidate_count", "row_eligible_count", "support_eligible_count", "selectable_count"):
            total[key] += expected[key]
        total["検査node"] += 1
    return dict(total)


# ----------------------------------------
ALGORITHM = "隣接float32境界の厳密MSE列挙"
THRESHOLD_RULE = "float32隣接異値のfloat64中点。等値は分けず、左<=/右>"
TIE_RULE = "特徴index昇順、同特徴の閾値昇順。同じ厳密改善なら最初を保持"
GAIN_RULE = "全行半重みの親MSEから行数加重子MSEを引く。金額整数と有理数で厳密比較、正改善のみ"





# ----------------------------------------
def parameters(depth: int, policy: str) -> dict:
    """同容量の保存引数と独自列挙の差分を独立定義する。

    引数: depth(int)は全体4又は子2、policy(str)はB0/Q0。
    返り値: dictは監査側の保存引数。実学習器を呼ばない。
    """
    return {**R56.regressor_parameters(depth), "random_state": None, "legacy_random_state": 51, "randomness_used": False,
        "algorithm": ALGORITHM, "support_required": True,
        "threshold_rule": THRESHOLD_RULE, "tie_rule": TIE_RULE, "gain_rule": GAIN_RULE}


# ----------------------------------------
def expected_rules() -> dict:
    """固定72S支持付き列挙へ共通準備と追加3列の規約を独立定義する。

    引数: なし。
    返り値: dictは新Lと比較する全規約。新Lの定数を読まない。
    """
    rules = R72.expected_rules()
    rules.update({"政策深さ": {policy: 4 for policy in COUNTS}, "政策特徴数": deepcopy(COUNTS),
        "教師": "旧69C可知pairへ当時の直近窓commonreadyを先にANDし、B61/Q64に同じpair・同じ順序を渡す",
        "回収教師": "確定無取引0を含む同じpnl5。全行重み0.5、scoreと約定支持は約定既知だけ",
        "追加指標": "Q0だけ直近公開3分5差分C/E/Jを追加。全P05/priceで独立技法票を増やさない",
        "未知": "6連続公開終値又はTV>0が成立しなければ両政策共通ready外。学習内で0補完・追加pair除外・片側追加をしない",
        "候補約定支持": {policy: "両子がfilled unique枠60・日6・場10を満たす候補だけ" for policy in COUNTS},
        "比較の限定": "同じ支持付き厳密列挙のB61対Q64。旧72Sは保存参考で、新commonreadyによる準備差を別に記録する",
        "旧指紋": "base61_fingerprintsは同commonready教師の旧61射影。Q64の全特徴指紋と同一視しない"})
    rules["共通固定段"].update(子特徴数={p: n - 2 for p, n in COUNTS.items()}, 子特徴列index={p: {
        "D0": [i for i in range(n) if i not in (0, 25)], "D1": [i for i in range(n) if i not in (0, 19)]} for p, n in COUNTS.items()})
    return rules


def canonical_rows(rows: list[dict], start: float, policy: str) -> tuple:
    """事前commonready教師を旧61検査へ射影し、全列と旧射影を別指紋にする。

    引数: rows(list[dict])は同pair、start(float)はstrict評価開始、policy(str)はB0/Q0。
    返り値: tuple[list,dict]は独立canonicalと六指紋。学習内で行を追加・除外しない。
    """
    for row in rows:
        float32(row["features"], COUNTS[policy])
    projected = [{**deepcopy(row), "features": deepcopy(row["features"][:61])} for row in rows]
    used61, old = R72.canonical_rows(projected, start)
    if len(used61) != len(rows):
        raise ValueError("共通ready後のpair数が変化")
    used = deepcopy(used61)
    for item, origin in zip(used, rows):
        if any(item[key] != origin[key] for key in ("session", "slot_id", "side")):
            raise ValueError("canonicalの同順IDが変化")
        item["features"] = [float(v) for v in origin["features"]]
    training = deepcopy(old)
    training.update(base61_fingerprints={key: old[key] for key in FINGERPRINT_FIELDS},
        input_rows_sha256=fingerprint(used), used_rows_sha256=fingerprint(used),
        used_barrier_rows_sha256=fingerprint([{key: row[key] for key in R69.CANONICAL_FIELDS if key not in ("pnl0", "pnl5", "pnl10", "recovery_end_time")} for row in used]),
        feature_missing_handling="73の共通readyで先に両方向pairを限定。B61/Q64に同じ可知教師。学習内の追加除外・0補完なし")
    return used, training



# ----------------------------------------
def check_raw_model(model: dict, used: list[dict], training: dict, meta: list[dict], identity: str, learner_sha: str, audit) -> dict:
    """新回帰木の全所属・現在有効4群・先着率と回収統計を独立再構成する。

    引数: model(dict)は保存木、used/trainingは独立教師、meta(list[dict])は61又は64列、
        identity/learner_sha(str)はID/版、audit(Audit)は記録。
    返り値: dictは候補数の小型集計。全所属と別列挙の最良閾値を検査し、固定段の最適性は要求しない。
    """
    count = len(meta)
    columns = {"D0": [i for i in range(count) if i not in (0, 25)], "D1": [i for i in range(count) if i not in (0, 19)]}
    audit.check(identity + ":schema", (model["schema_version"], model["model_id"], model["policy"]), (1, identity, identity.split("_")[0]))
    audit.check(identity + ":metadata", model["feature_meta"], meta)
    audit.check(identity + ":metadata指紋", model["feature_meta_sha256"], fingerprint(meta))
    audit.check(identity + ":学習code", model["source_sha256"], learner_sha)
    audit.check(identity + ":library", model["versions"], {"Python": platform.python_version(), "学習器": ALGORITHM, "算術": "整数/既約有理数", "sklearn.fit": 0})
    audit.check(identity + ":本体引数", model["parameters"], parameters(4, model["policy"]))
    audit.check(identity + ":子引数", model["subtree_parameters"], parameters(2, model["policy"]))
    audit.check(identity + ":構造", model["structure"], {"kind": "fixed_direction_current_episode", "fixed_nodes": R69.FIXED_NODES,
        "child_depth": 2, "child_features": count - 2, "child_feature_indices": columns,
        "excluded_feature_indices": {"D0": [0, 25], "D1": [0, 19]}, "feature_count": count,
        "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": ALGORITHM, "target": "pnl5"})
    audit.check(identity + ":規約", model["rules"], expected_rules())
    audit.check(identity + ":旧純補助bind", model["shared_source_sha256"], {OLD_L_PATH.relative_to(ROOT).as_posix(): OLD_L_SHA})
    audit.check(identity + ":独自子学習数", model["training"]["independent_regression_count"], sum(group["fit_performed"] for group in model["training"]["partition"].values()))
    audit.check(identity + ":sklearnfit0", model["training"]["sklearn_fit_count"], 0)
    audit.check(identity + ":targetdtype", model["training"]["target_dtype"], "Decimal金額の厳密10進整数")
    nodes, paths = model["nodes"], {0: []}
    audit.check(identity + ":固定根両子", (nodes[0]["left"], nodes[0]["right"]), (1, 2))
    for index, node in enumerate(nodes):
        if index not in paths:
            raise ValueError("到達不能node")
        audit.check(identity + ":node順", node["id"], index)
        audit.check(identity + ":depth4", len(paths[index]) <= 4, True)
        audit.check(identity + ":path", node["path"], paths[index])
        if index < 3:
            fixed = R69.FIXED_NODES[index]
            audit.check(identity + ":固定node", (node["feature"], node["feature_id"], node["threshold"]), (fixed["index"], fixed["feature"], fixed["threshold"]))
            audit.check(identity + ":固定内部保持", node["left"] >= 0 and node["right"] >= 0, True)
        if node["left"] == node["right"] == -1:
            audit.check(identity + ":葉記号", (node["feature"], node["feature_id"], node["family"], node["threshold"]), (-2, None, None, -2.))
            continue
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < count or not A.finite(node["threshold"]):
            raise ValueError("分岐値不正")
        if index >= 3:
            branch = "D1" if paths[index][0]["branch"] == "right" else "D0"
            audit.check(identity + ":枝別子候補列", feature in columns[branch], True)
        audit.check(identity + ":分岐metadata", (node["feature_id"], node["family"]), (meta[feature]["id"], meta[feature]["family"]))
        for branch, comparison in (("left", "<="), ("right", ">")):
            child = node[branch]
            if type(child) is not int or not index < child < len(nodes) or child in paths:
                raise ValueError("子ID又は重複親不正")
            paths[child] = paths[index] + [{"node": index, "feature": feature, "feature_id": meta[feature]["id"], "method": meta[feature]["method"],
                "family": meta[feature]["family"], "threshold": node["threshold"], "comparison": comparison, "branch": branch}]
    audit.check(identity + ":全node到達可能", set(paths), set(range(len(nodes))))
    membership = defaultdict(list)
    for row in used:
        leaf, path, visits = walk(model, row["features"])
        audit.check(identity + ":方向行path", path, nodes[leaf]["path"])
        for index in visits:
            membership[index].append(row)
    partition,offset={},3
    for d in (0,1):
        for valid in (0,1):
            key=f"D{d}_V{valid}"
            selected=[row for row in used if R65.group_key(row["features"][:60])==key]
            root=nodes[d+1]["right" if valid else "left"]
            descendants=[i for i,path in paths.items() if len(path)>=2 and path[0]["branch"]==("right" if d else "left") and path[1]["branch"]==("right" if valid else "left")]
            audit.check(identity+key+":子offset",root,offset)
            audit.check(identity+key+":連続ID",sorted(descendants),list(range(offset,offset+len(descendants))))
            audit.check(identity+key+":子depth2",all(len(paths[i])-2<=2 for i in descendants),True)
            audit.check(identity+key+":所属",membership[root],selected)
            if not selected:
                audit.check(identity+key+":空群一未知leaf",(len(descendants),nodes[root]["left"],nodes[root]["right"],nodes[root]["data_absent"]),(1,-1,-1,True))
            ids=[{k:row[k] for k in ("session","slot_id","side")} for row in selected]
            partition[key]={"d":d,"v":valid,"route":"T" if d else "R","policy":model["policy"],"excluded_feature_indices":[0,19 if d else 25],
                "child_feature_indices":columns[f"D{d}"],"direction_rows":len(selected),"pair_unique":len({(row["session"],row["slot_id"]) for row in selected}),
                "days":len({row["session"][:10] for row in selected}),"sessions":len({row["session"] for row in selected}),"row_ids_sha256":fingerprint(ids),
                "fit_performed":bool(selected),"root":root,"node_count":len(descendants),"fit_parameters":parameters(2, model["policy"])}
            offset+=len(descendants)
    audit.check(identity+":四群全方向",sum(p["direction_rows"] for p in partition.values()),len(used))
    audit.check(identity+":全training",model["training"],{**deepcopy(training),"partition":partition,"independent_regression_count":sum(group["fit_performed"] for group in partition.values()),"sklearn_fit_count":0,"target_dtype":"Decimal金額の厳密10進整数"})
    roots = {p["root"] for p in partition.values()}
    for index, node in enumerate(nodes):
        rows = membership[index]
        expected = {"impurity_kind": "squared_error", "methods": sorted({part["method"] for part in paths[index]}),
            "families": sorted({part["family"] for part in paths[index]}),
            "training_ids_sha256": fingerprint([{key: row[key] for key in ("session", "slot_id", "side")} for row in rows])}
        statistics = R69.expected_statistics(rows, paths[index])
        second = R56.decimal_statistics(rows)["second_moment"]
        for key in ("regression_value", "impurity"):
            value = statistics.pop(key)
            if index < 3:
                audit.check(identity + str(index) + ":固定段" + key, node[key], value)
            else:
                audit.check(identity + str(index) + ":生回帰器" + key, R56.numeric_match(node[key], value, "mean" if key == "regression_value" else "mse", second), True)
        for key, value in {**expected, **statistics}.items():
            audit.check(identity + str(index) + ":" + key, node[key], value)
        audit.check(identity + ":data_absent型", type(node["data_absent"]) is bool, True)
        eligibility = A.eligibility({**node, "score": 0.0 if node["score"] is None else node["score"]}, paths[index])
        audit.check(identity + ":支持旗", (node["leaf_support"], node["method_support"]), (eligibility["leaf_support"], eligibility["method_support"]))
        if index >= 3 and node["left"] != -1:
            audit.check(identity + ":通常子minleaf60", min(len(membership[node["left"]]), len(membership[node["right"]])) >= 60, True)
        if not rows and index >= 3:
            audit.check(identity + ":空は群root一葉", index in roots and node["left"] == node["right"] == -1, True)
    return check_optimality(model, used, audit)


# ----------------------------------------
def prior_prediction(model: dict, vectors: dict) -> dict:
    """保存木の両方向を独立採点し、未知枝では既知側への救済も行わない。

    引数: model(dict)は検算済みB0/Q0木、vectors(dict)は政策列数×両方向。
    返り値: dictは全予測。未知側だけscore/eligibilityをNoneとしraw既知値を保持する。
    """
    if not isinstance(vectors, dict) or set(vectors) != {"1", "-1"}:
        raise ValueError("両方向特徴が必要")
    if vectors["1"] == vectors["-1"] == []:
        return {"scores": {side: None for side in ("1", "-1")}, "leafs": {side: None for side in ("1", "-1")},
                "side": 0, "winner_side": 0, "reason": "特徴未準備WAIT", "eligibility": {side: None for side in ("1", "-1")}}
    scores, leafs, qualifications = {}, {}, {}
    for side in ("1", "-1"):
        leaf, path, _ = walk(model, vectors[side])
        node = model["nodes"][leaf]
        if node["path"] != path:
            raise ValueError("保存pathとwalk不一致")
        absent = node.get("barrier_data_absent") is True
        if absent and (node["score"] is not None or node["filled_direction_rows"] != 0):
            raise ValueError("未知枝のscore0補完又は行数不整合")
        if not absent and (not A.finite(node["score"]) or not 0 <= node["score"] <= 1):
            raise ValueError("既知枝のscore不正")
        scores[side], leafs[side] = node["score"], leaf
        qualifications[side] = None if absent else A.eligibility(node, path)
    result = {"scores": scores, "leafs": leafs, "side": 0, "winner_side": 0, "reason": "同点WAIT", "eligibility": qualifications}
    if any(value is None for value in scores.values()):
        result["reason"] = "未学習枝WAIT"
        return result
    if scores["1"] != scores["-1"]:
        winner = "1" if scores["1"] > scores["-1"] else "-1"
        failures = [label for key, label in (("score", "最高側score下限未達"), ("leaf_support", "最高側葉支持不足"),
                    ("method_support", "最高側複数技法不足")) if not qualifications[winner][key]]
        result.update(winner_side=int(winner), side=0 if failures else int(winner), reason="/".join(failures) if failures else "採用")
    return result


# ----------------------------------------
def reference_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """障壁score最高側へ回収支持と政策別のstrict正額だけを追加する。

    引数: model/calibration(dict)は同じ過去木・葉、vectors(dict)は当時特徴、policy(str)はE0/E1。
    返り値: dictは全採否。回帰平均で順位を変えず次点を救済しない。
    """
    if policy not in ("E0", "E1") or calibration["model_id"] != model["model_id"]:
        raise ValueError("候補又は回収木の対応不正")
    prior = prior_prediction(model, vectors)
    side, reason, leaf = prior["side"], prior["reason"], None
    if side:
        leaf = calibration["leaves"][str(prior["leafs"][str(side)])]
        if not leaf["support"]:
            side, reason = 0, "回収支持不足WAIT"
        elif policy.endswith("1") and not leaf["positive"]:
            side, reason = 0, "過去回収平均非正WAIT"
    return {"side": side, "reason": reason, "prior": prior, "recovery_leaf": leaf["leaf"] if leaf else None,
        "recovery_support": leaf["support"] if leaf else None, "recovery_mean5": leaf["mean_yen"]["5"] if leaf else None}


# ----------------------------------------
def qualified_sides(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """両方向の旧資格と回収条件を独立に導き選択候補を確定する。

    引数: model/calibration(dict)は過去保存値、vectors(dict)は同61/64列、policy(str)はE0/E1。
    返り値: dictは旧両側予測・各資格・適格集合・選択側。未知と同点は集合選択より優先する。
    """
    if policy not in ("E0", "E1") or calibration["model_id"] != model["model_id"]:
        raise ValueError("政策又は旧木と回収の対応不正")
    prior = prior_prediction(model, vectors)
    sides = {}
    for side in ("1", "-1"):
        leaf_id = prior["leafs"][side]
        if leaf_id is None or prior["scores"][side] is None:
            sides[side] = None
            continue
        leaf = calibration["leaves"][str(leaf_id)]
        if leaf["leaf"] != leaf_id:
            raise ValueError("回収葉ID不一致")
        support = leaf["unique_slots"] >= 60 and leaf["days"] >= 6 and leaf["sessions"] >= 10
        positive = leaf["direction_rows"] > 0 and Decimal(leaf["sum_yen"]["5"]) > 0
        if (leaf["support"], leaf["positive"]) != (support, positive):
            raise ValueError("回収支持又は十進符号に差")
        qualifications = prior["eligibility"][side]
        flags = {key: qualifications[key] for key in ("score", "leaf_support", "method_support")}
        flags.update(recovery_support=support, recovery_positive=positive)
        valid = all(flags[key] for key in ("score", "leaf_support", "method_support", "recovery_support"))
        if policy == "E1":
            valid = valid and positive
        sides[side] = {**flags, "eligible": bool(valid), "leaf": leaf_id, "mean5": leaf["mean_yen"]["5"]}
    selected = 0
    eligible = sorted((int(side) for side in ("1", "-1") if sides[side] is not None and sides[side]["eligible"]),
        key=lambda side: -prior["scores"][str(side)])
    if any(prior["scores"][side] is None for side in ("1", "-1")):
        boundary = "unknown"
    elif prior["scores"]["1"] == prior["scores"]["-1"]:
        boundary = "tie"
    elif eligible:
        boundary = "selected"
        selected = max(eligible, key=lambda side: prior["scores"][str(side)])
    else:
        boundary = "empty"
    return {"prior": prior, "sides": sides, "eligible": eligible, "side": selected, "boundary": boundary}


# ----------------------------------------
def selection_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """新選択器を呼ばず互換旧予測と両方向資格の保存辞書を構成する。

    引数: model/calibration(dict)は過去正本、vectors(dict)は両61/64列、policy(str)はE0/E1。
    返り値: dictは新prediction全文。WAIT時は旧回収欄、採用時は選択葉へ結ぶ。
    """
    chosen = qualified_sides(model, calibration, vectors, policy)
    prior, directions = chosen["prior"], {}
    unprepared = vectors["1"] == vectors["-1"] == []
    for side in ("1", "-1"):
        flags = chosen["sides"][side]
        if flags is None:
            directions[side] = {"known": False, "leaf": prior["leafs"][side], "score_value": None, "score": None,
                "leaf_support": None, "method_support": None, "families": None, "recovery_support": None,
                "recovery_positive": None, "recovery_mean5": None, "eligible": False,
                "reasons": ["特徴未準備" if unprepared else "未学習葉"]}
            continue
        reasons = [text for name, text in (("score", "score下限未達"), ("leaf_support", "葉支持不足"),
            ("method_support", "複数技法不足"), ("recovery_support", "回収支持不足")) if not flags[name]]
        if policy == "E1" and not flags["recovery_positive"]:
            reasons.append("過去回収平均未知" if flags["mean5"] is None else "過去回収平均非正")
        directions[side] = {"known": True, "leaf": flags["leaf"], "score_value": prior["scores"][side],
            **{name: flags[name] for name in ("score", "leaf_support", "method_support", "recovery_support", "recovery_positive")},
            "families": prior["eligibility"][side]["families"], "recovery_mean5": flags["mean5"],
            "eligible": flags["eligible"], "reasons": reasons}
    block = "特徴未準備WAIT" if unprepared else {"unknown": "未学習枝WAIT", "tie": "同点WAIT"}.get(chosen["boundary"])
    winner = 0 if block else 1 if prior["scores"]["1"] > prior["scores"]["-1"] else -1
    reference = reference_prediction(model, calibration, vectors, policy)
    side = chosen["side"]
    rescued = bool(side and side != winner)
    reason = block or ("両方向不適格WAIT" if not side else "適格な他方向を採用" if rescued else "採用")
    result = {"side": side, "reason": reason, "prior": deepcopy(prior),
        **{key: reference[key] for key in ("recovery_leaf", "recovery_support", "recovery_mean5")},
        "policy": policy, "reference_policy": "C0" if policy == "E0" else "R0", "original_winner_side": winner,
        "selected_side": side, "rescued": rescued, "rescue_reasons": directions[str(winner)]["reasons"] if rescued else [],
        "direction_eligibility": directions, "eligible_sides": chosen["eligible"], "ranking_block_reason": block, "reference": reference}
    if side:
        leaf = directions[str(side)]
        result.update(recovery_leaf=leaf["leaf"], recovery_support=leaf["recovery_support"], recovery_mean5=leaf["recovery_mean5"])
    return result


# ----------------------------------------
def expected_pruned(raw: dict, identity: str, digest: str) -> dict:
    """支持のみの独立DPを再用し、新政策の探索履歴も親のまま保持する。

    引数: raw(dict)はB0/Q0元木、identity/digest(str)は派生IDと元byteSHA。
    返り値: dictは全派生木期待値。新L.pruneを呼ばない。
    """
    result = R70.expected_model({**raw, "policy": "C0"}, identity, digest)
    result["policy"] = raw["policy"]
    result["pruning"]["source_model_content_sha256"] = fingerprint(raw)
    result["pruning"]["rules"].update(入力="新73のB0生木61列又はQ0生木64列。親統計と探索来歴を保持し剪定時学習0",
        予測="新73の政策別61/64列JSON walk/predict。旧globalと元辞書を変更せず、64列を旧61走査へ渡さない")
    result["pruning"].update(code_sha256=hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest(),
        shared_source_sha256={OLD_L_PATH.relative_to(ROOT).as_posix(): OLD_L_SHA})
    return result


# ----------------------------------------
def check_pruned(model: dict, raw: dict, identity: str, digest: str, audit) -> None:
    """全派生属性・元探索記録・親統計・ID対応を独立DPと比較する。

    引数: model/raw(dict)は派生/元木、identity/digest(str)は識別、audit(Audit)は記録。
    返り値: None。新しい分割や予測を作らず保存構造を検査する。
    """
    expected = expected_pruned(raw, identity, digest)
    audit.check("派生top集合", set(model), set(expected))
    for key in expected:
        if key != "nodes":
            audit.check("派生top:" + key, model[key], expected[key])
    audit.check("派生node数", len(model["nodes"]), len(expected["nodes"]))
    for node, value in zip(model["nodes"], expected["nodes"]):
        audit.check("派生node全属性", node, value)


# ----------------------------------------
def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """固定71監査の独立JSON走査と66選択で新四政策の全採否を作る。

    引数: model/calibration(dict)は過去木、vectors(dict)は当時61/64列、policy(str)はB0/B1/Q0/Q1。
    返り値: dictは全prediction。回収で方向順位を変えず最高score適格側を選ぶ。
    """
    if policy not in POLICIES or model["policy"] != policy[0] + "0":
        raise ValueError("新政策と木の不一致")
    return selection_prediction(model, calibration, vectors, "E0" if policy.endswith("0") else "E1")


# ----------------------------------------
def expected_slots(block: dict, prepared: dict, model: dict, calibration: dict, policy: str, phase: str) -> list[dict]:
    """保存予定枠と過去木から全純判断を独立に構成する。

    引数: block/prepared/model/calibration(dict)は元予定・当時特徴・過去木、policy/phase(str)は識別。
    返り値: list[dict]は全slot。rawDI0の役割WAITは従来どおり保持する。
    """
    rows = []
    for origin in block["slots"]:
        feature = prepared[origin["slot_id"]]
        prediction = expected_prediction(model, calibration, feature["vectors"], policy) if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        rows.append({**{key: origin[key] for key in BINDING}, "policy": policy, "phase": phase, "model_id": model["model_id"],
            "side": side, "role": "順行" if side and side == feature["background_direction"] else "反転" if side else "待機",
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": prediction})
    return rows


# ----------------------------------------
def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """276資源と新B0/B1/Q0/Q1各一代表の約定・台帳をHTTP照合する。

    引数: base(str|None)はURL、resources/accounts(list[dict])は保存値、source/auditは固定補助。
    返り値: dictはAPI範囲。未指定は未検証とする。
    """
    if not base:
        return {'実行':False,'理由':'--viewer-url未指定。API未検証、新184保存約定は全件照合'}
    query={'catalog_path':(STUDY/'一覧.resources.json').relative_to(ROOT).as_posix()}
    listing,_,_=source.fetch_json(base+'/api/resources?'+urlencode(query))
    audit.check('API276資源全集合',{row['id'] for row in listing['resources']},{row['id'] for row in resources})
    audit.check('API276資源数',len(listing['resources']),276)
    representatives=[]
    for policy in POLICIES:
        account=sorted([row for row in accounts if row['candidate']==policy],key=lambda row:(-abs(row['ledger']['5']),row['session']))[0]
        resource=next(row for row in resources if row['method_id']==policy and row['session']==account['session'])
        parameters={**query,'resource':resource['id'],'interval':'5','price':'last','width':1000,'height':700}
        meta,_,_=source.fetch_json(base+'/api/chart?'+urlencode(parameters))
        data,raw,headers=source.fetch_json(urljoin(base+'/',meta['data_url']))
        audit.check('API本文SHA',hashlib.sha256(raw).hexdigest(),meta['data_sha256'])
        audit.check('APIヘッダSHA',headers.get('x-chart-data-sha256'),meta['data_sha256'])
        audit.check('API集計alias',data['summary'],meta['summary'])
        audit.check('API台帳純額5',Decimal(str(data['summary']['realized_pnl_yen'])),Decimal(str(account['ledger']['5'])))
        trades=list(source.json_rows(ROOT/resource['pnl_path']))
        audit.check('API約定片数',len(data['events']),len(trades))
        for sequence,(trade,event) in enumerate(zip(trades,data['events']),1):
            for key in ('type','qty','position_id','method_id','price'):
                audit.check('API約定:'+key,event[key],trade[key])
            audit.check('API順',event['sequence'],sequence)
            audit.check('API時計',abs(event['timestamp_ms']-datetime.fromisoformat(trade['timestamp']).timestamp()*1000)<=.001,True)
        representatives.append({'候補':policy,'場':account['session'],'資源ID':resource['id'],'台帳観測5円':account['ledger']['5'],'数値SHA256':meta['data_sha256']})
    return {'実行':True,'全資源数':276,'新政策代表':representatives,'代表規約':'政策別最大絶対台帳観測額・場順。採否不使用'}


# ----------------------------------------
def input_expectation(entries: list[dict], blocks: dict, extended: dict, conditions: dict, measured: dict, old_blocks: dict, inherited: dict, audit) -> tuple:
    """固定72の旧61へ独立SOURCE算法を適用し、新B/Q全辞書と準備分布を作る。

    引数: entries/blocks/extended/conditions/measured/old_blocks/inheritedは固定入力、auditは照合器。
    返り値: tuple[dict,dict,dict]はB/Q特徴と事前接続の全期待値。新Iを呼ばない。
    """
    prepared_b, prepared_q, reasons = {}, {}, Counter()
    saved_count = 0
    for block in old_blocks.values():
        for slot in block["slots"]:
            audit.check("旧S当時61全文", slot["feature"], extended[slot["slot_id"]])
            saved_count += 1
    for block in blocks.values():
        for slot in block["slots"]:
            identity = slot["slot_id"]
            if identity in prepared_b:
                raise ValueError("予定枠ID重複")
            b, q = INPUT_AUDIT.derive(slot, extended[identity])
            prepared_b[identity], prepared_q[identity] = b, q
            if extended[identity]["ready"] and not b["ready"]:
                reasons[b["reason"]] += 1
            projection = deepcopy(q)
            if projection["ready"]:
                projection["vectors"] = {side: vector[:61] for side, vector in projection["vectors"].items()}
            audit.check("独立B/Q全文射影", projection, b)
            for feature in (b, q):
                prior = deepcopy(feature)
                prior.pop("recent_progress")
                prior["vectors"] = prior.pop("control_vectors61")
                prior["ready"], prior["reason"] = feature["recent_progress"]["old_ready"], feature["recent_progress"]["old_reason"]
                audit.check("独立旧61全文射影", prior, extended[identity])
    phase_counts = {}
    for name, group in (("全66", entries), ("学習専用20", entries[:20]), ("時系列検査20", entries[20:40]),
            ("条件選択24", entries[40:64]), ("既使用後続2", entries[64:])):
        ids = [slot["slot_id"] for entry in group for slot in blocks[entry["session"]]["slots"]]
        phase_counts[name] = {"全予定枠": len(ids), "旧準備済み枠": sum(extended[key]["ready"] for key in ids),
            "共通準備済み枠": sum(prepared_b[key]["ready"] for key in ids),
            "旧準備からの落ち": sum(extended[key]["ready"] and not prepared_b[key]["ready"] for key in ids)}
    checks = {"72の入力検査": inherited, "旧S保存運用": len(old_blocks), "旧S保存特徴照合": saved_count,
        "全予定枠": len(extended), "旧準備済み枠": sum(f["ready"] for f in extended.values()),
        "共通準備済み枠": sum(f["ready"] for f in prepared_b.values()), "共通準備落ち理由": dict(reasons),
        "準備分布": phase_counts, "旧61全文投影一致": len(prepared_b), "共通B/Q射影一致": len(prepared_q),
        "旧61特徴SHA256": fingerprint(extended), "B61特徴SHA256": fingerprint(prepared_b), "Q64特徴SHA256": fingerprint(prepared_q),
        "条件SHA256": fingerprint(conditions), "参照独立方向": len(measured)}
    return prepared_b, prepared_q, checks


def common_expectation(rows: list[dict], common: dict, extended: dict, prepared_b: dict, prepared_q: dict, audit) -> tuple:
    """旧可知pairへ共通readyを同じ順でANDし、母集合の差を独立記録する。

    引数: rows/commonは旧69Cの独立教師・要約、extended/prepared_b/prepared_q(dict)は当時特徴、auditは照合器。
    返り値: tuple[dict,dict]はB/Q同ID教師と新共通要約。未来labelで準備を選ばない。
    """
    inherited = {**{key: common[key] for key in ("全予定枠", "共通可知枠", "共通方向行", "除外枠数", "使用分類", "共通ID同順序", "方向重み")},
        "旧69共通集合SHA256": fingerprint(common), "旧69結果path": (TEACHER_STUDY / "結果.json").relative_to(ROOT).as_posix()}
    teachers, rejected = {p: [] for p in MODEL_POLICIES}, {}
    for row in rows:
        identity, side = row["slot_id"], str(row["side"])
        old = {**deepcopy(row), "features": deepcopy(extended[identity]["vectors"][side])}
        audit.check("旧61教師の60射影", {**old, "features": old["features"][:60]}, row)
        b, q = prepared_b[identity], prepared_q[identity]
        if b["ready"] != q["ready"]:
            raise ValueError("B/Q準備差")
        if not b["ready"]:
            rejected[identity] = b["reason"]
            continue
        left = {**deepcopy(row), "features": deepcopy(b["vectors"][side])}
        right = {**deepcopy(row), "features": deepcopy(q["vectors"][side])}
        audit.check("新B教師は旧61同値", left, old)
        audit.check("Q教師61射影はB", {**right, "features": right["features"][:61]}, left)
        teachers["B0"].append(left)
        teachers["Q0"].append(right)
    if not teachers["B0"] or len(teachers["B0"]) % 2:
        raise ValueError("共通ready教師pairが不正")
    result = deepcopy(inherited)
    result.update(旧72共通要約=deepcopy(inherited), 旧共通可知枠=inherited["共通可知枠"],
        共通可知枠=len(teachers["B0"]) // 2, 共通方向行=len(teachers["B0"]), 追加準備除外枠=len(rejected),
        追加準備除外理由=dict(Counter(rejected.values())), 追加準備除外ID=sorted(rejected), 除外枠数=inherited["除外枠数"] + len(rejected),
        使用分類={policy: dict(Counter(row["outcome"] for row in group)) for policy, group in teachers.items()},
        共通ID同順序=True, 同じ旧61特徴=True, 比較="同じ可知pairかつ直近窓共通準備。B61対Q64、候補支持は共通")
    return teachers, result


def check_baseline(raw: dict, model: dict, old_raw: dict, old_model: dict, common: dict, audit) -> None:
    """追加教師除外がない期だけ旧72Sの実質木再現を保存JSONへ照合する。

    引数: raw/model/old_raw/old_model(dict)は新B/旧S、common(dict)は新教師要約、auditは照合器。
    返り値: None。来歴・ID・政策の差と統計/構造を区別し、再fitしない。
    """
    if common["追加準備除外枠"]:
        return
    for key in ("nodes", "feature_meta", "feature_meta_sha256", "parameters", "subtree_parameters", "versions", "structure"):
        audit.check("同教師B元木再現:" + key, raw[key], old_raw[key])
    for key in (*FINGERPRINT_FIELDS, "base60_fingerprints"):
        audit.check("同教師B旧六指紋:" + key, raw["training"][key], old_raw["training"][key])
    for key in ("nodes", "feature_meta", "feature_meta_sha256", "parameters", "subtree_parameters", "versions", "structure"):
        audit.check("同教師B派生実質再現:" + key, model[key], old_model[key])



# ----------------------------------------
def run(viewer_url: str | None = None) -> dict:
    """同可知教師・厳密全候補・新十二木と実184運用を独立照合する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは公式proof。新73入力/主/学習/Engineを期待値へ呼ばず、一度だけ保存する。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("73保存物確認は作成済み。再実行しません")
    source, _, summary = A.helpers()
    audit = source.Audit()
    result, fixed, inputs = [source.read(STUDY / name) for name in ("結果.json", "固定.json", "入力台帳.json")]
    previous, proof, ledger = [source.read(path) for path in (OLD / "結果.json", OLD / "保存物確認.json", LEDGER)]
    teacher_result, teacher_proof = [source.read(TEACHER_STUDY / name) for name in ("結果.json", "保存物確認.json")]
    preflight_path = WORK.parent / "入力接続確認.json"
    old_preflight_path = TEACHER_WORK.parent / "入力接続確認.json"
    preflight, old_preflight = source.read(preflight_path), source.read(old_preflight_path)
    files = [STUDY / name for name in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    files += [WORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz", "実行完了.json")]
    files += [OLD / name for name in ("結果.json", "保存物確認.json", "固定.json", "一覧.resources.json")]
    files += [OLDWORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz", "実行完了.json")]
    files += [TEACHER_STUDY / name for name in ("結果.json", "保存物確認.json")]
    files += [TEACHER_WORK / "条件独立測定.jsonl.gz", LEDGER, preflight_path, old_preflight_path, source.MANIFEST, Path(__file__)]
    for meta in [*result["モデル"], *result["元学習モデル"], *result["回収集計"]]:
        files.append(ROOT / meta["path"])
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in files}
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("73固定:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    for name, digest in inputs["ファイルSHA256"].items():
        audit.check("73入力台帳:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("72完了台帳指定SHA", source.sha(LEDGER), LEDGER_SHA)
    audit.check("72成功監査", (proof["全件一致"], proof["不一致数"], proof["結果SHA256"]), (True, 0, source.sha(OLD / "結果.json")))
    audit.check("69成功監査", (teacher_proof["全件一致"], teacher_proof["不一致数"], teacher_proof["結果SHA256"]), (True, 0, source.sha(TEACHER_STUDY / "結果.json")))
    audit.check("72単一完了", source.read(OLDWORK / "実行完了.json")["結果SHA256"], proof["結果SHA256"])
    audit.check("72完了対象数", len(ledger["成果物SHA256"]), 241)
    for name, digest in ledger["成果物SHA256"].items():
        audit.check("72完了不変:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("73固定bind", (result["試行"], result["固定SHA256"], result["全66場既使用"]), (73, source.sha(STUDY / "固定.json"), True))
    audit.check("73単一完了", source.read(WORK / "実行完了.json")["結果SHA256"], source.sha(STUDY / "結果.json"))
    audit.check("新六候補集合", set(result["候補"]), {*CONTROLS, *POLICIES})
    names = ("新独自回帰学習", "新sklearnfit", "新分類器fit", "新保存木数", "新元学習木数", "新派生木数", "参照モデル数", "新独立計測", "参照独立測定", "新運用数")
    audit.check("73新処理範囲", tuple(result[name] for name in names), (24, 0, 0, 12, 6, 6, 3, 0, 4092, 184))
    audit.check("73保存対照", result["対照参照"], {"候補": list(CONTROLS), "元試行": 72, "市場再生": False})
    # 固定72の既存61算術だけを再用し、新3列は独立入力監査で構成する。
    reader = load_fixed(HERE.parent / "支持を満たす技法分割/入力.py", "直近73監査の固定72入力")
    entries, blocks, base, extended, immediate, conditions, measured, _, inherited = reader.verified_inputs()
    audit.check("固定72入力検査", inherited, source.read(reader.PREFLIGHT)["検査"])
    audit.check("既使用66場台帳", entries, source.read(source.MANIFEST)["entries"])
    evaluated = [entry["session"] for entry in entries[20:]]
    audit.check("同46評価場", result["評価場"], evaluated)
    audit.check("学習専用20場", result["学習専用場"], [entry["session"] for entry in entries[:20]])
    old_blocks = {(row["session"], row["policy"]): row for row in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz") if row["policy"] in CONTROLS}
    audit.check("旧S92集合", (len(old_blocks), set(old_blocks)), (92, {(session, policy) for session in evaluated for policy in CONTROLS}))
    prepared_b, prepared_q, input_checks = input_expectation(entries, blocks, extended, conditions, measured, old_blocks, inherited, audit)
    audit.check("73事前接続検査", preflight["検査"], input_checks)
    audit.check("73結果入力検査", result["入力検査"], input_checks)
    audit.check("73旧保存特徴数", input_checks["旧S保存特徴照合"], 3404)
    expected_keys = {(slot["slot_id"], side) for block in blocks.values() for slot in block["slots"] if extended[slot["slot_id"]]["ready"] for side in (1, -1)}
    audit.check("旧4092方向集合", (len(measured), set(measured)), (4092, expected_keys))
    audit.check("準備比較", result["準備比較"], {"旧準備済み枠": sum(f["ready"] for f in extended.values()),
        "共通準備済み枠": sum(f["ready"] for f in prepared_b.values()),
        "追加準備除外": dict(Counter(f["reason"] for key, f in prepared_b.items() if extended[key]["ready"] and not f["ready"]))})
    common_summaries = {}
    # ----------------------------------------
    models, calibrations, model_pins, searches = {}, {}, {}, {}
    model_meta = {(meta["policy"], meta["phase"]): meta for meta in result["モデル"]}
    raw_meta = {(meta["policy"], meta["phase"]): meta for meta in result["元学習モデル"]}
    cal_meta = {(meta["policy"], meta["phase"]): meta for meta in result["回収集計"]}
    expected_meta_keys = {(policy, phase) for policy in COUNTS for phase in ("W20", "W30", "F40")}
    audit.check("六元木/六派生/cal集合", (len(result["モデル"]), len(result["元学習モデル"]), len(result["回収集計"]), set(model_meta), set(raw_meta), set(cal_meta)),
        (6, 6, 6, expected_meta_keys, expected_meta_keys, expected_meta_keys))
    fit_count = 0
    for phase in R69.phases(entries, source):
        name = phase["id"]
        rows, common = R69.common_teachers(phase, blocks, base, immediate, measured)
        audit.check("69共通教師全文", common, teacher_result["共通教師"][name])
        teachers, common_new = common_expectation(rows["C0"], common, extended, prepared_b, prepared_q, audit)
        common_summaries[name] = common_new
        audit.check("73共通教師全文", result["共通教師"][name], common_new)
        trainings = {}
        for policy, count in COUNTS.items():
            identity, raw_identity = policy + "_" + name, policy + "_" + name + "_学習"
            meta, raw_info, cal_info = model_meta[policy, name], raw_meta[policy, name], cal_meta[policy, name]
            raw, model, calibration = [source.read(ROOT / item["path"]) for item in (raw_info, meta, cal_info)]
            for item in (raw_info, meta, cal_info):
                model_pins[item["path"]] = source.sha(ROOT / item["path"])
                audit.check("73木/calSHA", model_pins[item["path"]], item["SHA256"])
            used, training = canonical_rows(teachers[policy], phase["evaluation_start"], policy)
            trainings[policy] = training
            searches[raw_identity] = check_raw_model(raw, used, training, metadata(policy), raw_identity, source.sha(HERE / "学習.py"), audit)
            fit_count += sum(group["fit_performed"] for group in raw["training"]["partition"].values())
            check_pruned(model, raw, identity, model_pins[raw_info["path"]], audit)
            audit.check("73剪定全文", result["剪定"][name][policy], model["pruning"])
            audit.check("派生回収全葉", calibration, R69.expected_calibration(model))
            metadata_common = {"policy": policy, "phase": name, "特徴数": count,
                "学習場": [entry["session"] for entry in phase["train"]], "評価場": [entry["session"] for entry in phase["evaluation"]], "評価開始": phase["evaluation_start"]}
            expected_raw_meta = {**metadata_common, "id": raw_identity, "path": (STUDY / "models" / (raw_identity + ".json")).relative_to(ROOT).as_posix(), "SHA256": model_pins[raw_info["path"]]}
            audit.check("元木metadata全文", raw_info, expected_raw_meta)
            audit.check("派生metadata全文", meta, {**metadata_common, "id": identity,
                "path": (STUDY / "models" / (identity + ".json")).relative_to(ROOT).as_posix(), "SHA256": model_pins[meta["path"]],
                "元path": raw_info["path"], "元SHA256": model_pins[raw_info["path"]]})
            audit.check("calmetadata全文", cal_info, {"id": identity, "policy": policy, "phase": name,
                "path": (STUDY / "models" / ("回収_" + identity + ".json")).relative_to(ROOT).as_posix(), "SHA256": model_pins[cal_info["path"]]})
            models[policy, name], calibrations[policy, name] = model, calibration
        audit.check("B/Q同61教師射影", teachers["B0"], [{**row, "features": row["features"][:61]} for row in teachers["Q0"]])
        for key in (*FINGERPRINT_FIELDS, "base60_fingerprints"):
            audit.check("B/Q同61教師指紋:" + key, trainings["B0"][key] if key == "base60_fingerprints" else trainings["B0"]["base61_fingerprints"][key],
                trainings["Q0"][key] if key == "base60_fingerprints" else trainings["Q0"]["base61_fingerprints"][key])
        old_raw_path, old_model_path = [OLD / "models" / ("S0_" + name + suffix + ".json") for suffix in ("_学習", "")]
        check_baseline(source.read(ROOT / raw_meta["B0", name]["path"]), models["B0", name], source.read(old_raw_path), source.read(old_model_path), common_new, audit)
        for path in (old_raw_path, old_model_path):
            model_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
    audit.check("73学習参照", result["学習参照"], {"元試行": 69, "モデル政策": "C0",
        "同じ可知集合": all(group["追加準備除外枠"] == 0 for group in common_summaries.values()), "両政策共通準備集合": True,
        "同じ条件教師": True, "旧61投影同値": True, "新独自学習": True, "sklearnfit": 0,
        "比較": "同じ共通準備集合で直近集中C・方向効率E・最大方向Jを追加", "無取引": "回収0・障壁対象外"})
    audit.check("新独自回帰学習数", result["新独自回帰学習"], fit_count)
    # ----------------------------------------
    # 実184運用だけ原配列へ照合し、独立教師4092方向は69成功指紋で再用する。
    detail = defaultdict(list)
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        detail[block["session"]].append(block)
    audit.check("新詳細46場", set(detail), set(evaluated))
    phase_by_session = {entry["session"]: phase["id"] for phase in R69.phases(entries, source) for entry in phase["evaluation"]}
    labels = {policy: [] for policy in (*CONTROLS, *POLICIES)}
    slots_by_policy = {policy: [] for policy in POLICIES}
    for row in source.json_rows(OLDWORK / "入口先着.jsonl.gz"):
        if row["policy"] in CONTROLS:
            labels[row["policy"]].append(row)
    resources = source.read(STUDY / "一覧.resources.json")["resources"]
    resource_map = {(row["session"], row["method_id"]): row for row in resources}
    audit.check("276資源全集合", set(resource_map), {(session, policy) for session in evaluated for policy in (*CONTROLS, *POLICIES)})
    audit.check("276資源一意", (len(resources), len({row["id"] for row in resources})), (276, 276))
    for row in source.read(OLD / "一覧.resources.json")["resources"]:
        if row["method_id"] in CONTROLS:
            audit.check("旧G資源全文", resource_map[row["session"], row["method_id"]], row)
    accounts, summaries, cache_pins, viewer_pins = [], [], {}, {}
    entries_matched = closed_matched = 0
    for entry in entries[20:]:
        session, phase = entry["session"], phase_by_session[entry["session"]]
        tape, cache_path, digest, input_quality = R55.load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        audit.check("69成功cachebind", digest, teacher_proof["キャッシュSHA256"][cache_path])
        for control in CONTROLS:
            operation = old_blocks[session, control]["operation"]
            account = P.account(operation, source, audit)
            account["conditions"] = operation["conditions"]
            accounts.append(account)
        audit.check("新四政策順", [block["policy"] for block in detail[session]], list(POLICIES))
        for block in detail[session]:
            policy = block["policy"]
            model_policy = policy[0] + "0"
            prepared = prepared_b if model_policy == "B0" else prepared_q
            slots = expected_slots(blocks[session], prepared, models[model_policy, phase], calibrations[model_policy, phase], policy, phase)
            audit.check("73純全辞書", block["slots"], slots)
            audit.check("73評価phase", block["phase"], phase)
            slots_by_policy[policy].extend(slots)
            expected_conditions = {slot["slot_id"]: conditions[slot["slot_id"]] for slot in slots if slot["side"]}
            audit.check("73採用条件全文", block["conditions"], expected_conditions)
            local_labels, observed = {}, {}
            for slot in slots:
                if not slot["side"]:
                    continue
                identity = slot["slot_id"]
                record = measured[identity, slot["side"]]
                value = deepcopy(record["barrier"])
                value.update(policy=policy, role=slot["role"])
                audit.check("再用先着条件出典", value["condition"], expected_conditions[identity])
                audit.check("再用先着元時計", value["origin_slot"], {key: slot[key] for key in BINDING})
                local_labels[identity] = value
                observed[identity] = record["operation"]["conditions"][identity]["last_observation_time"]
                labels[policy].append(value)
            operation = block["operation"]
            audit.check("新実運用識別", (operation["session"], operation["candidate_id"]), (session, policy))
            audit.check("新入力品質", block["input_quality"], input_quality)
            account = R69.check_operation(block, local_labels, observed, tape, source, audit)
            accounts.append(account)
            for order in operation["orders"]:
                if order["kind"] == "entry" and order["status"] == "filled":
                    prior = measured[order["slot"]["slot_id"], order["slot"]["side"]]["barrier"]
                    audit.check("新実独立入口一致", prior["filled"], True)
                    audit.check("新実独立新規三属性", tuple(order["fill_" + key] for key in ("time", "line", "price")), tuple(prior["entry_" + key] for key in ("time", "line", "price")))
                    entries_matched += 1
            for closed in operation["closed"]:
                single = measured[closed["slot_id"], closed["side"]]["operation"]["closed"]
                audit.check("新実独立完結件数", len(single), 1)
                if single:
                    audit.check("新実独立完結非ID全文", R55.strict_close_equal(closed, single[0]), True)
                closed_matched += 1
            path = ROOT / resource_map[session, policy]["pnl_path"]
            audit.check("新Viewer正規パス", path.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            audit.check("新Viewer全約定", list(source.json_rows(path)), operation["trades"])
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            summaries.append({"場": session, "候補": policy, "期間": source.span(session), "入力品質": input_quality, "運用品質": operation["quality"], "運用集計": operation["metrics"]})
        print(session + " 候補支持/厳密最良/剪定/新四運用照合", flush=True)
    audit.check("新全184場別", result["場別"], summaries)
    audit.check("主二検査", result["検査"], {"同一条件実仮新規一致": entries_matched, "同一条件実独立完結一致": closed_matched})
    sequence = list(source.json_rows(WORK / "入口先着.jsonl.gz"))
    audit.check("先着全文と保存順", sequence, [row for policy in POLICIES for row in labels[policy]])
    audit.check("新条件入口評価数", result["新条件入口評価"], len(sequence))
    for policy in (*CONTROLS, *POLICIES):
        selected = [account for account in accounts if account["candidate"] == policy]
        for period in PERIODS:
            entrance = R68.entry_summary(labels[policy], period, source)
            operation = R68.operation_summary(selected, period, source, summary)
            audit.check(policy + period + "入口", result["候補"][policy][period]["入口"], entrance)
            audit.check(policy + period + "運用", result["候補"][policy][period]["運用"], operation)
            audit.check(policy + period + "同時適格", result["候補"][policy][period]["同時適格"], entrance["70目標"] and operation["活動適格"] and operation["費用適格"])
            for role in ("順行", "反転"):
                audit.check(policy + period + role, result["役割別入口"][policy][period][role], R68.entry_summary([row for row in labels[policy] if row["role"] == role], period, source))
            if policy in POLICIES:
                audit.check(policy + period + "段階", result["条件段階"][policy][period], R68.stage_summary(slots_by_policy[policy], labels[policy], selected, period, source))
                audit.check(policy + period + "理由", result["判断理由"][policy][period], dict(Counter(row["reason"] for row in slots_by_policy[policy] if source.span(row["session"]) == period)))
        if policy in CONTROLS:
            audit.check("旧G対照全期", result["候補"][policy], previous["候補"][policy])
    audit.check("新採用", result["採用"], [policy for policy in POLICIES if all(result["候補"][policy][period]["同時適格"] for period in PERIODS[:2])])
    audit.check("新詳細二系列", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("新詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins, **cache_pins, **viewer_pins}.items():
        audit.check("監査中参照不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 73, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0,
        "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples, "結果SHA256": source.sha(STUDY / "結果.json"),
        "本物fit再実行": False, "新主処理import": False, "新入力import": False, "新学習import": False, "Engine期待値import": False, "市場戦略再生": False,
        "既存特徴算術再構成": True, "新特徴追加": True, "新特徴独立算法監査": True, "共通教師の追加準備除外": {key: value["追加準備除外枠"] for key, value in common_summaries.items()}, "全候補最適性再列挙": True, "新元学習木数": 6, "新派生木数": 6, "新運用数": 184, "再用独立教師数": len(measured),
        "同一条件実仮新規数": entries_matched, "同一条件実独立完結数": closed_matched, "厳密候補探索": searches,
        "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api,
        "検証範囲": "旧72完了対象/旧69成功証明、旧61再構成と独立SOURCE6/C/E/J/commonready全辞書、共通ready教師の61/64指紋、全候補厳密最良、元6/派生6/回収集計、全純採否、新184原BBO条件/注文/保護/現金/品質、6候補集計・Viewer276/新4代表。",
        "限定": "既存61算術再構成あり。新3列は新I/L/主/Engineを期待値に呼ばず独立算法で検査。旧4092独立教師は成功指紋で再用し再計測しない。B/Qは共通ready教師で比較し、旧Sとの準備差を別記。教師集合が変わらない期だけ旧SとBの実質木を保存JSONへ照合。新fit・戦略再生・未知収益又は心理因果の実証ではない。"}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


# ----------------------------------------
def self_test() -> dict:
    """架空入力・教師だけで独立入力/最適分割/全木/剪定/採否を接続する。

    引数: なし。
    返り値: dictは人工成功/比較数と範囲。新Lは人工の出力側だけで呼び、本物入力を読まない。
    """
    source, _, _ = A.helpers()
    audit = source.Audit()
    learner = load_fixed(HERE / "学習.py", "直近73監査の人工出力学習")
    selector = load_fixed(HERE.parent / "適格方向の選択/選択.py", "直近73監査の固定66人工")
    old_l = load_fixed(OLD_L_PATH, "直近73監査の人工旧S出力", OLD_L_SHA)
    initial = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    input_test = INPUT_AUDIT.self_test()
    audit.check("独立入力35系列", (input_test["人工成功"], input_test["不一致数"]), (True, 0))
    for prices, expected_ready in ((None, True), ([100] * 6, False)):
        slot, prior = INPUT_AUDIT.fixture(prices)
        old_blocks = {(slot["session"], "S0"): {"slots": [{**slot, "feature": prior}]}}
        bp, qp, checks = input_expectation([{"session": slot["session"]}], {slot["session"]: {"slots": [slot]}},
            {slot["slot_id"]: prior}, {}, {}, old_blocks, {}, audit)
        audit.check("全枠入力期待値の共通準備", (bp[slot["slot_id"]]["ready"], qp[slot["slot_id"]]["ready"]), (expected_ready, expected_ready))
        audit.check("旧準備から共通落ちの枠分母", checks["準備分布"]["全66"]["旧準備からの落ち"], int(not expected_ready))
    rows_b, rows_q, _, _, evaluation = learner.synthetic_inputs()
    groups, learned = ["独立SOURCE6と共通準備"], {}
    regressions = 0
    # ----------------------------------------
    # 元木全属性と全候補を別算し、64列が実分岐した木も全所属検算する。
    for policy, rows in (("B0", rows_b), ("Q0", rows_q)):
        used, training = canonical_rows(rows, evaluation, policy)
        raw = learner.fit(rows, metadata(policy), evaluation, policy, policy + "_人工_学習")
        searches = check_raw_model(raw, used, training, metadata(policy), raw["model_id"], initial, audit)
        audit.check("全候補の独立検査", searches["検査node"] > 0, True)
        regressions += raw["training"]["independent_regression_count"]
        derived = learner.prune(raw, policy + "_人工", "a" * 64)
        check_pruned(derived, raw, policy + "_人工", "a" * 64, audit)
        calibration = R69.expected_calibration(derived)
        for index in range(0, 24, 2):
            vectors = {"1": rows[index]["features"], "-1": rows[index + 1]["features"]}
            for mode in ("0", "1"):
                actual = selector.predict(derived, calibration, vectors, learner, "E" + mode)
                audit.check("独立全採否" + policy + mode, actual, expected_prediction(derived, calibration, vectors, policy[0] + mode))
        audit.check("未準備WAIT全文", selector.predict(derived, calibration, {"1": [], "-1": []}, learner, "E0"),
            expected_prediction(derived, calibration, {"1": [], "-1": []}, policy))
        learned[policy] = raw, derived, used, training
    groups += ["61全元nodeと全候補", "64全元nodeと全候補", "全派生支持DP", "独立64JSON採否"]
    audit.check("新列の人工分割", any(node["feature"] >= 61 for node in learned["Q0"][0]["nodes"]), True)
    # ----------------------------------------
    # 支持付き旧Sとの実質再現を、人工出力の保存形に対してだけ検査する。
    old_raw = old_l.fit(rows_b, metadata("B0"), evaluation, "S0", "S0_人工_学習")
    old_derived = old_l.prune(old_raw, "S0_人工", "a" * 64)
    check_baseline(learned["B0"][0], learned["B0"][1], old_raw, old_derived, {"追加準備除外枠": 0}, audit)
    audit.check("B/Q base61六指紋", learned["B0"][3]["base61_fingerprints"], learned["Q0"][3]["base61_fingerprints"])
    audit.check("Q全列指紋は61と別", learned["Q0"][3]["input_rows_sha256"] != learned["B0"][3]["input_rows_sha256"], True)
    groups += ["同教師旧S実質再現", "61射影と64指紋分離"]
    # ----------------------------------------
    # 合計金額ではなく厳密改善を改変した証拠と、64列の値域逸脱を検出する。
    corrupt = deepcopy(learned["Q0"][0])
    selected = next(node for node in corrupt["nodes"][3:] if node["split_search"]["selected"])
    selected["split_search"]["selected"]["gain"]["numerator"] = "0"
    rejection = source.Audit()
    check_optimality(corrupt, learned["Q0"][2], rejection)
    audit.check("最良改善の偽造を検出", rejection.bad > 0, True)
    for extra in ((.199, 0., 0), (.5, 1.01, 1), (.5, 0., .5), (.5, 0., True), (.5, float("nan"), 0)):
        invalid = rows_q[0]["features"][:61] + list(extra)
        try:
            float32(invalid, 64)
            rejected = False
        except ValueError:
            rejected = True
        audit.check("64定義域拒否", rejected, True)
    groups += ["最適性反例", "64値域と未知拒否"]
    # ----------------------------------------
    # 共通ready落ちを教師pairの両方向へ同時適用し、旧母集合との違いを検査する。
    old_rows = [{**deepcopy(row), "features": row["features"][:60]} for row in rows_b[:4]]
    extended, bs, qs = {}, {}, {}
    for rb, rq in zip(rows_b[:4], rows_q[:4]):
        identity, side = rb["slot_id"], str(rb["side"])
        extended.setdefault(identity, {"ready": True, "reason": "", "vectors": {}})["vectors"][side] = rb["features"]
        bs.setdefault(identity, {"ready": True, "reason": "", "vectors": {}})["vectors"][side] = rb["features"]
        qs.setdefault(identity, {"ready": True, "reason": "", "vectors": {}})["vectors"][side] = rq["features"]
    drop = next(iter(bs))
    bs[drop].update(ready=False, reason="人工TV0", vectors={"1": [], "-1": []})
    qs[drop].update(ready=False, reason="人工TV0", vectors={"1": [], "-1": []})
    common = {"全予定枠": 2, "共通可知枠": 2, "共通方向行": 4, "除外枠数": 0,
        "使用分類": {}, "共通ID同順序": True, "方向重み": .5}
    teachers, stats = common_expectation(old_rows, common, extended, bs, qs, audit)
    audit.check("共通準備で両方向drop", (len(teachers["B0"]), len(teachers["Q0"]), stats["追加準備除外枠"], stats["共通可知枠"]), (2, 2, 1, 1))
    audit.check("追加準備理由は枠分母", stats["追加準備除外理由"], {"人工TV0": 1})
    groups.append("母集合の両方向共通除外")
    audit.check("人工中の固定学習不変", hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest(), initial)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "テスト件数": len(groups), "テスト群": groups, "入力独立人工": input_test,
        "人工独自学習API": 3, "人工独自子学習": regressions + old_raw["training"]["independent_regression_count"],
        "sklearnfit": 0, "分類器fit": 0, "本物入力読取": False, "本物fit": 0, "市場戦略再生": False}


# ----------------------------------------
def main() -> None:
    """正式監査と人工を排他的CLIへ公開する。

    引数: CLIのrun/self_test(bool)は動作、viewer_url(str|None)はViewer。
    返り値: None。正式監査はrootが一度だけ実行する。
    """
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--run", action="store_true")
    modes.add_argument("--self-test", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    if args.run or args.self_test:
        result = run(args.viewer_url) if args.run else self_test()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
        if not result.get("全件一致", result.get("人工成功", False)):
            raise SystemExit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
