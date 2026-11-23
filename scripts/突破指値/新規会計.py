"""固定Decimal会計を保持し、新規の最初指値BBOと単一受付だけを別検算する。"""

from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any
import numpy as np


def first_eligible(q: dict, requested: float, side: int, limit: float | None) -> int | None:
    """有効化から失効までを原順に走査し、最初の新規適格BBOを返す。

    引数: q(dict)は正常気配/時刻境界、requested(float)は要求、side(int)は方向、limit(float|None)は指値又は即時。
    返り値: int|Noneは適格原順位置。30秒等号可・停止/強制等号不可。
    """
    _, _, cutoff, force = q["bounds"]
    for index in range(int(np.searchsorted(q["now"], requested+1, side="left")), len(q["now"])):
        clock = float(q["now"][index])
        if clock > requested+30 or clock >= cutoff or clock >= force:
            return None
        price = float(q["ask"][index] if side == 1 else q["bid"][index])
        if limit is None or side*(price-limit) <= 0:
            return index
    return None


def acceptance(detail: dict, cases: list[dict], q: dict, audit: Any) -> None:
    """新規注文の全約定可否と、保有/pending時の信号抑止を検算する。

    引数: detail(dict)は一場詳細、cases(list[dict])は当該純登録、q(dict)は正常気配、audit(Any)は照合先。
    返り値: None。返済理由・追尾線の発動は別の独立追尾へ接続する。
    """
    cid = detail["候補ID"]
    limited = cid == "3分_E1_XF"
    source = {r["イベントID"]: r for r in cases}
    new_orders = [r for r in detail["注文"] if r["区分"] == "新規"]
    orders = {r["入口イベントID"]: r for r in new_orders}
    audit.check(cid+detail["場"]+":新規要求の入口一意", len(orders), len(new_orders))
    for order in new_orders:
        row = source[order["入口イベントID"]]
        prefix = cid+order["注文ID"]
        for field in ("要求時計秒", "要求原板行"):
            audit.check(prefix+field, order[field], row[field])
        side = row["side"]
        limit = row["新規指値価格"] if limited else None
        first = first_eligible(q, order["要求時計秒"], side, limit)
        audit.check(prefix+":約定可否", order["状態"] == "約定", first is not None)
        if limited:
            audit.check(prefix+":指値固定", order["新規指値価格"], limit)
            audit.check(prefix+":根拠固定", order["指値根拠"], row["指値根拠"])
        if first is not None:
            audit.check(prefix+":最初適格時計", order["約定時計秒"], float(q["now"][first]))
            audit.check(prefix+":最初適格行", order["約定原板行"], int(q["line"][first]))
    positions = {}
    for fill in detail["約定"]:
        key = fill["position_id"]
        if fill["type"].endswith("N"):
            positions[key] = {"開始": (fill["price_clock"], fill["source_line"]), "終了": None}
        else:
            positions[key]["終了"] = (fill["price_clock"], fill["source_line"])
    _, _, cutoff, force = q["bounds"]
    audit.check(cid+detail["場"]+":入口取扱集合", {r["イベントID"] for r in detail["入口取扱"]}, set(source))
    for signal in detail["入口取扱"]:
        event = signal["イベントID"]
        key = signal["要求時計秒"], signal["要求原板行"]
        held = any(p["開始"] <= key and (p["終了"] is None or key < p["終了"]) for p in positions.values())
        pending = any((o["要求時計秒"], o["要求原板行"]) < key
            and key[0] <= o["要求時計秒"]+30 and key[0] < min(cutoff, force)
            and (o["約定時計秒"] is None or key < (o["約定時計秒"], o["約定原板行"])) for o in new_orders)
        accepted = event in orders
        audit.check(cid+event+":単一受付", accepted, not held and not pending)
        own_order = orders.get(event)
        expected = "建玉中抑止" if held else "注文待機中抑止" if pending else (
            "受付されるべき注文なし" if own_order is None else
            "新規約定" if own_order["状態"] == "約定" else own_order["状態"])
        audit.check(cid+event+":取扱理由", signal["取扱"], expected)
    if limited:
        for trade in detail["取引"]:
            row = source[trade["入口イベントID"]]
            prefix = cid+trade["建玉ID"]
            audit.check(prefix+":取引指値", trade["新規指値価格"], row["新規指値価格"])
            audit.check(prefix+":取引根拠", trade["指値根拠"], row["指値根拠"])
            audit.check(prefix+":価格限度", row["side"]*(trade["新規価格"]-row["新規指値価格"]) <= 0, True)


