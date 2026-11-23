"""固定D0の過去教師だけから、同じ葉の独立追尾回収を集計する。"""

from collections import defaultdict
from decimal import Decimal
import hashlib
import json


def fingerprint(value: object) -> str:
    """有限JSONの順序を保つ内容指紋を得る。

    引数: value(object)はJSON保存可能な値。
    返り値: strはSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def aggregate(model: dict, rows: dict, evaluation_start: float, learner) -> dict:
    """旧木の全過去教師へ独立回収を結合し、全葉を集計する。

    引数: model(dict)は固定D0、rows(dict)は(slot_id,side)から測定行、
        evaluation_start(float)は後続開始、learner(ModuleType)は固定54のwalk。
    返り値: dictは全葉の支持・回収・教師IDと除外理由。新fitをしない。
    """
    identities = model["training"]["row_ids"]
    pairs = defaultdict(dict)
    for identity in identities:
        key = identity["slot_id"], identity["side"]
        row = rows[key]
        if row["session"] != identity["session"] or not row["ready"]:
            raise ValueError("旧教師の同枠又は準備が不一致")
        if row["barrier"]["outcome"] not in ("250", "125", "期限"):
            raise ValueError("旧使用教師が既知障壁でない")
        if row["barrier"]["end_time"] >= evaluation_start or row["recovery_end_time"] >= evaluation_start:
            raise ValueError("回収又は障壁が評価開始の未来")
        if identity["side"] in pairs[identity["slot_id"]]:
            raise ValueError("同じ過去教師が重複")
        pairs[identity["slot_id"]][identity["side"]] = row
    if any(set(pair) != {-1, 1} for pair in pairs.values()):
        raise ValueError("過去教師は両方向pairが必要")
    excluded = [{"slot_id": key, "states": {str(s): pair[s]["status"] for s in (1, -1)}}
        for key, pair in pairs.items() if not all(pair[s]["status"] == "確定完結" for s in (1, -1))]
    excluded_ids = {row["slot_id"] for row in excluded}
    leaf_rows = {node["id"]: [] for node in model["nodes"] if node["left"] == -1}
    used = []
    for identity in identities:
        if identity["slot_id"] in excluded_ids:
            continue
        row = rows[identity["slot_id"], identity["side"]]
        leaf, _ = learner.walk(model, row["features"])
        close = row["operation"]["closed"][0]
        record = {**identity, "leaf": leaf, "recovery_end_time": row["recovery_end_time"],
            "barrier_end_time": row["barrier"]["end_time"],
            **{f"pnl{f}": close[f"pnl{f}"] for f in (0, 5, 10)}}
        leaf_rows[leaf].append(record)
        used.append(record)
    leaves = {}
    for leaf, selected in leaf_rows.items():
        unique = len({r["slot_id"] for r in selected})
        days = len({r["session"][:10] for r in selected})
        sessions = len({r["session"] for r in selected})
        sums = {str(f): sum((Decimal(str(r[f"pnl{f}"])) for r in selected), Decimal(0)) for f in (0, 5, 10)}
        leaves[str(leaf)] = {"leaf": leaf, "direction_rows": len(selected), "unique_slots": unique,
            "days": days, "sessions": sessions, "sum_yen": {f: str(v) for f, v in sums.items()},
            "mean_yen": {f: float(v / len(selected)) if selected else None for f, v in sums.items()},
            "support": unique >= 60 and days >= 6 and sessions >= 10,
            "positive": bool(selected) and sums["5"] > 0, "rows": selected,
            "max_teacher_end": max((max(r["barrier_end_time"], r["recovery_end_time"]) for r in selected), default=None)}
    return {"model_id": model["model_id"], "evaluation_start": evaluation_start,
        "old_teacher_direction_rows": len(identities), "old_teacher_ids_sha256": fingerprint(identities),
        "input_pairs": len(pairs), "used_pairs": len(pairs) - len(excluded), "excluded_pairs": excluded,
        "used_direction_rows": len(used), "weight_per_direction": 0.5, "used_rows_sha256": fingerprint(used),
        "leaves": leaves, "classifier_fit_count": 0,
        "meaning": "旧木の全過去教師と回収確定pairの共通部分による葉内記述。未来確率の校正ではない"}


# ----------------------------------------
# 過去集計と、評価時の採否を分ける。

def predict(model: dict, calibration: dict, vectors: dict, learner, policy: str) -> dict:
    """旧先着最高側に共通支持と回収正額の条件を加える。

    引数: model/calibration(dict)は過去の固定物、vectors(dict)は当時両側特徴、
        learner(ModuleType)は固定54予測、policy(str)はC0又はR0。
    返り値: dictは旧予測と追加判定。評価回収・未来値は引数に受け取らない。
    """
    if policy not in ("C0", "R0") or calibration["model_id"] != model["model_id"]:
        raise ValueError("候補又は回収集計のモデル対応が不正")
    prior = learner.predict(model, vectors)
    side, reason, leaf = prior["side"], prior["reason"], None
    if side:
        leaf = calibration["leaves"][str(prior["leafs"][str(side)])]
        if not leaf["support"]:
            side, reason = 0, "回収支持不足WAIT"
        elif policy == "R0" and not leaf["positive"]:
            side, reason = 0, "過去回収平均非正WAIT"
    return {"side": side, "reason": reason, "prior": prior, "recovery_leaf": leaf["leaf"] if leaf else None,
        "recovery_support": leaf["support"] if leaf else None,
        "recovery_mean5": leaf["mean_yen"]["5"] if leaf else None}
