"""65のDI/対応episode有効四群と同60教師・新92運用を独立に照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import importlib.util
import json
import math
import struct
from pathlib import Path
from urllib.parse import urlencode, urljoin

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00065_方向に対応する現在の有効状態を先に分ける"
WORK = ROOT / "work/状態と判断/00065"
OLD = ROOT / "study/00064_再試験の量と価格進行を別々に確認"
OLDWORK = ROOT / "work/量と価格進行/00064"
COMPLETE = ROOT / "work/量と価格進行/64完了記録.json"
MEASUREMENTS = ROOT / "work/独立追尾回収/00055/独立測定.jsonl.gz"
FRAMES = ROOT / "work/一目基準線/00028/全指標.jsonl.gz"
SLOTS50 = ROOT / "work/局所再開/00050/定時判断と運用.jsonl.gz"
POLICIES, CONTROLS = ("U0", "U1"), ("Q0", "Q1")
PERIODS = ("学習", "条件選択", "後続検査")
BINDING = ("slot_id", "session", "scheduled", "time", "line")
COUNTS = {"U0":60,"U1":60}
FIXED_NODES = [{"id":0,"feature":"F01","index":0,"threshold":0.},
    {"id":1,"feature":"F26","index":25,"threshold":.5},
    {"id":2,"feature":"F20","index":19,"threshold":.5}]
CHILD_COLUMNS = {"D0":[i for i in range(60) if i not in (0,25)],"D1":[i for i in range(60) if i not in (0,19)]}
QUANTITY_PATH = ROOT / "work/OBV反転/00029/全指標.jsonl.gz"
Q_FIELDS = ("観測差分量", "数量基準完全", "直前数量足数", "直前数量合計", "直前数量平均", "RVOL", "数量準備済",
    "最終採用数量時計", "最終採用価格時計", "最終採用原行", "数量不完全理由")
FINGERPRINT_FIELDS = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")


def load(path: Path, name: str):
    """固定純補助を独自名で読み、旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。新主処理を正式監査でimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R64 = load(ROOT/"scripts/量と価格進行/保存検証.py","現在状態監査_固定64")
R63,R62,R61=R64.R63,R64.R62,R64.R61
R60,R59,R58,R56,A,P,R55=R64.R60,R64.R59,R64.R58,R64.R56,R64.A,R64.P,R64.R55
S63,I49=R64.S63,R64.I49
fingerprint=A.fingerprint
path_coverage,episode_counts=R60.path_coverage,R60.episode_counts
feature_metadata,float32,prepare_features=R64.feature_metadata,R64.float32,R64.prepare_features
regime_coverage,quantity_coverage=R64.regime_coverage,R64.quantity_coverage
FINGERPRINT_FIELDS=R64.FINGERPRINT_FIELDS


# ----------------------------------------
# 旧64の全60独立算術を保持し、変更する固定段・教師・採否を別に検査する。


# ----------------------------------------
# 分岐DIはfloat32、実運用のDI役割は旧規約のraw符号を維持する。

def group_key(values: list) -> str:
    """float32 DIと対応episode有効から四群を確定する。

    引数: values(list)は固定64と同じ60特徴。
    返り値: strはD0_V0等。raw実役割やk成立と同一視しない。
    """
    converted=float32(values,60)
    direction=int(converted[0]>0)
    valid=int(converted[19 if direction else 25]>.5)
    return f"D{direction}_V{valid}"


def expected_rules() -> dict:
    """旧64のDI一根を対応episodeの固定二段へ変更する規約を定義する。

    引数: なし。
    返り値: dictはU0/U1規約。新Lを期待値として呼ばない。
    """
    rules=R64.expected_rules()
    for key in ("固定DI根","B1","Q1"):
        rules.pop(key)
    rules.update({"政策深さ":{"U0":4},"政策特徴数":{"U0":60},
        "U0固定段":{"根":{"feature":"F01","index":0,"threshold":0.0},
            "第二段":{"D0":{"feature":"F26","index":25,"threshold":0.5,"route":"R"},
                "D1":{"feature":"F20","index":19,"threshold":0.5,"route":"T"}},
            "群":["D0_V0","D0_V1","D1_V0","D1_V1"],"子深さ":2,"子特徴数":58,
            "子特徴列index":CHILD_COLUMNS,"MSE最適固定段ではない":True},
        "U1":"同一U0木を使用。従来の回収支持とstrict正額追加条件を後段で判定",
        "群の意味":"float32 DI非正側はR/正側はTの現在episode有効。Rも出生bから真で、f/r/k成立とは別",
        "群の除外":"V0も四群に残し即WAITにしない。全pair除外は分割前に行い、枝内pair成立を要求しない",
        "複数技法":"固定DI根trendと対応episode旗priceが有効pathへ入る。従来gateは変更せず構造的に充足する",
        "比較の限定":"同60情報/教師。固定順・枝別58列投影・深さ3から2への容量配分と技法資格自動充足を含み、flagや量の単独効果ではない"})
    return rules


def recovery_training(rows: list[dict], evaluation_start: float, count: int = 60) -> tuple:
    """固定64の全60教師検査を保持し同じ六指紋をbase60へ加える。

    引数: rows(list[dict])は同じ60列教師、evaluation_start(float)は評価開始、count(int)は60のみ。
    返り値: tuple[list,dict]は同じ使用行と旧18/30/38/46/54/60指紋。
    """
    if count!=60:
        raise ValueError("65は60列が必要")
    used,training=R64.recovery_training(rows,evaluation_start,60)
    training["base60_fingerprints"]={key:training[key] for key in FINGERPRINT_FIELDS}
    training["feature_missing_handling"]="旧64全60特徴・同じ教師pair。追加情報・追加除外なし"
    return used,training