# ----------------------------------------
# 下段のaudit_sessionは固定00008のDecimal全会計を複写し、最初新規BBOの条件だけ変更する。
# 原実装のSHAは独立監査の出典へ記録し、他の数量・費用・所有・品質比較は保持する。


def audit_session(detail: dict, q: dict, audit: Any) -> dict:
    """一候補・一場の約定、注文、取引、品質を照合する。

    引数: detail (dict) は作業正本、q (dict) は正常板、audit (Any) は比較先。
    返り値: dict は独立場別会計と照合済み取引。要求生成は再実装しない。
    """
    cid, session = detail["候補ID"], detail["場"]
    prefix = cid + "/" + session
    fills, info = detail["約定"], detail["品質"]
    orders = {v["注文ID"]: v for v in detail["注文"]}
    signals = {v["イベントID"]: v for v in detail["入口取扱"]}
    trades = {v["建玉ID"]: v for v in detail["取引"]}
    for name, keyed, raw in (("注文", orders, detail["注文"]), ("入口", signals, detail["入口取扱"]), ("取引", trades, detail["取引"])):
        audit.check(prefix + ":" + name + "一意", len(keyed), len(raw))
    begin, end, cutoff, force = q["bounds"]
    positions, completed, ids = {}, [], set()
    cash, fees, previous = Decimal(0), Decimal(0), None
    for fill in fills:
        name = prefix + "/" + fill["id"]
        opening = fill["type"].endswith("N")
        side = 1 if fill["type"].startswith("Long") else -1
        clock, line = float(fill["price_clock"]), int(fill["source_line"])
        index = q["at"][line]
        checks = {"手法所有": (fill["method_id"], cid), "ID一意": (fill["id"] not in ids, True),
                  "非後退": (previous is None or (clock, line) >= previous, True),
                  "場内": (begin <= clock < end, True), "原行時計": (q["now"][index], clock),
                  "ISO時計": (datetime.fromisoformat(fill["timestamp"]).timestamp(), clock),
                  "最初適格BBO": (index, first_eligible(q, fill["request_clock"], side,
                      orders[fill["order_id"]]["新規指値価格"] if cid == "3分_E1_XF" else None) if opening else
                      int(np.searchsorted(q["now"], fill["request_clock"]+1, side="left"))),
                  "BBO": (fill["price"], q["ask"][index] if (opening and side == 1) or (not opening and side == -1) else q["bid"][index]),
                  "数量": (fill["qty"], 1), "費用": (fill["fee_yen"], 11)}
        for key, values in checks.items():
            audit.check(name + ":" + key, *values)
        ids.add(fill["id"])
        previous = clock, line
        order = orders[fill["order_id"]]
        for key, actual, expected in (("注文場", order["場"], session), ("注文入口", order["入口イベントID"], fill["entry_event_id"]),
                                      ("入口存在", fill["entry_event_id"] in signals, True), ("注文状態", order["状態"], "約定")):
            audit.check(name + ":" + key, actual, expected)
        for column, field in (("要求時計秒", "request_clock"), ("要求原板行", "request_source_line"),
                              ("約定時計秒", "price_clock"), ("約定原板行", "source_line"), ("約定価格", "price")):
            audit.check(name + ":注文:" + column, order[column], fill[field])
        price, fee = Decimal(str(fill["price"])), Decimal(str(fill["fee_yen"]))
        cash -= fee
        fees += fee
        identity = fill["position_id"]
        if opening:
            audit.check(name + ":一建玉", sum(v["qty"] for v in positions.values()), 0)
            audit.check(name + ":新規期限", clock <= fill["request_clock"] + 30 and clock < cutoff, True)
            positions[identity] = {"qty": 1, "side": side, "price": price, "fill": fill}
            continue
        position = positions[identity]
        entry = position["fill"]
        audit.check(name + ":返済数量", position["qty"], 1)
        audit.check(name + ":返済方向", position["side"], side)
        audit.check(name + ":返済入口所有", fill["entry_event_id"], entry["entry_event_id"])
        gross = side * (price - position["price"]) * 10
        cash += gross
        net = gross - Decimal(str(entry["fee_yen"])) - fee
        trade = trades[identity]
        expected = {"手法": cid, "入口イベントID": fill["entry_event_id"], "枚数": 1,
                    "新規価格": position["price"], "返済価格": price, "粗損益円": gross, "手数料円": 22,
                    "基準純損益円": net, "利確価格": position["price"] + side * 250,
                    "保護価格": position["price"] - side * 125, "新規時計秒": entry["price_clock"],
                    "新規原板行": entry["source_line"], "返済時計秒": clock, "返済原板行": line}
        for key, value in expected.items():
            audit.check(name + ":取引:" + key, trade[key], value)
        for slip in (0, 5, 10):
            audit.check(name + f":追加{slip}", trade[f"追加滑り{slip}pt純損益円"], net - 20 * slip)
        entered = float(entry["price_clock"])
        waiting_gap = any(entry["request_clock"] < r <= entered for l, r in q["gaps"])
        held_gap = any(entered < r <= clock for l, r in q["gaps"])
        for key, value in (("新規待機空白", waiting_gap), ("保有経路空白", held_gap), ("観測経路注意", waiting_gap or held_gap)):
            audit.check(name + ":" + key, trade[key], value)
        completed.append({"entry": entered, "exit": clock, "net": net, "attention": waiting_gap or held_gap})
        position["qty"] = 0
    held_gaps = sum(any(float(p["fill"]["price_clock"]) < r and (p["qty"] or any(t["entry"] == p["fill"]["price_clock"] and t["exit"] >= r for t in completed)) for p in positions.values()) for l, r in q["gaps"])
    waiting_gaps = sum(float(o["要求時計秒"]) < r and (float(o["約定時計秒"]) if o["約定時計秒"] is not None else min(float(o["要求時計秒"]) + 30, cutoff, force)) > l for l, r in q["gaps"] for o in orders.values() if o["区分"] == "新規")
    unresolved = sum(p["qty"] for p in positions.values())
    tail = not len(q["now"]) or bool(q["now"][-1] < force)
    flagged = [t for t in completed if t["attention"]]
    attention = bool(unresolved or flagged or held_gaps or waiting_gaps or tail)
    states = Counter(s["取扱"] for s in signals.values())
    expected = {"候補要求数": len(signals), "新規約定数": sum(f["type"].endswith("N") for f in fills),
                "完結取引数": len(completed), "終了建玉": unresolved, "終了返済待機": sum(o["状態"] == "待機" for o in orders.values()),
                "観測現金増減円": cash, "観測完結取引純損益円": sum((t["net"] for t in completed), Decimal(0)),
                "手数料円": fees, "観測経路注意取引数": len(flagged),
                "経路注意取引純損益円": sum((t["net"] for t in flagged), Decimal(0)),
                "場内正常板空白区間数": len(q["gaps"]), "保有中空白区間数": held_gaps, "新規待機中空白区間数": waiting_gaps,
                "正常板数": len(q["now"]), "正常板最終時計秒": float(q["now"][-1]) if len(q["now"]) else None,
                "最長正常板間隔秒": q["maximum_gap"], "時計後退除外数": q["backwards"],
                "EOF期限未達": tail, "期限まで300秒超尾部": not len(q["now"]) or bool(force - q["now"][-1] > 300),
                "観測経路注意": attention, "確定対象純損益円": None if attention else cash,
                "新規取消数": sum(o["区分"] == "新規" and o["状態"] not in ("約定", "待機") for o in orders.values()),
                "建玉中抑止数": states["建玉中抑止"], "注文待機中抑止数": states["注文待機中抑止"],
                "両方向見送り数": states["同時両方向見送り"], "確認遅延不可数": states["足確定確認遅延30秒超"]}
    for key, value in expected.items():
        audit.check(prefix + ":品質:" + key, info[key], value)
    audit.check(prefix + ":取引全件", len(completed), len(trades))
    return {"候補ID": cid, "場": session, "期間": info["期間"], **expected, "約定片数": len(fills),
            "場時間分": (end - begin) / 60, "取引": detail["取引"]}
