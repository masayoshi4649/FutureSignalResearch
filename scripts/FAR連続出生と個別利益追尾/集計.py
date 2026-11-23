"""94の保存Actual台帳を独立検算し、12口座の会計と閲覧形式を保存する。"""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import gzip
import hashlib
import json
from pathlib import Path


POLICIES = ("S0", "P0", "P1")
KEYS = tuple(f"{p}_C{c}_D{d}" for p in POLICIES for c in (0, 5) for d in (0, 1))
BASELINE = {"gross_yen": 2898000, "S0_C0_D0": 2839865, "S0_C5_D0": 2084865}
FEE = Decimal("38.5")
POINT = Decimal(100)
ZERO = Decimal(0)
PHASE = {"pre_fill": 0, "after_source": 1}
SOURCE_METHODS = {"NK225_" + name: name for name in ("D164_15", "P164_06", "U165_03")}


def fail(message: str) -> None:
    """
    機能: 保存会計の不整合を正常値へ補完せず停止する。
    引数: message(str)は不一致の説明。
    返り値: None。常にValueErrorを送出する。
    """
    raise ValueError(message)


def require(condition: bool, message: str) -> None:
    """
    機能: 最適化オプションで消えない不変条件を検査する。
    引数: condition(bool)は成立条件、message(str)は不一致の説明。
    返り値: None。不成立なら例外。
    """
    if not condition:
        fail(message)


def number(value, label: str) -> Decimal:
    """
    機能: boolや非有限値を数値として受理せず十進数へ統一する。
    引数: value(any)は保存数値、label(str)は項目名。
    返り値: Decimalは有限値。
    """
    require(type(value) in (int, float, Decimal), label + "の型")
    result = Decimal(str(value))
    require(result.is_finite(), label + "の非有限値")
    return result


def integer(value, label: str, minimum: int = 0) -> int:
    """
    機能: 数量や連番の整数型と下限を検査する。
    引数: value(any)は保存値、label(str)は項目、minimum(int)は下限。
    返り値: intは検査した値。
    """
    require(type(value) is int and value >= minimum, label + "の整数/下限")
    return value


def money(value, label: str) -> Decimal:
    """
    機能: 半円単位の金額を丸めず検査する。
    引数: value(any)は金額、label(str)は項目名。
    返り値: Decimalは0.5円格子の金額。
    """
    result = number(value, label)
    require(result * 2 == (result * 2).to_integral_value(), label + "の半円精度")
    return result


def equal(actual, expected, label: str) -> None:
    """
    機能: 数値型のbool混同を避けて保存値を照合する。
    引数: actual/expected(any)は実値と規範、label(str)は項目。
    返り値: None。不一致なら例外。
    """
    require(not (isinstance(actual, bool) ^ isinstance(expected, bool)), label + "のbool混同")
    if isinstance(actual, dict) and isinstance(expected, dict):
        require(actual.keys() == expected.keys(), label + "のキー集合")
        for key in actual:
            equal(actual[key], expected[key], label + "." + str(key))
        return
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        require(len(actual) == len(expected), label + "の長さ")
        for n, (a, b) in enumerate(zip(actual, expected)):
            equal(a, b, label + f"[{n}]")
        return
    require(actual == expected, f"{label}: {actual!r} != {expected!r}")


