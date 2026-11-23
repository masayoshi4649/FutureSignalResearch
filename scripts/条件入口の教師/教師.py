"""即時と条件入口の確定性を分離し、共通の可知な両方向教師を作る。"""

from collections import Counter
from copy import deepcopy
import math


KNOWN_BARRIERS = {"250", "125", "期限"}
KNOWN_NO_TRADE = {"未約定", "既超過", "設定否定", "前提否定", "未発動", "発動未約定"}


def finite(value: object) -> bool:
    """教師の時計と損益が有限の数値か確認する。

    引数: value(object)は検査対象。
    返り値: boolはbool以外の有限int/float。
    """
    return type(value) in (int, float) and math.isfinite(value)


def describe(slot: dict, feature: dict, side: int, barrier: dict | None,
             operation: dict | None, source: str) -> dict:
    """一方向を確定無取引・確定約定・未知へ分類する。

    引数: slot/feature(dict)は当時情報、side(int)は±1、barrier(dict|None)は入口先着、
        operation(dict|None)は独立運用、source(str)は即時又は条件。
    返り値: dictは分類・理由・可知時計・canonical行。未知のrowはNone。
    """
    if source not in ("即時", "条件") or type(side) is not int or side not in (-1, 1):
        raise ValueError("教師出典又は方向が不正")
    identity = {key: slot[key] for key in ("session", "slot_id")}
    result = {**identity, "side": side, "source": source, "status": "未知", "reason": "技法未準備",
        "known_end_time": None, "row": None}
    if not feature["ready"]:
        return result
    if not finite(slot.get("time")) or ("line" in slot and (type(slot["line"]) is not int or slot["line"] <= 0)):
        raise ValueError("準備済み判断の価格時計又は原行が不正")
    if barrier is None or operation is None:
        raise ValueError("準備済み独立測定の入力が欠落")
    for key in ("session", "slot_id", "scheduled", "time", "line"):
        if key in barrier and key in slot:
            if key in ("scheduled", "time"):
                matched = finite(barrier[key]) and finite(slot[key]) and barrier[key] == slot[key]
            else:
                matched = type(barrier[key]) is type(slot[key]) and barrier[key] == slot[key]
            if not matched:
                raise ValueError("先着と元判断の結合差:" + key)
    if "side" in barrier and (type(barrier["side"]) is not int or barrier["side"] != side):
        raise ValueError("先着と測定方向の結合差")
    if type(barrier.get("filled")) is not bool:
        raise ValueError("入口約定フラグが不正")
    if barrier.get("outcome") not in KNOWN_BARRIERS | KNOWN_NO_TRADE or barrier.get("watch_quality", False):
        result["reason"] = "入口又は障壁の観測不足"
        return result
    final = operation["final_state"]
    if final.get("position") is not None or final.get("pending") is not None or final.get("watch") is not None:
        result["reason"] = "独立運用の未解消"
        return result
    if not operation["quality"]["損益確定可能"]:
        result["reason"] = "独立回収の品質注意"
        return result
    entry_orders = [order for order in operation["orders"] if order["kind"] == "entry" and order["status"] == "filled"]
    if bool(entry_orders) != barrier["filled"] or len(entry_orders) > 1:
        raise ValueError("独立先着と回収の約定有無が不一致")
    if source == "条件":
        condition = operation["conditions"].get(slot["slot_id"])
        if condition is None or condition["status"] != "終了":
            result["reason"] = "条件監視又は注文が未終了"
            return result
        if condition["condition_outcome"] != barrier["condition_outcome"]:
            raise ValueError("条件の操作と独立先着が不一致")
    if barrier["filled"]:
        if barrier["outcome"] not in KNOWN_BARRIERS or len(operation["closed"]) != 1:
            result["reason"] = "約定後の障壁又は回収が未確定"
            return result
        entry = entry_orders[0]
        if (not finite(barrier.get("entry_time")) or not finite(barrier.get("entry_price"))
                or barrier["entry_price"] <= 0 or type(barrier.get("entry_line")) is not int
                or barrier["entry_line"] <= 0 or barrier["entry_time"] <= slot["time"]
                or ("line" in slot and barrier["entry_line"] <= slot["line"])):
            raise ValueError("新規価格時計又は原行が不正")
        if any(entry["fill_" + key] != barrier["entry_" + key] for key in ("time", "line", "price")):
            raise ValueError("独立先着と回収の入口価格時計が不一致")
        closed = operation["closed"][0]
        recovery_end = closed["exit_time"]
        money = {key: closed[key] for key in ("pnl0", "pnl5", "pnl10")}
        status, outcome = "確定約定", barrier["outcome"]
    else:
        if barrier["outcome"] not in KNOWN_NO_TRADE or operation["closed"] or operation["trades"]:
            raise ValueError("確定無取引に取引又は障壁結果が混入")
        recovery_end = barrier["end_time"]
        money = {key: 0.0 for key in ("pnl0", "pnl5", "pnl10")}
        status, outcome = "確定無取引", "無取引"
    end_time = barrier["end_time"]
    if not all(finite(value) for value in (*money.values(), recovery_end, end_time)):
        raise ValueError("確定教師に非有限の時計又は金額")
    if min(end_time, recovery_end) < slot["time"]:
        raise ValueError("教師の終端が実判断より前")
    if barrier["filled"] and min(end_time, recovery_end) < barrier["entry_time"]:
        raise ValueError("約定教師の終端が新規より前")
    row = {**identity, "side": side, "features": deepcopy(feature["vectors"][str(side)]),
        "filled": barrier["filled"], "outcome": outcome, "end_time": end_time,
        "recovery_end_time": recovery_end, **money}
    result.update(status=status, reason="必要な結果が全て確定", known_end_time=max(end_time, recovery_end), row=row)
    return result


