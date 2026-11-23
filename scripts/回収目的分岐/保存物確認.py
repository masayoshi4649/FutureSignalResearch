"""56の回帰分岐・過去教師・新混合運用を保存値から独立照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00056_追尾回収を目的に技法を分岐"
WORK = ROOT / "work/回収目的分岐/00056"
OLD = ROOT / "study/00055_先着候補へ独立追尾回収を加える"
OLDWORK = ROOT / "work/独立追尾回収/00055"
OLD54 = ROOT / "study/00054_方向と局所帯を先に分岐"
COMPLETE = ROOT / "work/独立追尾回収/55完了記録.json"
POLICIES = ("G0", "G1")
CONTROLS = ("C0", "R0")
PERIODS = ("学習", "条件選択", "後続検査")
BINDING = ("slot_id", "session", "scheduled", "time", "line")


def load(path: Path, name: str):
    """固定純補助を固有名で読み、旧モジュールの大域値を変えない。

    引数: path(Path)はコード、name(str)は固有の読込名。
    返り値: ModuleTypeは固定純補助。新しい主処理は正式監査で読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load(ROOT / "scripts/独立追尾回収/保存物確認.py", "回収目的監査_固定55")
A, P = R.A, R.P
fingerprint = A.fingerprint


# ----------------------------------------
# 計測自体の再生を重ねず、既検証出典と教師としての時間境界を結ぶ。

