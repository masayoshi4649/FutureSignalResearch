"""95の出生/grid受付を保存値から結合し、固定94会計を再用して独立集計する。"""

import argparse
from collections import defaultdict
import copy
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import types


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / "scripts/FAR連続出生と個別利益追尾/集計.py"
BASE_SHA = "7c0c1d1b365226c74027405589099cb72382c7850090627a83788e1e2066c381"
if hashlib.sha256(BASE_PATH.read_bytes()).hexdigest() != BASE_SHA:
    raise ValueError("固定94集計の由来SHA差")
SPEC = importlib.util.spec_from_file_location("固定94保存会計の再用", BASE_PATH)
BASE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(BASE)
need, equal, number, integer = BASE.require, BASE.equal, BASE.number, BASE.integer
read_json, write_json, serial = BASE.read_json, BASE.write_json, BASE.serial
TIMINGS = ("N", "B5", "B5Q")
KEYS = tuple(("" if t == "N" else t + "_") + f"P0_C{c}_D{d}" for t in TIMINGS for c in (0, 5) for d in (0, 1))
BASELINE_PROOF = ROOT / "study/00094_連続出生を固定した個別利益追尾/完了記録.json"
BASELINE_DIR = BASELINE_PROOF.parent / "成果物"
BASELINE_SHA = "ccbc365b647c8225f5ef238f707778e9fbff01c5decba721c2843cb3f1972f80"
N_TARGET = {"P0_C0_D0": -525135, "P0_C0_D1": -111135, "P0_C5_D0": -800135, "P0_C5_D1": -481981}
NEW_TOP = ("entry_opportunities", "grid_traces", "grid_metrics")


def clock_delta(a, b) -> Decimal:
    """
    機能: Go型のepoch秒float64同士の差を同じ丸めで再構成する。
    引数: a/b(number)は保存された有限時計。
    返り値: Decimalはfloat64差の十進表記。金額には使用しない。
    """
    return Decimal(str(float(number(a, "時計")) - float(number(b, "時計"))))


def key_config(key: str) -> tuple:
    """
    機能: 明示された12口座名を入口/固定94側名/費用/遅延に分ける。
    引数: key(str)は定義済みActor名。
    返り値: tupleはtiming/base_key/slip/delay。
    """
    need(key in KEYS, "95 Actor key")
    timing = "B5Q" if key.startswith("B5Q_") else "B5" if key.startswith("B5_") else "N"
    base_key = key if timing == "N" else key[len(timing) + 1:]
    _, c, d = base_key.split("_")
    return timing, base_key, int(c[1:]), int(d[1:])


def project94(book: dict) -> dict:
    """
    機能: 95の追加5fieldと外keyだけを除き、共通金融を94型へ投影する。
    引数: book(dict)は95の実Go Marshal ActualResult。
    返り値: dictは独立複写。元Sourceイベントの時計/内容は変えない。
    """
    result = copy.deepcopy(book)
    for name in NEW_TOP: result.pop(name)
    result["config"].pop("entry_timing"); result["config"].pop("us_open")
    result["key"] = key_config(book["key"])[1]
    return result


def event_before(event: dict, at, q: dict | None) -> bool:
    """
    機能: RootのForce→grid→原行時計で、gridまでに公開された源通知を選ぶ。
    引数: event(dict)は保存源通知、at(number)は枠、q(dict|None)は最新受理原行。
    返り値: boolは当時公開済み。未来の同秒原行を含めない。
    """
    if event["at"] < at: return True
    return event["at"] == at and q is not None and all(
        event["quote"][field] <= q[field] for field in ("time", "index", "source_line"))


def accepted_entries_at_grid(book: dict, at, q: dict | None) -> set:
    """
    機能: grid終了時点の受理済みnewを、Nの原行受付とBの枠内受付に分けて選ぶ。
    引数: book(dict)はGo型保存台帳、at(number)は枠、q(dict|None)は枠直前の最新原行。
    返り値: set[str]は当時受理済み注文ID。同秒の後続原行出生は含めない。
    """
    timing = key_config(book["key"])[0]
    accepted = set()
    for p in book["entry_opportunities"]:
        if p["status"] != "accepted" or p["evaluated_at"] > at:
            continue
        if p["evaluated_at"] == at:
            if timing == "N":
                if not event_before({"at": p["evaluated_at"], "quote": p["quote"]}, at, q):
                    continue
            else:
                equal(p["quote"], q, "当grid受理の公開原行")
        accepted.add(p["entry_order_id"])
    return accepted


