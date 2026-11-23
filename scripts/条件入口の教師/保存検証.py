"""69の共通教師・約定限定障壁率と条件運用を保存物から独立検査する。"""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode, urljoin

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00069_条件入口に合わせて技法群の教師を作る"
WORK = ROOT / "work/条件入口の教師/00069"
OLD = ROOT / "study/00068_発動前の反対端否定で条件を取り消す"
OLDWORK = ROOT / "work/条件発動前の否定/00068"
LEDGER = ROOT / "work/条件発動前の否定/68完了記録.json"
PREFLIGHT = ROOT / "work/条件入口の教師/入力接続確認.json"
POLICIES, CONTROLS = ("I0", "I1", "C0", "C1"), ("N0", "N1")
PERIODS = ("学習", "条件選択", "後続検査")
BINDING = ("slot_id", "session", "scheduled", "time", "line")
CANONICAL_FIELDS = ("session", "slot_id", "side", "features", "filled", "outcome", "end_time", "recovery_end_time", "pnl0", "pnl5", "pnl10")
KNOWN = {"250", "125", "期限"}
NO_TRADE = {"未約定", "既超過", "設定否定", "前提否定", "未発動", "発動未約定"}


def load(path: Path, name: str):
    """固定純補助を固有名で読み、大域値を書き換えない。

    引数: path(Path)はコード、name(str)は固有名。
    返り値: ModuleTypeは読取補助。69主・教師・学習・計測・68Engineは正式期待値に呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R68 = load(HERE.parent / "条件発動前の否定/保存検証.py", "条件教師69の固定68監査")
R66 = R68.R67.R66
R65, A, P, R55, R56 = R66.R65, R68.A, R68.P, R68.R55, R66.R65.R56
fingerprint = A.fingerprint
SLOT_FIELDS = R68.SLOT_FIELDS
FIXED_NODES = deepcopy(R65.FIXED_NODES)
CHILD_COLUMNS = deepcopy(R65.CHILD_COLUMNS)
float32 = R65.float32


# ----------------------------------------
def teacher_description(slot: dict, feature: dict, side: int, barrier: dict | None, operation: dict | None, source: str) -> dict:
    """一方向の既知無取引・既知約定・未知を保存状態から独立分類する。

    引数: slot/feature(dict)は当時判断、side(int)は±1、barrier/operation(dict|None)は保存測定、source(str)は即時/条件。
    返り値: dictは分類・可知時計と11項目教師。時計は有限数値の値同値、IDと原行は型も要求する。
    """
    if source not in ("即時", "条件") or type(side) is not int or side not in (-1, 1):
        raise ValueError("教師方向又は出典が不正")
    result = {"session": slot["session"], "slot_id": slot["slot_id"], "side": side, "source": source,
        "status": "未知", "reason": "技法未準備", "known_end_time": None, "row": None}
    if not feature["ready"]:
        return result
    if not A.finite(slot.get("time")) or type(slot.get("line")) is not int or slot["line"] <= 0:
        raise ValueError("準備済み元判断の時計又は原行が不正")
    if barrier is None or operation is None:
        raise ValueError("準備済み独立方向の保存記録が欠落")
    for key in BINDING:
        if key not in barrier or key not in slot:
            continue
        actual, expected = barrier[key], slot[key]
        valid = A.finite(actual) and A.finite(expected) if key in ("time", "scheduled") else type(actual) is type(expected)
        if not valid or actual != expected:
            raise ValueError("先着の元判断結合差:" + key)
    if "side" in barrier and (type(barrier["side"]) is not int or barrier["side"] != side):
        raise ValueError("方向結合差")
    if type(barrier.get("filled")) is not bool:
        raise ValueError("約定旗がboolでない")
    final = operation["final_state"]
    reason = None
    if barrier.get("outcome") not in KNOWN | NO_TRADE or barrier.get("watch_quality", False):
        reason = "入口又は障壁の観測不足"
    elif any(final.get(key) is not None for key in ("position", "pending", "watch")):
        reason = "独立運用の未解消"
    elif not operation["quality"]["損益確定可能"]:
        reason = "独立回収の品質注意"
    if reason:
        result["reason"] = reason
        return result
    entries = [row for row in operation["orders"] if row["kind"] == "entry" and row["status"] == "filled"]
    if len(entries) > 1 or bool(entries) != barrier["filled"]:
        raise ValueError("先着と回収の約定有無に差")
    if source == "条件":
        condition = operation["conditions"].get(slot["slot_id"])
        if condition is None or condition["status"] != "終了":
            result["reason"] = "条件監視又は注文が未終了"
            return result
        if condition["condition_outcome"] != barrier["condition_outcome"]:
            raise ValueError("条件終端に差")
    if barrier["filled"]:
        if barrier["outcome"] not in KNOWN or len(operation["closed"]) != 1:
            result["reason"] = "約定後の障壁又は回収が未確定"
            return result
        if (not A.finite(barrier.get("entry_time")) or not A.finite(barrier.get("entry_price"))
                or barrier["entry_price"] <= 0 or type(barrier.get("entry_line")) is not int
                or barrier["entry_line"] <= slot["line"] or barrier["entry_time"] <= slot["time"]):
            raise ValueError("新規の時計又は価格が不正")
        if any(entries[0]["fill_" + key] != barrier["entry_" + key] for key in ("time", "line", "price")):
            raise ValueError("先着と独立新規が不一致")
        closed = operation["closed"][0]
        recovery_end = closed["exit_time"]
        money = {key: closed[key] for key in ("pnl0", "pnl5", "pnl10")}
        status, outcome = "確定約定", barrier["outcome"]
    else:
        if barrier["outcome"] not in NO_TRADE or operation["closed"] or operation["trades"]:
            raise ValueError("無取引分類へ取引が混入")
        recovery_end, money, status, outcome = barrier["end_time"], dict.fromkeys(("pnl0", "pnl5", "pnl10"), 0.0), "確定無取引", "無取引"
    end = barrier["end_time"]
    if not all(A.finite(value) for value in (end, recovery_end, *money.values())) or min(end, recovery_end) < slot["time"]:
        raise ValueError("教師終端又は回収値が不正")
    if barrier["filled"] and min(end, recovery_end) < barrier["entry_time"]:
        raise ValueError("教師終端が新規より前")
    row = {"session": slot["session"], "slot_id": slot["slot_id"], "side": side,
        "features": deepcopy(feature["vectors"][str(side)]), "filled": barrier["filled"], "outcome": outcome,
        "end_time": end, "recovery_end_time": recovery_end, **money}
    result.update(status=status, reason="必要な結果が全て確定", known_end_time=max(end, recovery_end), row=row)
    return result


def common_teachers(phase: dict, blocks: dict, prepared: dict, immediate: dict, conditional: dict) -> tuple:
    """両入口×両方向の可知性を先に確認して同順の共通pairを作る。

    引数: phase/blocks/prepared/immediate/conditional(dict)は時系列分割・当時特徴・保存測定。
    返り値: tuple[dict,dict]はI0/C0教師と独立した使用・除外・分類集計。
    """
    rows, excluded, ids = {"I0": [], "C0": []}, [], []
    counts, total = {"即時": Counter(), "条件": Counter()}, 0
    for entry in phase["train"]:
        for slot in blocks[entry["session"]]["slots"]:
            total += 1
            feature, group, reasons = prepared[slot["slot_id"]], {}, {}
            for name, table in (("即時", immediate), ("条件", conditional)):
                group[name] = []
                for side in (1, -1):
                    record = table.get((slot["slot_id"], side))
                    item = teacher_description(slot, feature, side, record["barrier"] if record else None,
                        record["operation"] if record else None, name)
                    group[name].append(item)
                    counts[name][item["status"]] += 1
                    if item["status"] == "未知":
                        reasons[name + str(side)] = item["reason"]
                    elif item["known_end_time"] >= phase["evaluation_start"]:
                        reasons[name + str(side)] = "結果が評価開始よりstrict前に確定していない"
            if reasons:
                excluded.append({"session": slot["session"], "slot_id": slot["slot_id"], "理由": reasons})
            else:
                ids.append({"session": slot["session"], "slot_id": slot["slot_id"]})
                for name, policy in (("即時", "I0"), ("条件", "C0")):
                    rows[policy].extend(item["row"] for item in group[name])
    summary = {"phase": phase["id"], "評価開始": phase["evaluation_start"], "全予定枠": total,
        "共通可知枠": len(ids), "共通方向行": len(rows["I0"]), "使用枠": ids, "除外枠数": len(excluded), "除外": excluded,
        "全測定分類": {name: dict(value) for name, value in counts.items()},
        "使用分類": {policy: dict(Counter(row["outcome"] if row["filled"] else "無取引" for row in selected)) for policy, selected in rows.items()},
        "共通ID同順序": True, "方向重み": 0.5}
    return rows, summary


def canonical_rows(rows: list[dict], evaluation_start: float) -> tuple:
    """11項目の独立canonicalと期間・target・pair指紋を組み立てる。

    引数: rows(list[dict])は共通可知pair、evaluation_start(float)はstrict未来境界。
    返り値: tuple[list,dict]は使用順のcanonicalと全training。新prepareは呼ばない。
    """
    if not A.finite(evaluation_start) or not rows:
        raise ValueError("有限の評価開始と非空教師が必要")
    canonical, pairs = [], defaultdict(set)
    for original in rows:
        row = {key: deepcopy(original[key]) for key in CANONICAL_FIELDS}
        if any(type(row[key]) is not str or not row[key] for key in ("session", "slot_id")) or type(row["side"]) is not int or row["side"] not in (-1, 1) or type(row["filled"]) is not bool:
            raise ValueError("教師ID/方向/約定旗が不正")
        float32(row["features"], 60)
        row["features"] = list(map(float, row["features"]))
        identity = row["session"], row["slot_id"]
        if row["side"] in pairs[identity]:
            raise ValueError("方向重複")
        pairs[identity].add(row["side"])
        for key in ("end_time", "recovery_end_time"):
            if not A.finite(row[key]) or not 0 <= row[key] < evaluation_start:
                raise ValueError("教師の結果確定は評価開始よりstrict前が必要")
            row[key] = float(row[key])
        for key in ("pnl0", "pnl5", "pnl10"):
            try:
                value = Decimal(str(row[key]))
                converted = float(value)
            except (ArithmeticError, ValueError, TypeError) as error:
                raise ValueError("回収値の数値表現が不正") from error
            if not value.is_finite() or isinstance(row[key], bool) or not math.isfinite(converted) or value != 0 and converted == 0:
                raise ValueError("回収値が不正")
            text = format(value, "f")
            row[key] = "0" if value == 0 else text.rstrip("0").rstrip(".") if "." in text else text
        if (row["filled"] and row["outcome"] not in KNOWN) or (not row["filled"] and (row["outcome"] != "無取引" or any(Decimal(row[key]) != 0 for key in ("pnl0", "pnl5", "pnl10")))):
            raise ValueError("無取引/未知/障壁の契約差")
        if original.get("sample_weight", 0.5) != 0.5:
            raise ValueError("方向重みは0.5")
        canonical.append(row)
    if any(sides != {-1, 1} for sides in pairs.values()):
        raise ValueError("両方向pairが必要")
    ids = [{key: row[key] for key in ("session", "slot_id", "side")} for row in canonical]
    period = {"sessions": list(dict.fromkeys(row["session"] for row in canonical)),
        "max_label_end_time": max(row["end_time"] for row in canonical), "max_recovery_end_time": max(row["recovery_end_time"] for row in canonical),
        "evaluation_start": float(evaluation_start), "same_second_allowed": False}
    training = {"evaluation_start": float(evaluation_start), "input_pairs": len(pairs), "used_pairs": len(pairs), "excluded_pair_count": 0,
        "excluded_pairs": [], "direction_rows": len(canonical), "weight_per_direction": 0.5, "total_weight": len(canonical) * 0.5,
        "filled_direction_rows": sum(row["filled"] for row in canonical), "unfilled_direction_rows": sum(not row["filled"] for row in canonical), "row_ids": ids,
        "input_rows_sha256": fingerprint(canonical), "used_rows_sha256": fingerprint(canonical), "row_ids_sha256": fingerprint(ids),
        "target_rows_sha256": fingerprint([{**identity, "pnl5": row["pnl5"]} for identity, row in zip(ids, canonical)]),
        "used_barrier_rows_sha256": fingerprint([{key: row[key] for key in CANONICAL_FIELDS if key not in ("pnl0", "pnl5", "pnl10", "recovery_end_time")} for row in canonical]),
        "period": period, "period_sha256": fingerprint(period), "canonical_fields": list(CANONICAL_FIELDS), "target": "pnl5", "target_dtype": "float64",
        "unknown_handling": "rootで共通pair除外済み、ここでは未知を拒否",
        "feature_missing_handling": "旧65全60特徴・共通可知の両方向pair。確定無取引0を回帰へ含め、先着分母から分離"}
    return canonical, training


def expected_statistics(rows: list[dict], path: list[dict]) -> dict:
    """全可知回帰と約定限定の障壁・支持を独立分母で算出する。

    引数: rows(list[dict])はnode所属、path(list[dict])は根からの方法列。
    返り値: dictは二種の回収/分母/支持/score/MSE。無取引0を失敗0へ混ぜない。
    """
    filled = [row for row in rows if row["filled"]]
    statistics, filled_statistics = R56.decimal_statistics(rows), R56.decimal_statistics(filled)
    statistics.pop("second_moment")
    score = sum(row["outcome"] == "250" for row in filled) / len(filled) if filled else None
    unique, days, sessions = len({(row["session"], row["slot_id"]) for row in filled}), len({row["session"][:10] for row in filled}), len({row["session"] for row in filled})
    node = {"direction_rows": len(rows), "weighted_rows": len(rows) / 2, "total_weight": len(rows) / 2,
        "filled_direction_rows": len(filled), "unfilled_direction_rows": len(rows) - len(filled), "barrier_total_weight": len(filled) / 2,
        "success_weight": sum(row["outcome"] == "250" for row in filled) / 2, "score": score, "fill_rate": len(filled) / len(rows) if rows else None,
        "unique_slots": unique, "days": days, "sessions": sessions, "filled_unique_slots": unique, "filled_days": days, "filled_sessions": sessions,
        "all_unique_slots": len({(row["session"], row["slot_id"]) for row in rows}), "all_days": len({row["session"][:10] for row in rows}), "all_sessions": len({row["session"] for row in rows}),
        "barrier_gini": 2 * score * (1 - score) if score is not None else None, "data_absent": not rows, "barrier_data_absent": not filled,
        "recovery_filled": filled_statistics["recovery"], **statistics}
    gate = A.eligibility({**node, "score": score if score is not None else 0.0}, path)
    return {**node, "leaf_support": gate["leaf_support"], "method_support": gate["method_support"]}


def expected_calibration(model: dict) -> dict:
    """検算済み全葉から約定支持/約定平均と無取引込み平均を分離する。

    引数: model(dict)は保存されたI0/C0木。
    返り値: dictは固定66選択器へ接続する葉別回収。新主calibrationを呼ばない。
    """
    leaves = {}
    for node in model["nodes"]:
        if node["left"] != -1:
            continue
        leaves[str(node["id"])] = {"leaf": node["id"], "support": node["leaf_support"], "positive": bool(node["recovery_positive"]),
            "direction_rows": node["filled_direction_rows"], "all_direction_rows": node["direction_rows"], "unique_slots": node["unique_slots"], "days": node["days"], "sessions": node["sessions"], "fill_rate": node["fill_rate"],
            "sum_yen": {str(cost): node["recovery_filled"]["pnl" + str(cost)]["sum"] for cost in (0, 5, 10)},
            "mean_yen": {str(cost): node["recovery_filled"]["pnl" + str(cost)]["mean"] for cost in (0, 5, 10)},
            "mean_all_yen": {str(cost): node["recovery"]["pnl" + str(cost)]["mean"] for cost in (0, 5, 10)}}
    return {"model_id": model["model_id"], "policy": model["policy"], "evaluation_start": model["training"]["evaluation_start"], "leaves": leaves,
        "meaning": "共通可知教師。支持とmean_yenは約定既知のみ、mean_all_yenは確定無取引0込み"}


def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """約定先着なしを未知葉に射影し、固定66の独立両側資格算術を使う。

    引数: model/calibration(dict)は検算済み過去木、vectors(dict)は当時60値、policy(str)はI0/I1/C0/C1。
    返り値: dictはprediction全文。局所複写のみを変え、旧globalや正本を書き換えない。
    """
    if policy not in POLICIES or model["policy"] != policy[0] + "0":
        raise ValueError("モデルと政策が不一致")
    projected = {**model, "policy": "U0", "nodes": [{**node, "data_absent": node["barrier_data_absent"], "direction_rows": node["filled_direction_rows"]} for node in model["nodes"]]}
    return R66.expected_prediction(projected, calibration, vectors, "E0" if policy.endswith("0") else "E1")



def expected_rules() -> dict:
    """69で変更した教師・分母規約だけを固定65規約へ明示接続する。

    引数: なし。
    返り値: dictは監査側の規約literal。新学習moduleは読み込まない。
    """
    rules = deepcopy(R65.expected_rules())
    rules.pop("U0固定段")
    rules.pop("U1")
    rules.update({"政策深さ": {"I0": 4, "C0": 4}, "政策特徴数": {"I0": 60, "C0": 60},
    "共通固定段": deepcopy(R65.expected_rules()["U0固定段"]),
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
    return rules


def check_model(model: dict, used: list[dict], training: dict, meta: list[dict], identity: str, learner_sha: str, audit) -> None:
    """新回帰木の全所属・現在有効4群・先着率と回収統計を独立再構成する。

    引数: model(dict)は保存木、used/trainingは独立教師、meta(list[dict])は60列、
        identity/learner_sha(str)はID/版、audit(Audit)は記録。
    返り値: None。最良閾値の探索や別fitはせず、固定段の最適性を要求しない。
    """
    audit.check(identity + ":schema", (model["schema_version"], model["model_id"], model["policy"]), (1, identity, identity.split("_")[0]))
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
    shared = [ROOT / "scripts/方向局面分岐/学習.py", ROOT / "scripts/局所帯分岐/学習.py", ROOT / "scripts/回収目的分岐/学習.py", ROOT / "scripts/波の区間分離/学習.py", ROOT / "scripts/現行経路の状態分岐/学習.py", ROOT / "scripts/方向と再開確認/学習.py", ROOT / "scripts/局面強弱の複合確認/学習.py", ROOT / "scripts/量と価格進行/学習.py", ROOT / "scripts/現在状態と量価格/学習.py"]
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
        leaf, path, visits = R65.walk({**model, "policy": "U0"}, row["features"])
        audit.check(identity + ":方向行path", path, nodes[leaf]["path"])
        for index in visits:
            membership[index].append(row)
    partition,offset={},3
    for d in (0,1):
        for valid in (0,1):
            key=f"D{d}_V{valid}"
            selected=[row for row in used if R65.group_key(row["features"])==key]
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
                "child_feature_indices":CHILD_COLUMNS[f"D{d}"],"direction_rows":len(selected),"pair_unique":len({(row["session"],row["slot_id"]) for row in selected}),
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
        statistics = expected_statistics(rows, paths[index])
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


# ----------------------------------------
def singleton_calendar(source, scheduled: float):
    """一枠測定だけに限定した暦adapterを明示的に作る。

    引数: source(ModuleType)は固定49補助、scheduled(float)は一つの予定時計。
    返り値: SimpleNamespaceは同じ場境界と分母1のcalendar。元moduleは変更しない。
    """
    proxy = SimpleNamespace(**vars(source))

    def calendar(session: str) -> tuple:
        """同じ場の始終端を保ち、単独予定だけを返す。

        引数: session(str)は場名。
        返り値: tupleはstart/force/end/[scheduled]。
        """
        start, force, end, _ = source.calendar(session)
        return start, force, end, [scheduled]

    proxy.calendar = calendar
    return proxy


def check_quality(operation: dict, tape: dict, audit) -> None:
    """条件監視と保有中の観測不足だけを損益注意へ独立接続する。

    引数: operation/tape(dict)は保存状態と正常BBO原配列、audit(Audit)は比較記録。
    返り値: None。flat後の省略品質は全日と同値要求せず、保有とwatchの品質を要求する。
    """
    positions = list(operation["closed"])
    if operation["final_state"]["position"] is not None:
        positions.append(operation["final_state"]["position"])
    quotes, gaps = tape["normal"], 0
    for position in positions:
        begin = max(1, int(quotes["line"].searchsorted(position["entry_line"], side="right")))
        stop = int(quotes["line"].searchsorted(position.get("exit_line", math.inf), side="right"))
        gaps += int(((quotes["now"][begin:stop] - quotes["now"][begin - 1:stop - 1]) > 300).sum())
    watch = sum(row["registered"] and row["watch_quality"] for row in operation["conditions"].values())
    unresolved = any(operation["final_state"][key] is not None for key in ("position", "pending"))
    reasons = set()
    if gaps:
        reasons.add("建玉又は返済pending中に正常気配間隔300秒超")
    if watch:
        reasons.add("条件監視の正常BBOかつ有限正Lastの間隔300秒超")
    if unresolved:
        reasons.add("場末の建玉又は返済pending未解消")
    audit.check("独立保有気配間隔数", operation["quality"]["保有中長気配間隔数"], gaps)
    audit.check("独立watch品質数", operation["quality"]["条件監視観測不足取消数"], watch)
    audit.check("独立損益理由", set(operation["quality"]["損益注意理由"]), reasons)
    audit.check("独立損益確定", operation["quality"]["損益確定可能"], not bool(reasons))


def check_prefix(operation: dict, slot: dict, tape: dict, source, audit) -> None:
    """切出前の時計・原行・前正常気配・flat品質を原配列から独立に組む。

    引数: operation/slot/tape(dict)は一枠測定と元入力、source/auditは固定数値補助と比較記録。
    返り値: None。原配列から一場一度の累積個数だけを構築し、未来の状態をseedへ入れない。
    """
    events, quotes, np = tape["events"], tape["normal"], source.np
    if "prefix_counts69" not in tape:
        good = events["valid"] & np.isfinite(events["bid"]) & np.isfinite(events["ask"]) & (events["bid"] > 0) & (events["bid"] < events["ask"])
        tape["prefix_counts69"] = np.concatenate(([0], np.cumsum(~good)))
        tape["prefix_gaps69"] = np.concatenate(([0], np.cumsum(np.diff(quotes["now"]) > 300)))
    index = int(np.searchsorted(events["line"], slot["line"]))
    normal_count = int(np.searchsorted(quotes["line"], slot["line"]))
    previous = index - 1
    expected = {"last_time": float(events["now"][previous]) if index else None,
        "last_line": int(events["line"][previous]) if index else None, "raw_line": int(events["line"][previous]) if index else 0,
        "last_quote_time": float(quotes["now"][normal_count - 1]) if normal_count else None,
        "非正常BBO行数": int(tape["prefix_counts69"][index]),
        "空き時間長気配間隔数": int(tape["prefix_gaps69"][normal_count - 1]) if normal_count else 0}
    measurement = operation["measurement"]
    audit.check("切出prefix全文", measurement["prefix"], expected)
    audit.check("切出prefixイベント数", measurement["prefixイベント数"], index)
    audit.check("切出全イベント数", measurement["入力イベント数"], len(events["line"]))
    audit.check("切出開始key", measurement["切出開始key"], [float(events["now"][index]), int(events["line"][index])])
    count = measurement["供給イベント数"]
    audit.check("切出供給範囲", type(count) is int and 0 < count <= len(events["line"]) - index, True)
    if count:
        final = index + count - 1
        audit.check("切出最後key", measurement["走査最終key"], [float(events["now"][final]), int(events["line"][final])])
    audit.check("単独分母/並列解釈", (measurement["予定枠分母"], measurement["独立一枠測定"], measurement["同時実行可能な全体売買ではない"], measurement["全予定枠活動の評価には使わない"]), (1, True, True, True))
    audit.check("切出元DI", measurement["background_direction"], slot["feature"]["background_direction"])
    sources = {"scripts/独立追尾回収/計測.py": "26f1c6f846cce9286a87ee1ab54094a38d83c23c4255335c65a807bb7ccd3e01",
        "scripts/条件発動前の否定/運用.py": "0c107e406dc71531f6d25cf77c245bb96ab0174f6cdff4386645a76ae89c1d9b",
        "scripts/条件発動前の否定/先着.py": "f6546699516c008e29a6d118a319167807ab6e8747e54bbf0e654990bd09b2eb"}
    audit.check("切出固定参照", measurement["固定参照SHA256"], sources)


def check_operation(block: dict, expected: dict, observed: dict, tape: dict, source, audit, singleton: bool = False) -> dict:
    """独立一枠又は実全予定の条件・注文・保護・現金を検査する。

    引数: block/expected/observed/tape(dict)は保存運用と独立先着、source/auditは固定補助、singleton(bool)は分母1adapterの指定。
    返り値: dictは独立現金accountと条件。期待値へEngineや新計測を呼ばない。
    """
    calendar = singleton_calendar(source, block["slots"][0]["scheduled"]) if singleton else source
    _, force, end, _ = calendar.calendar(block["session"])
    operation = block["operation"]
    R68.check_conditions(block, expected, observed, tape, calendar, audit)
    R68.check_orders(operation, expected, {row["slot_id"]: row for row in block["slots"]}, tape, force, end, source, audit)
    source.check_trail(operation, tape, audit)
    check_quality(operation, tape, audit)
    account = source.check_cash(operation, operation["trades"], tape, audit)
    account["conditions"] = operation["conditions"]
    return account


# ----------------------------------------
def expected_slots(block: dict, prepared: dict, model: dict, calibration: dict, policy: str, phase: str) -> list:
    """検算した過去木と当時特徴だけから全予定判断を組み立てる。

    引数: block/prepared/model/calibration(dict)は旧判断と過去保存値、policy/phase(str)は識別。
    返り値: list[dict]は全辞書の独立期待値。未知・DI同値の最終WAITを保持する。
    """
    slots = []
    for origin in block["slots"]:
        feature = prepared[origin["slot_id"]]
        prediction = expected_prediction(model, calibration, feature["vectors"], policy) if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        slots.append({**{key: origin[key] for key in BINDING}, "policy": policy, "phase": phase, "model_id": model["model_id"],
            "side": side, "role": "順行" if side and side == feature["background_direction"] else "反転" if side else "待機",
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": prediction})
    return slots


def independent_slot(slot: dict, feature: dict, side: int) -> dict:
    """全readyの一方向を、教師選別なしの純条件入力へ写す。

    引数: slot/feature(dict)は当時判断、side(int)は測定方向。
    返り値: dictは元時計と測定用役割・凍結ATR/D。DI0は仮に順行と記すだけ。
    """
    return {**{key: slot[key] for key in BINDING}, "policy": "独立69", "side": side,
        "role": "順行" if feature["background_direction"] in (0, side) else "反転", "ready": True,
        "reason": "採否と独立した全定時条件測定", "atr": feature["atr"], "D": feature["D"], "feature": feature}


def phases(entries: list[dict], source) -> list[dict]:
    """既定の20→10・30→10・40→26を場境界で独立に区切る。

    引数: entries(list[dict])は固定66場、source(ModuleType)は旧暦。
    返り値: list[dict]は教師と評価場・strict開始時計。
    """
    if len(entries) != 66:
        raise ValueError("既使用66場が必要")
    return [{"id": name, "train": entries[:start], "evaluation": entries[start:stop],
        "evaluation_start": source.calendar(entries[start]["session"])[0]} for name, start, stop in (("W20", 20, 30), ("W30", 30, 40), ("F40", 40, 66))]


def run(viewer_url: str | None = None) -> dict:
    """4092独立教師・共通pair・6木と184実運用を正式に一度検査する。

    引数: viewer_url(str|None)は任意のViewer HTTP入口。
    返り値: dictは独立監査proof。新fit・主・教師・計測・Engineは期待値へ呼ばず、既存proofを上書きしない。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("69保存物確認は作成済み。再実行・上書きしません")
    source, oracle, summary = A.helpers()
    audit = source.Audit()
    result, fixed, inputs = [source.read(STUDY / name) for name in ("結果.json", "固定.json", "入力台帳.json")]
    ledger, previous, old_proof, preflight = [source.read(path) for path in (LEDGER, OLD / "結果.json", OLD / "保存物確認.json", PREFLIGHT)]
    files = [STUDY / name for name in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    files += [WORK / name for name in ("条件独立測定.jsonl.gz", "定時判断と運用.jsonl.gz", "入口先着.jsonl.gz", "共通教師_W20.json", "共通教師_W30.json", "共通教師_F40.json")]
    files += [OLD / name for name in ("結果.json", "保存物確認.json", "固定.json", "一覧.resources.json")]
    files += [OLDWORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [LEDGER, PREFLIGHT, source.MANIFEST, R65.FRAMES, Path(__file__), HERE / "保存検証の人工検査.py", HERE / "監査仕様.md"]
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in files}
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("69固定:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    for name, digest in inputs["ファイルSHA256"].items():
        audit.check("69入力台帳:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("68完了台帳指定SHA", source.sha(LEDGER), "693bc60f329efa2ec2810fee9f77a4f77140247373459b361ceed17108ef294e")
    audit.check("68成功証明", (old_proof["全件一致"], old_proof["不一致数"], old_proof["結果SHA256"]), (True, 0, source.sha(OLD / "結果.json")))
    for name, digest in ledger["成果物SHA256"].items():
        audit.check("68完了不変:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("69固定bind", (result["試行"], result["固定SHA256"], result["全66場既使用"]), (69, source.sha(STUDY / "固定.json"), True))
    audit.check("69新範囲", (result["新分類器fit"], result["新保存木数"], result["参照モデル数"], result["新運用数"]), (0, 6, 3, 184))
    audit.check("69候補集合", set(result["候補"]), {*CONTROLS, *POLICIES})
    audit.check("69学習意味", result["学習参照"], {"元構造": 65, "同じ60特徴": True, "同じ可知集合": True,
        "I教師": "旧即時49/55", "C教師": "新68条件入口の独立先着とO49回収", "無取引": "回収0・障壁対象外"})
    audit.check("69旧保存参照", result["対照参照"], {"候補": list(CONTROLS), "元試行": 68, "市場再生": False})
    # ----------------------------------------
    # 既検証65の同60列を純再用する。既存算術再構成あり、新特徴の独立算法監査ではない。
    fixed_reader = load(HERE.parent / "現在状態と量価格/検証.py", "条件教師69監査の固定65読取")
    entries, blocks, prepared, baseline, immediate, _, _ = fixed_reader.verified_saved_inputs()
    audit.check("旧65固定読取と予約台帳", entries, source.read(source.MANIFEST)["entries"])
    audit.check("全66場と予定分母", (len(entries), len(prepared)), (66, 2442))
    audit.check("全特徴指紋", fingerprint(prepared), preflight["全特徴SHA256"])
    audit.check("全予定判断指紋", fingerprint({name: block["slots"] for name, block in blocks.items()}), preflight["全予定判断SHA256"])
    metadata = R65.feature_metadata(60)
    evaluated = [entry["session"] for entry in entries[20:]]
    audit.check("同46評価場", result["評価場"], evaluated)
    audit.check("学習専用20場", result["学習専用場"], [entry["session"] for entry in entries[:20]])
    frames = defaultdict(list)
    for row in source.json_rows(R65.FRAMES):
        if row["minutes"] == 3:
            frames[row["場"]].append({"session": row["場"], **{key: row[key] for key in A.SOURCE if key != "session"}})
    conditions = {}
    checks = {"旧68完了不変": len(ledger["成果物SHA256"]), "旧68特徴保存一致": 0, "旧68採用条件一致": 0, "全ready条件線": 0, "即時教師接続": 0}
    for block in blocks.values():
        for slot in block["slots"]:
            feature = prepared[slot["slot_id"]]
            if not feature["ready"]:
                continue
            pure = independent_slot(slot, feature, 1)
            conditions[slot["slot_id"]] = R68.expected_condition(pure, frames[block["session"]])
            checks["全ready条件線"] += 1
            for side in (1, -1):
                prior = immediate[slot["slot_id"], side]
                audit.check("旧55障壁接続", prior["barrier"], baseline[slot["slot_id"], side])
                audit.check("旧55特徴接続", prior["features"], feature["vectors"][str(side)])
                checks["即時教師接続"] += 1
    audit.check("全条件指紋", fingerprint(conditions), preflight["全条件SHA256"])
    old_blocks = list(source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz"))
    for block in old_blocks:
        for slot in block["slots"]:
            audit.check("旧68当時特徴全文", slot["feature"], prepared[slot["slot_id"]])
            checks["旧68特徴保存一致"] += 1
        for identity, condition in block["conditions"].items():
            audit.check("旧68採用条件全文", condition, conditions[identity])
            checks["旧68採用条件一致"] += 1
    audit.check("入力検査全辞書", result["入力検査"], checks)
    audit.check("準備時入力検査", preflight["検査"], checks)
    audit.check("全ready方向", (len(conditions) * 2, preflight["新独立測定予定方向"]), (4092, 4092))
    # ----------------------------------------
    # 独立教師は全66場、実戦略は評価46場。原配列は各場一度だけ展開する。
    measured_by_session, actual_by_session = defaultdict(list), defaultdict(list)
    for record in source.json_rows(WORK / "条件独立測定.jsonl.gz"):
        measured_by_session[record["session"]].append(record)
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        actual_by_session[block["session"]].append(block)
    audit.check("独立教師66場", set(measured_by_session), {entry["session"] for entry in entries})
    audit.check("実運用46場", set(actual_by_session), set(evaluated))
    resources = source.read(STUDY / "一覧.resources.json")["resources"]
    resource_map = {(row["session"], row["method_id"]): row for row in resources}
    audit.check("276資源全集合", set(resource_map), {(session, policy) for session in evaluated for policy in (*CONTROLS, *POLICIES)})
    audit.check("276資源一意", (len(resources), len({row["id"] for row in resources})), (276, 276))
    for resource in source.read(OLD / "一覧.resources.json")["resources"]:
        if resource["method_id"] in CONTROLS:
            audit.check("旧N資源全文", resource_map[resource["session"], resource["method_id"]], resource)
    model_pins, models, calibrations = {}, {}, {}
    model_meta = {(meta["phase"], meta["policy"]): meta for meta in result["モデル"]}
    cal_meta = {(meta["phase"], meta["policy"]): meta for meta in result["回収集計"]}
    audit.check("新6モデル集合", set(model_meta), {(phase, policy) for phase in ("W20", "W30", "F40") for policy in ("I0", "C0")})
    audit.check("新6回収集合", set(cal_meta), set(model_meta))
    for key, meta in model_meta.items():
        models[key] = source.read(ROOT / meta["path"])
        calibrations[key] = source.read(ROOT / cal_meta[key]["path"])
        for item in (meta, cal_meta[key]):
            model_pins[item["path"]] = source.sha(ROOT / item["path"])
            audit.check("新モデルcalSHA", model_pins[item["path"]], item["SHA256"])
    # 教師検査とmodel検査を全て終えてから、保存純判断の採否を照合する。
    conditional, accounts, cache_pins, viewer_pins, summaries = {}, [], {}, {}, []
    classification = Counter()
    actual_blocks = {}
    entry_matches = closed_matches = independent_filled = 0
    for entry in entries:
        session = entry["session"]
        tape, cache_path, digest, input_quality = R55.load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        if session in evaluated:
            audit.check("旧68監査cachebind", digest, old_proof["キャッシュSHA256"][cache_path])
        slot_map = {slot["slot_id"]: slot for slot in blocks[session]["slots"]}
        expected_keys = {(identity, side) for identity, slot in slot_map.items() if prepared[identity]["ready"] for side in (1, -1)}
        records = measured_by_session[session]
        audit.check("一場全ready両側一意", (len(records), {(row["slot_id"], row["side"]) for row in records}), (len(expected_keys), expected_keys))
        _, force, end, _ = source.calendar(session)
        for record in records:
            identity, side = record["slot_id"], record["side"]
            origin, feature = slot_map[identity], prepared[identity]
            pure = independent_slot(origin, feature, side)
            expected, last = R68.expected_label(tape, pure, conditions[identity], force, end, source, oracle)
            audit.check("独立先着全属性", record["barrier"], expected)
            operation = record["operation"]
            audit.check("測定識別", (operation["session"], operation["candidate_id"]), (session, "M69_" + str(int(origin["scheduled"])) + ("買" if side == 1 else "売")))
            for field in BINDING:
                audit.check("測定元枠:" + field, record[field], origin[field])
            block = {"session": session, "slots": [pure], "conditions": {identity: conditions[identity]}, "operation": operation}
            check_operation(block, {identity: expected}, {identity: last}, tape, source, audit, True)
            check_prefix(operation, pure, tape, source, audit)
            audit.check("測定内独立先着", operation["measurement"]["独立先着"], expected)
            audit.check("測定内新規一致旗", operation["measurement"]["独立先着約定一致"], True)
            descriptor = teacher_description(origin, feature, side, expected, operation, "条件")
            audit.check("測定分類/可知時計", tuple(record[key] for key in ("status", "reason", "known_end_time")), tuple(descriptor[key] for key in ("status", "reason", "known_end_time")))
            conditional[identity, side] = {**record, "barrier": expected, "監査最終監視時計": last}
            classification[descriptor["status"]] += 1
            independent_filled += int(expected["filled"])
        if session not in evaluated:
            print(session + " 独立条件教師照合", flush=True)
            continue
        for old in (block for block in old_blocks if block["session"] == session):
            account = P.account(old["operation"], source, audit)
            account["conditions"] = old["operation"]["conditions"]
            accounts.append(account)
        audit.check("新四政策順", [block["policy"] for block in actual_by_session[session]], list(POLICIES))
        for block in actual_by_session[session]:
            policy = block["policy"]
            actual_blocks[session, policy] = block
            local_labels, observed = {}, {}
            for slot in block["slots"]:
                if slot["side"]:
                    record = conditional[slot["slot_id"], slot["side"]]
                    value = deepcopy(record["barrier"])
                    value.update(policy=policy, role=slot["role"])
                    local_labels[slot["slot_id"]] = value
                    observed[slot["slot_id"]] = record["監査最終監視時計"]
            expected_conditions = {slot["slot_id"]: conditions[slot["slot_id"]] for slot in block["slots"] if slot["side"]}
            audit.check("実採用条件線", block["conditions"], expected_conditions)
            audit.check("実入力品質", block["input_quality"], input_quality)
            operation = block["operation"]
            audit.check("実運用識別", (operation["session"], operation["candidate_id"]), (session, policy))
            account = check_operation(block, local_labels, observed, tape, source, audit)
            accounts.append(account)
            for order in operation["orders"]:
                if order["kind"] == "entry" and order["status"] == "filled":
                    independent = conditional[order["slot"]["slot_id"], order["slot"]["side"]]["barrier"]
                    audit.check("実独立新規一致", (order["fill_time"], order["fill_line"], order["fill_price"]), tuple(independent["entry_" + key] for key in ("time", "line", "price")))
                    entry_matches += 1
            for closed in operation["closed"]:
                single = conditional[closed["slot_id"], closed["side"]]["operation"]["closed"]
                audit.check("実独立完結数", len(single), 1)
                if single:
                    audit.check("実独立完結非ID全属性", R55.strict_close_equal(closed, single[0]), True)
                closed_matches += 1
            viewer = ROOT / resource_map[session, policy]["pnl_path"]
            audit.check("新Viewer正規パス", viewer.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            viewer_pins[viewer.relative_to(ROOT).as_posix()] = source.sha(viewer)
            audit.check("新Viewer全約定", list(source.json_rows(viewer)), operation["trades"])
            summaries.append({"場": session, "候補": policy, "期間": source.span(session), "入力品質": input_quality, "運用品質": operation["quality"], "運用集計": operation["metrics"]})
        print(session + " 独立教師/実四運用照合", flush=True)
    audit.check("独立方向分類", result["独立教師分類"], dict(classification))
    audit.check("独立方向総数", (result["新独立計測"], len(conditional)), (4092, 4092))
    audit.check("新場別184", result["場別"], summaries)
    expected_checks = {"独立方向数": len(conditional), "全日単独比較": 132, "先着新規一致": independent_filled,
        "同一条件実仮新規一致": entry_matches, "同一条件実独立完結一致": closed_matches}
    audit.check("主全5検査", result["検査"], expected_checks)
    # ----------------------------------------
    # 保存教師と全nodeの独立所属・回収・filled分母を確認し、保存採否を別walkする。
    fit_count = 0
    for phase in phases(entries, source):
        rows, common = common_teachers(phase, blocks, prepared, immediate, conditional)
        audit.check("共通教師正本:" + phase["id"], source.read(WORK / ("共通教師_" + phase["id"] + ".json")), common)
        audit.check("共通教師結果:" + phase["id"], result["共通教師"][phase["id"]], common)
        used_ids = []
        for policy in ("I0", "C0"):
            key, identity = (phase["id"], policy), policy + "_" + phase["id"]
            used, training = canonical_rows(rows[policy], phase["evaluation_start"])
            model, calibration = models[key], calibrations[key]
            check_model(model, used, training, metadata, identity, source.sha(HERE / "学習.py"), audit)
            audit.check("新回収全葉:" + identity, calibration, expected_calibration(model))
            meta = model_meta[key]
            audit.check("モデル場/開始/列", (meta["学習場"], meta["評価場"], meta["評価開始"], meta["特徴数"]),
                ([entry["session"] for entry in phase["train"]], [entry["session"] for entry in phase["evaluation"]], phase["evaluation_start"], 60))
            fit_count += sum(part["fit_performed"] for part in model["training"]["partition"].values())
            used_ids.append(training["row_ids"])
        audit.check("I/C使用ID同順", used_ids[0], used_ids[1])
        for entry in phase["evaluation"]:
            for policy in POLICIES:
                expected = expected_slots(blocks[entry["session"]], prepared, models[phase["id"], policy[0] + "0"], calibrations[phase["id"], policy[0] + "0"], policy, phase["id"])
                actual = actual_blocks[entry["session"], policy]
                audit.check("全純判断全辞書", actual["slots"], expected)
                audit.check("評価phase", actual["phase"], phase["id"])
    audit.check("非空群fit実数", result["新回帰器fit"], fit_count)
    labels = {policy: [] for policy in (*CONTROLS, *POLICIES)}
    slots_by_policy = {policy: [] for policy in POLICIES}
    for row in source.json_rows(OLDWORK / "入口先着.jsonl.gz"):
        labels[row["policy"]].append(row)
    for policy in POLICIES:
        for session in evaluated:
            for slot in actual_blocks[session, policy]["slots"]:
                slots_by_policy[policy].append(slot)
                if slot["side"]:
                    row = deepcopy(conditional[slot["slot_id"], slot["side"]]["barrier"])
                    row.update(policy=policy, role=slot["role"])
                    labels[policy].append(row)
    sequence = list(source.json_rows(WORK / "入口先着.jsonl.gz"))
    audit.check("新先着全文/保存順", sequence, [row for policy in POLICIES for row in labels[policy]])
    audit.check("新先着件数", result["新条件入口評価"], len(sequence))
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
                audit.check(policy + period + "条件段階", result["条件段階"][policy][period], R68.stage_summary(slots_by_policy[policy], labels[policy], selected, period, source))
                audit.check(policy + period + "判断理由", result["判断理由"][policy][period], dict(Counter(row["reason"] for row in slots_by_policy[policy] if source.span(row["session"]) == period)))
        if policy in CONTROLS:
            audit.check("旧N保存対照全期", result["候補"][policy], previous["候補"][policy])
    audit.check("新採用", result["採用"], [policy for policy in POLICIES if all(result["候補"][policy][period]["同時適格"] for period in PERIODS[:2])])
    audit.check("新詳細3系列", set(result["詳細"]), {"条件独立測定.jsonl.gz", "定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins, **cache_pins, **viewer_pins}.items():
        audit.check("監査中参照不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 69, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0,
        "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples, "結果SHA256": source.sha(STUDY / "結果.json"),
        "本物fit再実行": False, "新主処理import": False, "新教師import": False, "新学習import": False, "新計測import": False,
        "Engine期待値import": False, "市場戦略再生": False, "独立教師数": len(conditional), "新運用数": 184,
        "独立先着約定数": independent_filled, "同一条件実仮新規数": entry_matches, "同一条件実独立完結数": closed_matches,
        "全日単独比較": {"主保存照合数": 132, "監査で再実行": False, "監査の追加保証": "全4092のprefix・条件全遷移・注文・原BBO現金・保有/watch品質を独立検査"},
        "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api,
        "検証範囲": "全66場4092独立教師は一枠暦adapter、46場184実運用は全予定暦。原配列による固定68別式先着、prefixと条件/保有品質、注文/現金/保護、共通可知pair/除外/6木全node・cal・全純採否・六候補集計・Viewer276と新4代表。",
        "限定": "旧65の固定読取と既成功指紋を再用。既存算術再構成あり、新特徴の独立算法監査ではない。最良回帰分岐を再fitせず、保存所属・算術・採否を照合。独立教師損益合算を実戦略損益としない。全日132比較は主保存値へのbindであり監査で再生しない。"}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload



def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """276資源と新I0/I1/C0/C1各一代表の約定・台帳をHTTP照合する。

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
    """保存監査の独立式を架空価格と人工fitだけで検査する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致。公式proofや本物入力は生成しない。
    """
    fixture = load(HERE / "保存検証の人工検査.py", "条件教師69保存監査の人工")
    return fixture.self_test()


def main() -> None:
    """人工検査と正式保存照合の明示CLIを分離する。

    引数: CLIのrun/self_test(bool)は排他、viewer_url(str|None)はHTTP入口。
    返り値: None。正式runはroot所有で一度だけ実行する。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--self-test", action="store_true")
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