def expected_counts(inherited: dict, matches: int, closed: int, quantity_counts: dict) -> dict:
    """旧64の13項目を完全照合し旧64保存一致を1件追加する。

    引数: inherited(dict)は旧64結果、matches/closed(int)は保存60/同一新規完結数、quantity_counts(dict)は既存数量。
    返り値: dictは14項目。旧38等の継承項目を省略しない。
    """
    names=("測定特徴方向一致","旧評価特徴完全一致","同一新規完結一致","旧18特徴完全一致",
        "旧38特徴保存一致","旧46特徴保存一致","旧46射影一致","旧62特徴保存一致")
    if not set(names)<=set(inherited):
        raise ValueError("旧八キーに欠落")
    prior=R64.expected_counts({key:inherited[key] for key in names},3404,inherited["同一新規完結一致"],quantity_counts)
    if not S63.strict_equal(prior,inherited) or matches!=3404 or type(closed) is not int or closed<0:
        raise ValueError("旧13カウンタ又は今回保存照合数に差")
    return {**inherited,"同一新規完結一致":closed,"旧64特徴保存一致":matches}


def state_distribution(used: list[dict], prepared: dict) -> dict:
    """DIと対応有効旗の教師四群を排他的段階・両経路状態へ分解する。

    引数: used(list[dict])は使用教師、prepared(dict)は独立全60特徴。
    返り値: dictはD×V四群。枠数と独立episode数を分離する。
    """
    result={}
    for d in (0,1):
        role="T" if d else "R"
        for valid in (0,1):
            key=f"D{d}_V{valid}"
            selected=[row for row in used if group_key(row["features"])==key]
            targets=[prepared[row["slot_id"]]["paths"][str(row["side"])][role] for row in selected]
            stages=[]
            for path in targets:
                if path["episode_id"] is None:
                    stages.append("未ID又は失効")
                else:
                    stage=next((event for event in ("k","r","f","b") if path.get(event) is not None),"段階不明")
                    stages.append(stage+("取消" if path["cancel"] is not None else "有効" if path["episode_valid"] else "無効"))
            item={"方向枝":"DI正" if d else "DI非正","対象経路":role,"episode有効":valid,
                "方向行":len(selected),"unique枠":len({(row["session"],row["slot_id"]) for row in selected}),
                "日数":len({row["session"][:10] for row in selected}),"場数":len({row["session"] for row in selected}),
                "対象現在段階":dict(sorted(Counter(stages).items()))}
            for route in ("T","R"):
                paths=[prepared[row["slot_id"]]["paths"][str(row["side"])][route] for row in selected]
                ids=Counter(path["episode_id"] for path in paths if path["episode_id"] is not None)
                item[route]={"形成あり":sum(path["episode_id"] is not None for path in paths),"形成なし":sum(path["episode_id"] is None for path in paths),
                    "取消あり":sum(path["cancel"] is not None for path in paths),"episode有効":sum(path["episode_valid"] for path in paths),
                    **{event+"あり":sum(path.get(event) is not None for path in paths) for event in ("b","f","r","k")},
                    "k有効":sum(path["k_valid"] for path in paths),"形成ID数":len(ids),"最大反復":max(ids.values(),default=0),
                    "段階":dict(sorted(Counter(str(path["stage"]) for path in paths).items()))}
            result[key]=item
    return result


def walk(model: dict, values: list) -> tuple:
    """同じ60列の保存木を独立に走査する。

    引数: model(dict)はU0保存木、values(list)は同列数の特徴。
    返り値: tupleはleaf/path/全所属node。新L.walkは呼ばない。
    """
    count = COUNTS.get(model.get("policy"))
    values, index, path, visits = float32(values, count), 0, [], []
    while True:
        if type(index) is not int or not 0 <= index < len(model["nodes"]) or index in visits:
            raise ValueError("保存木の循環又は範囲外")
        node = model["nodes"][index]
        if node["id"] != index:
            raise ValueError("node ID不整合")
        visits.append(index)
        if node["left"] == node["right"] == -1:
            return index, path, visits
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < count or not A.finite(node["threshold"]):
            raise ValueError("分岐値不正")
        branch = "left" if values[feature] <= node["threshold"] else "right"
        meta = model["feature_meta"][feature]
        path.append({"node": index, "feature": feature, "feature_id": meta["id"], "method": meta["method"], "family": meta["family"],
            "threshold": node["threshold"], "comparison": "<=" if branch == "left" else ">", "branch": branch})
        index = node[branch]


def check_reused_proof(source, audit) -> tuple:
    """旧64の成功監査・完了台帳と数量/測定の既検証版を結ぶ。

    引数: source(ModuleType)は固定読取、audit(Audit)は照合記録。
    返り値: tupleは旧64結果/proof/完了台帳。旧監査や市場を再起動しない。
    """
    R64.check_reused_proof(source,audit)
    previous,proof,done=[source.read(path) for path in (OLD/"結果.json",OLD/"保存物確認.json",COMPLETE)]
    audit.check("64単一市場実行",(done["試行"],done["市場実行終了"],done["本物実行回数"]),(64,True,1))
    audit.check("64監査成功",(proof["全件一致"],proof["不一致数"]),(True,0))
    audit.check("64結果bind",source.sha(OLD/"結果.json"),proof["結果SHA256"])
    paths=[OLD/name for name in ("結果.json","固定.json","保存物確認.json","一覧.resources.json")]
    paths += [OLDWORK/name for name in ("定時判断と運用.jsonl.gz","入口先着.jsonl.gz")]
    paths += [ROOT/meta["path"] for meta in previous["モデル"]+previous["回収集計"]]
    for path in paths:
        name,digest=path.relative_to(ROOT).as_posix(),source.sha(path)
        audit.check("64完了SHA:"+name,digest,done["成果物SHA256"][name])
        if path!=OLD/"保存物確認.json":
            audit.check("64成功監査SHA:"+name,digest,{**proof["参照SHA256"],**proof["モデルSHA256"]}[name])
    for path in (MEASUREMENTS,QUANTITY_PATH,SLOTS50):
        name=path.relative_to(ROOT).as_posix()
        audit.check("64検証済み入力bind:"+name,source.sha(path),proof["参照SHA256"][name])
    return previous,proof,done