def source_at(book: dict, at, q: dict | None) -> dict:
    """
    機能: 保存Source new/fill/cancel/closeの明示IDから当時の取得/予約を再構成する。
    引数: book(dict)は95台帳、at(number)は枠、q(dict|None)は最新原行。
    返り値: dictは源出生ID→state/hold/量/予約。
    """
    events = [e for e in book["source_events"] if event_before(e, at, q)]
    states, holds, closes = {}, {}, defaultdict(list)
    # 同原行取消はnew_signal traceより前でも、当原行の出生登録は既に公開される。
    for e in events:
        if e["kind"] == "new_signal": states[(e["method"], e["signal_id"])] = {"state": "pending", "hold": "", "q": None, "reserved": None}
    for e in events:
        key = e["method"], e["signal_id"]
        if e["kind"] == "cancel":
            need(key in states and states[key]["state"] == "pending", "当時Source取消")
            states[key]["state"] = "cancelled"
        elif e["kind"] == "new_fill":
            need(key in states and states[key]["state"] == "pending", "当時Source new fill")
            states[key].update(state="filled", hold=e["hold_id"], q=e["quantity"], reserved=0)
            hold = e["method"], e["hold_id"]
            need(hold not in holds, "当時Source所有重複")
            holds[hold] = states[key]
        elif e["kind"] == "close_notice":
            hold = e["method"], e["hold_id"]
            need(hold in holds, "当時Source close所有")
            h = holds[hold]
            equal(e["before"], h["q"] - h["reserved"], "Source独立Before")
            h["reserved"] += e["quantity"]; closes[key].append((hold, e["quantity"]))
        elif e["kind"] == "close_fill":
            need(key in closes, "通知のないSource close fill")
            equal(sum(qty for _, qty in closes[key]), e["quantity"], "Source close fill総量")
            for hold, qty in closes.pop(key):
                h = holds[hold]; h["q"] -= qty; h["reserved"] -= qty
                need(h["q"] >= h["reserved"] >= 0, "当時Source残/予約")
    return states


def pending_quantity(book: dict, orders: dict, timeline, at, q: dict, side: int, allowed: set) -> int:
    """
    機能: 当時受理済みのnewだけを、未来取消を混ぜず未取得予約へ数える。
    引数: book/ orders(dict)、timeline(Timeline)、at(number)、q(dict)、side(int)、allowed(set)は当時受理ID。
    返り値: intは当時の未取得予約枚数。
    """
    quantity = 0
    visible = [e for e in book["source_events"] if event_before(e, at, q)]
    for oid in allowed:
        o = orders[oid]
        if o["side"] != side: continue
        fill = timeline.fill_by_order.get(oid)
        if fill is not None and fill["quote"]["index"] <= q["index"]: continue
        cancelled = any(e["actual_new_cancelled"] > 0 and
                        ((e["kind"] == "cancel" and e["method"] == o["source"]["method"] and e["signal_id"] == o["source"]["signal_id"])
                         or (e["kind"] == "close_notice" and e["method"] == o["source"]["method"] and e["hold_id"] == o["source_hold_id"])) for e in visible)
        if not cancelled: quantity += o["quantity"]
    return quantity


def available_at(book: dict, orders: dict, timeline, at, q: dict, side: int, allowed: set) -> int:
    """
    機能: 保存Fill所有と当時受理new予約から片側の空きを独立計算する。
    引数: book/orders(dict)、timeline(Timeline)、at(number)、q(dict)、side(int)、allowed(set)は当時受理ID。
    返り値: intは0〜10の空き。
    """
    point = {"quote": q, "phase": "after_source"}
    owned = sum(h["quantity"] for pid in timeline.histories if (h := timeline.state_at(pid, point)) is not None and h["side"] == side)
    pending = pending_quantity(book, orders, timeline, at, q, side, allowed)
    free = 10 - owned - pending; need(0 <= free <= 10, "95所有/予約の上限")
    return free