def read_json(path: Path) -> dict:
    """
    機能: 保存JSONを十進数で読み、非標準のNaN表現を拒否する。
    引数: path(Path)はJSON。
    返り値: dictは保存値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal,
                      parse_constant=lambda value: fail("非標準JSON数値 " + value))


def serial(value):
    """
    機能: 十進数を有限なJSON数値へ変換する。
    引数: value(any)は直列化対象。
    返り値: int又はfloatは変換値。
    """
    if isinstance(value, Decimal):
        require(value.is_finite(), "非有限の出力")
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(type(value).__name__)


def write_json(path: Path, value) -> None:
    """
    機能: 既存記録を上書きせずUTF-8 JSONを保存する。
    引数: path(Path)は新規先、value(any)は保存値。
    返り値: None。
    """
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=serial, allow_nan=False)
        stream.write("\n")


def quote(value: dict, label: str, normal: bool = True) -> tuple:
    """
    機能: 元特徴Indexと物理行を別に検査し、気配の出典順を返す。
    引数: value(dict)はQuoteStamp、label(str)は名称、normal(bool)は正常必須。
    返り値: tupleはIndex/時刻/物理行。
    """
    require(set(value) == {"time", "index", "source_line", "last", "bid", "ask", "quote_ok"}, label + "の型集合")
    for name in ("time", "last", "bid", "ask"):
        number(value[name], label + "." + name)
    integer(value["index"], label + ".index")
    integer(value["source_line"], label + ".source_line")
    require(type(value["quote_ok"]) is bool, label + ".quote_ok")
    if normal:
        require(value["quote_ok"] and value["time"] > 0 and value["index"] >= 0
                and value["source_line"] > 0 and value["last"] > 0
                and value["ask"] > value["bid"] > 0, label + "の正常気配")
    return value["index"], value["time"], value["source_line"]


def point_order(value: dict) -> tuple:
    """
    機能: 少数MTM点を原行と金融phaseで順序付ける。
    引数: value(dict)はMTMPoint又はAccountPoint。
    返り値: tupleはIndex/phaseの順序。
    """
    quote(value["quote"], "MTM.quote")
    require(value["phase"] in PHASE, "MTM.phase")
    return value["quote"]["index"], PHASE[value["phase"]]


def source_identity(value: dict) -> tuple:
    """
    機能: 元Signalの出典を型どおり検査し、所有照合キーを返す。
    引数: value(dict)はSourceIdentity。
    返り値: tupleはmethod/Signal ID。
    """
    expected = {"method", "signal_id", "kind", "parent", "source_id", "quantity_micro",
                "birth_quantity", "birth_time", "birth_quote"}
    require(set(value) == expected, "SourceIdentityの集合")
    require(value["method"] in SOURCE_METHODS and value["signal_id"], "SourceIdentityのID")
    integer(value["quantity_micro"], "元micro量")
    require(integer(value["birth_quantity"], "元mini出生量", 1) <= 10, "元mini出生量の上限")
    number(value["birth_time"], "元出生時刻")
    quote(value["birth_quote"], "元出生quote", normal=False)
    return value["method"], value["signal_id"]


class Timeline:
    """保存Fillだけを前後phaseへ投影し、少数MTM点の時点配賦を検算する。"""

    def __init__(self, fills: list, slip: Decimal, orders: dict):
        """
        機能: 純現金寄与とPositionごとの所有履歴を構築する。
        引数: fills(list)は検査済み約定列、slip(Decimal)は片道1枚の仮定滑り円、orders(dict)は注文。
        返り値: None。
        """
        self.fills, self.slip, self.orders = fills, slip, orders
        self.fill_by_order = {f["order_id"]: f for f in fills}
        self.indices, self.cash = [], []
        self.histories = defaultdict(list)
        self.state = {}
        running = ZERO
        for fill in fills:
            pid = fill["position_id"]
            if fill["action"] == "new":
                self.state[pid] = {"quantity": fill["quantity"], "realized": ZERO,
                                   "entry": fill["price"], "side": fill["side"]}
            else:
                state = self.state[pid]
                state["quantity"] -= fill["quantity"]
                state["realized"] += sum((a["net_yen"] for a in fill["allocations"]), ZERO)
            state = self.state[pid]
            self.histories[pid].append((fill["quote"]["index"], dict(state)))
            running += fill["net_contribution_yen"]
            self.indices.append(fill["quote"]["index"])
            self.cash.append(running)

    def state_at(self, pid: str, point: dict):
        """
        機能: 当原行のfill前又は全fill後のPosition配賦を返す。
        引数: pid(str)は実所有ID、point(dict)はMTM点。
        返り値: dict又はNoneは当時状態。
        """
        history = self.histories[pid]
        indices = [row[0] for row in history]
        at = point["quote"]["index"]
        n = (bisect_left if point["phase"] == "pre_fill" else bisect_right)(indices, at)
        return history[n - 1][1] if n else None

    def verify_position_point(self, pid: str, value: dict) -> None:
        """
        機能: MTMの量・確定純額・単価u・全玉Wを当時Fillだけで検算する。
        引数: pid(str)は実所有ID、value(dict)は保存MTM点。
        返り値: None。最初/最大を全経路から証明する処理ではない。
        """
        expected = {"quote", "phase", "quantity", "reserved", "mark_price", "gain_points",
                    "unit_net", "realized_net", "whole_net"}
        require(set(value) == expected, "MTMPointの集合")
        point_order(value)
        state = self.state_at(pid, value)
        require(state is not None and state["quantity"] > 0, "非保有時のMTM")
        equal(integer(value["quantity"], "MTM量", 1), state["quantity"], "MTM所有量")
        require(integer(value["reserved"], "MTM予約量") <= value["quantity"], "MTM過剰予約")
        reserved = 0
        for order in self.orders.values():
            if order["kind"] != "exit" or order["position_id"] != pid:
                continue
            request_index = order["request_quote"]["index"]
            index = value["quote"]["index"]
            accepted = request_index < index or (request_index == index and value["phase"] == "after_source"
                                                and order["protection_point"] is None)
            accepted = accepted and order["request_time"] <= value["quote"]["time"]
            fill = self.fill_by_order.get(order["id"])
            already_filled = fill is not None and (fill["quote"]["index"] < index or
                              (fill["quote"]["index"] == index and value["phase"] == "after_source"))
            if accepted and not already_filled:
                reserved += order["quantity"]
        equal(value["reserved"], reserved, "MTM当時予約量（当phaseの自己保護要求前）")
        mark = value["quote"]["bid" if state["side"] == 1 else "ask"]
        gain = state["side"] * (mark - state["entry"])
        unit = gain * POINT - 2 * (FEE + self.slip)
        for name, actual in (("mark_price", mark), ("gain_points", gain), ("unit_net", unit),
                             ("realized_net", state["realized"]),
                             ("whole_net", state["realized"] + state["quantity"] * unit)):
            equal(value[name], actual, "MTM." + name)

    def verify_account_point(self, value: dict) -> None:
        """
        機能: P/U合算口座の少数評価点を純現金と残玉から別式で検算する。
        引数: value(dict)はAccountPoint。
        返り値: None。全原行の極値取り落としは別Raw監査に残す。
        """
        require(set(value) == {"quote", "phase", "equity", "cash_net", "open_buy", "open_sell"}, "AccountPointの集合")
        point_order(value)
        at = value["quote"]["index"]
        n = (bisect_left if value["phase"] == "pre_fill" else bisect_right)(self.indices, at)
        cash = self.cash[n - 1] if n else ZERO
        equity = cash
        quantities = {1: 0, -1: 0}
        for pid in self.histories:
            state = self.state_at(pid, value)
            if state is None:
                continue
            qty = state["quantity"]
            quantities[state["side"]] += qty
            mark = value["quote"]["bid" if state["side"] == 1 else "ask"]
            equity += qty * (state["side"] * (mark - state["entry"]) * POINT - FEE - self.slip)
        for name, actual in (("cash_net", cash), ("equity", equity), ("open_buy", quantities[1]), ("open_sell", quantities[-1])):
            equal(value[name], actual, "口座点." + name)


def verify_marks(position: dict, timeline: Timeline, policy: str) -> None:
    """
    機能: 少数の正益/返し/極値と保護・ATRの保存整合を検査する。
    引数: position(dict)は所有正本、timeline(Timeline)はFill規範、policy(str)はS0/P0/P1。
    返り値: None。原行全経路の独立再計算は行わない。
    """
    marks = position["marks"]
    mark_fields = {"first", "last", "first_unit_positive", "first_whole_positive",
                   "first_unit_nonpositive_after", "first_unit_negative_after", "first_whole_nonpositive_after",
                   "first_whole_negative_after", "unit_max", "unit_min", "whole_max", "whole_min"}
    require(set(marks) == mark_fields, "PositionMarksの集合")
    points = list(marks.values()) + [position[k] for k in ("activation", "floor_updated", "first_floor_hit")]
    for value in points:
        if value is not None:
            timeline.verify_position_point(position["id"], value)
    for prefix, amount in (("unit", "unit_net"), ("whole", "whole_net")):
        first = marks["first_" + prefix + "_positive"]
        if first is not None:
            require(first[amount] > 0, prefix + "の正益等号")
        for suffix, strict in (("nonpositive_after", False), ("negative_after", True)):
            value = marks["first_" + prefix + "_" + suffix]
            if value is not None:
                require(first is not None and point_order(first) < point_order(value), prefix + "の正益後時系列")
                require(value[amount] < 0 if strict else value[amount] <= 0, prefix + "の返し符号")
        maximum, minimum = marks[prefix + "_max"], marks[prefix + "_min"]
        if maximum is not None and minimum is not None:
            require(maximum[amount] >= minimum[amount], prefix + "の極値順")
            for value in marks.values():
                if value is not None:
                    require(minimum[amount] <= value[amount] <= maximum[amount], prefix + "の保存点極値範囲")
    if marks["first"] is not None:
        require(marks["last"] is not None, "firstだけのMTM")
        require(point_order(marks["first"]) <= point_order(marks["last"]), "first/last逆転")
        require(position["has_mark"] is True, "MTMあり/has_mark不一致")
        equal(position["peak_gain"], marks["unit_max"]["gain_points"], "方向幅peak")
        for value in points:
            if value is not None:
                require(point_order(marks["first"]) <= point_order(value) <= point_order(marks["last"]), "保存点の観測範囲")
    else:
        require(position["has_mark"] is False and all(v is None for v in marks.values()), "未観測のnullable")
    if policy == "S0":
        require(not position["protection_active"] and all(position[k] is None for k in
                ("activation", "floor_gain", "floor_updated", "first_floor_hit")), "S0の追加保護")
    elif position["protection_active"]:
        require(position["activation"] is not None and position["activation"]["unit_net"] > 0, "保護の起動")
        equal(position["activation"], marks["first_unit_positive"], "起動と単価正益初回")
        minimum = ZERO if policy == "P0" else ((2 * (FEE + timeline.slip) / POINT / 5).to_integral_value(rounding=ROUND_CEILING) * 5)
        require(number(position["floor_gain"], "床") >= minimum, "最低床")
    else:
        require(position["protection_active"] is False and all(position[k] is None for k in
                ("activation", "floor_gain", "floor_updated", "first_floor_hit")), "未起動床のnullable")
    atr = position["atr"]
    if atr is not None:
        require(set(atr) == {"value", "available", "nominal", "age_seconds", "width", "quote", "after_entry"}, "ATRLockの集合")
        quote(atr["quote"], "ATR.quote")
        value = number(atr["value"], "ATR")
        require(value > 0 and atr["quote"]["time"] >= atr["available"] >= atr["nominal"] > 0, "ATR公開時計")
        equal(atr["age_seconds"], atr["quote"]["time"] - atr["available"], "ATR age")
        equal(atr["width"], (2 * value / 5).to_integral_value(rounding=ROUND_CEILING) * 5, "2ATR幅")
        require(type(atr["after_entry"]) is bool, "ATR後取得型")
        equal(atr["after_entry"], atr["quote"]["index"] > position["entry_quote"]["index"], "ATR後取得の出典")


def verify_source_events(book: dict, orders: dict, timeline: Timeline) -> None:
    """
    機能: 保存Source作用の整数比率と実注文へのID結合を照合する。
    引数: book(dict)はActualResult、orders(dict)は実注文写像、timeline(Timeline)は実Fill規範。
    返り値: None。元戦略の全通知生成・原板時計は再計算しない。
    """
    allowed = {"new_signal", "new_fill", "close_fill", "cancel", "close_notice"}
    notices, births, executions, cancelled = set(), set(), set(), set()
    source_holds = {}
    accepted_orders, cancelled_actual = set(), set()
    for event in book["source_events"]:
        require(event["kind"] in allowed and event["method"] in SOURCE_METHODS, "Source event種別")
        number(event["at"], "Source event時刻")
        quote(event["quote"], "Source event quote", normal=False)
        for name in ("quantity", "before", "actual_pending_before", "actual_new_cancelled", "actual_free_before",
                     "actual_exit_requested", "actual_free_after", "actual_accepted", "available"):
            integer(event[name], "Source event." + name)
        key = event["method"], event["signal_id"]
        if event["kind"] == "new_signal":
            equal(event["phase"], "native_new", "Source new phase")
            require(key not in births, "Source出生重複")
            births.add(key)
            require(0 < event["quantity"] <= 10 and event["available"] <= 10, "Source出生量/空き上限")
            at = event["quote"]["index"]
            point = {"quote": event["quote"], "phase": "after_source"}
            owned = sum(state["quantity"] for pid in timeline.histories
                        if (state := timeline.state_at(pid, point)) is not None and state["side"] == event["side"])
            pending = 0
            for oid in accepted_orders:
                order = orders[oid]
                fill = timeline.fill_by_order.get(oid)
                if order["side"] == event["side"] and source_identity(order["source"]) not in cancelled_actual and (fill is None or fill["quote"]["index"] > at):
                    pending += order["quantity"]
            require(0 <= owned + pending <= 10, "Source出生直前の実所有＋new予約")
            equal(event["available"], 10 - owned - pending, "Source出生時の独立空き")
            equal(event["actual_accepted"], 0 if key in cancelled else min(event["quantity"], event["available"]), "Source出生量/空きのmin")
            if event["order_id"]:
                order = orders[event["order_id"]]
                equal(order["kind"], "entry", "Source new注文種別")
                equal(source_identity(order["source"]), key, "Source new注文出典")
                equal(order["quantity"], event["actual_accepted"], "Source受理量")
                equal(order["request_time"], event["at"], "Source new要求時刻")
                equal(order["request_quote"], event["quote"], "Source new要求quote")
                equal(order["source"]["birth_quantity"], event["quantity"], "Source出生量")
                accepted_orders.add(order["id"])
            else:
                equal(event["actual_accepted"], 0, "Source new注文なし受理")
        elif event["kind"] in ("new_fill", "close_fill"):
            equal(event["phase"], "native_fill", "Source fill phase")
            execution = event["method"], event["execution_id"]
            require(execution[1] and execution not in executions, "Source ExecutionID")
            executions.add(execution)
            if event["kind"] == "new_fill":
                hold = event["method"], event["hold_id"]
                require(hold[1] and hold not in source_holds, "Source実在HoldID")
                source_holds[hold] = key
        elif event["kind"] == "cancel":
            equal(event["phase"], "before_fill", "Source取消phase")
            require(key not in cancelled, "Source取消重複")
            cancelled.add(key)
            cancelled_actual.add(key)
        elif event["kind"] == "close_notice":
            equal(event["phase"], "source_close", "Source close phase")
            notice = event["method"], event["notice_id"]
            require(notice[1] and notice not in notices, "Source notice重複")
            notices.add(notice)
            before, qty, free = event["before"], event["quantity"], event["actual_free_before"]
            require(0 < qty <= before, "Source close Before/Quantity")
            expected = free if qty == before else (free * qty + before - 1) // before
            equal(event["actual_exit_requested"], expected, "Source ceil/全残例外")
            equal(event["actual_free_after"], free - expected, "Source free残量")
            equal(event["actual_new_cancelled"], event["actual_pending_before"], "Source未取得new全取消")
            if event["actual_new_cancelled"]:
                cancelled_actual.add(source_holds[(event["method"], event["hold_id"])])
            if event["order_id"]:
                order = orders[event["order_id"]]
                equal(order["kind"], "exit", "Source close注文種別")
                for field, value in (("quantity", expected), ("source_hold_id", event["hold_id"]),
                                     ("native_close_signal_id", event["signal_id"]), ("native_close_notice_id", event["notice_id"]),
                                     ("request_time", event["at"]), ("request_quote", event["quote"]), ("protection_point", None)):
                    equal(order[field], value, "Source close注文." + field)
            else:
                equal(expected, 0, "Source返済注文なし")
    for order in orders.values():
        key = source_identity(order["source"])
        require(key in births, "Source出生へ結合しないActual注文")
        if order["source_hold_id"]:
            equal(source_holds[(key[0], order["source_hold_id"])], key, "SourceHoldと出生対応")


def verify_book(book: dict, key: str) -> dict:
    """
    機能: Actualの全注文/約定/配賦/所有/総額と少数MTM点を独立に検算する。
    引数: book(dict)は実Go型ActualResult、key(str)は12口座の識別子。
    返り値: dictは検算結果と実Positionの比較用情報。
    """
    require(key in KEYS and book["key"] == key, "Actor key")
    policy, cost, delay = key.split("_")
    config = {"policy": policy, "slip_pts": int(cost[1:]), "delay_seconds": int(delay[1:])}
    equal(book["config"], config, "Actor config")
    require(book["complete"] is True and book["finished"] is True and book["failure"] == "", "未完了Actor")
    slip = number(config["slip_pts"], "滑りpt") * POINT
    orders = {o["id"]: o for o in book["orders"]}
    require(len(orders) == len(book["orders"]) and all(orders), "注文ID重複/空")
    fills = book["fills"]
    seen, holds, used_orders = set(), {}, set()
    gross = fees = slips = ZERO
    entry_quantity = close_quantity = 0
    last_order = (-1, ZERO, -1)
    for fill in fills:
        fid, pid = fill["id"], fill["position_id"]
        require(fid and fid not in seen and fill["order_id"] in orders and fill["order_id"] not in used_orders, "Fill/Order ID")
        seen.add(fid); used_orders.add(fill["order_id"])
        order = orders[fill["order_id"]]
        source_identity(order["source"])
        equal(order["status"], "filled", "約定注文status")
        equal(order["kind"], "entry" if fill["action"] == "new" else "exit", "注文/Fill種別")
        equal(fill["source"], order["source"], "注文/Fill Source")
        equal(fill["source_hold_id"], order["source_hold_id"], "注文/Fill SourceHold")
        qorder = quote(fill["quote"], "Fill.quote")
        require(qorder >= last_order, "Fill原行順序")
        last_order = qorder
        qty = integer(fill["quantity"], "Fill量", 1)
        require(fill["side"] in (-1, 1) and type(fill["side"]) is int, "Fill.side")
        equal(fill["price"], fill["quote"]["ask" if fill["side"] == 1 else "bid"], "約定BBO")
        quote(order["request_quote"], "要求quote", normal=False)
        require(fill["quote"]["index"] > order["request_quote"]["index"], "同原行/過去fill")
        require(fill["quote"]["time"] >= order["request_time"] + config["delay_seconds"], "要求時刻/遅延")
        for name in ("quantity", "side", "position_id", "source_hold_id", "native_close_signal_id", "native_close_notice_id", "reason"):
            equal(fill[name], order[name], "注文/Fill." + name)
        equal(order["fill_id"], fid, "注文fill_id")
        equal(fill["fee_yen"], FEE * qty, "Fill手数料")
        equal(fill["slip_yen"], slip * qty, "Fill仮定滑り")
        fees += FEE * qty; slips += slip * qty
        if fill["action"] == "new":
            require(pid and pid not in holds and not fill["allocations"], "新規所有/配賦")
            holds[pid] = {"q": qty, "initial": qty, "closed": 0, "entry": fill["price"], "side": fill["side"],
                          "quote": fill["quote"], "gross": ZERO, "net": ZERO, "source": fill["source"],
                          "source_hold": fill["source_hold_id"], "entry_order": fill["order_id"], "last_close": None}
            entry_quantity += qty
            equal(fill["gross_yen"], 0, "新規gross")
            require(qty <= order["source"]["birth_quantity"], "元出生量超過")
        else:
            require(fill["action"] == "close" and pid in holds, "返済所有ID")
            hold = holds[pid]
            require(fill["side"] == -hold["side"] and qty <= hold["q"], "返済方向/量")
            equal(fill["source"], hold["source"], "返済Source出典")
            equal(fill["source_hold_id"], hold["source_hold"], "返済Source所有")
            allocations = fill["allocations"]
            require(len(allocations) == 1, "Actual一所有の返済配賦数")
            a = allocations[0]
            amount = hold["side"] * (fill["price"] - hold["entry"]) * POINT * qty
            expected = {"position_id": pid, "source_hold_id": hold["source_hold"], "quantity": qty,
                        "entry_price": hold["entry"], "entry_quote": hold["quote"],
                        "exit_price": fill["price"], "exit_quote": fill["quote"], "gross_yen": amount,
                        "entry_fee_yen": FEE * qty, "exit_fee_yen": FEE * qty,
                        "entry_slip_yen": slip * qty, "exit_slip_yen": slip * qty,
                        "net_yen": amount - 2 * (FEE + slip) * qty}
            equal(a, expected, "返済配賦全値")
            equal(fill["gross_yen"], amount, "返済gross")
            hold["q"] -= qty; hold["closed"] += qty
            hold["gross"] += amount; hold["net"] += expected["net_yen"]
            hold["last_close"] = fill["quote"]
            gross += amount; close_quantity += qty
        equal(fill["net_contribution_yen"], fill["gross_yen"] - FEE * qty - slip * qty, "Fill純現金寄与")
        for side in (-1, 1):
            require(sum(h["q"] for h in holds.values() if h["side"] == side) <= 10, "片側実所有上限")
    require(all(h["q"] == 0 for h in holds.values()) and entry_quantity == close_quantity, "期末flat")
    for order in orders.values():
        source_identity(order["source"])
        integer(order["quantity"], "注文量", 1)
        require(type(order["side"]) is int and order["side"] in (-1, 1), "注文side")
        require(order["kind"] in ("entry", "exit"), "注文kind")
        if order["id"] in used_orders:
            require(order["cancel_time"] is None and not order["cancel_reason"], "fill注文の取消")
        else:
            require(order["cancel_time"] is not None and order["cancel_reason"] and not order["fill_id"], "未完了/不明な未約定注文")
            require(order["status"] == "cancelled" and order["kind"] == "entry", "未約定取消status/kind")
            require(order["cancel_time"] >= order["request_time"], "取消時計")
    timeline = Timeline(fills, slip, orders)
    verify_source_events(book, orders, timeline)
    saved = {p["id"]: p for p in book["positions"]}
    require(len(saved) == len(book["positions"]) and set(saved) == set(holds), "保存Position集合")
    for pid, h in holds.items():
        p = saved[pid]
        for name, actual in (("initial_quantity", h["initial"]), ("quantity", 0), ("reserved", 0),
                             ("closed_quantity", h["closed"]), ("entry_price", h["entry"]), ("entry_quote", h["quote"]),
                             ("side", h["side"]), ("source", h["source"]), ("source_hold_id", h["source_hold"]),
                             ("entry_order_id", h["entry_order"]), ("closed_quote", h["last_close"]),
                             ("gross_yen", h["gross"]), ("realized_net", h["net"])):
            equal(p[name], actual, "Position." + name)
        verify_marks(p, timeline, policy)
    for order in orders.values():
        point = order["protection_point"]
        if point is not None:
            require(order["kind"] == "exit" and policy != "S0" and point["phase"] == "after_source", "保護要求phase")
            timeline.verify_position_point(order["position_id"], point)
            equal(order["request_quote"], point["quote"], "保護要求quote")
            equal(order["request_time"], point["quote"]["time"], "保護要求time")
            equal(order["quantity"], point["quantity"] - point["reserved"], "保護要求未予約全残")
            require(not order["native_close_signal_id"] and not order["native_close_notice_id"], "保護要求の元通知偽装")
    totals = {"entry_quantity": entry_quantity, "close_quantity": close_quantity,
              "open_buy": 0, "open_sell": 0, "pending_buy": 0, "pending_sell": 0,
              "gross_yen": gross, "fee_yen": fees, "slip_yen": slips, "gross_minus_fee_yen": gross - fees,
              "net_yen": gross - fees - slips, "closed_net_yen": gross - fees - slips, "open_entry_costs_yen": ZERO}
    equal(book["totals"], totals, "ActualTotals全値")
    for name in ("gross_yen", "fee_yen", "slip_yen", "gross_minus_fee_yen", "net_yen", "closed_net_yen"):
        money(totals[name], name)
    account = book["account"]
    for name in ("first", "last", "peak", "max", "min", "drawdown_peak", "drawdown_trough"):
        if account[name] is not None:
            timeline.verify_account_point(account[name])
    require(number(account["max_drawdown"], "口座DD") >= 0 and number(account["max_gap_seconds"], "最大評価間隔") >= 0, "口座DD/評価間隔")
    integer(account["count"], "口座評価数")
    peak, trough = account["drawdown_peak"], account["drawdown_trough"]
    if trough is not None:
        if peak is not None:
            require(point_order(peak) <= point_order(trough), "DDのpeak/trough時系列")
        equal(account["max_drawdown"], (peak["equity"] if peak else ZERO) - trough["equity"], "保存DD二点算術")
    else:
        equal(account["max_drawdown"], 0, "troughなしDD")
    if account["last"] is not None:
        equal(account["last"]["equity"], totals["net_yen"], "最終MTM/最終純額")
    counts = {"positions": len(saved), "fills": len(fills), "orders": len(orders),
              "unit_positive_positions": sum(p["marks"]["first_unit_positive"] is not None for p in saved.values()),
              "whole_positive_positions": sum(p["marks"]["first_whole_positive"] is not None for p in saved.values()),
              "protection_activated_positions": sum(p["protection_active"] for p in saved.values())}
    for basis in ("unit", "whole"):
        counts[basis + "_positive_closed_negative"] = sum(p["marks"]["first_" + basis + "_positive"] is not None
                                                       and p["realized_net"] < 0 for p in saved.values())
    counts["activated_closed_negative"] = sum(p["protection_active"] and p["realized_net"] < 0 for p in saved.values())
    counts.update({
        "entry_requests": sum(o["kind"] == "entry" for o in orders.values()),
        "entry_accepted_quantity": sum(o["quantity"] for o in orders.values() if o["kind"] == "entry"),
        "cancelled_entries": sum(o["status"] == "cancelled" for o in orders.values()),
        "entry_fills": sum(f["action"] == "new" for f in fills),
        "exit_fills": sum(f["action"] == "close" for f in fills),
        "source_exit_requests": sum(o["kind"] == "exit" and o["protection_point"] is None for o in orders.values()),
        "protection_exit_requests": sum(o["protection_point"] is not None for o in orders.values()),
        "protection_exit_fills": sum(orders[f["order_id"]]["protection_point"] is not None for f in fills),
        "atr_deferred_positions": sum(p["atr"] is None or p["atr"]["after_entry"] for p in saved.values()),
    })
    for metric, kind in (("native_new_signals", "new_signal"), ("native_new_fills", "new_fill"),
                         ("native_close_notices", "close_notice"), ("native_close_fills", "close_fill"), ("native_cancels", "cancel")):
        counts[metric] = sum(e["kind"] == kind for e in book["source_events"])
    for name, count in book["metrics"].items():
        integer(count, "Metrics." + name)
    equal(account["count"], 2 * (book["metrics"]["rows"] - book["metrics"]["bad_quote_rows"]), "正常原行×前後2評価")
    for name in counts.keys() & book["metrics"].keys():
        equal(book["metrics"][name], counts[name], "Metrics." + name)
    return {"totals": totals, "counts": counts, "account_max_drawdown_yen": account["max_drawdown"],
            "positions": saved, "orders": orders, "timeline": timeline}


def normalized_actual_fill(fill: dict) -> tuple:
    """
    機能: S0の実約定を元所有と物理行を含む比較値へ射影する。
    引数: fill(dict)はActualFill。
    返り値: tupleは費用とActual独自IDだけを除いた約定値。
    """
    return (SOURCE_METHODS[fill["source"]["method"]], fill["action"], fill["source"]["signal_id"] if fill["action"] == "new" else fill["native_close_signal_id"],
            fill["source_hold_id"], fill["side"], fill["quantity"], fill["price"],
            tuple(fill["quote"][n] for n in ("time", "index", "source_line", "last", "bid", "ask", "quote_ok")))


def native_fill_projection(method: str, fills: list[dict]) -> list[tuple]:
    """
    機能: 実Go型Native Fillの大文字親と小文字Closed子を検査して射影する。
    引数: method(str)は明示の手法ID、fills(list[dict])はNativeのFillRecord列。
    返り値: list[tuple]はActual鏡像と比較する所有別約定。
    """
    short = SOURCE_METHODS.get(method, method)
    require(short in SOURCE_METHODS.values(), "Native手法ID")
    expected = []
    for record in fills:
        fill = record["fill"]
        equal(fill["Fee"], 0, "Source内部Fee0")
        equal(fill["Time"], record["quote"]["time"], "Native Fill時計")
        if record["action"] == "new":
            require(not fill["Closed"] and not record["allocations"], "Native新規のClosed")
            pieces = [(fill["HoldID"], fill["Quantity"])]
        else:
            equal(record["action"], "close", "Native返済action")
            targets = []
            for target in fill["Closed"]:
                equal(set(target), {"id", "quantity"}, "実Go LotTargetの小文字tag")
                targets.append((target["id"], integer(target["quantity"], "LotTarget.quantity", 1)))
            pieces = [(a["hold_id"], a["quantity"]) for a in record["allocations"]]
            equal(sorted(targets), sorted(pieces), "Native Closed/配賦の全所有量")
        equal(sum(qty for _, qty in pieces), fill["Quantity"], "Native全Fill量")
        for hold_id, qty in pieces:
            expected.append((short, record["action"], fill["SignalID"], hold_id, record["side"], qty, fill["Price"],
                             tuple(record["quote"][n] for n in ("time", "index", "source_line", "last", "bid", "ask", "quote_ok"))))
    return expected


def verify_api_mirror(fixture: dict) -> None:
    """
    機能: 手製APIの実Go Marshal NativeBatchと無保護D0の全約定を比較する。
    引数: fixture(dict)はsteps/timers/actorsを持つ型export。
    返り値: None。genuine Ledgerや自然Source生成の成功を補完しない。
    """
    expected = []
    for step in fixture["steps"]:
        for batch in step["batches"]:
            expected.extend(native_fill_projection(batch["method"], batch["delta"]["fills"]))
    for key in ("S0_C0_D0", "S0_C5_D0"):
        equal(Counter(normalized_actual_fill(f) for f in fixture["actors"][key]["fills"]), Counter(expected), key + "API全Fill鏡像")


def verify_mirror(value: dict) -> None:
    """
    機能: 同一保存ファイルのmini ShadowとS0 D0を所有別全Fillで独立照合する。
    引数: value(dict)はReplayResult。
    返り値: None。93正本とのShadow全文同値は別証拠に分担する。
    """
    expected, source_holds = [], {}
    for method, ledger in value["shadows"].items():
        equal(ledger["method"], "NK225_" + method, "Shadow.method")
        for hold in ledger["holds"]:
            key = method, hold["hold_id"]
            require(key not in source_holds, "Shadow所有ID重複")
            source_holds[key] = hold
        expected.extend(native_fill_projection(method, ledger["fills"]))
    reference = Counter(expected)
    for key in ("S0_C0_D0", "S0_C5_D0"):
        equal(Counter(normalized_actual_fill(f) for f in value["books"][key]["fills"]), reference, key + "全Fill Source鏡像")
        owned = set()
        for p in value["books"][key]["positions"]:
            identity = SOURCE_METHODS[p["source"]["method"]], p["source_hold_id"]
            require(identity in source_holds and identity not in owned, key + "Source所有集合")
            owned.add(identity)
            h = source_holds[identity]
            for field, expected_value in (("signal_id", h["entry_id"]), ("kind", h["kind"]), ("parent", h["parent"]), ("source_id", h["source_id"])):
                equal(p["source"][field], expected_value, key + "Source." + field)
            for field in ("side", "initial_quantity", "entry_price", "entry_quote"):
                equal(p[field], h[field], key + "Source所有." + field)
        equal(owned, set(source_holds), key + "全Source所有対応")
    for delay in (0, 1):
        a, b = (value["books"][f"S0_C{cost}_D{delay}"] for cost in (0, 5))
        equal([normalized_actual_fill(f) for f in a["fills"]], [normalized_actual_fill(f) for f in b["fills"]], "S0 C0/C5全取引列")


def viewer_trades(book: dict) -> list[dict]:
    """
    機能: Actor自身の実Fillを半円費用と独立所有を保ったViewer行へ変換する。
    引数: book(dict)はActualResult。
    返り値: list[dict]は新規/返済の表示行。
    """
    rows = []
    for fill in book["fills"]:
        side = fill["side"] if fill["action"] == "new" else -fill["side"]
        rows.append({"id": fill["id"], "timestamp": datetime.fromtimestamp(float(fill["quote"]["time"]), timezone(timedelta(hours=9))).isoformat(),
                     "type": ("Long" if side == 1 else "Short") + ("N" if fill["action"] == "new" else "R"),
                     "position_id": fill["position_id"], "price": fill["price"], "qty": fill["quantity"],
                     "fee_yen": fill["fee_yen"] + fill["slip_yen"], "method_id": book["key"], "source_line": fill["quote"]["source_line"]})
    return rows


def entry_fingerprint(position: dict, orders: dict) -> tuple:
    """
    機能: 同Source内の同実入口を価格/量/要求/物理行まで比較する。
    引数: position(dict)は実玉、orders(dict)は注文ID写像。
    返り値: tupleは入口の完全比較値。
    """
    order = orders[position["entry_order_id"]]
    q = position["entry_quote"]
    return (order["request_time"], position["side"], q["time"], q["index"], q["source_line"],
            position["entry_price"], position["initial_quantity"])


def compare_positions(a: dict, b: dict) -> dict:
    """
    機能: Source出生一致→同実入口/取得変更/片側参加に分け、差額を保存する。
    引数: a/b(dict)はverify_bookの比較用返り値。
    返り値: dictは差額と救った赤字/失った黒字の限定分解。
    """
    def mapping(row):
        """
        機能: 一度だけ受理する元出生IDへ実玉を結ぶ。
        引数: row(dict)は検算済み口座。
        返り値: dictはSource→実玉。
        """
        output = {}
        for p in row["positions"].values():
            key = source_identity(p["source"])
            require(key not in output, "同Source出生の複数実玉")
            output[key] = p
        return output
    aa, bb = mapping(a), mapping(b)
    same, changed, a_only, b_only = [], [], [], []
    for source in aa.keys() | bb.keys():
        if source not in aa:
            b_only.append(bb[source]); continue
        if source not in bb:
            a_only.append(aa[source]); continue
        pair = (aa[source], bb[source])
        (same if entry_fingerprint(pair[0], a["orders"]) == entry_fingerprint(pair[1], b["orders"]) else changed).append(pair)
    delta = lambda pairs: sum((pb["realized_net"] - pa["realized_net"] for pa, pb in pairs), ZERO)
    same_delta, changed_delta = delta(same), delta(changed)
    aa_amount = sum((p["realized_net"] for p in a_only), ZERO)
    bb_amount = sum((p["realized_net"] for p in b_only), ZERO)
    total = b["totals"]["net_yen"] - a["totals"]["net_yen"]
    equal(total, same_delta + changed_delta - aa_amount + bb_amount, "参加差の会計式")
    return {"同Source出生": len(same) + len(changed), "同実入口": len(same), "取得変更": len(changed),
            "Aのみ": len(a_only), "Bのみ": len(b_only), "全差円": total, "同実入口差円": same_delta,
            "取得変更差円": changed_delta, "Aのみ円": aa_amount, "Bのみ円": bb_amount,
            "同実入口の赤字から黒字": sum(pa["realized_net"] < 0 < pb["realized_net"] for pa, pb in same),
            "同実入口の黒字から赤字": sum(pb["realized_net"] < 0 < pa["realized_net"] for pa, pb in same),
            "限定": "同実入口だけを退出差と呼ぶ。参加/取得変更を保護単独効果にしない。"}


def analyze_saved(values: list[dict], scope: str = "正式") -> dict:
    """
    機能: 保存済みReplayResult群を集計し、正式事前値と12Actor集合を照合する。
    引数: values(list[dict])は保存値、scope(str)は正式/接続/人工。
    返り値: dictは検算済み結果JSON。人工は実Go型exportのみから呼び出す。
    """
    require(scope in ("正式", "接続", "人工"), "集計scope")
    if scope == "正式":
        equal(len(values), 54, "正式54場")
    elif scope == "接続":
        equal(len(values), 2, "先頭接続2場")
    combined = {key: defaultdict(Decimal) for key in KEYS}
    sessions, seen = [], set()
    comparisons = defaultdict(list)
    for value in values:
        session = value["session"]
        require(isinstance(session, str) and session not in seen, "session重複/型")
        seen.add(session)
        equal(set(value["books"]), set(KEYS), "12Actor集合")
        if scope != "人工":
            expected_methods = {"D164_15"} if session.endswith("_Day") else {"P164_06", "U165_03"}
            equal(set(value["shadows"]), expected_methods, "当場Shadow手法集合")
            match = value["shadow_match"]
            require(match["all"] is True and match["baseline_proof_sha256"] == "e811571a876f3fdc2f5ba7c09b3906c84db9e380ef89c24b920e5c3f199a2a37", "固定93Shadow照合証拠")
            equal(match["methods"], {method: True for method in expected_methods}, "全Shadow照合手法")
        verify_mirror(value)
        checked = {}
        for key in KEYS:
            book = value["books"][key]
            result = checked[key] = verify_book(book, key)
            summary = {"session": session, "key": key, "totals": result["totals"], "counts": result["counts"],
                       "account_max_drawdown_yen": result["account_max_drawdown_yen"], "metrics": book["metrics"]}
            sessions.append(summary)
            for name, amount in result["totals"].items():
                combined[key][name] += amount
            for name, count in result["counts"].items():
                combined[key][name] += count
            combined[key]["active_sessions"] += bool(result["counts"]["positions"])
            combined[key]["negative_sessions"] += result["totals"]["net_yen"] < 0
            combined[key]["max_session_mtm_drawdown_yen"] = max(combined[key]["max_session_mtm_drawdown_yen"], result["account_max_drawdown_yen"])
        for cost in (0, 5):
            for delay in (0, 1):
                for a, b in (("S0", "P0"), ("S0", "P1"), ("P0", "P1")):
                    name = f"{b}対{a}_C{cost}_D{delay}"
                    comparisons[name].append({"session": session, **compare_positions(checked[f"{a}_C{cost}_D{delay}"], checked[f"{b}_C{cost}_D{delay}"])})
    if scope == "正式":
        for key in ("S0_C0_D0", "S0_C5_D0"):
            equal(combined[key]["gross_yen"], BASELINE["gross_yen"], key + "固定gross")
            equal(combined[key]["net_yen"], BASELINE[key], key + "固定純額")
    return {"試行": 94, "成功": True, "scope": scope, "場数": len(values), "Actor数": 12, "会計数": len(sessions),
            "集計": {key: dict(row) for key, row in combined.items()}, "場別": sessions,
            "同実入口と参加差": dict(comparisons), "固定対照値": BASELINE,
            "固定54場金額照合実施": scope == "正式",
            "Source比較": "S0 D0全Fillを当保存Shadowへ所有/価格/量/物理行で照合。Shadow対93全文は別証拠。",
            "MTM検査範囲": "少数保存点のu/W・口座EquityをFillの当時配賦から検算。初回/極値の全原行取り落としと適格気配/Source全作用は別Raw監査。",
            "分母": "残玉単価uと全Hold Wの初回正益/最終赤字を別集計。D1容量/参加差と動的C5出口差は別運転。",
            "費用": "gross/指定feeのみ/当Actorの追加slip込みを分離。Source部分作用は未予約量にceil、源全残例外。",
            "未実施": {"原板本文読取": 0, "Source再計算": 0, "金融再生": 0, "資本金ROI": None}}


def render(summary: dict) -> str:
    """
    機能: 正本から12口座の最小会計表と検算範囲を生成する。
    引数: summary(dict)は検算済み結果。
    返り値: strはMarkdown。
    """
    lines = ["# 94：連続出生を固定した個別利益追尾・保存会計", "",
             f"{summary['場数']}場・{summary['会計数']}会計。scope={summary['scope']}。全てラージBBOによるmini模型。", "",
             "| Actor | 実玉/枚 | gross | 指定feeのみ | 仮定slip込み | u正益後赤字/正益玉 | W正益後赤字/正益玉 | 取引あり場 | 赤字場 | 最大場内MTM DD円 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        row = summary["集計"][key]
        lines.append(f"| {key} | {row['positions']}/{row['entry_quantity']} | {row['gross_yen']} | {row['gross_minus_fee_yen']} | {row['net_yen']} | {row['unit_positive_closed_negative']}/{row['unit_positive_positions']} | {row['whole_positive_closed_negative']}/{row['whole_positive_positions']} | {row['active_sessions']}/{summary['場数']} | {row['negative_sessions']}/{summary['場数']} | {row['max_session_mtm_drawdown_yen']} |")
    lines += ["", "C0は指定手数料のみが主。C5は起動と床へ費用を反映した別運転であり、C0の実績から滑りだけを引いた反実仮想ではない。",
              "", "uは未返済単価、Wは配賦済み確定益＋残玉即時清算純額。正益後赤字は最終純額が負の実玉で、途中の赤字戻りとは別。",
              "", summary["MTM検査範囲"], "最大場内DDを期間全体の連続DDと呼ばず、未知の気配区間の評価も保証しない。",
              "", "S0のD0固定対照と所有別Fillを照合。Sourceの生成全文同値は別証拠。参加変更を追尾単独の効果へ帰属させない。全額ROIは算出しない。", ""]
    return "\n".join(lines)


def main() -> None:
    """
    機能: 完了指紋付き54保存JSONだけを読み、独立検算後に新規成果物を保存する。
    引数: --run(Path)は完了JSONのdir、--out(Path)は新規dir、--limit(int)は正式54又は接続2。
    返り値: None。不整合時は非0終了し、実市場や原板を再生しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, choices=(2, 54), default=54)
    args = parser.parse_args()
    completion_path = args.run / "完了.json"
    code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    completion_sha = hashlib.sha256(completion_path.read_bytes()).hexdigest()
    completion = read_json(completion_path)
    equal(completion["場数"], args.limit, "完了場数")
    require(len(completion["結果SHA256"]) == args.limit and not args.out.exists(), "入力数/新規出力")
    values, bodies = [], []
    fingerprints = {}
    for name, expected_sha in sorted(completion["結果SHA256"].items()):
        path = (args.run / name).resolve()
        require(path.is_relative_to(args.run.resolve()) and path.suffix == ".json", "入力path境界")
        body = path.read_bytes()
        equal(hashlib.sha256(body).hexdigest(), expected_sha, "保存入力SHA")
        value = json.loads(body, parse_float=Decimal, parse_constant=lambda n: fail(n))
        values.append(value); bodies.append((name, body)); fingerprints[name] = expected_sha
    summary = analyze_saved(values, scope="正式" if args.limit == 54 else "接続")
    summary["入力SHA256"] = fingerprints
    summary["完了記録SHA256"] = completion_sha
    summary["集計コードSHA256"] = code_sha
    args.out.mkdir(parents=True)
    resources = []
    for value, (name, body) in zip(values, bodies):
        for key in KEYS:
            book = value["books"][key]
            identity = "94_" + key + "_" + value["session"]
            trade_path = identity + ".trades.jsonl"
            with (args.out / trade_path).open("x", encoding="utf-8", newline="\n") as stream:
                for trade in viewer_trades(book):
                    stream.write(json.dumps(trade, ensure_ascii=False, allow_nan=False, default=serial) + "\n")
            resources.append({"id": identity, "title": "個別利益追尾 " + key + " " + value["session"], "symbol": "NK225", "product": "NK225mini",
                              "session": value["session"], "method_id": key, "point_value": 100, "pnl_format": "trades", "pnl_basis": "net",
                              "pnl_path": trade_path, "market_path": "NK225/" + value["session"] + "/book.jsonl.gz"})
        with (args.out / (Path(name).name + ".gz")).open("xb") as compressed:
            with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as stream:
                stream.write(body)
    equal(len(resources), args.limit * 12, "Viewer資源数")
    after = {}
    for name, expected in fingerprints.items():
        after[name] = hashlib.sha256((args.run / name).read_bytes()).hexdigest()
        equal(after[name], expected, "入力前後SHA")
    equal(hashlib.sha256(completion_path.read_bytes()).hexdigest(), completion_sha, "完了記録前後SHA")
    equal(hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), code_sha, "コード前後SHA")
    summary["入力SHA256前"] = fingerprints
    summary["入力SHA256後"] = after
    summary["入力前後不変"] = True
    write_json(args.out / "結果.json", summary)
    write_json(args.out / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    (args.out / "結果.md").write_text(render(summary), encoding="utf-8", newline="\n")
    print(json.dumps({"成功": True, "場数": args.limit, "会計数": args.limit * 12, "資源数": len(resources), "scope": summary["scope"], "集計": summary["集計"]}, ensure_ascii=False, default=serial))


if __name__ == "__main__":
    main()