def check_model(model: dict, used: list[dict], training: dict, meta: list[dict], identity: str, learner_sha: str, audit) -> None:
    """新回帰木の全所属・現在有効4群・先着率と回収統計を独立再構成する。

    引数: model(dict)は保存木、used/trainingは独立教師、meta(list[dict])は60列、
        identity/learner_sha(str)はID/版、audit(Audit)は記録。
    返り値: None。最良閾値の探索や別fitはせず、固定段の最適性を要求しない。
    """
    audit.check(identity + ":schema", (model["schema_version"], model["model_id"], model["policy"]), (1, identity, "U0"))
    audit.check(identity + ":metadata", model["feature_meta"], meta)
    audit.check(identity + ":metadata指紋", model["feature_meta_sha256"], fingerprint(meta))
    audit.check(identity + ":学習code", model["source_sha256"], learner_sha)
    audit.check(identity + ":library", model["versions"]["scikit-learn"], "1.9.1")
    audit.check(identity + ":本体引数", model["parameters"], R56.regressor_parameters(4))
    audit.check(identity + ":子引数", model["subtree_parameters"], R56.regressor_parameters(2))
    audit.check(identity + ":構造", model["structure"], {"kind": "fixed_direction_current_episode", "fixed_nodes": FIXED_NODES,
        "child_depth": 2, "child_features": 58, "child_feature_indices": CHILD_COLUMNS,
        "excluded_feature_indices": {"D0": [0, 25], "D1": [0, 19]}, "feature_count": 60,
        "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"})
    audit.check(identity + ":規約", model["rules"], expected_rules())
    shared = [ROOT / "scripts/方向局面分岐/学習.py", ROOT / "scripts/局所帯分岐/学習.py", ROOT / "scripts/回収目的分岐/学習.py", ROOT / "scripts/波の区間分離/学習.py", ROOT / "scripts/現行経路の状態分岐/学習.py", ROOT / "scripts/方向と再開確認/学習.py", ROOT / "scripts/局面強弱の複合確認/学習.py", ROOT / "scripts/量と価格進行/学習.py"]
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
            fixed = FIXED_NODES[index]
            audit.check(identity + ":固定node", (node["feature"], node["feature_id"], node["threshold"]), (fixed["index"], fixed["feature"], fixed["threshold"]))
            audit.check(identity + ":固定内部保持", node["left"] >= 0 and node["right"] >= 0, True)
        if node["left"] == node["right"] == -1:
            audit.check(identity + ":葉記号", (node["feature"], node["feature_id"], node["family"], node["threshold"]), (-2, None, None, -2.))
            continue
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < 60 or not A.finite(node["threshold"]):
            raise ValueError("分岐値不正")
        if index >= 3:
            branch = "D1" if paths[index][0]["branch"] == "right" else "D0"
            audit.check(identity + ":枝別子58列", feature in CHILD_COLUMNS[branch], True)
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
            selected=[row for row in used if group_key(row["features"])==key]
            root=nodes[d+1]["right" if valid else "left"]
            descendants=[i for i,path in paths.items() if len(path)>=2 and path[0]["branch"]==("right" if d else "left") and path[1]["branch"]==("right" if valid else "left")]
            audit.check(identity+key+":子offset",root,offset)
            audit.check(identity+key+":連続ID",sorted(descendants),list(range(offset,offset+len(descendants))))
            audit.check(identity+key+":子depth2",all(len(paths[i])-2<=2 for i in descendants),True)
            audit.check(identity+key+":所属",membership[root],selected)
            if not selected:
                audit.check(identity+key+":空群一未知leaf",(len(descendants),nodes[root]["left"],nodes[root]["right"],nodes[root]["data_absent"]),(1,-1,-1,True))
            ids=[{k:row[k] for k in ("session","slot_id","side")} for row in selected]
            partition[key]={"d":d,"v":valid,"route":"T" if d else "R","policy":"U0","excluded_feature_indices":[0,19 if d else 25],
                "child_feature_indices":CHILD_COLUMNS[f"D{d}"],"direction_rows":len(selected),"pair_unique":len({(row["session"],row["slot_id"]) for row in selected}),
                "days":len({row["session"][:10] for row in selected}),"sessions":len({row["session"] for row in selected}),"row_ids_sha256":fingerprint(ids),
                "fit_performed":bool(selected),"root":root,"node_count":len(descendants),"fit_parameters":R56.regressor_parameters(2)}
            offset+=len(descendants)
    audit.check(identity+":四群全方向",sum(p["direction_rows"] for p in partition.values()),len(used))
    audit.check(identity+":全training",model["training"],{**deepcopy(training),"partition":partition})
    roots = {p["root"] for p in partition.values()}
    for index, node in enumerate(nodes):
        rows = membership[index]
        successes = sum(A.TARGETS[r["outcome"]] for r in rows)
        score = successes / len(rows) if rows else None
        expected = {"direction_rows": len(rows), "weighted_rows": len(rows) / 2, "success_weight": successes / 2, "total_weight": len(rows) / 2,
            "score": score, "barrier_gini": 2 * score * (1 - score) if score is not None else None, "impurity_kind": "squared_error",
            "unique_slots": len({(r["session"], r["slot_id"]) for r in rows}), "days": len({r["session"][:10] for r in rows}), "sessions": len({r["session"] for r in rows}),
            "methods": sorted({p["method"] for p in paths[index]}), "families": sorted({p["family"] for p in paths[index]}), "data_absent": not bool(rows),
            "training_ids_sha256": fingerprint([{k: r[k] for k in ("session", "slot_id", "side")} for r in rows])}
        statistics = R56.decimal_statistics(rows)
        second = statistics.pop("second_moment")
        for key in ("regression_value", "impurity"):
            value = statistics.pop(key)
            if index < 3:
                audit.check(identity + str(index) + ":固定段" + key, node[key], value)
            else:
                audit.check(identity + str(index) + ":生回帰器" + key, R56.numeric_match(node[key], value, "mean" if key == "regression_value" else "mse", second), True)
        for key, value in {**expected, **statistics}.items():
            audit.check(identity + str(index) + ":" + key, node[key], value)
        audit.check(identity + ":data_absent型", type(node["data_absent"]) is bool, True)
        eligibility = A.eligibility(node, paths[index])
        audit.check(identity + ":支持旗", (node["leaf_support"], node["method_support"]), (eligibility["leaf_support"], eligibility["method_support"]))
        if index >= 3 and node["left"] != -1:
            audit.check(identity + ":通常子minleaf60", min(len(membership[node["left"]]), len(membership[node["right"]])) >= 60, True)
        if not rows and index >= 3:
            audit.check(identity + ":空は群root一葉", index in roots and node["left"] == node["right"] == -1, True)


