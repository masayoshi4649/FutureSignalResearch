"""71の当時取得位置・同可知教師・raw回帰木と支持剪定を独立検査する。"""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
from urllib.parse import urlencode, urljoin

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00071_技法の組み合わせへ取得位置を加える"
WORK = ROOT / "work/取得位置と支持/00071"
OLD = ROOT / "study/00070_約定支持を保つ粒度で技法を組み合わせる"
OLDWORK = ROOT / "work/支持を保つ技法群/00070"
TEACHER_STUDY = ROOT / "study/00069_条件入口に合わせて技法群の教師を作る"
TEACHER_WORK = ROOT / "work/条件入口の教師/00069"
LEDGER = ROOT / "work/支持を保つ技法群/70完了記録.json"
POLICIES, CONTROLS = ("B0", "B1", "G0", "G1"), ("P0", "P1")
COUNTS = {"B0": 60, "G0": 61}
PERIODS = ("学習", "条件選択", "後続検査")
F61 = {"id": "F61", "name": "取得位置と上位端", "method": "P01", "family": "price", "scale": "m15"}


def load(path: Path, name: str):
    """既存純補助を固有名で読み、大域値を書き換えない。

    引数: path(Path)は固定コード、name(str)は固有名。
    返り値: ModuleTypeは補助。新71主・入力・学習・Engineは正式期待値へ呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R70 = load(HERE.parent / "支持を保つ技法群/保存検証.py", "取得位置71の固定70監査")
R69, R68, R66, R65 = R70.R69, R70.R68, R70.R66, R70.R65
A, P, R55, R56 = R69.A, R69.P, R69.R55, R69.R56
fingerprint = R69.fingerprint
BINDING, SLOT_FIELDS = R69.BINDING, R69.SLOT_FIELDS
FINGERPRINT_FIELDS = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256", "target_rows_sha256", "used_barrier_rows_sha256")


# ----------------------------------------
def metadata(policy: str) -> list[dict]:
    """旧60列と追加1列を、実装側に問い合わせず定義する。

    引数: policy(str)はraw政策B0又はG0。
    返り値: list[dict]は固定60又は61metadata。
    """
    if policy not in COUNTS:
        raise ValueError("raw政策はB0又はG0")
    return [*R65.feature_metadata(60), *([deepcopy(F61)] if policy == "G0" else [])]


def float32(values: list, count: int) -> list[float]:
    """旧60の共同mask検査を維持し、追加gだけ有限float32を要求する。

    引数: values(list)は60又は61値、count(int)は対応列数。
    返り値: list[float]は予測比較値。未知や桁あふれを0へ補完しない。
    """
    if count not in (60, 61) or not isinstance(values, list) or len(values) != count:
        raise ValueError("特徴の列数が不一致")
    converted = R65.float32(values[:60], 60)
    if count == 61:
        if not A.finite(values[60]):
            raise ValueError("gは有限数値が必要")
        try:
            extra = struct.unpack("f", struct.pack("f", values[60]))[0]
        except (OverflowError, struct.error) as error:
            raise ValueError("gのfloat32範囲を超えた") from error
        if not math.isfinite(extra):
            raise ValueError("gのfloat32が非有限")
        converted.append(extra)
    return converted


def g_values(slot: dict, feature: dict, quote: dict) -> dict:
    """当時上位SOURCEと判断新規側気配から十進Fractionで両方向gを別算する。

    引数: slot(dict)は元5key、feature(dict)は旧60準備、quote(dict)は55保存decision_bbo6。
    返り値: dict[str,float]は±方向のg。Lastは式・準備へ追加せず、異常BBOや不足を拒否する。
    """
    if (feature["ready"] is not True or not A.finite(slot.get("time")) or not A.finite(slot.get("scheduled"))
            or slot["time"] < slot["scheduled"] or type(slot.get("line")) is not int or slot["line"] <= 0):
        raise ValueError("gには準備済みの正常判断時計が必要")
    if not isinstance(quote, dict) or set(quote) != {"now", "line", "last", "bid", "ask", "valid"}:
        raise ValueError("判断BBOは元6列が必要")
    if (not A.finite(quote["now"]) or quote["now"] != slot["time"] or type(quote["line"]) is not int
            or quote["line"] != slot["line"] or quote["valid"] is not True
            or not all(A.finite(quote[key]) and quote[key] > 0 for key in ("bid", "ask")) or quote["bid"] >= quote["ask"]):
        raise ValueError("判断時計又は元数量flagを含むBBOが不正")
    upper = feature["base"]["base"]["sources"]["upper"]
    if (upper["session"] != slot["session"] or upper["publish"] is not True or upper["minutes"] != 15 or upper["missing"] != 0
            or not all(A.finite(upper[key]) for key in ("start", "end")) or upper["end"] - upper["start"] != 900
            or not 0 <= slot["scheduled"] - upper["end"] <= 900
            or not A.finite(upper["confirm"]) or type(upper["confirm_line"]) is not int or upper["confirm_line"] <= 0 or upper["confirm"] < upper["end"]
            or (upper["confirm"], upper["confirm_line"]) > (slot["time"], slot["line"])):
        raise ValueError("上位SOURCEの当時完全公開条件が不成立")
    if (not all(A.finite(upper[key]) and upper[key] > 0 for key in ("open", "high", "low", "close"))
            or not upper["low"] <= min(upper["open"], upper["close"]) <= max(upper["open"], upper["close"]) <= upper["high"]):
        raise ValueError("上位OHLCが不正")
    distance = feature["D"]
    if not A.finite(distance) or not 5 <= distance <= 125:
        raise ValueError("元定時Dが不正")
    result = {}
    for side in (1, -1):
        edge = upper["high"] if side == 1 else upper["low"]
        entry = quote["ask"] if side == 1 else quote["bid"]
        value = Fraction(side) * (Fraction(str(edge)) - Fraction(str(entry))) / Fraction(str(distance))
        result[str(side)] = float(value)
        if not math.isfinite(result[str(side)]):
            raise ValueError("gのfloat64が非有限")
    return result


def extend_feature(slot: dict, feature: dict, quote: dict | None) -> dict:
    """当時位置の小型出典を独立算術で付加し、旧60辞書の投影を保持する。

    引数: slot/feature(dict)は旧判断と旧60、quote(dict|None)は当時判断BBO。
    返り値: dictは61特徴/position、未準備は旧辞書の深い写し。
    """
    result = deepcopy(feature)
    if not feature["ready"]:
        return result
    values = g_values(slot, feature, quote)
    upper = feature["base"]["base"]["sources"]["upper"]
    current = feature["base"]["base"]["sources"]["current"]
    distances = {}
    for side in (1, -1):
        reference, entry = (upper["high"], quote["ask"]) if side == 1 else (upper["low"], quote["bid"])
        exact = Fraction(side) * (Fraction(str(reference)) - Fraction(str(entry))) / Fraction(str(feature["D"]))
        result["vectors"][str(side)].append(values[str(side)])
        distances[str(side)] = {"value": values[str(side)], "exact": str(exact), "M": reference, "E_star": entry}
    result["position"] = {"feature_id": "F61", "formula": "s*(M-E*)/D", "upper_source": deepcopy(upper),
        "quote": {key: quote[key] for key in ("now", "line", "bid", "ask", "valid")}, "D": feature["D"],
        "upper_age_seconds": slot["scheduled"] - upper["end"], "same_end": current["end"] == upper["end"],
        "same_close": current["close"] == upper["close"], "values": distances}
    return result


def canonical_rows(rows: list[dict], evaluation_start: float, policy: str) -> tuple:
    """旧60pair検査を先行し、full列とbase60の六指紋を独立に作る。

    引数: rows(list[dict])は同可知教師、evaluation_start(float)はstrict境界、policy(str)はB0/G0。
    返り値: tuple[list,dict]は同順canonicalとtraining。追加gで教師を落とさない。
    """
    if policy not in COUNTS:
        raise ValueError("raw政策不正")
    count = COUNTS[policy]
    for row in rows:
        float32(row["features"], count)
    projected = [{**deepcopy(row), "features": row["features"][:60]} for row in rows]
    used, training = R69.canonical_rows(projected, evaluation_start)
    baseline = {key: training[key] for key in FINGERPRINT_FIELDS}
    for row, original in zip(used, rows):
        row["features"] = list(map(float, original["features"]))
    training.update(input_rows_sha256=fingerprint(used), used_rows_sha256=fingerprint(used),
        used_barrier_rows_sha256=fingerprint([{key: row[key] for key in R69.CANONICAL_FIELDS if key not in ("pnl0", "pnl5", "pnl10", "recovery_end_time")} for row in used]),
        base60_fingerprints=baseline, feature_missing_handling="旧69C共通可知の同pair。B60/G61とも追加除外なし、g欠測は拒否")
    return used, training


def walk(model: dict, values: list) -> tuple:
    """60/61列をfloat32で独立走査し、保存pathと全所属nodeを返す。

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