def prepare_common_pairs(phase: dict, blocks: dict, prepared: dict, immediate: dict, conditional: dict) -> tuple:
    """即時・条件の両側とも評価前に可知な枠だけを共通教師にする。

    引数: phase/blocks/prepared(dict)は固定分割と全定時入力、immediate(dict)は旧55測定、
        conditional(dict)は(slot_id,side)から新しい独立運用と先着を引く辞書。
    返り値: tupleはI0/C0の同順序教師と、採用/除外の理由・分母。
    """
    rows = {"I0": [], "C0": []}
    excluded, pair_ids, statuses = [], [], {"即時": Counter(), "条件": Counter()}
    all_count = 0
    for entry in phase["train"]:
        for slot in blocks[entry["session"]]["slots"]:
            all_count += 1
            feature = prepared[slot["slot_id"]]
            group = {"即時": {}, "条件": {}}
            for side in (1, -1):
                prior = immediate[slot["slot_id"], side]
                new = conditional.get((slot["slot_id"], side))
                if feature["ready"] and new is None:
                    raise ValueError("新測定の準備済み方向が欠落")
                group["即時"][side] = describe(slot, feature, side, prior["barrier"], prior["operation"], "即時")
                group["条件"][side] = describe(slot, feature, side,
                    new["barrier"] if new else None, new["operation"] if new else None, "条件")
            reasons = {}
            for source, sides in group.items():
                for side, item in sides.items():
                    statuses[source][item["status"]] += 1
                    if item["status"] == "未知":
                        reasons[source + str(side)] = item["reason"]
                    elif item["known_end_time"] >= phase["evaluation_start"]:
                        reasons[source + str(side)] = "結果が評価開始よりstrict前に確定していない"
            if reasons:
                excluded.append({"session": slot["session"], "slot_id": slot["slot_id"], "理由": reasons})
                continue
            pair_ids.append({"session": slot["session"], "slot_id": slot["slot_id"]})
            for source, policy in (("即時", "I0"), ("条件", "C0")):
                rows[policy].extend(group[source][side]["row"] for side in (1, -1))
    identities = [[(row["session"], row["slot_id"], row["side"]) for row in rows[policy]] for policy in ("I0", "C0")]
    if identities[0] != identities[1]:
        raise ValueError("新旧教師の共通ID順が不一致")
    for old, new in zip(rows["I0"], rows["C0"]):
        if old["features"] != new["features"]:
            raise ValueError("同じ教師枠の特徴が不一致")
    summary = {"phase": phase["id"], "評価開始": phase["evaluation_start"], "全予定枠": all_count,
        "共通可知枠": len(pair_ids), "共通方向行": len(rows["I0"]), "使用枠": pair_ids,
        "除外枠数": len(excluded), "除外": excluded,
        "全測定分類": {key: dict(value) for key, value in statuses.items()},
        "使用分類": {policy: dict(Counter(row["outcome"] if row["filled"] else "無取引" for row in selected))
            for policy, selected in rows.items()}, "共通ID同順序": True, "方向重み": 0.5}
    return rows, summary