def predict(model: dict, vectors: dict) -> dict:
    """保存木の両方向を独立採点し、未知枝では既知側への救済も行わない。

    引数: model(dict)は検算済みU0木、vectors(dict)は政策列数×両方向。
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
        absent = node.get("data_absent") is True
        if absent and (node["score"] is not None or node["direction_rows"] != 0):
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


def expected_calibration(model: dict, measurements: dict, evaluation_start: float) -> dict:
    """新U0の使用教師へ確定回収pairを結び、全葉を独立集計する。

    引数: model(dict)は新U0木、measurements(dict)は枠/side→測定、evaluation_start(float)は後続開始。
    返り値: dictは全葉の支持・十進純額・平均・採否符号・教師指紋。新fitをしない。
    """
    identities = model["training"]["row_ids"]
    pairs = {}
    for identity in identities:
        key = identity["slot_id"], identity["side"]
        row = measurements[key]
        if row["session"] != identity["session"] or row["ready"] is not True:
            raise ValueError("旧教師の準備又は場が不一致")
        barrier = row["barrier"]
        if barrier is None or barrier["outcome"] not in ("250", "125", "期限"):
            raise ValueError("旧使用教師の障壁結果が未知")
        if not A.finite(barrier["end_time"]) or not A.finite(row["recovery_end_time"]) or max(barrier["end_time"], row["recovery_end_time"]) >= evaluation_start:
            raise ValueError("障壁又は回収が評価開始よりstrict前ではない")
        pair = pairs.setdefault(identity["slot_id"], {})
        if identity["side"] in pair:
            raise ValueError("過去教師の重複")
        pair[identity["side"]] = row
    if any(set(pair) != {-1, 1} for pair in pairs.values()):
        raise ValueError("過去教師の片側抜け")
    excluded = [{"slot_id": key, "states": {str(s): pair[s]["status"] for s in (1, -1)}}
                for key, pair in pairs.items() if any(pair[s]["status"] != "確定完結" for s in (1, -1))]
    blocked = {row["slot_id"] for row in excluded}
    leaf_rows = {node["id"]: [] for node in model["nodes"] if node["left"] == -1}
    used = []
    for identity in identities:
        if identity["slot_id"] in blocked:
            continue
        row = measurements[identity["slot_id"], identity["side"]]
        if len(row["operation"]["closed"]) != 1:
            raise ValueError("確定回収は単独一完結が必要")
        leaf, _, _ = walk(model, row["features"])
        closed = row["operation"]["closed"][0]
        value = {**identity, "leaf": leaf, "recovery_end_time": row["recovery_end_time"], "barrier_end_time": row["barrier"]["end_time"],
                 **{f"pnl{fee}": closed[f"pnl{fee}"] for fee in (0, 5, 10)}}
        leaf_rows[leaf].append(value)
        used.append(value)
    leaves = {}
    for leaf, selected in leaf_rows.items():
        sums = {str(f): sum((Decimal(str(r[f"pnl{f}"])) for r in selected), Decimal(0)) for f in (0, 5, 10)}
        unique, days, sessions = len({r["slot_id"] for r in selected}), len({r["session"][:10] for r in selected}), len({r["session"] for r in selected})
        leaves[str(leaf)] = {"leaf": leaf, "direction_rows": len(selected), "unique_slots": unique, "days": days, "sessions": sessions,
            "sum_yen": {f: str(v) for f, v in sums.items()}, "mean_yen": {f: float(v / len(selected)) if selected else None for f, v in sums.items()},
            "support": unique >= 60 and days >= 6 and sessions >= 10, "positive": bool(selected) and sums["5"] > 0, "rows": selected,
            "max_teacher_end": max((max(r["barrier_end_time"], r["recovery_end_time"]) for r in selected), default=None)}
    return {"model_id": model["model_id"], "evaluation_start": evaluation_start, "old_teacher_direction_rows": len(identities),
        "old_teacher_ids_sha256": fingerprint(identities), "input_pairs": len(pairs), "used_pairs": len(pairs) - len(excluded),
        "excluded_pairs": excluded, "used_direction_rows": len(used), "weight_per_direction": .5, "used_rows_sha256": fingerprint(used),
        "leaves": leaves, "classifier_fit_count": 0,
        "meaning": "旧木の全過去教師と回収確定pairの共通部分による葉内記述。未来確率の校正ではない"}


def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """障壁score最高側へ回収支持と政策別のstrict正額だけを追加する。

    引数: model/calibration(dict)は同じ過去木・葉、vectors(dict)は当時特徴、policy(str)はU0/U1。
    返り値: dictは全採否。回帰平均で順位を変えず次点を救済しない。
    """
    if policy not in POLICIES or model["policy"] != policy[0]+"0" or calibration["model_id"] != model["model_id"]:
        raise ValueError("候補又は回収木の対応不正")
    prior = predict(model, vectors)
    side, reason, leaf = prior["side"], prior["reason"], None
    if side:
        leaf = calibration["leaves"][str(prior["leafs"][str(side)])]
        if not leaf["support"]:
            side, reason = 0, "回収支持不足WAIT"
        elif policy.endswith("1") and not leaf["positive"]:
            side, reason = 0, "過去回収平均非正WAIT"
    return {"side": side, "reason": reason, "prior": prior, "recovery_leaf": leaf["leaf"] if leaf else None,
        "recovery_support": leaf["support"] if leaf else None, "recovery_mean5": leaf["mean_yen"]["5"] if leaf else None}


def check_periods(accounts: list[dict], labels: dict, result: dict, source, summary, audit) -> None:
    """旧二対照と新二候補の先着・費用・活動を別集計する。

    引数: accounts/labelsは会計と先着、result(dict)は保存結果、source/summary(ModuleType)/audit(Audit)は純補助。
    返り値: None。単独測定の重複利益や分母1を活動へ流用しない。
    """
    for policy in (*CONTROLS, *POLICIES):
        selected = [row for row in accounts if row["candidate"] == policy]
        for period in PERIODS:
            entry = source.entry_summary(labels[policy], period)
            operation = summary.operation_summary(selected, period, source)
            audit.check(policy + period + ":入口", result["候補"][policy][period]["入口"], entry)
            audit.check(policy + period + ":運用", result["候補"][policy][period]["運用"], operation)
            audit.check(policy + period + ":同時適格", result["候補"][policy][period]["同時適格"], entry["70目標"] and operation["活動適格"] and operation["費用適格"])
            for role in ("順行", "反転"):
                audit.check(policy + period + role, result["役割別入口"][policy][period][role], source.entry_summary([r for r in labels[policy] if r["role"] == role], period))
            if policy in POLICIES:
                reasons = Counter(d["reason"] for row in selected if source.span(row["session"]) == period for d in row["decisions"])
                audit.check(policy + period + ":判断理由", result["判断理由"][policy][period], dict(reasons))
    audit.check("新二候補だけの採用", result["採用"], [p for p in POLICIES if all(result["候補"][p][s]["同時適格"] for s in PERIODS[:2])])


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """184資源と新二候補一代表のAPI約定・台帳を照合する。

    引数: base(str|None)はAPI、resources/accounts(list[dict])は保存値、source(ModuleType)/audit(Audit)は純補助。
    返り値: dictはAPI実行範囲。未指定なら未検証を明記する。
    """
    if not base:
        return {"実行": False, "理由": "--viewer-url未指定。API未検証、新92保存約定は全件照合"}
    query = {"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}
    listing, _, _ = source.fetch_json(base + "/api/resources?" + urlencode(query))
    audit.check("API184全集合", {r["id"] for r in listing["resources"]}, {r["id"] for r in resources})
    audit.check("API資源数", len(listing["resources"]), 184)
    representatives = []
    for policy in POLICIES:
        account = sorted([a for a in accounts if a["candidate"] == policy], key=lambda a: (-abs(a["ledger"]["5"]), a["session"]))[0]
        resource = next(r for r in resources if r["method_id"] == policy and r["session"] == account["session"])
        parameters = {**query, "resource": resource["id"], "interval": "5", "price": "last", "width": 1000, "height": 700}
        meta, _, _ = source.fetch_json(base + "/api/chart?" + urlencode(parameters))
        data, raw, headers = source.fetch_json(urljoin(base + "/", meta["data_url"]))
        audit.check("API本文SHA", hashlib.sha256(raw).hexdigest(), meta["data_sha256"])
        audit.check("APIヘッダSHA", headers.get("x-chart-data-sha256"), meta["data_sha256"])
        audit.check("API集計alias", data["summary"], meta["summary"])
        audit.check("API台帳純額5", Decimal(str(data["summary"]["realized_pnl_yen"])), Decimal(str(account["ledger"]["5"])))
        trades = list(source.json_rows(ROOT / resource["pnl_path"]))
        audit.check("API約定片数", len(data["events"]), len(trades))
        for sequence, (trade, event) in enumerate(zip(trades, data["events"]), 1):
            for key in ("type", "qty", "position_id", "method_id", "price"):
                audit.check("API約定" + key, event[key], trade[key])
            audit.check("API順", event["sequence"], sequence)
            audit.check("API時刻", abs(event["timestamp_ms"] - datetime.fromisoformat(trade["timestamp"]).timestamp() * 1000) <= .001, True)
        representatives.append({"候補": policy, "場": account["session"], "資源ID": resource["id"], "台帳観測5円": account["ledger"]["5"], "数値SHA256": meta["data_sha256"]})
    return {"実行": True, "全資源数": 184, "新政策代表": representatives, "代表規約": "候補別最大絶対台帳観測額。採否へ不使用"}


def episode_support(model: dict, used: list[dict], prepared: dict) -> dict:
    """全60教師を独立走査し各葉の経路反復を再集計する。

    引数: model(dict)はU0木、used(list[dict])は同教師、prepared(dict)は同じ当時特徴。
    返り値: dictは全葉の方向行とT/R形成。支持を独立episodeへ置換しない。
    """
    selected={node["id"]:[] for node in model["nodes"] if node["left"]==-1}
    for row in used:
        feature,side=prepared[row["slot_id"]],str(row["side"])
        leaf,_,_=walk(model,feature["vectors"][side])
        selected[leaf].append(feature["paths"][side])
    return {str(leaf):{"方向行":len(paths),**{role:episode_counts([path[role] for path in paths]) for role in ("T","R")}} for leaf,paths in selected.items()}


def run(viewer_url: str | None = None) -> dict:
    """保存された三木と新92運用をfit・市場再生なしで独立監査する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは全差・原典と結果の指紋・Viewer範囲。既存proofは上書きしない。
    """
    destination = STUDY/"保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    source,label_helper,summary=A.helpers()
    audit=source.Audit()
    files=[STUDY/name for name in ("結果.json","固定.json","条件.json","入力台帳.json","一覧.resources.json")]
    files += [WORK/name for name in ("定時判断と運用.jsonl.gz","入口先着.jsonl.gz")]
    files += [ROOT/"work/状態と判断/教師接続確認.json",COMPLETE,MEASUREMENTS,FRAMES,SLOTS50,QUANTITY_PATH,source.MANIFEST]
    files += [OLD/name for name in ("結果.json","固定.json","保存物確認.json","一覧.resources.json")]
    files += [OLDWORK/name for name in ("定時判断と運用.jsonl.gz","入口先着.jsonl.gz","保存検証_実行.log")]
    files += [Path(__file__),Path(__file__).with_name("学習.py"),ROOT/"scripts/量と価格進行/特徴.py",Path(__file__).with_name("監査人工.py"),Path(__file__).with_name("監査仕様.md")]
    before={path.relative_to(ROOT).as_posix():source.sha(path) for path in files}
    fixed,result=source.read(STUDY/"固定.json"),source.read(STUDY/"結果.json")
    for name,digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典:"+name,source.sha(ROOT/name),digest)
    audit.check("監査自己の固定包含",Path(__file__).relative_to(ROOT).as_posix() in fixed["ファイルSHA256"],True)
    audit.check("完全50slot固定包含",fixed["ファイルSHA256"][SLOTS50.relative_to(ROOT).as_posix()],source.sha(SLOTS50))
    audit.check("試行・固定bind",(result["試行"],result["固定SHA256"]),(65,source.sha(STUDY/"固定.json")))
    audit.check("全六候補",set(result["候補"]),{*CONTROLS,*POLICIES})
    audit.check("新fit種別・独立・運用",(result["新分類器fit"],result["新独立計測"],result["新運用数"]),(0,0,92))
    previous,previous_proof,_=check_reused_proof(source,audit)
    entries=source.read(source.MANIFEST)["entries"]
    phases=A.phases(entries,source)
    evaluated=[entry["session"] for entry in entries[20:]]
    audit.check("評価46場順",result["評価場"],evaluated)
    audit.check("初期20場学習専用",result["学習専用場"],[e["session"] for e in entries[:20]])
    audit.check("旧64モデルmetadata",result["対照モデル"],[m for m in previous["モデル"] if m["policy"]=="Q0"])
    audit.check("旧準備比較全辞書",result["準備比較"],previous["準備比較"])
    audit.check("測定保存再用",result["独立測定"],previous["独立測定"])
    audit.check("旧64対照参照",result["対照参照"],{"候補":list(CONTROLS),"元試行":64,"同じ評価46場":True,"市場再生":False})
    audit.check("測定参照",result["独立測定参照"],{"元試行":55,"path":MEASUREMENTS.relative_to(ROOT).as_posix(),"sha256":source.sha(MEASUREMENTS),"再計測":False})
    measurements,old_slots,features,baseline=R56.saved_measurements(source,audit)
    prepared,quantity_counts=prepare_features(old_slots,features,source,audit)
    variants={"U0":prepared}
    measured={policy:{key:{**row,"features":variants[policy][row["slot_id"]]["vectors"][str(row["side"])]} for key,row in measurements.items()} for policy in ("U0",)}
    teacher_blocks={e["session"]:{"slots":[slot for slot in old_slots.values() if slot["session"]==e["session"]]} for e in entries}
    preflight=source.read(ROOT/"work/状態と判断/教師接続確認.json")
    audit.check("fit前全特徴指紋",fingerprint(prepared),preflight["全特徴SHA256"])
    for key,value in (("価格経路分布",path_coverage(entries,teacher_blocks,prepared)),("局面分布",regime_coverage(entries,teacher_blocks,prepared)),("数量分布",quantity_coverage(entries,teacher_blocks,prepared))):
        audit.check("fit前"+key,value,preflight[key])
        audit.check("結果"+key,value,result[key])
    old_blocks,saved_features,old_matches={}, {},0
    for block in source.json_rows(OLDWORK/"定時判断と運用.jsonl.gz"):
        key=block["session"],block["policy"]
        if block["policy"] not in CONTROLS:
            continue
        if key in old_blocks:
            raise ValueError("旧64Q場候補の重複")
        old_blocks[key]=block
        for slot in block["slots"]:
            identity,feature=slot["slot_id"],slot["feature"]["base"]
            audit.check("旧64Q保存60全辞書",prepared[identity],slot["feature"])
            old_matches+=1
            audit.check("55検証済み18必要項目",{key:feature[key] for key in features[identity]},features[identity])
            if identity in saved_features:
                audit.check("旧二候補特徴全同値",feature,saved_features[identity])
            saved_features[identity]=feature
    audit.check("旧92集合",set(old_blocks),{(session,policy) for session in evaluated for policy in CONTROLS})
    detail=defaultdict(list)
    for block in source.json_rows(WORK/"定時判断と運用.jsonl.gz"):
        detail[block["session"]].append(block)
    audit.check("新詳細46場",set(detail),set(evaluated))
    labels={policy:[] for policy in (*CONTROLS,*POLICIES)}
    for row in source.json_rows(OLDWORK/"入口先着.jsonl.gz"):
        if row["policy"] in CONTROLS:
            labels[row["policy"]].append(row)
    sequence=list(source.json_rows(WORK/"入口先着.jsonl.gz"))
    labels_by_session=defaultdict(list)
    for row in sequence:
        labels_by_session[row["session"]].append(row)
    resources=source.read(STUDY/"一覧.resources.json")["resources"]
    resource_map={(row["session"],row["method_id"]):row for row in resources}
    audit.check("184資源全集合",set(resource_map),{(session,policy) for session in evaluated for policy in (*CONTROLS,*POLICIES)})
    audit.check("184資源一意",(len(resources),len({row["id"] for row in resources})),(184,184))
    for row in source.read(OLD/"一覧.resources.json")["resources"]:
        if row["method_id"] in CONTROLS:
            audit.check("旧92資源全属性",resource_map[row["session"],row["method_id"]],row)
            audit.check("旧Viewer固定包含",row["pnl_path"] in fixed["ファイルSHA256"],True)
    model_pins,models,calibrations,teacher_matches,set_matches={},{},{},{},{}
    for meta in previous["モデル"]+previous["対照モデル"]+previous["回収集計"]:
        model_pins[meta["path"]]=source.sha(ROOT/meta["path"])
    manifests={(meta["phase"],meta["policy"]):meta for meta in result["モデル"]}
    cal_manifests={(meta["phase"],meta["policy"]):meta for meta in result["回収集計"]}
    audit.check("三木順",[(m["phase"],m["policy"]) for m in result["モデル"]],[(p["id"],policy) for p in phases for policy in ("U0",)])
    audit.check("三回収順",[(m["phase"],m["policy"]) for m in result["回収集計"]],[(p["id"],policy) for p in phases for policy in ("U0",)])
    fits=0
    for phase in phases:
        phase_id=phase["id"]
        old_path=OLD/"models"/("Q0_"+phase_id+".json")
        old_model=source.read(old_path)
        relative=old_path.relative_to(ROOT).as_posix()
        model_pins[relative]=source.sha(old_path)
        audit.check("旧64木成功bind",model_pins[relative],previous_proof["モデルSHA256"][relative])
        _,barrier_training,_=A.training_rows(phase["train"],teacher_blocks,features,baseline,phase["evaluation_start"],18)
        keys=("input_rows_sha256","used_rows_sha256","row_ids_sha256","period_sha256")
        teacher_matches[phase_id]={key:barrier_training[key]==old_model["training"]["barrier_fingerprints"][key] for key in keys}
        audit.check("旧教師四指紋:"+phase_id,teacher_matches[phase_id],dict.fromkeys(keys,True))
        raw60=R56.recovery_input(phase["train"],teacher_blocks,prepared,measured["U0"])
        cal_old=source.read(OLD/"models"/("回収_Q0_"+phase_id+".json"))
        old_cal_ids=[{key:row[key] for key in ("session","slot_id","side")} for leaf in cal_old["leaves"].values() for row in leaf["rows"]]
        phase_ids=None
        for policy,count in (("U0",60),):
            identity=policy+"_"+phase_id
            raw=[{**row,"features":row["features"][:count]} for row in raw60]
            used,training=recovery_training(raw,phase["evaluation_start"],count)
            for key in (*FINGERPRINT_FIELDS,"base18_fingerprints","base30_fingerprints","base38_fingerprints","base46_fingerprints","base54_fingerprints","base60_fingerprints"):
                audit.check("fit前教師:"+identity+key,training[key],preflight["期間"][phase_id][policy][key])
            ids=[{key:row[key] for key in ("session","slot_id","side")} for row in used]
            audit.check("同一旧木使用ID:"+identity,ids,old_model["training"]["row_ids"])
            audit.check("同一旧回収ID集合:"+identity,sorted(ids,key=lambda r:(r["slot_id"],r["side"])),sorted(old_cal_ids,key=lambda r:(r["slot_id"],r["side"])))
            if phase_ids is not None:
                audit.check("B/Q同一教師順:"+phase_id,ids,phase_ids)
            phase_ids=ids
            set_matches[phase_id]=ids==old_model["training"]["row_ids"]
            for key in ("base18_fingerprints","base30_fingerprints","base38_fingerprints","base46_fingerprints","base54_fingerprints"):
                audit.check("旧prefix全指紋:"+identity+key,training[key],old_model["training"][key])
            audit.check("旧60六指紋:"+identity,training["base60_fingerprints"],{key:old_model["training"][key] for key in FINGERPRINT_FIELDS})
            audit.check("同一全60canonical:"+identity,{key:training[key] for key in FINGERPRINT_FIELDS},{key:old_model["training"][key] for key in FINGERPRINT_FIELDS})
            if policy=="U0":
                distribution=state_distribution(used,prepared)
                audit.check("fit前現在D×V四群:"+phase_id,distribution,preflight["状態分布"][phase_id])
                audit.check("結果現在D×V四群:"+phase_id,distribution,result["状態分布"][phase_id])
            path=STUDY/"models"/(identity+".json")
            model=source.read(path)
            digest=source.sha(path)
            model_pins[path.relative_to(ROOT).as_posix()]=digest
            check_model(model,used,training,feature_metadata(count),identity,source.sha(Path(__file__).with_name("学習.py")),audit)
            audit.check("全葉episode:"+identity,result["経路支持"][identity],episode_support(model,used,prepared))
            audit.check("新木metadata",manifests[phase_id,policy],{"id":identity,"policy":policy,"phase":phase_id,"path":path.relative_to(ROOT).as_posix(),"SHA256":digest,
                "学習場":[e["session"] for e in phase["train"]],"評価場":[e["session"] for e in phase["evaluation"]],"特徴数":count,"評価開始":phase["evaluation_start"]})
            fits+=sum(part["fit_performed"] for part in model["training"]["partition"].values())
            cal_path=STUDY/"models"/("回収_"+identity+".json")
            calibration=expected_calibration(model,measured[policy],phase["evaluation_start"])
            calibration.update(policy=policy,phase=phase_id,base_model_path=path.relative_to(ROOT).as_posix(),base_model_sha256=digest)
            audit.check("新全葉回収",source.read(cal_path),calibration)
            cal_digest=source.sha(cal_path)
            model_pins[cal_path.relative_to(ROOT).as_posix()]=cal_digest
            audit.check("回収metadata",cal_manifests[phase_id,policy],{"id":identity,"policy":policy,"phase":phase_id,"path":cal_path.relative_to(ROOT).as_posix(),"SHA256":cal_digest})
            models[phase_id,policy],calibrations[phase_id,policy]=model,calibration
        print(phase_id+" 四群の全node/教師/回収保存照合",flush=True)
    audit.check("新fit数",result["新回帰器fit"],fits)
    audit.check("最大12fit",fits<=12,True)
    audit.check("旧教師一致表示",result["旧教師一致"],teacher_matches)
    audit.check("教師集合一致表示",result["教師集合一致"],set_matches)
    accounts,summaries,cache_pins,viewer_pins,mixed_slots,closed_matches=[],[],{},{},0,0
    for entry in entries[20:]:
        session=entry["session"]
        phase=next(p for p in phases if session in {e["session"] for e in p["evaluation"]})
        phase_id=phase["id"]
        tape,cache_path,digest,input_quality=R55.load_tape(entry,source,audit)
        cache_pins[cache_path]=digest
        audit.check("原tapeの63bind",digest,previous_proof["キャッシュSHA256"][cache_path])
        for policy in CONTROLS:
            accounts.append(P.account(old_blocks[session,policy]["operation"],source,audit))
        audit.check("新二候補順",[block["policy"] for block in detail[session]],list(POLICIES))
        choices={}
        for block in detail[session]:
            policy,operation=block["policy"],block["operation"]
            parent=policy[0]+"0"
            model,calibration=models[phase_id,parent],calibrations[phase_id,parent]
            audit.check("新運用識別",(operation["candidate_id"],operation["session"],block["phase"]),(policy,session,phase_id))
            audit.check("入力品質",block["input_quality"],input_quality)
            source.check_decisions(block,tape,audit)
            source.check_orders(operation,tape,audit)
            source.check_trail(operation,tape,audit)
            for closed in operation["closed"]:
                counterpart=measurements[closed["slot_id"],closed["side"]]["operation"]["closed"]
                audit.check("同一新規単独一完結",len(counterpart),1)
                if counterpart:
                    audit.check("同一新規完結型値",R55.strict_close_equal(closed,counterpart[0]),True)
                closed_matches+=1
            path=ROOT/resource_map[session,policy]["pnl_path"]
            audit.check("Viewer正規保存先",path.resolve(),(STUDY/"viewer"/f"{policy}_{session}.trades.jsonl").resolve())
            viewer_pins[path.relative_to(ROOT).as_posix()]=source.sha(path)
            accounts.append(source.check_cash(operation,list(source.json_rows(path)),tape,audit))
            summaries.append({"場":session,"候補":policy,"期間":source.span(session),"入力品質":input_quality,"運用品質":operation["quality"],"運用集計":operation["metrics"]})
            choices[policy]={}
            for slot in block["slots"]:
                mixed_slots+=1
                identity=slot["slot_id"]
                feature,old=variants[parent][identity],old_slots[identity]
                predicted=expected_prediction(model,calibration,feature["vectors"],policy) if feature["ready"] else None
                side,reason=(predicted["side"],predicted["reason"]) if predicted else (0,feature["reason"])
                if side and feature["background_direction"]==0:
                    side,reason=0,"上位DI同値の役割未確定WAIT"
                role="待機" if not side else "順行" if side==feature["background_direction"] else "反転"
                expected={**{key:old[key] for key in BINDING},"policy":policy,"phase":phase_id,"model_id":model["model_id"],
                    "side":side,"role":role,"ready":feature["ready"],"reason":reason,"atr":feature["atr"],"D":feature["D"],"feature":feature,"prediction":predicted}
                audit.check("新slot全内容/採否",slot,expected)
                if side:
                    labels[policy].append({**baseline[identity,side],"policy":policy,"role":role})
                choices[policy][identity]=side
        for parent,child in (("U0","U1"),):
            audit.check(child+"は同方向純subset",all(not side or choices[parent][key]==side for key,side in choices[child].items()),True)
        for row in labels_by_session[session]:
            _,force,_,_=source.calendar(session)
            expected={**{key:row[key] for key in (*BINDING,"policy","side","role")},**label_helper.first_force_expected(tape,row,force,source)}
            audit.check("先着原BBO全属性",row,expected)
        print(session+" 新二運用の保存照合",flush=True)
    audit.check("新3404定時枠",mixed_slots,3404)
    audit.check("主内全14保存照合数",result["検査"],expected_counts(previous["検査"],old_matches,closed_matches,quantity_counts))
    # preflightの完結数は0、正式の新規数と分離する。
    audit.check("fit前全14照合数",preflight["検査"],expected_counts(previous["検査"],old_matches,0,quantity_counts))
    audit.check("先着コピーと順序",sequence,[row for policy in POLICIES for row in labels[policy]])
    audit.check("全場別表示",result["場別"],summaries)
    check_periods(accounts,labels,result,source,summary,audit)
    for policy in CONTROLS:
        audit.check("旧保存対照全期間",result["候補"][policy],previous["候補"][policy])
        audit.check("旧役割対照",result["役割別入口"][policy],previous["役割別入口"][policy])
    audit.check("新詳細二系列",set(result["詳細"]),{"定時判断と運用.jsonl.gz","入口先着.jsonl.gz"})
    for name,digest in result["詳細"].items():
        audit.check("詳細SHA:"+name,source.sha(WORK/name),digest)
    api=check_api(viewer_url,resources,accounts,source,audit)
    for name,digest in {**before,**model_pins,**viewer_pins}.items():
        audit.check("実行中不変:"+name,source.sha(ROOT/name),digest)
    payload={"試行":65,"確認日時":datetime.now(source.JST).isoformat(),"全件一致":audit.bad==0,"照合項目数":audit.count,"不一致数":audit.bad,"不一致":audit.examples,
        "結果SHA256":source.sha(STUDY/"結果.json"),"本物fit再実行":False,"市場戦略再生":False,"新独立計測":False,"新主処理import":False,"55測定再監査":False,
        "再用方向行数":len(measurements),"新運用数":92,"新予定比較数":mixed_slots,"回帰木数":len(models),"回収集計数":len(calibrations),"回帰器保存fit数":fits,
        "数量出典照合":quantity_counts,"参照SHA256":before,"モデルSHA256":model_pins,"キャッシュSHA256":cache_pins,"新Viewer約定SHA256":viewer_pins,"ViewerAPI":api,
        "検証範囲":"64成功proof/完了台帳と55測定の版連鎖。固定A64の完全50枠接続・旧60/Q11独立再構成と旧Q保存全辞書、同60教師六指紋・base18/30/38/46/54/60、DIと対応episode四群の枝別58列・全node/回収/予測、新92保存運用のBBO・注文・現金・連続追尾・先着・費用・全予定活動、Viewer184。",
        "限定":"新原板・新数量/独立計測・本物fit・最良閾値探索・市場戦略再生なし。V1はb出生を含みr/k完成ではなくV0も保持。固定trend+priceによる資格自動充足と容量再配分を含む構造比較であり、単独旗・量・心理の有効性や未見利益を証明しない。"}
    destination.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    return payload


def self_test() -> dict:
    """別ファイルの人工を主処理から独立して起動する。

    引数: なし。
    返り値: dictは人工成功/差数。実教師・本物fit・市場は読まない。
    """
    artificial = load(Path(__file__).with_name("監査人工.py"), "現在状態保存監査の独立人工")
    return artificial.self_test()


def main() -> None:
    """人工又はroot正式保存監査を上書きせず起動する。

    引数: CLIの--self-test/--run、任意--viewer-url。
    返り値: None。不一致は終了1、既存正式proofは拒否する。
    """
    parser = argparse.ArgumentParser(description="65のDIと対応episode有効四群・全60特徴・新92保存運用の独立監査")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    proof = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False))
    if proof["不一致数"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