def verify_source_b(book: dict, orders: dict, timeline) -> None:
    """
    機能: B系の出生即受理0と元通知/実返済作用を、架空のgridイベントを作らず検査する。
    引数: book/orders(dict)は95正本、timeline(Timeline)は固定94の独立Fill履歴。
    返り値: None。元Source自然生成/全原行を再運転しない。
    """
    births, notices, executions, holds = {}, set(), set(), {}
    source_requests, cancelled_orders = set(), set()
    positions_by_hold = {(p["source"]["method"], p["source_hold_id"]): p for p in book["positions"]}
    entries_by_source = {BASE.source_identity(o["source"]): o for o in orders.values() if o["kind"] == "entry"}
    for e in book["source_events"]:
        need(e["kind"] in ("new_signal", "new_fill", "close_fill", "close_notice", "cancel") and e["method"] in BASE.SOURCE_METHODS, "95 Source種別/手法")
        BASE.quote(e["quote"], "95 Source.quote", normal=False)
        for name in ("quantity", "before", "actual_pending_before", "actual_new_cancelled", "actual_free_before", "actual_exit_requested", "actual_free_after", "actual_accepted", "available"):
            integer(e[name], "Source." + name)
        key = e["method"], e["signal_id"]
        if e["kind"] == "new_signal":
            need(key not in births, "95出生重複"); births[key] = e
            equal(e["phase"], "native_new", "出生phase")
            need(e["actual_accepted"] == 0 and e["order_id"] == "", "B出生時の架空受理")
            allowed = {p["entry_order_id"] for p in book["entry_opportunities"] if p["status"] == "accepted" and p["evaluated_at"] <= e["at"]}
            equal(e["available"], available_at(book, orders, timeline, e["at"], e["quote"], e["side"], allowed), "B出生の当時空き")
        elif e["kind"] in ("new_fill", "close_fill"):
            equal(e["phase"], "native_fill", "Source fill phase")
            identity = e["method"], e["execution_id"]
            need(identity[1] and identity not in executions, "Source ExecutionID"); executions.add(identity)
            if e["kind"] == "new_fill":
                hold = e["method"], e["hold_id"]
                need(hold[1] and hold not in holds, "Source Hold重複"); holds[hold] = key
        elif e["kind"] == "cancel":
            equal(e["phase"], "before_fill", "Source cancel phase")
            equal(e["actual_new_cancelled"], 0, "B系はSource未取得出生をまだ実受理しない")
        else:
            equal(e["phase"], "source_close", "Source close phase")
            notice = e["method"], e["notice_id"]
            need(notice[1] and notice not in notices, "Source notice重複"); notices.add(notice)
            before, qty, free = e["before"], e["quantity"], e["actual_free_before"]
            need(0 < qty <= before, "Source Before/quantity")
            hold_key = e["method"], e["hold_id"]
            need(hold_key in holds, "Source close対象Hold")
            entry = entries_by_source.get(holds[hold_key])
            fill = None if entry is None else timeline.fill_by_order.get(entry["id"])
            published_entry = entry is not None and (entry["request_time"] < e["at"] or
                              (entry["request_time"] == e["at"] and entry["request_quote"]["index"] < e["quote"]["index"]))
            pending = entry["quantity"] if published_entry and entry["id"] not in cancelled_orders and (fill is None or fill["quote"]["index"] > e["quote"]["index"]) else 0
            equal(e["actual_pending_before"], pending, "Source close直前の実未取得量")
            if pending: cancelled_orders.add(entry["id"])
            p = positions_by_hold.get(hold_key)
            state = None if p is None else timeline.state_at(p["id"], {"quote": e["quote"], "phase": "after_source"})
            owned, reserved = (0 if state is None else state["quantity"]), 0
            if p is not None:
                for o in orders.values():
                    if o["kind"] != "exit" or o["position_id"] != p["id"]: continue
                    f = timeline.fill_by_order.get(o["id"])
                    if f is not None and f["quote"]["index"] <= e["quote"]["index"]: continue
                    protection_known = o["protection_point"] is not None and o["request_time"] <= e["at"] and (
                        o["request_quote"]["index"] < e["quote"]["index"] or
                        (o["request_quote"]["index"] == e["quote"]["index"] and e["at"] > e["quote"]["time"]))
                    if o["id"] in source_requests or protection_known: reserved += o["quantity"]
            equal(free, owned - reserved, "Source close直前の独立実未予約量")
            requested = free if qty == before else (free * qty + before - 1) // before
            equal(e["actual_exit_requested"], requested, "Source ceil/全残")
            equal(e["actual_free_after"], free - requested, "Source free残")
            equal(e["actual_new_cancelled"], e["actual_pending_before"], "未取得全取消")
            if e["order_id"]:
                o = orders[e["order_id"]]
                for field, expected in (("kind", "exit"), ("quantity", requested), ("source_hold_id", e["hold_id"]),
                    ("native_close_signal_id", e["signal_id"]), ("native_close_notice_id", e["notice_id"]),
                    ("request_time", e["at"]), ("request_quote", e["quote"]), ("protection_point", None)):
                    equal(o[field], expected, "Source exit." + field)
                source_requests.add(o["id"])
            else: equal(requested, 0, "Source注文なし")
    for o in orders.values():
        key = BASE.source_identity(o["source"]); need(key in births, "95 Source出生への注文結合")
        if o["source_hold_id"]: equal(holds[(key[0], o["source_hold_id"])], key, "95源Holdと出生")