def check_reused_proof(source, audit) -> tuple:
    """55の完了・監査・測定のSHA連鎖を確認する。

    引数: source(ModuleType)は固定読取補助、audit(Audit)は照合記録。
    返り値: tuple[dict,dict,dict]は旧結果・旧監査・完了記録。
    """
    previous, proof, done = (source.read(OLD / "結果.json"), source.read(OLD / "保存物確認.json"), source.read(COMPLETE))
    audit.check("55成功監査", (proof["全件一致"], proof["不一致数"]), (True, 0))
    audit.check("55完了単一実行", (done["試行"], done["市場実行終了"], done["本物市場実行回数"]), (55, True, 1))
    audit.check("55完了監査成功", (done["保存監査"]["全件一致"], done["保存監査"]["差"]), (True, 0))
    audit.check("55結果と監査bind", source.sha(OLD / "結果.json"), proof["結果SHA256"])
    paths = [OLD / "結果.json", OLD / "保存物確認.json", OLD / "固定.json", OLD / "一覧.resources.json",
             OLDWORK / "独立測定.jsonl.gz", OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz"]
    paths += [ROOT / m["path"] for m in previous["モデル"] + previous["対照モデル"]]
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if relative in done["成果物SHA256"]:
            audit.check("55完了指紋:" + relative, source.sha(path), done["成果物SHA256"][relative])
        elif path.is_relative_to(OLD):
            raise ValueError("55自身の成果物が完了記録にない")
        pins = {**proof["参照SHA256"], **proof["モデルSHA256"]}
        if path != OLD / "保存物確認.json":
            audit.check("55監査指紋:" + relative, source.sha(path), pins[relative])
    audit.check("独立測定の55結果bind", source.sha(OLDWORK / "独立測定.jsonl.gz"), previous["詳細"]["独立測定.jsonl.gz"])
    return previous, proof, done


def saved_measurements(source, audit) -> tuple:
    """検証済み4884方向行から過去教師と当時特徴の必要部分を読む。

    引数: source(ModuleType)は固定読取補助、audit(Audit)は重複と対称性の記録。
    返り値: tuple[dict,dict,dict,dict]は方向測定・元枠・特徴・先着。計測や特徴を再算しない。
    """
    measurements, slots, features, baseline, pairs = {}, {}, {}, {}, {}
    for row in source.json_rows(OLDWORK / "独立測定.jsonl.gz"):
        key = row["slot_id"], row["side"]
        if key in measurements or row["side"] not in (1, -1):
            raise ValueError("旧測定の方向重複又は方向不正")
        slim = {k: deepcopy(row[k]) for k in ("session", "slot_id", "scheduled", "time", "line", "side", "ready",
                 "feature_reason", "features", "background_direction", "atr", "D", "barrier", "status", "recovery_end_time")}
        slim["operation"] = {"closed": deepcopy(row["operation"]["closed"])} if row["operation"] is not None else None
        measurements[key] = slim
        pair = pairs.setdefault(row["slot_id"], {})
        pair[row["side"]] = slim
        if row["barrier"] is not None:
            baseline[key] = row["barrier"]
    audit.check("旧4884測定", len(measurements), 4884)
    for identity, pair in pairs.items():
        if set(pair) != {1, -1}:
            raise ValueError("旧測定の片側抜け")
        buy, sell = pair[1], pair[-1]
        for key in (*BINDING, "ready", "feature_reason", "background_direction", "atr", "D"):
            audit.check("旧両方向共通:" + key, buy[key], sell[key])
        slots[identity] = {k: buy[k] for k in BINDING}
        features[identity] = {"ready": buy["ready"], "reason": buy["feature_reason"],
                              "vectors": {str(side): pair[side]["features"] for side in (1, -1)},
                              "background_direction": buy["background_direction"], "atr": buy["atr"], "D": buy["D"]}
    audit.check("旧2442予定枠", len(slots), 2442)
    return measurements, slots, features, baseline


def decimal_text(value: Decimal) -> str:
    """十進値を指数と不要な末尾0なしの表現へ写す。

    引数: value(Decimal)は有限値。
    返り値: strは正本と比較する正規化表現。負の0も0とする。
    """
    raw = format(value, "f")
    return "0" if value == 0 else raw.rstrip("0").rstrip(".") if "." in raw else raw


def decimal_statistics(rows: list[dict]) -> dict:
    """方向回収の十進合計・平均・母分散を独立に計算する。

    引数: rows(list[dict])はpnl0/pnl5/pnl10文字列を持つ使用方向教師。
    返り値: dictは回収3額と精密MSE。未知を0へ置換しない。
    """
    recovery, targets = {}, []
    for fee in (0, 5, 10):
        values = [Fraction(Decimal(str(row[f"pnl{fee}"]))) for row in rows]
        total = sum(values, Fraction(0))
        # ----------------------------------------
        # 有理数和は正確に保ち、定義上の最後の除算だけを80桁にする。
        precision = max(80, len(str(abs(total.numerator))) + len(str(total.denominator)) + 4)
        with localcontext() as context:
            context.prec = precision
            context.rounding = ROUND_HALF_EVEN
            exact_total = Decimal(total.numerator) / Decimal(total.denominator)
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_EVEN
            mean = Decimal(total.numerator) / (Decimal(total.denominator) * len(values)) if values else None
        recovery[f"pnl{fee}"] = {"sum": decimal_text(exact_total), "mean": float(mean) if mean is not None else None,
                                  "mean_decimal": decimal_text(mean) if mean is not None else None}
        if fee == 5:
            targets = values
    if targets:
        mean_fraction = sum(targets, Fraction(0)) / len(targets)
        mse = sum(((value - mean_fraction) ** 2 for value in targets), Fraction(0)) / len(targets)
        second = sum((value * value for value in targets), Fraction(0)) / len(targets)
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_EVEN
            variance = Decimal(mse.numerator) / Decimal(mse.denominator)
            second_moment = Decimal(second.numerator) / Decimal(second.denominator)
    else:
        variance = second_moment = None
    return {"recovery": recovery, "recovery_positive": sum(targets, Fraction(0)) > 0 if rows else None,
            "recovery_mse_decimal": decimal_text(variance) if variance is not None else None,
            "regression_value": recovery["pnl5"]["mean"], "impurity": float(variance) if variance is not None else None,
            "second_moment": float(second_moment) if second_moment is not None else None}


def recovery_input(entries: list[dict], blocks: dict, features: dict, measurements: dict) -> list[dict]:
    """準備済み全過去枠の両方向を、保存測定から学習入力へ射影する。

    引数: entries/blocksは過去場・枠、features/measurements(dict)は検証済み保存値。
    返り値: list[dict]は障壁13項目と回収4項目。確定以外の額はNoneにする。
    """
    rows = []
    for entry in entries:
        for slot in blocks[entry["session"]]["slots"]:
            identity = slot["slot_id"]
            if not features[identity]["ready"]:
                continue
            for side in (1, -1):
                record = measurements[identity, side]
                barrier = record["barrier"]
                if barrier is None:
                    raise ValueError("準備済み測定の障壁出典なし")
                row = {k: deepcopy(barrier[k]) for k in A.TEACHER_FIELDS if k != "features"}
                row.update(features=deepcopy(record["features"]), entry_time=barrier.get("entry_time"), entry_line=barrier.get("entry_line"),
                           recovery_end_time=record["recovery_end_time"])
                certain = record["status"] == "確定完結"
                if certain and len(record["operation"]["closed"]) != 1:
                    raise ValueError("確定教師は単独一完結が必要")
                row.update({f"pnl{fee}": record["operation"]["closed"][0][f"pnl{fee}"] if certain else None for fee in (0, 5, 10)})
                rows.append(row)
    return rows


def barrier_training(rows: list[dict], evaluation_start: float) -> tuple:
    """障壁教師のpair・順序・未知除外を独立に検査する。

    引数: rows(list[dict])は全準備方向入力、evaluation_start(float)は評価開始。
    返り値: tupleはcanonical全行・使用行・旧指紋/期間。回収値をこの指紋へ混ぜない。
    """
    if not rows or not A.finite(evaluation_start):
        raise ValueError("教師なし又は評価開始不正")
    canonical, pairs = [], {}
    for original in rows:
        row = {k: deepcopy(original[k]) for k in A.TEACHER_FIELDS}
        row.update(entry_time=original.get("entry_time"), entry_line=original.get("entry_line"))
        if any(not isinstance(row[k], str) or not row[k] for k in ("slot_id", "session")) or type(row["side"]) is not int or row["side"] not in (1, -1):
            raise ValueError("教師識別子又は方向不正")
        if any(not A.finite(row[k]) for k in ("scheduled", "time", "end_time")) or any(type(row[k]) is not int or row[k] < 0 for k in ("line", "end_line")):
            raise ValueError("教師時計又は原行不正")
        if not row["scheduled"] <= row["time"] <= row["end_time"] < evaluation_start:
            raise ValueError("未来障壁教師又は逆順時計")
        if row["outcome"] not in {*A.TARGETS, "不足", "未約定"} or type(row["filled"]) is not bool:
            raise ValueError("障壁結果不正")
        A.float32(row["features"], 18)
        row["features"] = [float(value) for value in row["features"]]
        if original.get("sample_weight", .5) != .5:
            raise ValueError("重みは0.5固定")
        if row["outcome"] in A.TARGETS:
            if not row["filled"] or not A.finite(row["entry_time"]) or type(row["entry_line"]) is not int:
                raise ValueError("使用障壁の約定出典不足")
            if not (row["time"], row["line"]) <= (row["entry_time"], row["entry_line"]) <= (row["end_time"], row["end_line"]):
                raise ValueError("障壁約定又は終了key逆順")
        elif row["outcome"] == "未約定" and row["filled"]:
            raise ValueError("未約定の不整合")
        pair = pairs.setdefault((row["session"], row["slot_id"]), {})
        if row["side"] in pair:
            raise ValueError("教師重複")
        pair[row["side"]] = row
        canonical.append(row)
    excluded, eligible = [], set()
    for identity, pair in pairs.items():
        if set(pair) != {1, -1} or any(pair[1][k] != pair[-1][k] for k in BINDING):
            raise ValueError("教師片側抜け又は同時計不一致")
        if all(pair[s]["outcome"] in A.TARGETS for s in (1, -1)):
            eligible.add(identity)
        else:
            excluded.append({"session": identity[0], "slot_id": identity[1], "reason": "未約定又は不足を含むpair全体除外",
                             "outcomes": {str(s): pair[s]["outcome"] for s in (1, -1)}, "filled": {str(s): pair[s]["filled"] for s in (1, -1)}})
    used = [row for row in canonical if (row["session"], row["slot_id"]) in eligible]
    if not used:
        raise ValueError("既知障壁pairなし")
    ids = [{k: r[k] for k in ("session", "slot_id", "side")} for r in used]
    period = {"sessions": list(dict.fromkeys(r["session"] for r in used)), "first_scheduled": min(r["scheduled"] for r in used),
              "last_scheduled": max(r["scheduled"] for r in used), "max_label_end_key": list(max((r["end_time"], r["end_line"]) for r in used)),
              "max_input_label_end_key": list(max((r["end_time"], r["end_line"]) for r in canonical)), "evaluation_start": float(evaluation_start), "same_second_allowed": False}
    return canonical, used, {"used_pairs": len(eligible), "excluded_pairs": excluded, "excluded_pair_count": len(excluded),
        "input_rows_sha256": fingerprint(canonical), "used_rows_sha256": fingerprint(used), "row_ids_sha256": fingerprint(ids), "period_sha256": fingerprint(period), "period": period}


def recovery_training(rows: list[dict], evaluation_start: float) -> tuple:
    """旧障壁pairを先に検査し、両側回収の未知pairを独立に除く。

    引数: rows(list[dict])は保存教師と回収、evaluation_start(float)は評価開始。
    返り値: tuple[list[dict],dict]は使用行と新全指紋/期間。片側又は未来を隠さない。
    """
    canonical_barrier, barrier_used, old = barrier_training(rows, evaluation_start)
    eligible = {(r["session"], r["slot_id"]) for r in barrier_used}
    pairs, canonical, missing = {}, [], {}
    for original, base in zip(rows, canonical_barrier):
        row, absent = deepcopy(base), []
        for fee in (0, 5, 10):
            key, value = f"pnl{fee}", original.get(f"pnl{fee}")
            if value is None:
                row[key] = None
                absent.append(key)
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
                    raise ValueError("回収型不正")
                value = Decimal(str(value))
                if not value.is_finite() or not math.isfinite(float(value)) or value != 0 and float(value) == 0:
                    raise ValueError("回収非有限又はfloat64範囲外")
                row[key] = decimal_text(value)
        end = original.get("recovery_end_time")
        if end is None:
            absent.append("recovery_end_time")
        elif not A.finite(end) or not row["time"] <= end < evaluation_start or row["entry_time"] is not None and end < row["entry_time"]:
            raise ValueError("未来回収又は逆順時計")
        row["recovery_end_time"] = end
        identity = row["session"], row["slot_id"]
        pairs.setdefault(identity, {})[row["side"]] = row
        missing[identity, row["side"]] = absent
        canonical.append(row)
    excluded, selected, reasons = [], set(), Counter()
    old_excluded = {(r["session"], r["slot_id"]): r for r in old["excluded_pairs"]}
    for identity, pair in pairs.items():
        absent = {str(s): missing[identity, s] for s in (1, -1)}
        if identity not in eligible:
            excluded.append({**deepcopy(old_excluded[identity]), "stage": "障壁", "recovery_missing": absent})
        elif any(absent.values()):
            excluded.append({"session": identity[0], "slot_id": identity[1], "stage": "回収", "reason": "回収値又は回収終了が未知のpair全体除外",
                "recovery_missing": absent, "outcomes": {str(s): pair[s]["outcome"] for s in (1, -1)}, "filled": {str(s): pair[s]["filled"] for s in (1, -1)}})
            reasons.update(f"side{s}:{key}" for s in (1, -1) for key in absent[str(s)])
        else:
            selected.add(identity)
    used = [r for r in canonical if (r["session"], r["slot_id"]) in selected]
    if not used:
        raise ValueError("確定回収pairなし")
    ids = [{k: r[k] for k in ("session", "slot_id", "side")} for r in used]
    period = {"sessions": list(dict.fromkeys(r["session"] for r in used)), "first_scheduled": min(r["scheduled"] for r in used), "last_scheduled": max(r["scheduled"] for r in used),
        "max_label_end_key": list(max((r["end_time"], r["end_line"]) for r in used)), "max_input_label_end_key": old["period"]["max_input_label_end_key"],
        "max_recovery_end_time": max(r["recovery_end_time"] for r in used), "max_input_recovery_end_time": max(r["recovery_end_time"] for r in canonical if r["recovery_end_time"] is not None),
        "evaluation_start": float(evaluation_start), "same_second_allowed": False}
    return used, {"input_pairs": len(pairs), "used_pairs": len(selected), "excluded_pair_count": len(excluded), "excluded_pairs": excluded,
        "excluded_outcome_counts": dict(Counter("1=" + p["outcomes"]["1"] + ";-1=" + p["outcomes"]["-1"] for p in excluded)),
        "barrier_used_pairs": old["used_pairs"], "barrier_excluded_pair_count": old["excluded_pair_count"], "recovery_excluded_pair_count": sum(p["stage"] == "回収" for p in excluded),
        "recovery_missing_counts": dict(reasons), "direction_rows": len(used), "weight_per_direction": .5, "total_weight": len(used) * .5,
        "row_ids": ids, "input_rows_sha256": fingerprint(canonical), "used_rows_sha256": fingerprint(used), "row_ids_sha256": fingerprint(ids),
        "target_rows_sha256": fingerprint([{**identity, "pnl5": row["pnl5"]} for identity, row in zip(ids, used)]),
        "used_barrier_rows_sha256": fingerprint([{k: r[k] for k in (*A.TEACHER_FIELDS, "entry_time", "entry_line")} for r in used]),
        "barrier_fingerprints": {key: old[key] for key in ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256")},
        "barrier_period": old["period"], "period": period, "period_sha256": fingerprint(period), "target": "pnl5", "target_dtype": "float64",
        "feature_missing_handling": "rootが旧53と同じ18特徴readyのpairだけを入力。補完しない"}


def regressor_parameters(depth: int) -> dict:
    """分類木と共通の固定条件を回帰木引数へ独立に写す。

    引数: depth(int)は全体4又は子2。
    返り値: dictはsquared_errorの回帰引数。fitを呼ばない。
    """
    result = A.classifier_parameters(depth)
    result.pop("class_weight")
    result["criterion"] = "squared_error"
    return result


def expected_rules() -> dict:
    """採否と固定段を保った56規約を旧独立定義から作る。

    引数: なし。
    返り値: dictは学習処理をimportせずに定義した期待規約。
    """
    rules = P.expected_rules()
    fixed = rules.pop("D0固定段")
    fixed.pop("gini最適固定段ではない")
    fixed["MSE最適固定段ではない"] = True
    rules.pop("class_weight")
    rules.update({"政策深さ": {"G0": 4}, "政策特徴数": {"G0": 18}, "criterion": "squared_error", "学習目的": "pnl5",
        "子学習器": "DecisionTreeRegressor", "回帰class_weight": "引数なし", "G0固定段": fixed,
        "方向採点": "障壁250成功率のみ。回帰値で方向変更又は低い側救済をしない",
        "G1": "同一G0木を使用。回収支持と正の追加条件は後段の固定回収集計で判定",
        "回収教師": "旧障壁pair検査後、両方向pnl0/5/10と回収終了の既知を要求。欠測はpair全体除外",
        "未来回収": "非欠測のrecovery_end_timeは評価開始よりstrict前。同秒は拒否",
        "回収正": "Decimalのpnl5合計>0。epsilonなし", "Decimal平均精度": 80,
        "数値照合許容": {"mean_abs": 1e-10, "mean_rel": 1e-12, "mse_abs": 1e-8, "mse_second_moment_rel": 1e-10}})
    return rules


def numeric_match(actual: object, expected: object, kind: str, second: float | None = None) -> bool:
    """生回帰器の平均/MSEだけを明示数値許容で比較する。

    引数: actual/expected(object)は比較値、kind(str)はmean/mse、second(float|None)は二次モーメント。
    返り値: boolは比較結果。閾値・score・符号・支持・採否へ使わない。
    """
    if actual is None or expected is None:
        return actual is expected
    if not A.finite(actual) or not A.finite(expected):
        return False
    if kind == "mean":
        return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-10)
    if kind != "mse" or second is None:
        raise ValueError("比較種類又は二次モーメント不正")
    return abs(actual - expected) <= 1e-8 + 1e-10 * max(1., abs(second))


def check_model(model: dict, used: list[dict], training: dict, meta: list[dict], identity: str, learner_sha: str, audit) -> None:
    """新回帰木の全所属・4群・先着率と回収統計を独立再構成する。

    引数: model(dict)は保存木、used/trainingは独立教師、meta(list[dict])は18列、
        identity/learner_sha(str)はID/版、audit(Audit)は記録。
    返り値: None。最良閾値の探索や別fitはせず、固定段の最適性を要求しない。
    """
    audit.check(identity + ":schema", (model["schema_version"], model["model_id"], model["policy"]), (1, identity, "G0"))
    audit.check(identity + ":metadata", model["feature_meta"], meta)
    audit.check(identity + ":metadata指紋", model["feature_meta_sha256"], fingerprint(meta))
    audit.check(identity + ":学習code", model["source_sha256"], learner_sha)
    audit.check(identity + ":library", model["versions"]["scikit-learn"], "1.9.1")
    audit.check(identity + ":本体引数", model["parameters"], regressor_parameters(4))
    audit.check(identity + ":子引数", model["subtree_parameters"], regressor_parameters(2))
    audit.check(identity + ":構造", model["structure"], {"kind": "fixed_root_and_direction", "fixed_nodes": P.FIXED_NODES,
        "child_depth": 2, "child_features": 17, "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"})
    audit.check(identity + ":規約", model["rules"], expected_rules())
    shared = [ROOT / "scripts/方向局面分岐/学習.py", ROOT / "scripts/局所帯分岐/学習.py"]
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
            fixed = P.FIXED_NODES[index]
            audit.check(identity + ":固定node", (node["feature"], node["feature_id"], node["threshold"]), (fixed["index"], fixed["feature"], fixed["threshold"]))
            audit.check(identity + ":固定内部保持", node["left"] >= 0 and node["right"] >= 0, True)
        if node["left"] == node["right"] == -1:
            audit.check(identity + ":葉記号", (node["feature"], node["feature_id"], node["family"], node["threshold"]), (-2, None, None, -2.))
            continue
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < 18 or not A.finite(node["threshold"]):
            raise ValueError("分岐値不正")
        if index >= 3:
            audit.check(identity + ":子17列", feature < 17, True)
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
        leaf, path, visits = A.walk(model, row["features"])
        audit.check(identity + ":方向行path", path, nodes[leaf]["path"])
        for index in visits:
            membership[index].append(row)
    partition, offset = {}, 3
    for z in (0, 1):
        for direction in (0, 1):
            key = f"Z{z}_a{direction}"
            selected = [row for row in used if P.group_key(row["features"]) == key]
            root = nodes[z + 1]["right" if direction else "left"]
            descendants = [i for i, path in paths.items() if len(path) >= 2 and path[0]["branch"] == ("right" if z else "left") and path[1]["branch"] == ("right" if direction else "left")]
            audit.check(identity + key + ":子offset", root, offset)
            audit.check(identity + key + ":連続ID", sorted(descendants), list(range(offset, offset + len(descendants))))
            audit.check(identity + key + ":子depth2", all(len(paths[i]) - 2 <= 2 for i in descendants), True)
            audit.check(identity + key + ":所属", membership[root], selected)
            if not selected:
                audit.check(identity + key + ":空群一未知leaf", (len(descendants), nodes[root]["left"], nodes[root]["right"], nodes[root]["data_absent"]), (1, -1, -1, True))
            ids = [{k: r[k] for k in ("session", "slot_id", "side")} for r in selected]
            partition[key] = {"z": z, "a": direction, "policy": "G0", "direction_rows": len(selected), "pair_unique": len({(r["session"], r["slot_id"]) for r in selected}),
                "days": len({r["session"][:10] for r in selected}), "sessions": len({r["session"] for r in selected}), "row_ids_sha256": fingerprint(ids),
                "fit_performed": bool(selected), "root": root, "node_count": len(descendants), "fit_parameters": regressor_parameters(2)}
            offset += len(descendants)
    audit.check(identity + ":四群全方向", sum(p["direction_rows"] for p in partition.values()), len(used))
    audit.check(identity + ":全training", model["training"], {**deepcopy(training), "partition": partition})
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
        statistics = decimal_statistics(rows)
        second = statistics.pop("second_moment")
        for key in ("regression_value", "impurity"):
            value = statistics.pop(key)
            if index < 3:
                audit.check(identity + str(index) + ":固定段" + key, node[key], value)
            else:
                audit.check(identity + str(index) + ":生回帰器" + key, numeric_match(node[key], value, "mean" if key == "regression_value" else "mse", second), True)
        for key, value in {**expected, **statistics}.items():
            audit.check(identity + str(index) + ":" + key, node[key], value)
        audit.check(identity + ":data_absent型", type(node["data_absent"]) is bool, True)
        eligibility = A.eligibility(node, paths[index])
        audit.check(identity + ":支持旗", (node["leaf_support"], node["method_support"]), (eligibility["leaf_support"], eligibility["method_support"]))
        if index >= 3 and node["left"] != -1:
            audit.check(identity + ":通常子minleaf60", min(len(membership[node["left"]]), len(membership[node["right"]])) >= 60, True)
        if not rows and index >= 3:
            audit.check(identity + ":空は群root一葉", index in roots and node["left"] == node["right"] == -1, True)


def check_teacher_sets(actual: dict, expected: dict, audit) -> None:
    """旧教師・55回収共通部分との一致表示を確認する。

    引数: actual/expected(dict)は保存表示と独立ID一致、audit(Audit)は記録。
    返り値: None。mainの表示項目名を最終schemaに合わせて検査する。
    """
    audit.check("教師集合一致の全phase", set(actual), set(expected))
    for phase, flag in actual.items():
        audit.check("教師集合一致の全真:" + phase, flag, True)
        audit.check("教師集合独立全真:" + phase, all(expected[phase].values()), True)


def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """新回帰木の先着最高側へ支持と回収正額だけを追加する。

    引数: model/calibration(dict)は過去木・過去葉、vectors(dict)は当時特徴、policy(str)はG0/G1。
    返り値: dictは旧55同型の全予測。回帰平均で順位を変えず次点へ救済しない。
    """
    if policy not in POLICIES or calibration["model_id"] != model["model_id"]:
        raise ValueError("候補又は回収木の対応不正")
    prior = A.predict(model, vectors)
    side, reason, leaf = prior["side"], prior["reason"], None
    if side:
        leaf = calibration["leaves"][str(prior["leafs"][str(side)])]
        if not leaf["support"]:
            side, reason = 0, "回収支持不足WAIT"
        elif policy == "G1" and not leaf["positive"]:
            side, reason = 0, "過去回収平均非正WAIT"
    return {"side": side, "reason": reason, "prior": prior, "recovery_leaf": leaf["leaf"] if leaf else None,
            "recovery_support": leaf["support"] if leaf else None, "recovery_mean5": leaf["mean_yen"]["5"] if leaf else None}


# ----------------------------------------
# 混合運用の分母・会計とViewerを、回帰教師の独立損益から分離する。

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


def run(viewer_url: str | None = None) -> dict:
    """保存された新木と92運用だけを、再fit・再生せず監査する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは全差と版結合。旧55の計測・全特徴監査は繰り返さない。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    source, label_helper, summary = A.helpers()
    audit = source.Audit()
    files = [STUDY / n for n in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    files += [WORK / n for n in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [OLD / "結果.json", OLD / "保存物確認.json", OLD / "固定.json", OLD / "一覧.resources.json", COMPLETE,
              OLDWORK / "独立測定.jsonl.gz", OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz",
              source.MANIFEST, Path(__file__), Path(__file__).with_name("学習.py")]
    before = {p.relative_to(ROOT).as_posix(): source.sha(p) for p in files}
    fixed, result = source.read(STUDY / "固定.json"), source.read(STUDY / "結果.json")
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典:" + name, source.sha(ROOT / name), digest)
    audit.check("監査自己の固定包含", Path(__file__).relative_to(ROOT).as_posix() in fixed["ファイルSHA256"], True)
    audit.check("試行・固定bind", (result["試行"], result["固定SHA256"]), (56, source.sha(STUDY / "固定.json")))
    audit.check("候補集合", set(result["候補"]), {*CONTROLS, *POLICIES})
    audit.check("新分類器/新独立計測/新運用数", (result["新分類器fit"], result["新独立計測"], result["新運用数"]), (0, 0, 92))
    previous, previous_proof, _ = check_reused_proof(source, audit)
    entries = source.read(source.MANIFEST)["entries"]
    phases = A.phases(entries, source)
    evaluated = [e["session"] for e in entries[20:]]
    audit.check("評価46場順", result["評価場"], evaluated)
    audit.check("初期20場は学習専用", result["学習専用場"], [e["session"] for e in entries[:20]])
    audit.check("旧55回収metadata", result["対照モデル"], previous["モデル"])
    audit.check("準備比較は旧55全dict", result["準備比較"], previous["準備比較"])
    audit.check("独立測定状態の再用", result["独立測定"], previous["独立測定"])
    audit.check("旧55保存対照", result["対照参照"], {"候補": list(CONTROLS), "元試行": 55, "同じ評価46場": True, "市場再生": False})
    audit.check("独立測定参照", result["独立測定参照"], {"元試行": 55, "path": (OLDWORK / "独立測定.jsonl.gz").relative_to(ROOT).as_posix(),
                                                   "sha256": source.sha(OLDWORK / "独立測定.jsonl.gz"), "再計測": False})
    measurements, old_slots, features, baseline = saved_measurements(source, audit)
    teacher_blocks = {e["session"]: {"slots": [s for s in old_slots.values() if s["session"] == e["session"]]} for e in entries}
    old_blocks, saved_features = {}, {}
    for block in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz"):
        key = block["session"], block["policy"]
        if key in old_blocks or block["policy"] not in CONTROLS:
            raise ValueError("旧55場候補の重複又は範囲外")
        old_blocks[key] = block
        for slot in block["slots"]:
            identity, feature = slot["slot_id"], slot["feature"]
            slim = features[identity]
            audit.check("55検証済み特徴の必要項目", {k: feature[k] for k in slim}, slim)
            if identity in saved_features:
                audit.check("55二候補の特徴全dict同値", feature, saved_features[identity])
            saved_features[identity] = feature
    audit.check("旧92運用集合", set(old_blocks), {(s, p) for s in evaluated for p in CONTROLS})
    detail = defaultdict(list)
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        detail[block["session"]].append(block)
    audit.check("新詳細46場", set(detail), set(evaluated))
    labels = {p: [] for p in (*CONTROLS, *POLICIES)}
    for row in source.json_rows(OLDWORK / "入口先着.jsonl.gz"):
        labels[row["policy"]].append(row)
    sequence = list(source.json_rows(WORK / "入口先着.jsonl.gz"))
    labels_by_session = defaultdict(list)
    for row in sequence:
        labels_by_session[row["session"]].append(row)
    resources = source.read(STUDY / "一覧.resources.json")["resources"]
    resource_map = {(r["session"], r["method_id"]): r for r in resources}
    audit.check("184資源全集合", set(resource_map), {(s, p) for s in evaluated for p in (*CONTROLS, *POLICIES)})
    audit.check("184資源一意", (len(resources), len({r["id"] for r in resources})), (184, 184))
    for row in source.read(OLD / "一覧.resources.json")["resources"]:
        if row["method_id"] in CONTROLS:
            audit.check("旧92資源全属性", resource_map[row["session"], row["method_id"]], row)
            audit.check("旧Viewer固定包含", row["pnl_path"] in fixed["ファイルSHA256"], True)
    model_pins, models, calibrations, teacher_matches, set_matches = {}, {}, {}, {}, {}
    for manifest in previous["モデル"] + previous["対照モデル"]:
        model_pins[manifest["path"]] = source.sha(ROOT / manifest["path"])
    manifests, cal_manifests = ({m["phase"]: m for m in result[key]} for key in ("モデル", "回収集計"))
    audit.check("新三木順", [m["phase"] for m in result["モデル"]], [p["id"] for p in phases])
    audit.check("新三回収順", [m["phase"] for m in result["回収集計"]], [p["id"] for p in phases])
    fits = 0
    for phase in phases:
        phase_id, identity = phase["id"], "G0_" + phase["id"]
        base_path = OLD54 / "models" / ("D0_" + phase_id + ".json")
        old_model = source.read(base_path)
        relative = base_path.relative_to(ROOT).as_posix()
        model_pins[relative] = source.sha(base_path)
        audit.check("54旧木の55成功監査bind", model_pins[relative], previous_proof["モデルSHA256"][relative])
        barrier_used, barrier_training, _ = A.training_rows(phase["train"], teacher_blocks, features, baseline, phase["evaluation_start"], 18)
        keys = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256")
        teacher_matches[phase_id] = {k: barrier_training[k] == old_model["training"][k] for k in keys}
        audit.check("旧教師四指紋:" + phase_id, teacher_matches[phase_id], dict.fromkeys(keys, True))
        raw_rows = recovery_input(phase["train"], teacher_blocks, features, measurements)
        used, training = recovery_training(raw_rows, phase["evaluation_start"])
        old_cal = source.read(OLD / "models" / ("回収_" + phase_id + ".json"))
        cal_ids = [{k: r[k] for k in ("session", "slot_id", "side")} for leaf in old_cal["leaves"].values() for r in leaf["rows"]]
        ids = [{k: r[k] for k in ("session", "slot_id", "side")} for r in used]
        set_matches[phase_id] = {"旧D0使用ID": ids == old_model["training"]["row_ids"],
                                 "55回収使用ID集合": sorted(ids, key=lambda r: (r["slot_id"], r["side"])) == sorted(cal_ids, key=lambda r: (r["slot_id"], r["side"]))}
        audit.check("同一使用教師集合:" + phase_id, all(set_matches[phase_id].values()), True)
        path = STUDY / "models" / (identity + ".json")
        model = source.read(path)
        digest = source.sha(path)
        model_pins[path.relative_to(ROOT).as_posix()] = digest
        check_model(model, used, training, A.feature_metadata(), identity, source.sha(Path(__file__).with_name("学習.py")), audit)
        audit.check("新木metadata", manifests[phase_id], {"id": identity, "policy": "G0", "phase": phase_id, "path": path.relative_to(ROOT).as_posix(), "SHA256": digest,
                    "学習場": [e["session"] for e in phase["train"]], "評価場": [e["session"] for e in phase["evaluation"]], "特徴数": 18, "評価開始": phase["evaluation_start"]})
        fits += sum(part["fit_performed"] for part in model["training"]["partition"].values())
        cal_path = STUDY / "models" / ("回収_" + phase_id + ".json")
        calibration = R.expected_calibration(model, measurements, phase["evaluation_start"])
        calibration.update(phase=phase_id, base_model_path=path.relative_to(ROOT).as_posix(), base_model_sha256=digest)
        audit.check("新全葉回収集計", source.read(cal_path), calibration)
        cal_digest = source.sha(cal_path)
        model_pins[cal_path.relative_to(ROOT).as_posix()] = cal_digest
        audit.check("回収metadata", cal_manifests[phase_id], {"id": identity, "phase": phase_id, "path": cal_path.relative_to(ROOT).as_posix(), "SHA256": cal_digest})
        models[phase_id], calibrations[phase_id] = model, calibration
    audit.check("回帰器の実fit数", result["新回帰器fit"], fits)
    audit.check("旧教師一致表示", result["旧教師一致"], teacher_matches)
    check_teacher_sets(result["教師集合一致"], set_matches, audit)
    accounts, summaries, cache_pins, viewer_pins, mixed_slots, closed_matches = [], [], {}, {}, 0, 0
    for entry in entries[20:]:
        session = entry["session"]
        phase = next(p for p in phases if session in {e["session"] for e in p["evaluation"]})
        phase_id, model, calibration = phase["id"], models[phase["id"]], calibrations[phase["id"]]
        tape, cache_path, digest, input_quality = R.load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        audit.check("新運用原tapeの55監査bind", digest, previous_proof["キャッシュSHA256"][cache_path])
        for policy in CONTROLS:
            accounts.append(P.account(old_blocks[session, policy]["operation"], source, audit))
        audit.check("新二候補順", [b["policy"] for b in detail[session]], list(POLICIES))
        choices = {}
        for block in detail[session]:
            policy, operation = block["policy"], block["operation"]
            audit.check("新運用ID/場/phase", (operation["candidate_id"], operation["session"], block["phase"]), (policy, session, phase_id))
            audit.check("入力品質", block["input_quality"], input_quality)
            source.check_decisions(block, tape, audit)
            source.check_orders(operation, tape, audit)
            source.check_trail(operation, tape, audit)
            for closed in operation["closed"]:
                counterpart = measurements[closed["slot_id"], closed["side"]]["operation"]["closed"]
                audit.check("新mixed単独一完結対応", len(counterpart), 1)
                if counterpart:
                    audit.check("新mixedの同一新規完結型値", R.strict_close_equal(closed, counterpart[0]), True)
                closed_matches += 1
            path = ROOT / resource_map[session, policy]["pnl_path"]
            audit.check("新Viewer正規保存先", path.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            accounts.append(source.check_cash(operation, list(source.json_rows(path)), tape, audit))
            summaries.append({"場": session, "候補": policy, "期間": source.span(session), "入力品質": input_quality,
                              "運用品質": operation["quality"], "運用集計": operation["metrics"]})
            choices[policy] = {}
            for slot in block["slots"]:
                mixed_slots += 1
                identity = slot["slot_id"]
                feature, old = saved_features[identity], old_slots[identity]
                predicted = expected_prediction(model, calibration, feature["vectors"], policy) if feature["ready"] else None
                side, reason = (predicted["side"], predicted["reason"]) if predicted else (0, feature["reason"])
                if side and feature["background_direction"] == 0:
                    side, reason = 0, "上位DI同値の役割未確定WAIT"
                role = "待機" if not side else "順行" if side == feature["background_direction"] else "反転"
                expected = {**{k: old[k] for k in BINDING}, "policy": policy, "phase": phase_id, "model_id": model["model_id"],
                            "side": side, "role": role, "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": predicted}
                audit.check("新slot全内容/採否", slot, expected)
                if side:
                    labels[policy].append({**baseline[identity, side], "policy": policy, "role": role})
                choices[policy][identity] = side
        audit.check("純G1はG0同方向subset", all(not side or choices["G0"][key] == side for key, side in choices["G1"].items()), True)
        for row in labels_by_session[session]:
            _, force, _, _ = source.calendar(session)
            expected = {**{k: row[k] for k in (*BINDING, "policy", "side", "role")}, **label_helper.first_force_expected(tape, row, force, source)}
            audit.check("新先着の原BBO全属性", row, expected)
        print(session + " 回帰木・新二運用保存照合", flush=True)
    audit.check("新3404予定枠", mixed_slots, 3404)
    audit.check("主内保存照合数", result["検査"], {"測定特徴方向一致": 4884, "旧評価特徴完全一致": 3404, "同一新規完結一致": closed_matches})
    audit.check("先着全属性コピー/保存順", sequence, [r for p in POLICIES for r in labels[p]])
    audit.check("全場別表示", result["場別"], summaries)
    check_periods(accounts, labels, result, source, summary, audit)
    for policy in CONTROLS:
        audit.check("旧保存対照の全期間", result["候補"][policy], previous["候補"][policy])
        audit.check("旧保存役割対照", result["役割別入口"][policy], previous["役割別入口"][policy])
    audit.check("新詳細は二系列", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins, **viewer_pins}.items():
        audit.check("実行中不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 56, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0, "照合項目数": audit.count,
               "不一致数": audit.bad, "不一致": audit.examples, "結果SHA256": source.sha(STUDY / "結果.json"),
               "本物fit再実行": False, "市場戦略再生": False, "新独立計測": False, "新主処理import": False,
               "55測定再監査": False, "再用方向行数": len(measurements), "新運用数": 92, "新予定比較数": mixed_slots,
               "回帰木数": len(models), "回収集計数": len(calibrations), "回帰器保存fit数": fits,
               "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api,
               "検証範囲": "55完了/A/測定の版連鎖、保存教師のstrict過去・pair交差・四指紋、新全node所属/先着率/回収統計/MSE/支持/4群/JSON採否、新92運用のBBO・注文・現金・保存追尾・先着・費用・全予定活動。",
               "限定": "55検証済み独立計測と全特徴を再検証しない。別fit/最良閾値探索/全tick戦略再生なし。全66既使用で、葉内平均や一致から未見利益・心理因果を証明しない。"}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


# ----------------------------------------
# 人工だけで実装を検査する。正式監査は新fit/predictを呼ばない。

def artificial_rows(source) -> list[dict]:
    """20人工場の800方向へ異なる回収と特徴を紙上で付ける。

    引数: source(ModuleType)は固定暦の純補助。
    返り値: list[dict]は障壁と回収を持つ人工行。実市場・実モデルを読まない。
    """
    rows = R.artificial_rows(source)
    for index, row in enumerate(rows):
        pair = index // 2
        row["features"][1] = (pair % 8) / 7
        row["features"][4] = row["side"] * (pair % 9 - 4)
        target = (pair % 8 - 3) * 125 + row["side"] * 7.5
        row.update(pnl0=target + 100, pnl5=target, pnl10=target - 100, recovery_end_time=row["end_time"] + 10)
    return rows


def self_test() -> dict:
    """人工教師と保存木で回帰目的・採否・未知境界を検査する。

    引数: なし。実教師・本物モデル・原板を読まない。
    返り値: dictは人工成功/照合数/差。人工fitは回数を明示し、本物fitは0。
    """
    source, _, _ = A.helpers()
    audit = source.Audit()
    learner = load(Path(__file__).with_name("学習.py"), "回収目的監査_人工学習対象")
    recovery = load(ROOT / "scripts/独立追尾回収/回収集計.py", "回収目的監査_人工固定集計")
    rows = artificial_rows(source)
    evaluation = max(r["recovery_end_time"] for r in rows) + 3600
    used, training = recovery_training(rows, evaluation)
    actual_used, actual_training = learner.prepare_rows(rows, evaluation)
    audit.check("全17項目canonical教師", actual_used, used)
    audit.check("全教師pair/期間/指紋", actual_training, training)
    model = learner.fit(rows, A.feature_metadata(), "G0", "G0_人工", evaluation)
    check_model(model, used, training, A.feature_metadata(), "G0_人工", hashlib.sha256(Path(__file__).with_name("学習.py").read_bytes()).hexdigest(), audit)
    measurements = {}
    for row in used:
        measurements[row["slot_id"], row["side"]] = {"session": row["session"], "ready": True, "features": row["features"], "barrier": row,
            "status": "確定完結", "recovery_end_time": row["recovery_end_time"], "operation": {"closed": [{f"pnl{fee}": float(Decimal(row[f"pnl{fee}"])) for fee in (0, 5, 10)}]}}
    calibration = R.expected_calibration(model, measurements, evaluation)
    audit.check("全葉回収の独立再集計", recovery.aggregate(model, measurements, evaluation, learner), calibration)
    for pair in range(0, 100, 2):
        vectors = {str(side): used[pair + (0 if side == 1 else 1)]["features"] for side in (1, -1)}
        audit.check("回帰値でrankしない両方向予測", learner.predict(model, vectors), A.predict(model, vectors))
        for policy, old in (("G0", "C0"), ("G1", "R0")):
            audit.check("共通木/後段gate全予測", recovery.predict(model, calibration, vectors, learner, old), expected_prediction(model, calibration, vectors, policy))
    # ----------------------------------------
    # 空Zも固定DI内部nodeと未知葉を残し、既知側への救済をしない。
    empty_rows = deepcopy(rows)
    for row in empty_rows:
        row["features"][17] = 0
    empty_used, empty_training = recovery_training(empty_rows, evaluation)
    empty_model = learner.fit(empty_rows, A.feature_metadata(), "G0", "G0_空人工", evaluation)
    check_model(empty_model, empty_used, empty_training, A.feature_metadata(), "G0_空人工", hashlib.sha256(Path(__file__).with_name("学習.py").read_bytes()).hexdigest(), audit)
    vectors = {"1": deepcopy(rows[0]["features"]), "-1": deepcopy(rows[1]["features"])}
    vectors["1"][17], vectors["-1"][17] = 0, 1
    audit.check("片側未知は両WAIT", learner.predict(empty_model, vectors), A.predict(empty_model, vectors))
    audit.check("片側未知理由", A.predict(empty_model, vectors)["reason"], "未学習枝WAIT")
    # ----------------------------------------
    # 片側回収欠測はpair除外し、欠測と一緒に与えた未来時計も拒否する。
    unknown = deepcopy(rows)
    unknown[0]["pnl5"] = None
    expected_used, expected_training = recovery_training(unknown, evaluation)
    got_used, got_training = learner.prepare_rows(unknown, evaluation)
    audit.check("回収未知pair除外の全属性", (got_used, got_training), (expected_used, expected_training))
    audit.check("片側欠測は両側を除外", len(expected_used), len(used) - 2)
    invalids = []
    one_side = deepcopy(rows[1:])
    invalids.append(("片側抜け", one_side, evaluation))
    invalids.append(("終了等号", deepcopy(rows), max(r["recovery_end_time"] for r in rows)))
    future_unknown = deepcopy(unknown)
    future_unknown[0]["recovery_end_time"] = evaluation
    invalids.append(("未知でも未来回収拒否", future_unknown, evaluation))
    duplicate = deepcopy(rows) + [deepcopy(rows[0])]
    invalids.append(("重複拒否", duplicate, evaluation))
    wrong_clock = deepcopy(rows)
    wrong_clock[0]["time"] += 1
    invalids.append(("同時計不一致", wrong_clock, evaluation))
    for name, sample, boundary in invalids:
        for function in (recovery_training, learner.prepare_rows):
            rejected = False
            try:
                function(sample, boundary)
            except ValueError:
                rejected = True
            audit.check(name + function.__name__, rejected, True)
    for sample in ([], [{"pnl0": "0", "pnl5": "0", "pnl10": "0"}],
                   [{"pnl0": "0.1", "pnl5": "0.2", "pnl10": "0.3"}, {"pnl0": "0.2", "pnl5": "0.4", "pnl10": "0.6"}]):
        audit.check("有理数MSE/80桁平均/零未知", learner.recovery_statistics(sample), decimal_statistics(sample))
    audit.check("MSE誤差の許容超過拒否", numeric_match(100., 0., "mse", 1.), False)
    audit.check("平均誤差の許容超過拒否", numeric_match(1., 0., "mean"), False)
    audit.check("Decimal正を許容で変更しない", decimal_statistics([{"pnl0": "1e-20", "pnl5": "1e-20", "pnl10": "1e-20"}])["recovery_positive"], True)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
            "人工fitAPI回数": 2, "人工回帰器fit数": sum(p["fit_performed"] for m in (model, empty_model) for p in m["training"]["partition"].values()),
            "本物fit": 0, "市場戦略再生": False, "新主処理import": False}


def main() -> None:
    """人工とroot正式保存監査を別CLIとして実行する。

    引数: CLIの--self-test/--runと任意--viewer-url。
    返り値: None。失敗は終了1、正式proofの上書きは拒否する。
    """
    parser = argparse.ArgumentParser(description="56の回帰分岐・過去回収・新混合運用保存監査")
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