def check_raw_model(model: dict, used: list[dict], training: dict, meta: list[dict], identity: str, learner_sha: str, audit) -> None:
    """新回帰木の全所属・現在有効4群・先着率と回収統計を独立再構成する。

    引数: model(dict)は保存木、used/trainingは独立教師、meta(list[dict])は60又は61列、
        identity/learner_sha(str)はID/版、audit(Audit)は記録。
    返り値: None。最良閾値の探索や別fitはせず、固定段の最適性を要求しない。
    """
    count = len(meta)
    columns = {"D0": [i for i in range(count) if i not in (0, 25)], "D1": [i for i in range(count) if i not in (0, 19)]}
    audit.check(identity + ":schema", (model["schema_version"], model["model_id"], model["policy"]), (1, identity, identity.split("_")[0]))
    audit.check(identity + ":metadata", model["feature_meta"], meta)
    audit.check(identity + ":metadata指紋", model["feature_meta_sha256"], fingerprint(meta))
    audit.check(identity + ":学習code", model["source_sha256"], learner_sha)
    audit.check(identity + ":library", model["versions"]["scikit-learn"], "1.9.1")
    audit.check(identity + ":本体引数", model["parameters"], R56.regressor_parameters(4))
    audit.check(identity + ":子引数", model["subtree_parameters"], R56.regressor_parameters(2))
    audit.check(identity + ":構造", model["structure"], {"kind": "fixed_direction_current_episode", "fixed_nodes": R69.FIXED_NODES,
        "child_depth": 2, "child_features": count - 2, "child_feature_indices": columns,
        "excluded_feature_indices": {"D0": [0, 25], "D1": [0, 19]}, "feature_count": count,
        "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"})
    audit.check(identity + ":規約", model["rules"], expected_rules())
    shared = [ROOT / "scripts/方向局面分岐/学習.py", ROOT / "scripts/局所帯分岐/学習.py", ROOT / "scripts/回収目的分岐/学習.py", ROOT / "scripts/波の区間分離/学習.py", ROOT / "scripts/現行経路の状態分岐/学習.py", ROOT / "scripts/方向と再開確認/学習.py", ROOT / "scripts/局面強弱の複合確認/学習.py", ROOT / "scripts/量と価格進行/学習.py", ROOT / "scripts/現在状態と量価格/学習.py", ROOT / "scripts/条件入口の教師/学習.py", ROOT / "scripts/支持を保つ技法群/剪定.py"]
    audit.check(identity + ":旧純補助bind", model["shared_source_sha256"], {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in shared})
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
                "fit_performed":bool(selected),"root":root,"node_count":len(descendants),"fit_parameters":R56.regressor_parameters(2)}
            offset+=len(descendants)
    audit.check(identity+":四群全方向",sum(p["direction_rows"] for p in partition.values()),len(used))
    audit.check(identity+":全training",model["training"],{**deepcopy(training),"partition":partition})
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



