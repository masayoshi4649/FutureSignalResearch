"""
120のSHA指定3JSONだけを読み、保存証拠と全閲覧表を独立再計算する。

自然Raw・入力台帳・Native・CSVは開かない。条件の変更や市場実行は行わない。
最初の約定行・到達行だったこと、保存指標の自然Rawからの再形成は再証明しない。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
from typing import Any

POLICIES = ["P1", "P1plus", "P2", "P2plus", "P3", "P3plus"]
HORIZONS = [1800, 3600]
WIDTHS = [25, 50, 100, 125, 200]
JST = timezone(timedelta(hours=9))
COUNTS: Counter = Counter()


# ----------------------------------------
def need(ok: bool, message: str) -> None:
    """
    機能: 不成立の検算条件で中止する。
    引数: ok(bool)は判定、message(str)は理由。
    返り値: None。不成立時はValueErrorを送出する。
    """
    if not ok:
        raise ValueError(message)


# ----------------------------------------
def digest(data: bytes) -> str:
    """
    機能: バイト列のSHA256を求める。
    引数: data(bytes)。返り値: str型の小文字SHA256。
    """
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------
def compare(saved: Any, expected: Any, where: str) -> None:
    """
    機能: 全構造を照合し、平均・率は厳密分数の1回丸めと比較する。
    引数: saved/expected(Any)、where(str)。返り値: None。
    """
    if isinstance(expected, dict):
        need(isinstance(saved, dict) and saved.keys() == expected.keys(), f"{where}: キー差")
        for key, value in expected.items():
            compare(saved[key], value, f"{where}/{key}")
    elif isinstance(expected, list):
        need(isinstance(saved, list) and len(saved) == len(expected), f"{where}: 配列長差")
        for i, value in enumerate(expected):
            compare(saved[i], value, f"{where}/{i}")
    elif isinstance(expected, Fraction):
        need(saved is not None and Decimal(saved) == Decimal(str(float(expected))), f"{where}: 厳密分数の丸め差 {saved} != {expected}")
        COUNTS["平均率中央値"] += 1
    elif isinstance(expected, float):
        need(saved is not None and Decimal(saved) == Decimal(str(expected)), f"{where}: 参考区間の浮動小数差")
        COUNTS["参考区間"] += 1
    else:
        need(saved == expected, f"{where}: 値差 {saved!r} != {expected!r}")
        COUNTS["厳密照合"] += 1


# ----------------------------------------
def bounds(session: str) -> tuple[int, int]:
    """
    機能: 場名から日中・夜間の所定境界を求める。
    引数: session(str)。返り値: tuple[int,int]型のUnix秒。
    """
    date, kind = session.rsplit("_", 1)
    need(date != "2026-11-09" and kind in ("Day", "Night"), "対象場外")
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=JST)
    start = day + (timedelta(hours=8, minutes=45) if kind == "Day" else timedelta(hours=17))
    end = day + (timedelta(hours=15, minutes=45) if kind == "Day" else timedelta(days=1, hours=6))
    return int(start.timestamp()), int(end.timestamp())


# ----------------------------------------
def quote(q: dict, scene: dict, normal: bool = False) -> None:
    """
    機能: 保存気配の場内境界・順序範囲・必要時の正常BBOを確認する。
    引数: q/scene(dict)、normal(bool)。返り値: None。
    """
    begin, end = bounds(scene["session"])
    need(begin <= q["time"] <= end, "気配時計の場外")
    need(0 <= q["index"] < scene["quality"]["source_delivered"], "気配Index範囲外")
    need(q["index"] + 1 <= q["source_line"] <= scene["quality"]["lines"], "物理行範囲外")
    need(Decimal(q["last"]).is_finite() and q["last"] > 0, "Last不正")
    if "clock" in q:
        need(Decimal(str(datetime.fromisoformat(q["clock"]).timestamp())) == q["time"], "Clock文字列とUnix秒差")
    if normal:
        need(q["quote_ok"] is True and 0 < q["bid"] < q["ask"], "正常BBOでない")
    COUNTS["保存気配"] += 1


# ----------------------------------------
def slim(q: dict) -> dict:
    """
    機能: BBO付き気配を技術票の4項目へ射影する。
    引数: q(dict)。返り値: dict型の時刻・Index・物理行・Last。
    """
    return {key: q[key] for key in ("time", "index", "source_line", "last")}


# ----------------------------------------
def later(q: dict, old: dict, seconds: int = 0) -> bool:
    """
    機能: 原行・物理行が後で、時計が指定秒以上後かを判定する。
    引数: q/old(dict)、seconds(int)。返り値: bool。
    """
    return q["index"] > old["index"] and q["source_line"] > old["source_line"] and q["time"] >= old["time"] + seconds


# ----------------------------------------
def field_mark(q: dict, side: int, entering: bool) -> Any:
    """
    機能: 新規又は返済に使う反対気配を選ぶ。
    引数: q(dict)、side(int)、entering(bool)。返り値: 数値型のBid又はAsk。
    """
    return q["ask"] if (side == 1) == entering else q["bid"]


# ----------------------------------------
def events_check(scene: dict) -> dict[str, int]:
    """
    機能: 全1分イベント、当時参照、構造・共通ゲートと検出器診断件数を検査する。
    引数: scene(dict)。返り値: dict型のイベントIDとIndex対応。
    """
    events, prior, cooldown = {}, None, {}
    contract = scene["events"][0]["scope"]["contract"] if scene["events"] else None
    gate_births = Counter()
    for i, e in enumerate(scene["events"]):
        need(e["id"] not in events and e["policy"] in POLICIES and e["side"] in (-1, 1), "イベントID/政策/方向差")
        need(e["scope"] == {"session_id": scene["session"], "contract": contract} and bool(contract), "イベントScope差")
        at, b, side = e["at"], e["bar"], e["side"]
        quote(at, scene)
        if prior:
            need(at["time"] >= prior["time"] and at["index"] >= prior["index"] and at["source_line"] >= prior["source_line"], "イベント順序逆転")
        prior = at
        need(b["end"] == b["start"] + 60 and b["end"] <= at["time"] <= b["end"] + 30 and b["rows"] > 0, "1分閉鎖時計又は行数差")
        first, last, ohlc = b["first"], b["last"], b["ohlc"]
        quote(first, scene)
        quote(last, scene)
        need(b["start"] <= first["time"] <= last["time"] < b["end"] and first["index"] <= last["index"] < at["index"] and last["source_line"] < at["source_line"], "1分の形成範囲又は因果順序差")
        need(ohlc["open"] == first["last"] and ohlc["close"] == last["last"] and 0 < ohlc["low"] < ohlc["high"] and ohlc["low"] <= ohlc["open"] <= ohlc["high"] and ohlc["low"] <= ohlc["close"] <= ohlc["high"], "1分OHLC差")
        need(len(e["refs"]) in (3, 4), "公表参照数差")
        for j, ref in enumerate(e["refs"]):
            delivery = ref["delivered"]
            need(ref["width_seconds"] in (300, 900, 1800) and ref["end"] <= delivery["time"] <= at["time"] and delivery["index"] <= at["index"] and delivery["source_line"] <= at["source_line"], "未来の公表参照")
            if j < 3:
                need(ref["width_seconds"] == (300, 900, 1800)[j] and at["time"] < ref["end"] + ref["width_seconds"] + 60, "当場主参照の鮮度又は順序差")
            else:
                need(e["policy"].startswith("P3") and ref["width_seconds"] == 900 and ref["end"] < e["refs"][1]["end"], "過去BB参照差")
            COUNTS["公表参照"] += 1
        f = e["fields"]
        need(all(isinstance(v["known"], bool) and Decimal(v["value"]).is_finite() for v in f.values()), "技法値型又は有限性差")
        for key in ("atr5", "atr1_before14", "min1_tr", "min1_range", "min1_close_position", "min1_body_signed", "maximum_risk", "risk_at_last", "hold_boundary", "hold_minimum", "hold_strict", "hold_gap_at_birth"):
            need(f[key]["known"], "必須技法が未知")
        atr5, atr1 = f["atr5"]["value"], f["atr1_before14"]["value"]
        need(atr5 > 0 and atr1 > 0 and b["tr"]["known"] and b["tr"]["value"] == f["min1_tr"]["value"] <= 2 * atr1 and b["tr"]["value"] >= ohlc["high"] - ohlc["low"], "ATR/TR又はスパイクゲート差")
        maximum = Decimal(str(min(100, .5 * float(atr5))))
        extreme = ohlc["low"] if side == 1 else ohlc["high"]
        need(e["invalidation"] == extreme - side * 5 and f["maximum_risk"]["value"] == maximum, "否定境界又は最大リスク差")
        risk = side * (at["last"] - e["invalidation"])
        need(f["risk_at_last"]["value"] == risk and 0 < risk <= maximum, "出生時リスクゲート差")
        cap = Decimal(str(float(ohlc["close"]) + side * min(10, .15 * float(atr5))))
        need(e["entry_cap"] == cap and side * (at["last"] - cap) <= 0, "出生時capゲート差")
        location = (float(ohlc["close"]) - float(ohlc["low"])) / float(ohlc["high"] - ohlc["low"]) if side == 1 else (float(ohlc["high"]) - float(ohlc["close"])) / float(ohlc["high"] - ohlc["low"])
        need(f["min1_close_position"]["value"] == Decimal(str(location)) and location >= .7 and f["min1_body_signed"]["value"] == side * (ohlc["close"] - ohlc["open"]) > 0, "1分実体・終値位置ゲート差")
        hold, minimum, strict = [f[k]["value"] for k in ("hold_boundary", "hold_minimum", "hold_strict")]
        need(strict in (0, 1) and minimum == (5 if e["policy"].startswith("P2") else 0) and strict == (0 if e["policy"].startswith("P2") else 1), "構造維持条件差")
        gap = side * (at["last"] - hold)
        need(gap == f["hold_gap_at_birth"]["value"] and (gap > 0 if strict else gap >= minimum), "出生時構造維持差")
        key = e["policy"] + "/" + str(side)
        need(key not in cooldown or at["time"] - cooldown[key] >= 300, "政策別5分クールダウン差")
        cooldown[key] = at["time"]
        gate_births[key] += 1
        events[e["id"]] = i
        COUNTS["イベント"] += 1
    stats = scene["detector_stats"]
    need(stats["raw_rows"] == scene["quality"]["source_delivered"] and stats["births"] == len(events), "検出器Raw又は出生件数差")
    need(sum(v["births"] for v in stats["policies"].values()) == len(events), "政策別出生件数差")
    considered = set()
    for key, item in stats["policies"].items():
        need(item["births"] == gate_births[key] and item["all_gates_pass"] == item["births"] + item["cooldown_rejected"], "全gate/クールダウン/出生算術差")
        need(all(0 <= item[k] <= item["considered"] for k in ("shape_pass", "risk_pass", "cap_pass", "hold_pass", "background_pass", "structure_pass", "extra_pass", "all_gates_pass", "cooldown_rejected", "births")), "独立gate件数範囲差")
        considered.add(item["considered"])
    need(len(considered) <= 1, "政策ごとの共通Considered差")
    allowed = next(iter(considered), 0)
    failures = sum(stats[k] for k in ("publication_missing", "atr1_unavailable", "atr5_unavailable", "current_tr_unavailable", "spike_rejected", "range_rejected"))
    need(stats["eligible_closures"] == failures + allowed, "共通品質ゲート分解差")
    COUNTS["検出器診断場数"] += 1
    return events


# ----------------------------------------
def candidate_check(c: dict, scene: dict, events: dict) -> None:
    """
    機能: 1分構造候補の当時参照・要求・初回評価・取得capとリスクを確認する。
    引数: c/scene/events(dict)。返り値: None。
    """
    event = scene["events"][c["event"]]
    birth, side = c["birth"], c["birth"]["side"]
    need(c["policy"] in POLICIES and c["policy"] == event["policy"] and birth["id"] == event["id"] and side == event["side"], "候補とイベント差")
    need(events[event["id"]] == c["event"] and slim(birth["quote"]) == event["at"] and all(birth[k] == event["at"][k] for k in ("time", "index", "source_line")), "出生の原行差")
    quote(birth["quote"], scene)
    for key in ("entry_cap", "invalidation"):
        need(c[key] == event[key], "執行条件とイベント差")
    need(c["limit"] is None and c["atr5"] == event["fields"]["atr5"]["value"] and c["maximum_risk"] == Decimal(str(min(100, .5 * float(c["atr5"])))), "指値又は最大リスク差")
    need(c["hold_boundary"] == event["fields"]["hold_boundary"]["value"] and c["hold_minimum"] == event["fields"]["hold_minimum"]["value"] and c["hold_strict"] == (event["fields"]["hold_strict"]["value"] == 1), "構造維持条件の保存差")
    request, entry, evaluation = c["request"], c["entry"], c["evaluation"]
    need(c["expires"] <= birth["time"] + 30, "30秒を超えた新規期限")
    if c["expires"] <= birth["time"]:
        need(request is None and c["status"] == "force_close", "新規不可出生に要求")
        COUNTS["新規不可候補"] += 1
    else:
        need(request == birth["quote"], "パターン成立原行が要求でない")
    if evaluation:
        quote(evaluation, scene, True)
        need(request is not None and later(evaluation, request, 1) and evaluation["time"] < c["expires"], "初回評価の後原行1秒又は期限差")
        price = field_mark(evaluation, side, True)
        risk = side * (price - event["invalidation"])
        need(risk == c["risk_at_decision"], "保存評価リスク差")
        cap_bad = side * (price - event["entry_cap"]) > 0
        hold_gap = side * (evaluation["last"] - c["hold_boundary"])
        hold_bad = hold_gap <= 0 if c["hold_strict"] else hold_gap < c["hold_minimum"]
        risk_bad = risk <= 0 or risk > c["maximum_risk"]
        if cap_bad:
            need(c["status"] == "entry_cap_rejected" and entry is None, "cap拒否で取得又は優先順位差")
            COUNTS["cap即取消"] += 1
        elif hold_bad:
            need(c["status"] == "structure_lost" and entry is None, "構造維持崩壊で取得又は優先順位差")
            COUNTS["hold即取消"] += 1
        elif risk_bad:
            need(c["status"] == "risk_rejected" and entry is None, "リスク拒否で取得")
            COUNTS["risk即取消"] += 1
        else:
            need(c["status"] == "filled" and entry == evaluation and c["entry_price"] == price, "適格初回評価で取得しない")
    else:
        need(entry is None and c["risk_at_decision"] is None and c["status"] in ("force_close", "unfilled_expired", "eof_unfilled"), "評価証拠なしの取得又は拒否")
    need((c["status"] == "filled") == (entry is not None), "状態と取得証拠差")
    if entry is None:
        need(c["entry_price"] is None and c["outcomes"] == [], "未約定に期限損益")
        COUNTS["未約定nil"] += 1
        return
    quote(entry, scene, True)
    need([o["seconds"] for o in c["outcomes"]] == HORIZONS, "30/60期限差")
    for o in c["outcomes"]:
        need(o["deadline"] == entry["time"] + o["seconds"], "期限算術差")
        need([t["width"] for t in o["touches"]] == WIDTHS, "同幅先着の幅差")
        if o["status"] == "complete":
            end = o["endpoint"]
            quote(end, scene, True)
            need(later(end, entry) and o["deadline"] <= end["time"] <= o["deadline"] + 30, "期限評価原行又は30秒猶予差")
            gain = side * (field_mark(end, side, False) - c["entry_price"])
            need((o["points"], o["net0"], o["net5"]) == (gain, gain * 100 - 77, gain * 100 - 1077), "期限損益・費用差")
            COUNTS["完了期限算術"] += 1
        else:
            need(o["status"] in ("endpoint_missing", "eof_censored", "gap_censored", "bbo_gap_censored", "session_censored"), "観測状態不明")
            need(all(o[k] is None for k in ("endpoint", "points", "net0", "net5")), "打切り純額の補完")
            COUNTS["打切りnil"] += 1
        prior = None
        no_hit = False
        for t in o["touches"]:
            hit, direction = t["quote"], t["direction"]
            need(direction in (-1, 0, 1) and (hit is None) == (direction == 0), "方向と到達証拠差")
            if hit:
                quote(hit, scene, True)
                need(not no_hit and later(hit, entry) and hit["time"] <= o["deadline"], "小幅未到達又は取得・期限外の到達")
                need(direction * side * (field_mark(hit, side, False) - c["entry_price"]) >= t["width"], "同幅到達の幾何差")
                if prior:
                    need(hit["index"] >= prior["index"] and hit["source_line"] >= prior["source_line"] and hit["time"] >= prior["time"], "大幅先着が小幅より前")
                if o["endpoint"]:
                    need(hit["index"] <= o["endpoint"]["index"] and hit["source_line"] <= o["endpoint"]["source_line"], "評価後原行の混入")
                prior = hit
                COUNTS["先着幾何"] += 1
            else:
                no_hit = True
    short, long = c["outcomes"]
    for a, b in zip(short["touches"], long["touches"]):
        if a["direction"]:
            need(a == b, "30分先着と60分の差")
        elif b["direction"] and short["status"] == "complete" and b["quote"]["time"] <= short["deadline"]:
            need(b["quote"]["time"] == short["endpoint"]["time"] == short["deadline"] and later(b["quote"], short["endpoint"]), "短期未到達と長期先着の矛盾")
            COUNTS["期限同秒後行"] += 1
    COUNTS["取得証拠"] += 1


# ----------------------------------------
def average(values: list) -> Fraction | None:
    """
    機能: 数値列の平均を厳密分数で求める。
    引数: values(list)。返り値: Fraction|None。
    """
    return sum(map(Fraction, values), Fraction()) / len(values) if values else None


# ----------------------------------------
def middle(values: list) -> Fraction | None:
    """
    機能: 中央値を厳密分数で求める。
    引数: values(list)。返り値: Fraction|None。
    """
    if not values:
        return None
    ordered = sorted(map(Fraction, values))
    i = len(ordered) // 2
    return ordered[i] if len(ordered) % 2 else (ordered[i - 1] + ordered[i]) / 2


# ----------------------------------------
def summary(rows: list, policy: str, seconds: int, baselines: dict) -> dict:
    """
    機能: 件数・先着率・金額・同分構造基本入口対照を独立集計する。
    引数: rows(list)、policy(str)、seconds(int)、baselines(dict)。返り値: dict。
    """
    cases = [c for c in rows if c["policy"] == policy]
    entered = [c for c in cases if c["entry"]]
    observed = [(c, next(o for o in c["outcomes"] if o["seconds"] == seconds)) for c in entered]
    done = [(c, o) for c, o in observed if o["status"] == "complete"]
    totals = {}
    for width in WIDTHS:
        directions = Counter(next(t["direction"] for t in o["touches"] if t["width"] == width) for _, o in done)
        win, loss, neither = directions[1], directions[-1], directions[0]
        resolved = win + loss
        rate = Fraction(win, resolved) if resolved else None
        all_rate = Fraction(win, len(done)) if done else None
        lower = None
        if resolved:
            r = float(rate)
            z = 1.959963984540054
            lower = (r + z ** 2 / (2 * resolved) - z * math.sqrt(r * (1 - r) / resolved + z ** 2 / (4 * resolved ** 2))) / (1 + z ** 2 / resolved)
        totals[str(width)] = {"favorable": win, "adverse": loss, "neither": neither, "resolved": resolved, "resolved_rate": rate, "all_complete_favorable_rate": all_rate, "reference_binomial_lower95": lower, "target70_resolved": rate >= Fraction(7, 10) if rate is not None else None, "target70_all_complete": all_rate >= Fraction(7, 10) if all_rate is not None else None}
    pairs = []
    for c, o in done:
        base = baselines.get((c["session"], c["family"], c["bar_end"], c["birth"]["side"]))
        if base is None:
            continue
        original = next((x for x in base["outcomes"] if x["seconds"] == seconds and x["status"] == "complete"), None)
        if original:
            pairs.append((original["net5"], o["net5"], c["birth"]["side"] * (base["entry_price"] - c["entry_price"])))
    n0, n5 = [o["net0"] for _, o in done], [o["net5"] for _, o in done]
    return {"births": len(cases), "eligible_births": sum(c["expires"] > c["birth"]["time"] for c in cases), "requested": sum(c["request"] is not None for c in cases), "filled": len(entered), "complete": len(done), "censored": len(entered) - len(done), "filled_sessions": len({c["session"] for c in entered}), "complete_sessions": len({c["session"] for c, _ in done}), "states": dict(Counter(c["status"] for c in cases)), "observations": dict(Counter(o["status"] for _, o in observed)), "touches": totals, "mean_net0": average(n0), "mean_net5": average(n5), "median_net5": middle(n5), "positive_net5": sum(n > 0 for n in n5), "negative_net5": sum(n < 0 for n in n5), "pairs": len(pairs), "paired_base_mean_net5": average([p[0] for p in pairs]), "paired_candidate_mean_net5": average([p[1] for p in pairs]), "paired_mean_delta": average([p[1] - p[0] for p in pairs]), "paired_mean_price_improvement": average([p[2] for p in pairs])}


# ----------------------------------------
def as_jst(stamp: Any) -> str | None:
    """
    機能: 保存Unix秒を閲覧表と同じ秒単位JSTへ変換する。
    引数: stamp(数値|None)。返り値: str|None。
    """
    return datetime.fromtimestamp(float(stamp), JST).strftime("%Y-%m-%d %H:%M:%S") if stamp is not None else None


# ----------------------------------------
def label(o: dict | None, width: int) -> str:
    """
    機能: 観測状態と到達方向を日本語ラベルへ変換する。
    引数: o(dict|None)、width(int)。返り値: str。
    """
    if not o:
        return "対象外（未約定）"
    d = next(t["direction"] for t in o["touches"] if t["width"] == width)
    if o["status"] != "complete":
        return {1: "打切前順行", -1: "打切前逆行", 0: "観測不足"}[d]
    return {1: "順行先着", -1: "逆行先着", 0: "両方未到達"}[d]


# ----------------------------------------
def tables_check(tables: dict, rows: list, rebuilt: dict, groups: dict, names: list) -> None:
    """
    機能: CSV用4表の全行・全セルを独立生成値と比較する。
    引数: tables/rebuilt/groups(dict)、rows/names(list)。返り値: None。
    """
    expected = [[], [], [], []]
    for policy in POLICIES:
        for h in HORIZONS:
            s = rebuilt[policy][str(h)]
            expected[0].append([120, policy, h // 60, s["births"], s["eligible_births"], s["requested"], s["filled"], s["complete"], s["censored"], s["complete_sessions"], s["mean_net0"], s["mean_net5"], s["median_net5"], s["positive_net5"], s["negative_net5"], s["pairs"], s["paired_base_mean_net5"], s["paired_candidate_mean_net5"], s["paired_mean_delta"], s["paired_mean_price_improvement"]])
            for w in WIDTHS:
                t = s["touches"][str(w)]
                labels = ["評価不能" if t[k] is None else "到達" if t[k] else "未達" for k in ("target70_resolved", "target70_all_complete")]
                expected[1].append([120, policy, h // 60, w, s["births"], s["filled"], s["complete"], s["censored"], t["favorable"], t["adverse"], t["neither"], t["resolved_rate"], t["all_complete_favorable_rate"], t["reference_binomial_lower95"], *labels])
    for c in rows:
        for h in HORIZONS:
            o = next((v for v in c["outcomes"] if v["seconds"] == h), None)
            expected[2].append([120, c["session"], c["history"], c["mode"], c["birth"]["id"], "買" if c["birth"]["side"] == 1 else "売", c["role"], c["policy"], h // 60, c["status"], as_jst(c["birth"]["time"]), as_jst(c["request"]["time"]) if c["request"] else None, c["limit"], as_jst(c["entry"]["time"]) if c["entry"] else None, c["entry_price"], o["status"] if o else "not_entered", as_jst(o["deadline"]) if o else None, as_jst(o["endpoint"]["time"]) if o and o["endpoint"] else None, o["points"] if o else None, o["net0"] if o else None, o["net5"] if o else None, *[label(o, w) for w in WIDTHS]])
    for name in names:
        for policy in POLICIES:
            for h in HORIZONS:
                s = groups["session"][name][policy][str(h)]
                t = s["touches"]["100"]
                expected[3].append([120, name, policy, h // 60, s["births"], s["filled"], s["complete"], s["censored"], t["favorable"], t["adverse"], t["neither"], t["resolved_rate"], s["mean_net5"]])
    header_sets = [
        ['試行','候補','評価時間分','全出生','出生時新規可能数','要求数','約定代用数','評価完了数','観測不足数','評価完了場数','C0期限評価平均円','C5期限評価平均円','C5期限評価中央値円','C5正評価数','C5負評価数','同出生対照完了組数','同組基本入口C5平均円','同組候補C5平均円','同組C5平均差円','同組取得価格平均改善pt'],
        ['試行','候補','評価時間分','同幅pt','全出生','約定代用数','評価完了数','観測不足数','順行先着','逆行先着','両方未到達','到達済み分母順行率','全評価完了分母順行率','参考二項95下限','到達済み70%','全評価完了70%'],
        ['試行','セッション','期間区分','構造','出生ID','方向','確認段階','候補','評価時間分','新規状態','出生JST','注文要求JST','指値','約定代用JST','新規価格','観測状態','評価期限JST','期限評価原行JST','期限価格差pt','C0期限清算評価円','C5期限清算評価円','25pt先着','50pt先着','100pt先着','125pt先着','200pt先着'],
        ['試行','セッション','候補','評価時間分','全出生','約定代用数','評価完了数','観測不足数','100pt順行先着','100pt逆行先着','100pt未到達','100pt到達済み分母順行率','C5期限評価平均円'],
    ]
    need([t["name"] for t in tables["tables"]] == ["候補別集計", "幅別先着率", "全候補明細", "全70場集計"], "閲覧表名・順序差")
    for table, exp, headers in zip(tables["tables"], expected, header_sets):
        compare(table["headers"], headers, f"{table['name']}/見出し")
        compare(table["rows"], exp, table["name"])
        COUNTS[f"{table['name']}行数"] = len(exp)


# ----------------------------------------
def serial(value: Any) -> Any:
    """
    機能: 検算用分数をJSON保存用へ変換する。
    引数: value(Any)。返り値: Any。
    """
    if isinstance(value, (Fraction, Decimal)):
        return float(value)
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serial(v) for v in value]
    return value


# ----------------------------------------
def main() -> None:
    """
    機能: Root指定SHAの3JSONだけで検算し、未作成の確認JSONへ保存する。
    引数: CLIのresult/aggregate/tables及び各sha(str)、output(str)。返り値: None。
    """
    parser = argparse.ArgumentParser()
    for key in ("result", "aggregate", "tables"):
        parser.add_argument("--" + key, required=True)
        parser.add_argument("--" + key + "-sha", required=True)
    parser.add_argument("--output", required=True)
    args = vars(parser.parse_args())
    output = Path(args["output"]).absolute()
    need(not output.exists(), "確認先は未作成に限定")
    before, values = {}, {}
    for kind in ("result", "aggregate", "tables"):
        path = Path(args[kind]).absolute()
        expected = args[kind + "_sha"]
        need(len(expected) == 64 and all(c in "0123456789abcdef" for c in expected), "SHA指定不正")
        data = path.read_bytes()
        need(digest(data) == expected, kind + " SHA差")
        need(str(path) not in before, "許可ファイル重複")
        before[str(path)] = expected
        values[kind] = json.loads(data, parse_float=Decimal)
    self = Path(__file__).absolute()
    before[str(self)] = digest(self.read_bytes())
    result, saved, tables = values["result"], values["aggregate"], values["tables"]
    need(result["trial"] == 120 and result["success"] and not result["source_signals_used"] and not result["portfolio_pnl"] and result["candidate_quantity"] == 1, "試行又は独立1mini範囲差")
    need(result["input_sha256"] == "574771f654937036b48c78eceadb46a4c5ff3c10265f60b0ec7879efb0d862c3", "再用固定入力SHA差")
    need(result["policies"] == POLICIES and result["horizons"] == HORIZONS and result["widths"] == WIDTHS, "固定比較条件差")
    need(saved["試行"] == tables["試行"] == 120 and saved["成功"] and tables["成功"] and saved["元結果SHA256"] == tables["result_sha256"] == args["result_sha"], "結果・集計・表の結合差")
    need(saved["口座収支"] is False and saved["未約定0円補完"] is False and saved["Source通知使用"] is False, "集計範囲差")
    scenes = result["scenes"]
    names = [s["session"] for s in scenes]
    need(len(names) == 70 and names == sorted(set(names)) and names[53] == "2026-10-27_Night" and names[54] == "2026-10-28_Day" and names[-1] == "2026-11-06_Night", "70場と54/16境界差")
    rows, event_counts = [], Counter()
    unavailable = {p: 0 for p in POLICIES}
    for i, scene in enumerate(scenes):
        need(scene["success"] and not scene["source_signals_used"] and scene["raw_passes"] == 1 and scene["raw"]["sha256"] == scene["actual_sha256"] and scene["stat_before"] == scene["stat_after"], "場証拠又はRaw指紋保存差")
        need(scene["quality"]["source_parser_accepted"] == scene["quality"]["source_delivered"], "採用・配送数差")
        events = events_check(scene)
        event_counts.update(e["policy"] for e in scene["events"])
        need(len(scene["events"]) == len(scene["candidates"]), "イベントと候補数差")
        used = set()
        for c in scene["candidates"]:
            need(c["event"] not in used, "イベントの候補重複")
            used.add(c["event"])
            candidate_check(c, scene, events)
            c["session"] = scene["session"]
            c["history"] = "元54場" if i < 54 else "追加16場"
            c["family"] = c["policy"].removesuffix("plus")
            c["bar_end"] = scene["events"][c["event"]]["bar"]["end"]
            c["mode"] = c["family"]
            c["role"] = "追加確認" if c["policy"].endswith("plus") else "構造背景"
            rows.append(c)
            unavailable[c["policy"]] += c["expires"] <= c["birth"]["time"]
    compare(saved["イベント件数"], dict(event_counts), "イベント件数")
    need(len(rows) == sum(event_counts.values()), "候補数差")
    need(saved["独立期限算術検査数"] == COUNTS["完了期限算術"], "完了期限検算件数差")
    baseline = {}
    for c in rows:
        if not c["policy"].endswith("plus"):
            key = (c["session"], c["family"], c["bar_end"], c["birth"]["side"])
            need(key not in baseline, "同構造・同分・同方向の基本候補重複")
            baseline[key] = c
    rebuilt = {p: {str(h): summary(rows, p, h, baseline) for h in HORIZONS} for p in POLICIES}
    compare(saved["集計"], rebuilt, "候補全体")
    COUNTS["全体の幅期限条件数"] = sum(len(s["touches"]) for horizons in rebuilt.values() for s in horizons.values())
    COUNTS["全体の到達済み70%以上数"] = sum(t["target70_resolved"] is True for horizons in rebuilt.values() for s in horizons.values() for t in s["touches"].values())
    COUNTS["全体の全完了70%以上数"] = sum(t["target70_all_complete"] is True for horizons in rebuilt.values() for s in horizons.values() for t in s["touches"].values())
    groups = {}
    for kind, keys in (("side", ["-1", "1"]), ("history", ["元54場", "追加16場"]), ("session", names)):
        groups[kind] = {}
        for key in keys:
            selected = [c for c in rows if str(c["birth"]["side"] if kind == "side" else c[kind]) == key]
            groups[kind][key] = {p: {str(h): summary(selected, p, h, baseline) for h in HORIZONS} for p in POLICIES}
    compare(saved["群別"], groups, "群別全体")
    tables_check(tables, rows, rebuilt, groups, names)
    after = {path: digest(Path(path).read_bytes()) for path in before}
    need(before == after, "許可入力又は自身のコードが検算中に変化")
    proof = {"試行": 120, "成功": True, "場数": 70, "出生数": sum(event_counts.values()), "候補数": len(rows), "イベント件数": dict(event_counts), "検査件数": dict(COUNTS), "候補別の新規不可出生数": unavailable, "集計": serial(rebuilt), "入力SHA256": before, "後SHA256": after, "前後不変": True, "数値比較": "件数・金額は完全一致。平均・中央値・率はFraction再算出後のIEEE754倍精度1回丸め。参考二項95下限だけ明示式の浮動小数再算出。許容差なし。", "分母": "全出生には新規不可出生も含む。期限評価と先着は取得かつcompleteのみ。組比較は同構造・同分・同方向の基本入口も当該候補も当該期限completeの共通群。異なる取得・期限評価時刻を含む。", "確認範囲": ["全保存イベントと独立候補対応・1分構造・因果時計・票の参照", "要求後の原行及び1秒・初回正常BBO・capとriskの即時拒否及び成行価格", "30/60分期限・25/50/100/125/200pt先着の保存幾何・費用2条件", "全12候補期限集計・幅60集計・70場840集計・明細全セル", "買売・元54/追加16・全70場の群別全集計・同分構造基本入口組比較"], "未証明": ["全Rawを別再走査せず、最初の約定行・先着行・正常期限行だったことや途中欠測は再証明しない", "保存公表本文を許可入力として読まず、技法値・zone/confirm式を自然Rawから再形成しない", "ForceClose自体は保存結果にないため、expires<=born.timeを新規不可として照合。固定SourceのForceClose値はRootの固定入力とコード・実行証拠で検査する", "同時保有口座・片側10枚・mini実約定・必須追尾を含む運用収益ではない", "同じ場・波の依存があるため二項区間及び70%欄を将来勝率保証に使わない"], "自然Raw読取": 0, "Native読取": 0, "CSV読取": 0, "金融実行": False, "条件変更": False, "11月09読取": False}
    proof["確認範囲"][1] = "要求後の原行及び1秒・保存された初回評価BBOのcap→hold→risk優先と即時拒否・成行記帳価格"
    proof["未証明"][1] = "保存公表本文を許可入力として読まず、全技法値・全パターン式を自然Rawから再形成しない。P2のBB絶対境界等の未保存値は再証明しない"
    encoded = (json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with output.open("xb") as handle:
        handle.write(encoded)
    print(json.dumps({"成功": True, "確認": str(output), "sha256": digest(encoded), "件数": dict(COUNTS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