def verify_grid(book: dict, orders: dict, timeline, full_clock: bool) -> None:
    """
    機能: 一枠寿命/quiet/Source状態/受理順/実注文とgrid分母を保存から独立結合する。
    引数: book/orders(dict)、timeline(Timeline)、full_clock(bool)は正式の開始からの連続prefixを要求するか。
    返り値: None。全原行の最新気配/slot取り落としは別境界監査にも分担する。
    """
    timing, _, _, _ = key_config(book["key"])
    cfg, session = book["config"], book["session"]
    opportunities, grids = book["entry_opportunities"], book["grid_traces"]
    births = {(e["method"], e["signal_id"]): e for e in book["source_events"] if e["kind"] == "new_signal"}
    need(len(opportunities) == len(births), "全出生/全Opportunity")
    accepted, seen, source_cache = set(), set(), {}
    previous = None
    for n, p in enumerate(opportunities, 1):
        equal(p["ordinal"], n, "Opportunity連番")
        key = BASE.source_identity(p["source"]); need(key in births and key not in seen, "Opportunity出生一意"); seen.add(key)
        event = births[key]
        equal(p["source"]["birth_time"], event["at"], "出生時刻不変")
        equal(p["source"]["birth_quote"], event["quote"], "出生原行不変")
        equal(p["side"], event["side"], "出生方向")
        assigned = (number(event["at"], "birth") // 300 + 1) * 300
        equal(p["assigned_at"], assigned, "strict次5分")
        order = (event["at"], event["quote"]["index"], event["quote"]["source_line"], integer(p["batch_index"], "batch"), integer(p["signal_index"], "signal"))
        need(previous is None or previous <= order, "出生の安定順"); previous = order
        need(p["consumed"] is True and p["evaluated_at"] is not None and p["status"] in ("accepted", "expired")
             and type(p["required_unknown"]) is bool, "最終機会状態")
        if timing == "N":
            equal(p["evaluated_at"], event["at"], "N評価時計")
            equal(p["requested"], event["actual_accepted"], "N実受理")
            equal(p["entry_order_id"], event["order_id"], "N注文結合")
            need(p["required_unknown"] is False, "NにB系未知gateを追加しない")
        else:
            at, q = p["evaluated_at"], p["quote"]
            need(at >= event["at"], "出生前の受付")
            if q is not None:
                BASE.quote(q, "Opportunity.quote", normal=False)
                need(q["time"] <= at, "未来気配")
                equal(p["quote_age_seconds"], clock_delta(at, q["time"]), "気配age")
                equal(p["available"], available_at(book, orders, timeline, at, q, p["side"], accepted), "slot前の予約込み空き")
            else: need(p["quote_age_seconds"] is None, "quoteなしage")
            cache_key = at, None if q is None else q["index"]
            if cache_key not in source_cache: source_cache[cache_key] = source_at(book, at, q)
            h = source_cache[cache_key][key]
            equal(p["source_state"], h["state"], "当時Source状態")
            equal(p["source_hold_id"], h["hold"], "当時SourceHold")
            equal(p["source_quantity"], h["q"], "当時Source残量")
            equal(p["source_reserved"], h["reserved"], "当時Source予約")
            eof = p["reason"] == "EOFで未消費出生機会を失効"
            deadline = min(session["force_close"], cfg["us_open"] - 900) if key[0] == "NK225_P164_06" else session["force_close"]
            quiet = session["start"] <= at < session["start"] + 1800 or (session["kind"] == "Night" and cfg["us_open"] > 0 and cfg["us_open"] <= at < cfg["us_open"] + 1800)
            known_quote = q is not None and q["quote_ok"] and q["ask"] > q["bid"] > 0
            refusal = eof or at != assigned or at >= deadline or (timing == "B5Q" and quiet) or h["state"] in ("pending", "cancelled") or h["q"] == 0 or (h["reserved"] or 0) > 0
            unknown = not refusal and not known_quote
            equal(p["required_unknown"], unknown, "政策必須未知")
            eligible = not refusal and not unknown and p["available"] > 0
            equal(p["status"], "accepted" if eligible else "expired", "機会の独立採否")
            expected_quantity = min(p["source"]["birth_quantity"], h["q"], p["available"]) if eligible else 0
            equal(p["requested"], expected_quantity, "slot要求の3値min")
        if p["status"] == "accepted":
            o = orders[p["entry_order_id"]]
            for field, expected in (("kind", "entry"), ("source", p["source"]), ("side", p["side"]),
                ("quantity", p["requested"]), ("request_time", p["evaluated_at"]), ("request_quote", p["quote"])):
                equal(o[field], expected, "機会/実注文." + field)
            if timing != "N": equal(o["source_hold_id"], p["source_hold_id"], "grid取得済SourceHold")
            accepted.add(o["id"])
        else: need(p["requested"] == 0 and not p["entry_order_id"], "失効機会の架空注文")
    equal(accepted, {o["id"] for o in orders.values() if o["kind"] == "entry"}, "全新規注文の機会結合")
    by_grid = defaultdict(list)
    for p in opportunities:
        if timing != "N" and p["reason"] != "EOFで未消費出生機会を失効": by_grid[p["evaluated_at"]].append(p)
    last = None
    for trace in grids:
        at = trace["at"]
        need(at % 300 == 0 and session["start"] <= at < session["end"] and (last is None or last < at), "grid時計")
        last = at; equal(trace["timing"], timing, "grid入口名")
        q = trace["quote"]
        if q is not None:
            BASE.quote(q, "Grid.quote", normal=False); need(q["time"] <= at, "grid未来原行")
            equal(trace["quote_age_seconds"], clock_delta(at, q["time"]), "grid age")
        else: need(trace["quote_age_seconds"] is None, "grid quoteなしage")
        equal(trace["quote_known"], q is not None and q["quote_ok"] and q["ask"] > q["bid"] > 0, "grid正常性")
        equal(trace["us_clock_known"], session["kind"] == "Day" or cfg["us_open"] > 0, "米国時計既知")
        us_quiet = cfg["us_open"] <= at < cfg["us_open"] + 1800 if session["kind"] == "Night" and cfg["us_open"] > 0 else None
        equal(trace["us_quiet"], us_quiet, "米国quiet")
        quiet = session["start"] <= at < session["start"] + 1800 or us_quiet is True
        equal(trace["quiet"], quiet, "quiet半開境界"); equal(trace["quiet_applied"], quiet and timing == "B5Q", "quiet実適用")
        points = by_grid.get(at, [])
        equal(trace["ordinals"], [p["ordinal"] for p in points], "枠の候補順")
        for field, expected in (("candidate_count", len(points)), ("accepted_count", sum(p["status"] == "accepted" for p in points)),
            ("accepted_quantity", sum(p["requested"] for p in points)), ("expired_count", sum(p["status"] == "expired" for p in points)),
            ("unknown_count", sum(p["required_unknown"] for p in points))): equal(trace[field], expected, "grid." + field)
        if q is not None:
            point = {"quote": q, "phase": "after_source"}
            for side, field in ((1, "open_buy"), (-1, "open_sell")):
                owned = sum(h["quantity"] for pid in timeline.histories if (h := timeline.state_at(pid, point)) is not None and h["side"] == side)
                equal(trace[field], owned, "grid実保有")
            known_orders = accepted_entries_at_grid(book, at, q)
            for side, field in ((1, "pending_buy"), (-1, "pending_sell")):
                equal(trace[field], pending_quantity(book, orders, timeline, at, q, side, known_orders),
                      f"grid new予約量 {session['id']}/{book['key']}/at={at}/side={side}")
        action = "新規" if trace["accepted_count"] else "保有" if trace["open_buy"] + trace["open_sell"] else "判定不能" if trace["unknown_count"] else "待機"
        equal(trace["action"], action, "grid行動優先")
    if full_clock:
        verify_grid_prefix(session, [t["at"] for t in grids])
    metrics = {"births": len(opportunities), "grid_calls": len(grids), "quiet_grids": sum(t["quiet"] for t in grids),
        "unknown_us_grids": sum(not t["us_clock_known"] for t in grids), "accepted": sum(p["status"] == "accepted" for p in opportunities),
        "expired": sum(p["status"] == "expired" for p in opportunities), "required_unknown": sum(p["required_unknown"] for p in opportunities),
        "eof_expired": sum(p["reason"] == "EOFで未消費出生機会を失効" for p in opportunities)}
    for action, field in (("新規", "new_grids"), ("保有", "holding_grids"), ("待機", "waiting_grids"), ("判定不能", "unknown_grids")):
        metrics[field] = sum(t["action"] == action for t in grids)
    equal(book["grid_metrics"], metrics, "95 grid計数全体")


def verify_grid_prefix(session: dict, clocks: list) -> None:
    """
    機能: 開始を含み終了未満の5分予定列から、飛越し/重複/過剰のない連続prefixを検査する。
    引数: session(dict)は場時計、clocks(list)は観測されたgrid時計列。
    返り値: None。EOFまでの最終取り落としは原板を読む別境界監査へ分担する。
    """
    expected = list(range(int(session["start"]), int(session["end"]), 300))
    need(0 < len(clocks) <= len(expected), "正式grid prefixの開始/最大長")
    equal(clocks, expected[:len(clocks)], "正式gridの開始からの連続prefix")


def verify_grid_columns(value: dict) -> None:
    """
    機能: 同じReplayの12Actorが同じ観測grid時計列を受け取ったことを検査する。
    引数: value(dict)はbooksを持つ保存Replay。
    返り値: None。Actor別のEOF解釈や列の食い違いを拒否する。
    """
    equal(set(value["books"]), set(KEYS), "95全12Actorの時計列")
    reference = [t["at"] for t in value["books"][KEYS[0]]["grid_traces"]]
    for key in KEYS:
        equal([t["at"] for t in value["books"][key]["grid_traces"]], reference, "同Replay全12Actorのgrid時計列:" + key)


def verify_book(book: dict, key: str, full_clock: bool = False) -> dict:
    """
    機能: 固定94の会計/MTMを変更せず再用し、95の実受付だけを別規範に結ぶ。
    引数: book(dict)はGo型正本、key(str)は95口座、full_clock(bool)は正式prefix検査。
    返り値: dictは独立検算。金融/sourceイベントの改時刻は行わない。
    """
    timing, old_key, cost, delay = key_config(key)
    equal(book["key"], key, "95 key")
    equal(set(book["config"]), {"policy", "slip_pts", "delay_seconds", "entry_timing", "us_open"}, "95 config集合")
    equal(book["config"]["entry_timing"], timing, "95 timing")
    need(number(book["config"]["us_open"], "USOpen") >= 0, "USOpen負")
    proxy = project94(book)
    def source_validator(projected, orders, timeline):
        """
        機能: Nは旧94出生検査、B系は95保存受付規範を使う。
        引数: projected/ orders(dict)、timeline(Timeline)は固定94検算の引数。
        返り値: None。
        """
        if timing == "N": BASE.verify_source_events(projected, orders, timeline)
        else: verify_source_b(book, orders, timeline)
    # 固定moduleのglobalを変更せず、関数の名前空間だけ独立複写する。
    namespace = dict(vars(BASE)); namespace["verify_source_events"] = source_validator
    verifier = types.FunctionType(BASE.verify_book.__code__, namespace, "固定94会計と95受付の結合")
    checked = verifier(proxy, old_key)
    verify_grid(book, checked["orders"], checked["timeline"], full_clock)
    return checked


class Baseline94:
    """固定完了証拠へ結んだ旧94保存値だけをNの全金融本文対照にする。"""

    def __init__(self, folder: Path, proof_path: Path):
        """
        機能: 旧94完了SHAと自己除外指紋を確認する。
        引数: folder(Path)は旧成果物、proof_path(Path)は旧完了記録。
        返り値: None。
        """
        self.folder, self.proof_path = folder.resolve(), proof_path.resolve()
        equal(hashlib.sha256(self.proof_path.read_bytes()).hexdigest(), BASELINE_SHA, "固定94完了SHA")
        self.files = {k.replace("\\", "/"): v for k, v in read_json(self.proof_path)["自己を除く正式指紋"].items()}

    def compare(self, value: dict) -> dict:
        """
        機能: 同場の旧94 P0四口座と、指定5field以外を完全比較する。
        引数: value(dict)は新95保存値。
        返り値: dictは旧圧縮保存SHAと全本文一致の小型記録。
        """
        path = self.folder / (value["session"] + ".json.gz")
        body = path.read_bytes(); digest = hashlib.sha256(body).hexdigest()
        equal(digest, self.files["成果物/" + path.name], "固定94圧縮NativeSHA")
        old = json.loads(gzip.decompress(body), parse_float=Decimal)
        equal(old["session"], value["session"], "基準場")
        for key in N_TARGET:
            equal(project94(value["books"][key]), old["books"][key], "N対94全金融本文:" + key)
        return {"session": value["session"], "基準保存SHA256": digest, "基準完了SHA256": BASELINE_SHA,
                "一致口座": list(N_TARGET), "除外": ["config.entry_timing", "config.us_open", *NEW_TOP]}


def analyze_saved(values: list[dict], baseline: Baseline94, scope: str) -> dict:
    """
    機能: N4固定対照と全12保存会計/gridを集計し、実現額の比較を作る。
    引数: values(list[dict])は保存値、baseline(Baseline94)は固定旧対照、scope(str)は正式又は接続。
    返り値: dictは検算済みの小型集計。新市場/金融/原板は再生しない。
    """
    need(scope in ("正式", "接続"), "95集計scope")
    equal(len(values), 54 if scope == "正式" else 2, "95場数")
    groups = {key: defaultdict(Decimal) for key in KEYS}
    rows, matches, comparisons, sessions = [], [], defaultdict(list), set()
    for value in values:
        session = value["session"]; need(session not in sessions, "95場重複"); sessions.add(session)
        equal(set(value["books"]), set(KEYS), "95全12Actor")
        verify_grid_columns(value)
        need(value["shadow_match"]["all"] is True and value["shadow_match"]["baseline_proof_sha256"] ==
             "e811571a876f3fdc2f5ba7c09b3906c84db9e380ef89c24b920e5c3f199a2a37", "固定93Shadow証拠")
        methods = {"D164_15"} if session.endswith("_Day") else {"P164_06", "U165_03"}
        equal(set(value["shadows"]), methods, "Source手法集合")
        equal(value["shadow_match"]["methods"], {m: True for m in methods}, "全Shadow一致")
        matches.append(baseline.compare(value))
        checked = {}
        for key in KEYS:
            book = value["books"][key]
            current = checked[key] = verify_book(book, key, full_clock=True)
            timing = key_config(key)[0]
            rows.append({"session": session, "key": key, "entry_timing": timing, "totals": current["totals"],
                         "counts": current["counts"], "grid_metrics": book["grid_metrics"],
                         "account_max_drawdown_yen": current["account_max_drawdown_yen"]})
            group = groups[key]
            for name, amount in current["totals"].items(): group[name] += amount
            for name, amount in current["counts"].items(): group[name] += amount
            for name, amount in book["grid_metrics"].items(): group["grid_" + name] += amount
            group["active_sessions"] += current["counts"]["positions"] > 0
            group["negative_sessions"] += current["totals"]["net_yen"] < 0
            group["max_session_mtm_drawdown_yen"] = max(group["max_session_mtm_drawdown_yen"], current["account_max_drawdown_yen"])
        for cost in (0, 5):
            for delay in (0, 1):
                old = f"P0_C{cost}_D{delay}"
                for a, b in ((old, "B5_" + old), (old, "B5Q_" + old), ("B5_" + old, "B5Q_" + old)):
                    name = b + "対" + a
                    comparisons[name].append({"session": session, **BASE.compare_positions(checked[a], checked[b])})
    if scope == "正式":
        for key, expected in N_TARGET.items(): equal(groups[key]["net_yen"], expected, "N4固定純額:" + key)
    return {"試行": 95, "成功": True, "scope": scope, "場数": len(values), "Actor数": 12, "会計数": len(rows),
            "Actor設定": {key: {"entry_timing": key_config(key)[0], "key": key, "policy": "P0", "slip_pts": key_config(key)[2], "delay_seconds": key_config(key)[3]} for key in KEYS},
            "集計": {key: dict(row) for key, row in groups.items()}, "場別": rows, "同実入口と実現額差": dict(comparisons),
            "N4基準照合": matches, "N4固定純額円": N_TARGET, "固定54場金額照合実施": scope == "正式",
            "由来94集計SHA256": BASE_SHA, "基準94完了SHA256": BASELINE_SHA,
            "検算範囲": "94会計/MTM/費用を再用し、95出生0受付とOpportunity/grid受理/Source取得残・予約/cap/注文IDを独立結合。開始からの連続grid prefixと同Replay全12列を検査。EOFまでの最終取り落とし/全原行の最新出典は別境界監査。",
            "元段階と実参加": "Source.kindは元の段階。実取得は新規Fill/Positionで別記。親で最初の実取得の追加診断には明示parentと取得順の結合が必要。",
            "評価": "各Actorの実現粗額/fee/slip/net・u/W赤字/件数/DD。未参加/決済後の仮想利益や機会損失を評価しない。C5/遅延は別運転。",
            "未実施": {"新金融再生": 0, "原板本文読取": 0, "ViewerAPI": 0, "資本金ROI": None}}


def viewer_trades(book: dict) -> list[dict]:
    """
    機能: 固定94の約定片/費用出力を、95の実Actor名のまま再用する。
    引数: book(dict)は95実正本。
    返り値: list[dict]は所有IDと半円を保持したViewer標準行。
    """
    return BASE.viewer_trades(book)


def render(result: dict) -> str:
    """
    機能: 12口座の実現会計とgrid分母を最小Markdownへ出す。
    引数: result(dict)は検算済み結果。
    返り値: strは閲覧資料。
    """
    lines = ["# 95：5分判断と開始30分見送り・保存会計", "",
             f"{result['場数']}場/{result['会計数']}会計、scope={result['scope']}。共通P0、主C0と動的感度C5を分離。", "",
             "| Timing/key | 実玉/枚 | gross円 | 指定fee円 | 仮定slip円 | net円 | u正益後最終赤字/正益玉 | 全grid/新規/保有/待機/未知 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        r = result["集計"][key]
        lines.append(f"| {key_config(key)[0]}/{key} | {r['positions']}/{r['entry_quantity']} | {r['gross_yen']} | {r['fee_yen']} | {r['slip_yen']} | {r['net_yen']} | {r['unit_positive_closed_negative']}/{r['unit_positive_positions']} | {r['grid_grid_calls']}/{r['grid_new_grids']}/{r['grid_holding_grids']}/{r['grid_waiting_grids']}/{r['grid_unknown_grids']} |")
    lines += ["", "Nは指定5fieldを除き固定94 P0全金融本文へ一致。B系は出生Sourceイベントをそのまま保存し、実受付だけをOpportunity/gridへ分離する。",
              "", "Source部分返済は実未予約量へceil・源全残は未予約全量。u/Wと正益の分母を混ぜず、DDの全経路取り落としは別原板監査へ分担。",
              "", "各Actorの実現額を比較し、未参加/決済後の仮想利益・機会損失は評価しない。Shadow全手法の生成・mini実板執行の証明とは区別する。", ""]
    return "\n".join(lines)


def main() -> None:
    """
    機能: 完了指紋付き保存JSONだけを独立検算し、新規成果物を作る。
    引数: --run/--out(Path)、--limit(int、既定54/接続2)、--baseline/--baseline-proof(Path)は固定94参照。
    返り値: None。不整合は非0。既存出力を上書きしない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, choices=(2, 54), default=54)
    parser.add_argument("--baseline", type=Path, default=BASELINE_DIR); parser.add_argument("--baseline-proof", type=Path, default=BASELINE_PROOF)
    args = parser.parse_args(); need(not args.out.exists(), "新規出力先だけ")
    completion_path = args.run / "完了.json"; completion = read_json(completion_path)
    equal(completion["場数"], args.limit, "完了場数"); equal(len(completion["結果SHA256"]), args.limit, "保存数")
    code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    completion_sha = hashlib.sha256(completion_path.read_bytes()).hexdigest()
    values, bodies, before = [], [], {}
    for name, expected in sorted(completion["結果SHA256"].items()):
        path = (args.run / name).resolve(); need(path.is_relative_to(args.run.resolve()) and path.suffix == ".json", "入力path境界")
        body = path.read_bytes(); equal(hashlib.sha256(body).hexdigest(), expected, "保存SHA")
        values.append(json.loads(body, parse_float=Decimal)); bodies.append((name, body)); before[name] = expected
    baseline = Baseline94(args.baseline, args.baseline_proof)
    result = analyze_saved(values, baseline, "正式" if args.limit == 54 else "接続")
    result.update(入力SHA256=before, 完了記録SHA256=completion_sha, 集計コードSHA256=code_sha)
    args.out.mkdir(parents=True); resources = []
    for value, (name, body) in zip(values, bodies):
        for key in KEYS:
            timing = key_config(key)[0]; identity = "95_" + key + "_" + value["session"]; trade_path = identity + ".trades.jsonl"
            with (args.out / trade_path).open("x", encoding="utf-8", newline="\n") as stream:
                for row in viewer_trades(value["books"][key]): stream.write(json.dumps(row, ensure_ascii=False, default=serial, allow_nan=False) + "\n")
            resources.append({"id": identity, "title": "出生一回 " + timing + "/" + key + " " + value["session"],
                "symbol": "NK225", "product": "NK225mini", "session": value["session"], "method_id": key, "point_value": 100,
                "pnl_format": "trades", "pnl_basis": "net", "pnl_path": trade_path, "market_path": "NK225/" + value["session"] + "/book.jsonl.gz"})
        with (args.out / (Path(name).name + ".gz")).open("xb") as file:
            with gzip.GzipFile(filename="", mode="wb", fileobj=file, mtime=0) as stream: stream.write(body)
    equal(len(resources), args.limit * 12, "Viewer資源数")
    after = {name: hashlib.sha256((args.run / name).read_bytes()).hexdigest() for name in before}
    equal(after, before, "入力前後不変"); equal(hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), code_sha, "コード前後不変")
    equal(hashlib.sha256(BASE_PATH.read_bytes()).hexdigest(), BASE_SHA, "由来94前後不変")
    equal(hashlib.sha256(completion_path.read_bytes()).hexdigest(), completion_sha, "完了記録前後不変")
    equal(hashlib.sha256(args.baseline_proof.read_bytes()).hexdigest(), BASELINE_SHA, "旧94完了前後不変")
    result.update(入力SHA256前=before, 入力SHA256後=after, 入力前後不変=True)
    write_json(args.out / "結果.json", result)
    write_json(args.out / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    (args.out / "結果.md").write_text(render(result), encoding="utf-8", newline="\n")
    print(json.dumps({"成功": True, "scope": result["scope"], "場数": args.limit, "会計数": args.limit * 12,
                      "閲覧資源": len(resources), "N4固定純額照合": result["固定54場金額照合実施"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