def expected_rules() -> dict:
    """旧69の教師契約へ71の二政策/取得位置だけを明示追加する。

    引数: なし。
    返り値: dictは監査側raw学習規約。新Lをimportしない。
    """
    rules = R69.expected_rules()
    rules.update({"政策深さ": {"B0": 4, "G0": 4}, "政策特徴数": deepcopy(COUNTS),
    "回収教師": "固定69で作成済みの即時/条件共通可知pairからC条件教師を再用。新しいpair選別・追加除外なし",
    "教師": "固定69C条件教師の同一可知pair。B0/G0とも新fitし、B1/G1は同木の回収strict正条件",
    "追加指標": "G0だけF61=g=s*(M-E*)/D。買M=当時上位high/E*=ask、売M=low/E*=bid。計算はroot入力側",
    "未知": "旧60準備と共通可知pairを保持。取得位置の入力欠落/不一致はpreflight停止し、0補完・mask・clip・余分な符号gateなし",
    "取得位置の限定": "F61はP01/priceであり既存価格の加工と重なる。独立技法票や反転確認としない",
    "比較の限定": "B0は旧60の同演算、G0は同容量の子候補へF61だけを追加。同じ支持剪定で比較し未見利益を保証しない"})
    rules["共通固定段"].update(子特徴数={"B0": 58, "G0": 59}, 子特徴列index={policy: {
        "D0": [i for i in range(count) if i not in (0, 25)], "D1": [i for i in range(count) if i not in (0, 19)]} for policy, count in COUNTS.items()})
    return rules


def prior_prediction(model: dict, vectors: dict) -> dict:
    """保存木の両方向を独立採点し、未知枝では既知側への救済も行わない。

    引数: model(dict)は検算済みB0/G0木、vectors(dict)は政策列数×両方向。
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



def qualified_sides(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """両方向の旧資格と回収条件を独立に導き選択候補を確定する。

    引数: model/calibration(dict)は過去保存値、vectors(dict)は同60/61列、policy(str)はE0/E1。
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


def selection_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """新選択器を呼ばず互換旧予測と両方向資格の保存辞書を構成する。

    引数: model/calibration(dict)は過去正本、vectors(dict)は両60/61列、policy(str)はE0/E1。
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



def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """政策名だけをE0/E1へ写し、独立60/61走査から全選択を構成する。

    引数: model/calibration(dict)は過去派生木、vectors(dict)は当時値、policy(str)はB0/B1/G0/G1。
    返り値: dictは固定66同型の全prediction。最高障壁側と回収条件を分離する。
    """
    if policy not in POLICIES or model["policy"] != policy[0] + "0":
        raise ValueError("政策とモデルの対応が不正")
    return selection_prediction(model, calibration, vectors, "E0" if policy.endswith("0") else "E1")


def expected_pruned(raw: dict, identity: str, digest: str) -> dict:
    """固定70の逆ID支持DPを局所射影し、60/61派生木を独立構成する。

    引数: raw(dict)は新raw木、identity/digest(str)は新IDと元byteSHA。
    返り値: dictは全派生辞書。統計はraw親を保持し、同じ支持以外で剪定しない。
    """
    result = R70.expected_model({**raw, "policy": "C0"}, identity, digest)
    result["policy"] = raw["policy"]
    pruning = result["pruning"]
    pruning["source_model_content_sha256"] = fingerprint(raw)
    pruning["rules"].update({"入力": "新71のB0生木60列又はG0生木61列。同政策の派生木へ変換し、剪定時fit0",
        "予測": "新71の同政策・同列数のJSON walk/predictで生木と派生木を扱う。旧globalや元辞書を変更しない"})
    pruning["code_sha256"] = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    pruning["shared_source_sha256"] = {"scripts/条件入口の教師/学習.py": "f0569e4d25834b038caba57929f941367e22e397a64d8306a14406f41fef77de",
        "scripts/支持を保つ技法群/剪定.py": "0584e185a87d3cc58f19aad464ecf7f81bfb9a7e04a4ea5ff6cea9be927a485c"}
    return result


def check_pruned(model: dict, raw: dict, identity: str, digest: str, audit) -> None:
    """独立支持DPと全source node統計・新旧ID対応を保存派生木へ照合する。

    引数: model/raw(dict)は派生と元学習、identity/digest(str)は元情報、audit(Audit)は記録。
    返り値: None。新L.pruneを期待値に呼ばず、元trainingは旧IDのまま保持する。
    """
    expected = expected_pruned(raw, identity, digest)
    audit.check("派生top集合", set(model), set(expected))
    for key in expected:
        if key != "nodes":
            audit.check("派生top:" + key, model[key], expected[key])
    audit.check("派生node数", len(model["nodes"]), len(expected["nodes"]))
    for node, value in zip(model["nodes"], expected["nodes"]):
        audit.check("派生node全属性", node, value)
    audit.check("派生の旧学習証拠保持", model["training"], raw["training"])


def expected_slots(block: dict, prepared: dict, model: dict, calibration: dict, policy: str, phase: str) -> list[dict]:
    """当時60/61特徴と独立JSON採否から新全予定slotを構成する。

    引数: block/prepared/model/calibration(dict)は元判断と過去木、policy/phase(str)は識別。
    返り値: list[dict]は純slot全文。DI0WAITと実方向役割を維持する。
    """
    result = []
    for origin in block["slots"]:
        feature = prepared[origin["slot_id"]]
        prediction = expected_prediction(model, calibration, feature["vectors"], policy) if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        result.append({**{key: origin[key] for key in BINDING}, "policy": policy, "phase": phase, "model_id": model["model_id"], "side": side,
            "role": "順行" if side and side == feature["background_direction"] else "反転" if side else "待機",
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": prediction})
    return result


def quotes_for(slot: dict, immediate: dict) -> dict:
    """旧55の両方向5keyを独立照合し、共通判断BBO6を取り出す。

    引数: slot(dict)は元判断、immediate(dict)は旧55保存測定。
    返り値: dictは当時6列の深い写し。片側欠落や不一致は拒否する。
    """
    values = []
    for side in (1, -1):
        row = immediate[slot["slot_id"], side]
        if type(row["side"]) is not int or row["side"] != side:
            raise ValueError("判断BBOの方向不一致")
        for key in BINDING:
            actual, expected = row[key], slot[key]
            valid = A.finite(actual) and A.finite(expected) if key in ("scheduled", "time") else type(actual) is type(expected)
            if not valid or actual != expected:
                raise ValueError("判断BBOの5key結合差:" + key)
        values.append(row["decision_bbo"])
    if values[0] != values[1]:
        raise ValueError("同じ判断BBOの両方向不一致")
    return deepcopy(values[0])


def base_projection(feature: dict) -> dict:
    """追加位置だけを取り除き、旧60全辞書へ厳密に射影する。

    引数: feature(dict)は新61又は未準備辞書。
    返り値: dictは旧60全辞書の深い写し。
    """
    result = deepcopy(feature)
    if result["ready"]:
        result.pop("position")
        result["vectors"] = {side: values[:60] for side, values in result["vectors"].items()}
    return result


# ----------------------------------------
def baseline_raw(model: dict, original: dict, audit) -> None:
    """基礎60の再学習木を、版と政策識別以外の旧69証拠へ照合する。

    引数: model/original(dict)は新B0と旧C0、audit(Audit)は照合記録。
    返り値: None。新旧code/rules/model_idの差をnode統計の差と混同しない。
    """
    for key in ("nodes", "feature_meta", "parameters", "subtree_parameters", "versions"):
        audit.check("B0旧69再現:" + key, model[key], original[key])
    keys = ("evaluation_start", "input_pairs", "used_pairs", "direction_rows", "filled_direction_rows", "unfilled_direction_rows",
        "row_ids", "input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "used_barrier_rows_sha256",
        "period", "period_sha256", "weight_per_direction", "total_weight")
    for key in keys:
        audit.check("B0旧69教師:" + key, model["training"][key], original["training"][key])
    partition = deepcopy(model["training"]["partition"])
    for group in partition.values():
        group["policy"] = "C0"
    audit.check("B0旧69四群", partition, original["training"]["partition"])


def baseline_operation(slots: list[dict], operation: dict, old: dict, audit) -> None:
    """基礎60の全判断と約定経済を、旧70保存P運用へ照合する。

    引数: slots(list[dict])/operation(dict)は新B、old(dict)は対応旧P、audit(Audit)は記録。
    返り値: None。新policy/model識別子を除き、prediction全文・価格経路・品質を保持する。
    """
    keys = (*BINDING, "side", "role", "ready", "reason", "atr", "D", "feature", "prediction")
    audit.check("B/P全判断件数", len(slots), len(old["slots"]))
    for new, previous in zip(slots, old["slots"]):
        for key in keys:
            audit.check("B/P判断:" + key, new[key], previous[key])
    prior = old["operation"]
    for key in ("metrics", "quality"):
        audit.check("B/P運用:" + key, operation[key], prior[key])
    audit.check("B/P完結数", len(operation["closed"]), len(prior["closed"]))
    for closed, previous in zip(operation["closed"], prior["closed"]):
        audit.check("B/P完結非ID全文", R55.strict_close_equal(closed, previous), True)


def run(viewer_url: str | None = None) -> dict:
    """同可知教師・取得位置・新十二木と実184運用を独立照合する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは公式proof。新71入力/主/学習/Engineを期待値へ呼ばず、一度だけ保存する。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("71保存物確認は作成済み。再実行しません")
    source, _, summary = A.helpers()
    audit = source.Audit()
    result, fixed, inputs = [source.read(STUDY / name) for name in ("結果.json", "固定.json", "入力台帳.json")]
    previous, proof, ledger = [source.read(path) for path in (OLD / "結果.json", OLD / "保存物確認.json", LEDGER)]
    teacher_result, teacher_proof = [source.read(TEACHER_STUDY / name) for name in ("結果.json", "保存物確認.json")]
    preflight_path = WORK.parent / "入力接続確認.json"
    old_preflight_path = TEACHER_WORK.parent / "入力接続確認.json"
    preflight, old_preflight = source.read(preflight_path), source.read(old_preflight_path)
    files = [STUDY / name for name in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    files += [WORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [OLD / name for name in ("結果.json", "保存物確認.json", "固定.json", "一覧.resources.json")]
    files += [OLDWORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz", "実行完了.json")]
    files += [TEACHER_STUDY / name for name in ("結果.json", "保存物確認.json")]
    files += [TEACHER_WORK / "条件独立測定.jsonl.gz", LEDGER, preflight_path, old_preflight_path, source.MANIFEST,
        Path(__file__), HERE / "保存検証の人工検査.py", HERE / "監査仕様.md"]
    for meta in [*result["モデル"], *result["元学習モデル"], *result["回収集計"]]:
        files.append(ROOT / meta["path"])
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in files}
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("71固定:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    for name, digest in inputs["ファイルSHA256"].items():
        audit.check("71入力台帳:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("70完了台帳指定SHA", source.sha(LEDGER), "7dcd85171c51a8ba6a526b7a0e5f3e5ae25375e8b6e3f5676ab45b07140d3c33")
    audit.check("70成功監査", (proof["全件一致"], proof["不一致数"], proof["結果SHA256"]), (True, 0, source.sha(OLD / "結果.json")))
    audit.check("69成功監査", (teacher_proof["全件一致"], teacher_proof["不一致数"], teacher_proof["結果SHA256"]), (True, 0, source.sha(TEACHER_STUDY / "結果.json")))
    audit.check("70単一完了", source.read(OLDWORK / "実行完了.json")["結果SHA256"], proof["結果SHA256"])
    audit.check("70完了対象数", len(ledger["成果物SHA256"]), 138)
    for name, digest in ledger["成果物SHA256"].items():
        audit.check("70完了不変:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("71固定bind", (result["試行"], result["固定SHA256"], result["全66場既使用"]), (71, source.sha(STUDY / "固定.json"), True))
    audit.check("新六候補集合", set(result["候補"]), {*CONTROLS, *POLICIES})
    names = ("新回帰器fit", "新分類器fit", "新保存木数", "新元学習木数", "新派生木数", "参照モデル数", "新独立計測", "参照独立測定", "新運用数")
    audit.check("71新処理範囲", tuple(result[name] for name in names), (24, 0, 12, 6, 6, 3, 0, 4092, 184))
    audit.check("71保存対照", result["対照参照"], {"候補": list(CONTROLS), "元試行": 70, "市場再生": False})
    audit.check("71学習参照", result["学習参照"], {"元試行": 69, "モデル政策": "C0", "同じ可知集合": True, "同じ条件教師": True,
        "基礎60投影同値": True, "新fit": True, "追加": F61, "無取引": "回収0・障壁対象外"})
    # ----------------------------------------
    # 固定69の既存算術を再構成し、取得位置は本監査の分数算術で別に作る。
    reader = load(HERE.parent / "条件入口の教師/入力.py", "取得71監査の固定69入力")
    entries, blocks, base, immediate, conditions, _, inherited = reader.verified_inputs()
    audit.check("旧69検査", inherited, old_preflight["検査"])
    audit.check("旧69全特徴SHA", fingerprint(base), old_preflight["全特徴SHA256"])
    audit.check("旧69全条件SHA", fingerprint(conditions), old_preflight["全条件SHA256"])
    audit.check("旧69全予定判断SHA", fingerprint({name: block["slots"] for name, block in blocks.items()}), old_preflight["全予定判断SHA256"])
    audit.check("既使用66場台帳", entries, source.read(source.MANIFEST)["entries"])
    evaluated = [entry["session"] for entry in entries[20:]]
    audit.check("同46評価場", result["評価場"], evaluated)
    audit.check("学習専用20場", result["学習専用場"], [entry["session"] for entry in entries[:20]])
    old_blocks = {(block["session"], block["policy"]): block for block in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz")}
    audit.check("旧P92集合", set(old_blocks), {(session, policy) for session in evaluated for policy in CONTROLS})
    features_compared = 0
    for block in old_blocks.values():
        for slot in block["slots"]:
            audit.check("70P当時全60辞書", slot["feature"], base[slot["slot_id"]])
            features_compared += 1
    audit.check("旧P全3404特徴", features_compared, 3404)
    measured = {}
    for row in source.json_rows(TEACHER_WORK / "条件独立測定.jsonl.gz"):
        key = row["slot_id"], row["side"]
        if key in measured:
            raise ValueError("旧独立方向の重複")
        measured[key] = row
    expected_keys = {(slot["slot_id"], side) for block in blocks.values() for slot in block["slots"] if base[slot["slot_id"]]["ready"] for side in (1, -1)}
    audit.check("旧4092方向の集合", (len(measured), set(measured)), (4092, expected_keys))
    extended, ages, signs = {}, Counter(), {"1": Counter(), "-1": Counter()}
    ready = same_end = same_close = both = 0
    for block in blocks.values():
        for slot in block["slots"]:
            feature = base[slot["slot_id"]]
            quote = quotes_for(slot, immediate) if feature["ready"] else None
            new = extend_feature(slot, feature, quote)
            extended[slot["slot_id"]] = new
            audit.check("取得位置旧60射影", base_projection(new), feature)
            if not feature["ready"]:
                continue
            ready += 1
            position = new["position"]
            same_end += int(position["same_end"])
            same_close += int(position["same_close"])
            both += int(position["same_end"] and position["same_close"])
            ages[str(position["upper_age_seconds"])] += 1
            for side in ("1", "-1"):
                value = position["values"][side]["value"]
                signs[side]["正" if value > 0 else "負" if value < 0 else "零"] += 1
    checks = {"旧69検査": inherited, "旧70全特徴一致": features_compared, "全予定枠": len(base), "準備済み枠": ready,
        "旧60投影一致": len(base), "BBO両方向5項目結合": ready, "新取得位置方向": ready * 2, "旧条件方向": len(measured),
        "旧保存運用": len(old_blocks), "上位と現3分の同end": same_end, "上位と現3分の同close": same_close, "両方同じ": both,
        "上位古さ秒": dict(ages), "g符号": {side: dict(counter) for side, counter in signs.items()}, "全60特徴SHA256": fingerprint(base),
        "全61特徴SHA256": fingerprint(extended), "全条件SHA256": fingerprint(conditions), "旧70台帳SHA256": source.sha(LEDGER)}
    audit.check("追加後同2442準備2046", (len(extended), ready, set(extended)), (2442, 2046, set(base)))
    audit.check("71事前接続検査", preflight["検査"], checks)
    audit.check("71結果入力検査", result["入力検査"], checks)
    audit.check("71事前metadata", preflight["特徴metadata"], {policy: metadata(policy) for policy in COUNTS})
    # ----------------------------------------
    # 可知pairを再構成し、全raw統計と支持だけの剪定・派生calを別々に確認する。
    models, calibrations, model_pins = {}, {}, {}
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
        fields = ("全予定枠", "共通可知枠", "共通方向行", "除外枠数", "使用分類", "共通ID同順序", "方向重み")
        audit.check("71同共通教師要約", result["共通教師"][name], {**{key: common[key] for key in fields},
            "旧69共通集合SHA256": fingerprint(common), "旧69結果path": (TEACHER_STUDY / "結果.json").relative_to(ROOT).as_posix()})
        teachers = {"B0": deepcopy(rows["C0"]), "G0": []}
        for row in rows["C0"]:
            new = deepcopy(row)
            new["features"] = deepcopy(extended[row["slot_id"]]["vectors"][str(row["side"])])
            audit.check("61教師旧60全射影", {**new, "features": new["features"][:60]}, row)
            teachers["G0"].append(new)
        trainings = {}
        for policy, count in COUNTS.items():
            identity, raw_identity = policy + "_" + name, policy + "_" + name + "_学習"
            meta, raw_info, cal_info = model_meta[policy, name], raw_meta[policy, name], cal_meta[policy, name]
            raw, model, calibration = [source.read(ROOT / item["path"]) for item in (raw_info, meta, cal_info)]
            for item in (raw_info, meta, cal_info):
                model_pins[item["path"]] = source.sha(ROOT / item["path"])
                audit.check("71木/calSHA", model_pins[item["path"]], item["SHA256"])
            used, training = canonical_rows(teachers[policy], phase["evaluation_start"], policy)
            trainings[policy] = training
            check_raw_model(raw, used, training, metadata(policy), raw_identity, source.sha(HERE / "学習.py"), audit)
            fit_count += sum(group["fit_performed"] for group in raw["training"]["partition"].values())
            check_pruned(model, raw, identity, model_pins[raw_info["path"]], audit)
            audit.check("71剪定全文", result["剪定"][name][policy], model["pruning"])
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
            if policy == "B0":
                old_raw_path = TEACHER_STUDY / "models" / ("C0_" + name + ".json")
                old_model_path = OLD / "models" / ("P0_" + name + ".json")
                old_raw, old_model = source.read(old_raw_path), source.read(old_model_path)
                audit.check("69元木成功bind", source.sha(old_raw_path), teacher_proof["モデルSHA256"][old_raw_path.relative_to(ROOT).as_posix()])
                baseline_raw(raw, old_raw, audit)
                audit.check("B0旧70派生nodes全文", model["nodes"], old_model["nodes"])
                model_pins[old_raw_path.relative_to(ROOT).as_posix()] = source.sha(old_raw_path)
                model_pins[old_model_path.relative_to(ROOT).as_posix()] = source.sha(old_model_path)
            models[policy, name], calibrations[policy, name] = model, calibration
        audit.check("B/G同使用ID", trainings["B0"]["row_ids_sha256"], trainings["G0"]["row_ids_sha256"])
        audit.check("B/G同base60六指紋", trainings["B0"]["base60_fingerprints"], trainings["G0"]["base60_fingerprints"])
    audit.check("新回帰器fit数", result["新回帰器fit"], fit_count)
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
            audit.check("旧P資源全文", resource_map[row["session"], row["method_id"]], row)
    accounts, summaries, cache_pins, viewer_pins = [], [], {}, {}
    entries_matched = closed_matched = controls_matched = 0
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
            prepared = base if model_policy == "B0" else extended
            slots = expected_slots(blocks[session], prepared, models[model_policy, phase], calibrations[model_policy, phase], policy, phase)
            audit.check("71純全辞書", block["slots"], slots)
            audit.check("71評価phase", block["phase"], phase)
            slots_by_policy[policy].extend(slots)
            expected_conditions = {slot["slot_id"]: conditions[slot["slot_id"]] for slot in slots if slot["side"]}
            audit.check("71採用条件全文", block["conditions"], expected_conditions)
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
            if policy.startswith("B"):
                baseline_operation(slots, operation, old_blocks[session, "P" + policy[1]], audit)
                controls_matched += 1
            path = ROOT / resource_map[session, policy]["pnl_path"]
            audit.check("新Viewer正規パス", path.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            audit.check("新Viewer全約定", list(source.json_rows(path)), operation["trades"])
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            summaries.append({"場": session, "候補": policy, "期間": source.span(session), "入力品質": input_quality, "運用品質": operation["quality"], "運用集計": operation["metrics"]})
        print(session + " 取得位置/元木/剪定/新四運用照合", flush=True)
    audit.check("新全184場別", result["場別"], summaries)
    audit.check("主五検査", result["検査"], {"同一条件実仮新規一致": entries_matched, "同一条件実独立完結一致": closed_matched,
        "旧69元木再現": 3, "旧70派生木再現": 3, "旧70運用再現": controls_matched})
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
            audit.check("旧P対照全期", result["候補"][policy], previous["候補"][policy])
        if policy.startswith("B"):
            audit.check("B/P全期集計", result["候補"][policy], previous["候補"]["P" + policy[1]])
    audit.check("新採用", result["採用"], [policy for policy in POLICIES if all(result["候補"][policy][period]["同時適格"] for period in PERIODS[:2])])
    audit.check("新詳細二系列", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("新詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins, **cache_pins, **viewer_pins}.items():
        audit.check("監査中参照不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 71, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0,
        "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples, "結果SHA256": source.sha(STUDY / "結果.json"),
        "本物fit再実行": False, "新主処理import": False, "新入力import": False, "新学習import": False, "Engine期待値import": False, "市場戦略再生": False,
        "既存特徴算術再構成": True, "新取得位置独立算術": True, "新元学習木数": 6, "新派生木数": 6, "新運用数": 184, "再用独立教師数": len(measured),
        "同一条件実仮新規数": entries_matched, "同一条件実独立完結数": closed_matched, "旧対照運用同値数": controls_matched,
        "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api,
        "検証範囲": "旧70完了138対象/旧69成功証明、取得位置の当時5key/BBO/上位SOURCEとFraction値、同可知pair/60・61六指紋/六raw全node統計、支持DP/六派生cal、全純JSON採否、新184原BBO条件/注文/保護/現金/品質、六候補集計とViewer276/新4代表。",
        "限定": "固定69入力の既存特徴算術再構成あり、新特徴全体の独立算法監査ではない。旧4092独立教師は成功指紋で再用し再測定/全件再監査しない。回帰分岐の最適性を再fitせず、支持剪定と採否・会計を検査する。gは設定気配であり将来取得・未知収益・心理因果を証明しない。"}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


# ----------------------------------------
def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """276資源と新B0/B1/G0/G1各一代表の約定・台帳をHTTP照合する。

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


def self_test() -> dict:
    """取得位置と支持剪定の保存監査を、架空木・架空価格だけで検査する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致。人工fitだけを許容し、本物入力・公式proofは生成しない。
    """
    fixture = load(HERE / "保存検証の人工検査.py", "取得位置71保存監査の人工")
    return fixture.self_test()


def main() -> None:
    """人工と正式照合を排他CLIで公開する。

    引数: CLIのrun/self_test(bool)はモード、viewer_url(str|None)はHTTP。
    返り値: None。正式runはroot所有で一度だけ実行する。
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
