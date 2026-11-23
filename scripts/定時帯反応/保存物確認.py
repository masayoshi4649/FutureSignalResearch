"""49の保存物を原BBO・現金・不変条件へ独立照合する。戦略は再生しない。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
from itertools import groupby
import json
import math
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00049_15分定時の序盤帯反応"
WORK = ROOT / "work/定時帯反応/00049"
MANIFEST = ROOT / "study/00028_基準線復帰と上位一目の方向/入力台帳.json"
JST = timezone(timedelta(hours=9))
POLICIES = ("S0", "S1")
SPANS = ("学習", "条件選択", "後続検査")
ACTIONS = ("買い新規要求", "売り新規要求", "待ち", "保有継続", "処理中", "判定不能")
FROZEN_PROTECTION = ("h", "L", "arm", "arm_time", "arm_line", "arm_r", "arm_net", "D", "entry_atr")


class Audit:
    """必要な不変条件の比較数と、小型の不一致例を保持する。"""

    def __init__(self) -> None:
        """空の検査を作る。

        引数: なし。
        返り値: None。
        """
        self.count, self.bad, self.examples = 0, 0, []

    def check(self, name: str, actual: object, expected: object) -> None:
        """値を厳密比較する。

        引数: name(str)は項目、actual/expected(object)は実測と独立期待値。
        返り値: None。不一致を最大40例だけ保存する。
        """
        self.count += 1
        if actual != expected:
            self.bad += 1
            if len(self.examples) < 40:
                self.examples.append({"項目": name, "実際": str(actual)[:700], "期待": str(expected)[:700]})


def sha(path: Path) -> str:
    """ファイルを指紋化する。

    引数: path(Path)は入力。
    返り値: strはSHA256。
    """
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path: Path) -> dict:
    """JSONを読む。

    引数: path(Path)は入力。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_rows(path: Path):
    """保存JSONLを順次読む。

    引数: path(Path)はgzip又は通常JSONL。
    返り値: Iterator[dict]は非空行の内容。モデルは起動しない。
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def calendar(session: str) -> tuple[float, float, float, list[float]]:
    """独立の暦から全予定枠を列挙する。

    引数: session(str)は開始日とDay/Night。
    返り値: tupleは開始/強制/終了と、25又は49枠。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        start, first, force, end, n = (8, 45), (9, 15), (15, 35), (15, 40), 25
    elif session.endswith("_Night"):
        start, first, force, end, n = (17, 0), (17, 30), (29, 50), (29, 55), 49
    else:
        raise ValueError("場名不正")
    point = lambda x: (day + timedelta(hours=x[0], minutes=x[1])).timestamp()
    return point(start), point(force), point(end), [point(first) + 900 * i for i in range(n)]


def span(session: str) -> str:
    """固定の日付区分を返す。

    引数: session(str)は場。
    返り値: strは期間。
    """
    day = session[:10]
    return "学習" if day < "2026-10-19" else "条件選択" if day < "2026-11-04" else "後続検査"


def cash_pair(entry: float, exit_price: float, side: int, extra: int) -> Decimal:
    """新規/返済の符号別現金を足して費用後額を得る。

    引数: entry/exit_price(float)は保存価格、side(int)は±1、extra(int)は片道pt。
    返り値: Decimalはmicro1枚の円。約定価格へ滑りを足さない。
    """
    opening = -Decimal(side) * Decimal(str(entry)) * 10 - 11 - extra * 10
    closing = Decimal(side) * Decimal(str(exit_price)) * 10 - 11 - extra * 10
    return opening + closing


def direction_pt(side: int, mark: float, entry: float) -> float:
    """保存十進価格から実方向幅を得る。

    引数: side(int)は±1、mark/entry(float)は保存価格。
    返り値: floatはpt。任意許容幅は加えない。
    """
    return float(Decimal(side) * (Decimal(str(mark)) - Decimal(str(entry))))


def tape_from_arrays(data: dict, session: str, audit: Audit) -> dict:
    """時計の累積最大で非後退行を独立抽出する。

    引数: data(dict)は元8列配列、session(str)は場、audit(Audit)は検査先。
    返り値: dictは合法イベント列と正常BBO列。同値時計の原順を保持する。
    """
    start, _, end, _ = calendar(session)
    now = np.asarray(data["now"], dtype=float)
    line = np.asarray(data["line"], dtype=np.int64)
    audit.check(session + ":元正常旗型", np.asarray(data["valid"]).dtype == np.dtype(bool), True)
    audit.check(session + ":原行strict", bool(np.all(np.diff(line) > 0)), True)
    finite = np.isfinite(now)
    maximum = np.maximum.accumulate(np.where(finite, now, -np.inf))
    legal = finite & (now == maximum) & (now >= start) & (now < end)
    keep = np.flatnonzero(legal)
    event = {k: np.asarray(data[k])[keep] for k in ("now", "line", "bid", "ask", "valid")}
    good = event["valid"].astype(bool) & np.isfinite(event["bid"]) & np.isfinite(event["ask"]) & (event["bid"] > 0) & (event["bid"] < event["ask"])
    normal = {k: v[good] for k, v in event.items()}
    return {"events": event, "normal": normal, "normal_lines": {int(v): i for i, v in enumerate(normal["line"])}}


def load_tape(entry: dict, audit: Audit) -> tuple[dict, str, str]:
    """固定キャッシュを検算し、一場だけ展開する。

    引数: entry(dict)は既予約台帳、audit(Audit)は照合先。
    返り値: tupleは抽出配列、相対パス、圧縮ファイルSHA。
    """
    path = ROOT / "work/複合検証" / entry["cache_path"]
    digest = sha(path)
    audit.check(entry["session"] + ":cacheSHA", digest, entry["sha256_cache"])
    with np.load(path, allow_pickle=False) as archive:
        audit.check("元8列集合", set(archive.files), {"now", "line", "last", "bid", "ask", "valid", "volume", "volume_time"})
        data = {k: archive[k] for k in archive.files}
    return tape_from_arrays(data, entry["session"], audit), path.resolve().relative_to(ROOT.resolve()).as_posix(), digest


def first_normal(tape: dict, request: float, line: int | None) -> int | None:
    """要求+1秒・後行の最初正常BBO位置を探す。

    引数: tape(dict)は独立抽出列、request(float)/line(int|None)は要求出典。
    返り値: int|Noneは正常配列位置。要求以前へ戻さない。
    """
    q = tape["normal"]
    i = int(np.searchsorted(q["now"], request + 1, side="left"))
    if line is not None:
        i = max(i, int(np.searchsorted(q["line"], line, side="right")))
    return i if i < len(q["now"]) else None


def saved_label_expected(tape: dict, row: dict, force: float) -> dict:
    """原正常BBOの全障壁と空白をベクトル比較する。

    引数: tape(dict)は正常列、row(dict)は保存要求、force(float)は仮先着期限。
    返り値: dictは独立のfill/outcome/endと価格。主labelは呼ばない。
    """
    q = tape["normal"]
    i = first_normal(tape, row["time"], row["line"])
    result = {"filled": False, "outcome": "未約定", "end_time": row["time"] + 30, "end_line": row["line"]}
    if i is None or q["now"][i] > row["time"] + 30:
        return result
    price = float(q["ask"][i] if row["side"] == 1 else q["bid"][i])
    result.update(filled=True, entry_time=float(q["now"][i]), entry_line=int(q["line"][i]), entry_price=price)
    stop = int(np.searchsorted(q["now"], force, side="right"))
    if i >= stop:
        raise ValueError("仮約定はforceより前である必要があります")
    marks = q["bid"][i:stop] if row["side"] == 1 else q["ask"][i:stop]
    r = row["side"] * (marks - price)
    gaps = np.r_[False, np.diff(q["now"][i:stop]) > 300]
    barriers = (r <= -125) | (r >= 250)
    found = np.flatnonzero(gaps | barriers)
    if len(found):
        j = int(found[0])
        result.update(outcome="不足" if gaps[j] else "125" if r[j] <= -125 else "250",
                      end_time=float(q["now"][i + j]), end_line=int(q["line"][i + j]))
    else:
        j = len(r) - 1
        last = float(q["now"][stop - 1])
        if last == force:
            result.update(outcome="期限", end_time=force, end_line=int(q["line"][stop - 1]))
        elif stop < len(q["now"]):
            result.update(outcome="期限" if force - last <= 300 else "不足", end_time=force, end_line=int(q["line"][stop]))
        else:
            result.update(outcome="不足", end_time=last, end_line=int(q["line"][stop - 1]))
    result.update(mfe=max(0.0, float(np.max(r[:j + 1]))), mae=min(0.0, float(np.min(r[:j + 1]))))
    return result


def entry_summary(rows: list[dict], target: str) -> dict:
    """独立に候補分母・先着・仮約定後の非重複集合を数える。

    引数: rows(list[dict])は一候補、target(str)は期間。
    返り値: dictは主結果と比較する集計。B+/B−は呼出し側で分ける。
    """
    chosen = [r for r in rows if span(r["session"]) == target]
    filled = [r for r in chosen if r["filled"]]
    thin, terminal = [], {}
    for r in filled:
        identity = r["session"]
        if (r["entry_time"], r["entry_line"]) > terminal.get(identity, (-math.inf, -1)):
            thin.append(r)
            terminal[identity] = (r["end_time"], r["end_line"])
    n, nt = len(filled), len(thin)
    success, thinned = sum(r["outcome"] == "250" for r in filled), sum(r["outcome"] == "250" for r in thin)
    days, sessions = len({r["session"][:10] for r in filled}), len({r["session"] for r in filled})
    minimum = (60, 6, 10, 20) if target == "学習" else (20, 3, 5, 10)
    support = all(a >= b for a, b in zip((n, days, sessions, nt), minimum))
    return {"候補": len(chosen), "約定": n, "250": success, "結果別": dict(Counter(r["outcome"] for r in chosen)),
            "率": success / n if n else None, "間引き約定": nt, "間引き250": thinned,
            "間引き率": thinned / nt if nt else None, "日数": days, "場数": sessions, "支持": support,
            "70目標": bool(n and nt and support and success * 10 >= n * 7 and thinned * 10 >= nt * 7)}


# ----------------------------------------
# 保存された実注文・追尾を、その出典と不変条件へ照合する。

def check_decisions(block: dict, tape: dict, audit: Audit) -> None:
    """予定枠・最初イベント・保有分類を照合する。

    引数: block(dict)は一場一候補の保存詳細、tape(dict)は原イベント、audit(Audit)は検査先。
    返り値: None。入口の価格パターンや指標は再計算しない。
    """
    op, slots = block["operation"], block["slots"]
    session, policy = block["session"], block["policy"]
    _, _, _, expected_times = calendar(session)
    name = session + ":" + policy
    audit.check(name + ":全予定", [r["scheduled"] for r in slots], expected_times)
    audit.check(name + ":全判断", [r["scheduled"] for r in op["decisions"]], expected_times)
    audit.check(name + ":id一意", len({r["slot_id"] for r in slots}), len(slots))
    events = tape["events"]
    for s, d in zip(slots, op["decisions"]):
        prefix = name + ":" + str(s["scheduled"])
        j = int(np.searchsorted(events["now"], s["scheduled"], side="left"))
        exists = j < len(events["now"]) and events["now"][j] <= s["scheduled"] + 30
        expected_line = int(events["line"][j]) if exists else None
        expected_time = float(events["now"][j]) if exists else s["scheduled"]
        audit.check(prefix + ":最初原行", (s["time"], s["line"]), (expected_time, expected_line))
        for key in ("scheduled", "time", "line", "slot_id", "side", "role", "atr", "D", "reason", "ready"):
            audit.check(prefix + ":純" + key, d[key], s[key])
        good = exists and int(events["line"][j]) in tape["normal_lines"]
        expected = "判定不能" if not good else "処理中" if d["pending_kind"] else "保有継続" if d["holding"] else "判定不能" if not s["ready"] else "待ち" if not s["side"] else "買い新規要求" if s["side"] == 1 else "売り新規要求"
        audit.check(prefix + ":状態分類", d["action"], expected)
        audit.check(prefix + ":待ち旗", d["wait"], expected == "待ち")
        audit.check(prefix + ":判定可能旗", d["activity_valid"], expected != "判定不能")
    counts = Counter(d["action"] for d in op["decisions"])
    n, wait, invalid = len(expected_times), counts["待ち"], counts["判定不能"]
    metrics = op["metrics"]
    expected = {"予定枠数": n, "判断別数": {a: counts[a] for a in ACTIONS}, "待ち数": wait,
                "主待ち率": wait / n, "保守待ち率上限": (wait + invalid) / n,
                "全枠判定可能": invalid == 0, "待ち率条件適格": 2 * (wait + invalid) <= n}
    for k, v in expected.items():
        audit.check(name + ":活動" + k, metrics[k], v)


def check_orders(op: dict, tape: dict, audit: Audit) -> None:
    """注文の最初適格BBO・TTL・価格を原配列へ照合する。

    引数: op(dict)は保存運用、tape(dict)は正常BBO、audit(Audit)は検査先。
    返り値: None。新しい注文判断は生成しない。
    """
    _, force, _, _ = calendar(op["session"])
    q = tape["normal"]
    by_position = {r["id"]: r for r in op["closed"]}
    if op["final_state"]["position"]:
        p = op["final_state"]["position"]
        by_position[p["id"]] = p
    audit.check("注文id一意", len({r["id"] for r in op["orders"]}), len(op["orders"]))
    requests = {d["slot_id"]: d for d in op["decisions"] if d["action"] in ("買い新規要求", "売り新規要求")}
    audit.check("全新規注文の受付集合", {o["slot"]["slot_id"] for o in op["orders"] if o["kind"] == "entry"}, set(requests))
    for order in op["orders"]:
        name = op["session"] + ":" + order["id"]
        i = first_normal(tape, order["request_time"], order["request_line"])
        exists = i is not None
        if order["kind"] == "entry":
            saved = order["slot"]
            decision = requests[saved["slot_id"]]
            audit.check(name + ":新規要求出典", (order["request_time"], order["request_line"]), (saved["time"], saved["line"]))
            for k in ("side", "role", "atr", "D", "time", "line", "scheduled"):
                audit.check(name + ":受付" + k, saved[k], decision[k])
            exists = exists and q["now"][i] <= order["request_time"] + 30 and q["now"][i] < force
            audit.check(name + ":TTL定義", order["expires"], order["request_time"] + 30)
        expected_status = "filled" if exists else "cancelled" if order["kind"] == "entry" else "pending"
        audit.check(name + ":約定可否", order["status"], expected_status)
        if not exists:
            if order["kind"] == "entry":
                audit.check(name + ":取消時計", order.get("cancel_time"), min(order["expires"], force))
            continue
        audit.check(name + ":最初BBO", (order["fill_time"], order["fill_line"]), (float(q["now"][i]), int(q["line"][i])))
        if order["kind"] == "entry":
            side = order["slot"]["side"]
            price = float(q["ask"][i] if side == 1 else q["bid"][i])
            matches = [p for p in by_position.values() if p["slot_id"] == order["slot"]["slot_id"]]
            audit.check(name + ":新規建玉一意", len(matches), 1)
            if matches:
                p, s = matches[0], order["slot"]
                audit.check(name + ":ATR/D/役割固定", (p["entry_atr"], p["D"], p["side"], p["role"]), (s["atr"], s["D"], s["side"], s["role"]))
        else:
            matches = [p for p in by_position.values() if p.get("exit_request_time") == order["request_time"] and p.get("exit_request_line") == order["request_line"]]
            audit.check(name + ":返済対象一意", len(matches), 1)
            if not matches:
                continue
            price = float(q["bid"][i] if matches[0]["side"] == 1 else q["ask"][i])
        audit.check(name + ":原BBO価格", order["fill_price"], price)


def check_cash(op: dict, viewer: list[dict], tape: dict, audit: Audit) -> dict:
    """約定片から別式の現金と未完結片道費用を作る。

    引数: op(dict)は保存運用、viewer(list[dict])は保存Viewer約定、tape(dict)は元板、audit(Audit)は検査先。
    返り値: dictは独立期間集計用の小型会計。未完結の元本を利益へ足さない。
    """
    audit.check("Viewer全約定属性", viewer, op["trades"])
    audit.check("fills別名", op["fills"], op["trades"])
    positions, result = {}, {str(f): Decimal(0) for f in (0, 5, 10)}
    q = tape["normal"]
    closed = {r["id"]: r for r in op["closed"]}
    for trade in viewer:
        i = tape["normal_lines"].get(trade["source_line"])
        audit.check("約定原行normal", i is not None, True)
        if i is None:
            continue
        side = 1 if trade["type"].startswith("Long") else -1
        opening = trade["type"].endswith("N")
        price = float(q["ask"][i] if opening and side == 1 or not opening and side == -1 else q["bid"][i])
        audit.check("約定BBO", trade["price"], price)
        audit.check("約定時計", datetime.fromisoformat(trade["timestamp"]).timestamp(), float(q["now"][i]))
        audit.check("数量/主片道費用", (trade["qty"], trade["fee_yen"]), (1, 61))
        identity = trade["position_id"]
        if opening:
            audit.check("一建玉", len(positions), 0)
            positions[identity] = trade
        else:
            start = positions.pop(identity)
            record = closed[identity]
            audit.check("完結side/価格", (record["side"], record["entry_price"], record["exit_price"]), (side, start["price"], price))
            audit.check("完結line", (record["entry_line"], record["exit_line"]), (start["source_line"], trade["source_line"]))
            for f in (0, 5, 10):
                cash = cash_pair(start["price"], price, side, f)
                audit.check(identity + ":現金" + str(f), Decimal(str(record["pnl" + str(f)])), cash)
                result[str(f)] += cash
    final = op["final_state"]["position"]
    audit.check("残建玉", set(positions), {final["id"]} if final else set())
    metrics, quality = op["metrics"], op["quality"]
    observed = {k: float(v) for k, v in result.items()}
    ledger = {str(f): float(result[str(f)] - len(positions) * (11 + f * 10)) for f in (0, 5, 10)}
    audit.check("完結観測現金", metrics["完結取引観測純額円"], observed)
    audit.check("台帳観測現金", metrics["約定台帳観測確定円"], ledger)
    audit.check("未解消建玉数", quality["未解消建玉数"], len(positions))
    invalid_earnings = bool(quality["損益注意理由"])
    if final or op["final_state"]["pending"]:
        audit.check("未解消の注意", invalid_earnings, True)
    audit.check("確定額null", metrics["全体確定対象円"], {k: None if invalid_earnings else v for k, v in ledger.items()})
    return {"session": op["session"], "candidate": op["candidate_id"], "ledger": ledger,
            "observed": observed, "closed": op["closed"], "decisions": op["decisions"],
            "caution": invalid_earnings, "unresolved": len(positions)}


def check_trail(op: dict, tape: dict, audit: Audit) -> None:
    """保存変化点の保護式と、返済待ち中の設定凍結を点検する。

    引数: op(dict)は保存追尾、tape(dict)は原板、audit(Audit)は検査先。
    返り値: None。変化のない全tickの戦略再生はしない。
    """
    previous = None
    for log in op["trail"]:
        state, action = log["state"], log["action"]
        current = state["position"]
        old = previous["position"] if previous else None
        pending = previous["pending"] if previous else None
        if old and pending and pending["kind"] == "exit" and current:
            audit.check("返済pending設定凍結", {k: current[k] for k in FROZEN_PROTECTION}, {k: old[k] for k in FROZEN_PROTECTION})
        if action == "新規約定":
            audit.check("初期保護", (current["h"], current["L"], current["arm"]), (0.0, max(-125.0, -current["D"]), False))
        if old and current and old["id"] == current["id"]:
            audit.check("線非緩和", current["L"] >= old["L"], True)
            audit.check("起動非解除", not old["arm"] or current["arm"], True)
        if action == "保護更新":
            i = tape["normal_lines"].get(log["line"])
            audit.check("保護原行normal", i is not None, True)
            if i is not None and old:
                q = tape["normal"]
                audit.check("保護更新時計", log["time"], float(q["now"][i]))
                mark = float(q["bid"][i] if current["side"] == 1 else q["ask"][i])
                r = direction_pt(current["side"], mark, current["entry_price"])
                net = Decimal(current["side"]) * (Decimal(str(mark)) - Decimal(str(current["entry_price"]))) * 10 - 122
                arm = old["arm"] or net > 0
                high = max(old["h"], 0.0, r)
                level = max(old["L"], -125.0, high - current["D"], 0.0 if arm else -math.inf)
                audit.check("保護式/現在起動", (current["h"], current["L"], current["arm"]), (high, level, arm))
                audit.check("保護表示出典", (log["r"], log["mark"], log["current_net"]), (r, mark, float(net)))
                if arm and not old["arm"]:
                    audit.check("初起動出典", (current["arm_time"], current["arm_line"], current["arm_r"], current["arm_net"]), (log["time"], log["line"], r, float(net)))
        if action == "返済要求" and log["reason"] == "連続追尾" and current:
            i = tape["normal_lines"].get(log["line"])
            audit.check("連続返済要求normal", i is not None, True)
            if i is not None:
                q = tape["normal"]
                mark = float(q["bid"][i] if current["side"] == 1 else q["ask"][i])
                audit.check("要求時の線到達", direction_pt(current["side"], mark, current["entry_price"]) <= current["L"], True)
        previous = state


def check_periods(accounts: list[dict], labels: dict, result: dict, audit: Audit) -> None:
    """全予定分母、期間会計、入口支持を保存結果へ照合する。

    引数: accounts(list[dict])は独立会計、labels(dict)は照合済先着、result(dict)は正本、audit(Audit)は検査先。
    返り値: None。後段診断の帯別優劣は選別しない。
    """
    for policy in POLICIES:
        for target in SPANS:
            actual = result["候補"][policy][target]
            expected_entry = entry_summary(labels[policy], target)
            audit.check(policy + target + ":入口全分母", actual["入口"], expected_entry)
            chosen = [r for r in accounts if r["candidate"] == policy and span(r["session"]) == target]
            decisions = [d for r in chosen for d in r["decisions"]]
            closed = [{**c, "session": r["session"]} for r in chosen for c in r["closed"]]
            counts = Counter(d["action"] for d in decisions)
            n, waiting, invalid = len(decisions), counts["待ち"], counts["判定不能"]
            ledger = {str(f): float(sum(Decimal(str(r["ledger"][str(f)])) for r in chosen)) for f in (0, 5, 10)}
            observed = {str(f): float(sum(Decimal(str(r["observed"][str(f)])) for r in chosen)) for f in (0, 5, 10)}
            cautions = [r["session"] for r in chosen if r["caution"]]
            days, sessions = len({r["session"][:10] for r in closed}), len({r["session"] for r in closed})
            buys = sum(c["side"] == 1 for c in closed)
            minimum = (20, 6, 10, 5, 5) if target == "学習" else (10, 3, 6, 3, 3)
            support = all(a >= b for a, b in zip((len(closed), days, sessions, buys, len(closed) - buys), minimum))
            active = bool(n) and 2 * (waiting + invalid) <= n
            earning = support and not cautions and ledger["5"] > 0
            expected = {"予定枠": n, "判断別": dict(counts), "待ち数": waiting, "主待ち率": waiting / n if n else None,
                        "判定不能": invalid, "待ち率保守上限": (waiting + invalid) / n if n else None,
                        "全枠判定可能": invalid == 0, "活動適格": active, "完結数": len(closed),
                        "買い": buys, "売り": len(closed) - buys, "日数": days, "場数": sessions,
                        "品質注意場": cautions, "未解消": sum(r["unresolved"] for r in chosen),
                        "完結観測額円": observed, "台帳観測額円": ledger,
                        "全体確定額円": {k: None if cautions else v for k, v in ledger.items()},
                        "費用支持": support, "費用適格": earning}
            for k, v in expected.items():
                audit.check(policy + target + ":運用" + k, actual["運用"][k], v)
            audit.check(policy + target + ":同時適格", actual["同時適格"], expected_entry["70目標"] and active and earning)
            for role in ("順行", "反転"):
                expected_role = entry_summary([r for r in labels[policy] if r["role"] == role], target)
                audit.check(policy + target + role + ":役割入口", result["役割別入口"][policy][target][role], expected_role)
    for policy in ("B+", "B-"):
        for target in SPANS:
            audit.check(policy + target + ":方向別基準", result["時刻基準"][policy][target], entry_summary(labels[policy], target))
    adopted = [p for p in POLICIES if all(result["候補"][p][s]["同時適格"] for s in SPANS[:2])]
    audit.check("最終採用", result["採用"], adopted)


def fetch_json(url: str) -> tuple[dict, bytes, dict]:
    """Viewerの小型JSONを取得する。

    引数: url(str)はAPI/数値JSONのURL。
    返り値: tupleは内容/本文/小文字化ヘッダ。画像や原価格の複製はしない。
    """
    with urlopen(url, timeout=60) as response:
        raw = response.read()
        headers = {k.lower(): v for k, v in response.headers.items()}
    return json.loads(raw), raw, headers


def check_viewer_api(base: str | None, resources: list[dict], accounts: list[dict], audit: Audit) -> dict:
    """全資源集合と各候補の代表一場をViewer APIへ照合する。

    引数: base(str|None)はローカルURL、resources(list[dict])は一覧、accounts(list[dict])は会計、audit(Audit)は検査先。
    返り値: dictは範囲と代表。指定なしは未実行と明示する。
    """
    if base is None:
        return {"実行": False, "理由": "--viewer-url未指定。全保存132資源/約定は別途照合済み"}
    query = {"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}
    listed, _, _ = fetch_json(base + "/api/resources?" + urlencode(query))
    audit.check("API全132集合", {r["id"] for r in listed["resources"]}, {r["id"] for r in resources})
    representatives = []
    for policy in POLICIES:
        row = sorted([r for r in accounts if r["candidate"] == policy], key=lambda r: (-abs(r["ledger"]["5"]), r["session"]))[0]
        resource = next(r for r in resources if r["session"] == row["session"] and r["method_id"] == policy)
        params = {**query, "resource": resource["id"], "interval": "5", "price": "last", "width": 1000, "height": 700}
        meta, _, _ = fetch_json(base + "/api/chart?" + urlencode(params))
        data, raw, headers = fetch_json(urljoin(base + "/", meta["data_url"]))
        audit.check("API本文SHA", hashlib.sha256(raw).hexdigest(), meta["data_sha256"])
        audit.check("APIヘッダSHA", headers.get("x-chart-data-sha256"), meta["data_sha256"])
        audit.check("APIメタ集計", data["summary"], meta["summary"])
        audit.check("API独立台帳5", Decimal(str(data["summary"]["realized_pnl_yen"])), Decimal(str(row["ledger"]["5"])))
        saved = list(json_rows(STUDY / resource["pnl_path"]))
        audit.check("API片数", len(data["events"]), len(saved))
        for seq, (fill, event) in enumerate(zip(saved, data["events"]), 1):
            for k in ("type", "qty", "position_id", "method_id", "price"):
                audit.check("API約定" + k, event[k], fill[k])
            audit.check("API物理行", event["sequence"], seq)
            audit.check("API約定ミリ秒", abs(event["timestamp_ms"] - datetime.fromisoformat(fill["timestamp"]).timestamp() * 1000) <= .001, True)
        representatives.append({"候補": policy, "場": row["session"], "資源ID": resource["id"],
                                "台帳観測額5円": row["ledger"]["5"], "品質注意": row["caution"], "数値SHA256": meta["data_sha256"]})
    return {"実行": True, "接続先": base, "全資源数": len(listed["resources"]), "代表": representatives,
            "代表規約": "各候補の最大絶対台帳観測額場。売買採否には不使用。PNGなし"}


def run(viewer_url: str | None = None) -> dict:
    """root実行後の保存物を一度だけ検査し証明を保存する。

    引数: viewer_url(str|None)は任意のViewer。
    返り値: dictは合否/範囲/出典。不一致でも証明は一度だけ保存する。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    audit = Audit()
    files = [STUDY / n for n in ("結果.json", "固定.json", "条件.json", "一覧.resources.json")]
    files += [WORK / "定時判断と運用.jsonl.gz", WORK / "入口先着.jsonl.gz", MANIFEST, Path(__file__)]
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in files}
    fixed, result, manifest, catalog = read(files[1]), read(files[0]), read(MANIFEST), read(files[3])
    for relative, expected in fixed["ファイルSHA256"].items():
        audit.check("固定出典:" + relative, sha(ROOT / relative), expected)
    audit.check("結果の固定bind", result["固定SHA256"], sha(STUDY / "固定.json"))
    entries = {r["session"]: r for r in manifest["entries"]}
    audit.check("既使用66場", len(entries), 66)
    resources = catalog["resources"]
    resource_map = {(r["session"], r["method_id"]): r for r in resources}
    audit.check("保存132資源", set(resource_map), {(s, p) for s in entries for p in POLICIES})
    audit.check("保存資源重複なし", len(resources), 132)
    audit.check("保存資源id一意", len({r["id"] for r in resources}), 132)
    for resource in resources:
        audit.check("資源商品/倍率", (resource["symbol"], resource["product"], resource["point_value"]), ("NK225", "NK225micro", 10))
    labels = {p: [] for p in (*POLICIES, "B+", "B-")}
    by_session = defaultdict(list)
    for row in json_rows(WORK / "入口先着.jsonl.gz"):
        labels[row["policy"]].append(row)
        by_session[row["session"]].append(row)
    audit.check("先着候補集合", set(labels), {*POLICIES, "B+", "B-"})
    audit.check("先着場集合", set(by_session) <= set(entries), True)
    accounts, cache_pins, viewer_pins, visited = [], {}, {}, set()
    stream = json_rows(WORK / "定時判断と運用.jsonl.gz")
    for session, items in groupby(stream, key=lambda r: r["session"]):
        audit.check("場の再出現なし", session not in visited, True)
        visited.add(session)
        tape, relative, digest = load_tape(entries[session], audit)
        cache_pins[relative] = digest
        blocks = list(items)
        audit.check("場の二候補", [b["policy"] for b in blocks], list(POLICIES))
        expected_labels, label_sources = set(), {}
        for block in blocks:
            policy, op = block["policy"], block["operation"]
            check_decisions(block, tape, audit)
            check_orders(op, tape, audit)
            check_trail(op, tape, audit)
            path = STUDY / resource_map[session, policy]["pnl_path"]
            viewer_pins[path.relative_to(ROOT).as_posix()] = sha(path)
            accounts.append(check_cash(op, list(json_rows(path)), tape, audit))
            for slot in block["slots"]:
                binding = {k: slot[k] for k in ("slot_id", "session", "policy", "scheduled", "time", "line", "side", "role")}
                if slot["ready"] and slot["side"]:
                    expected_labels.add((policy, slot["slot_id"]))
                    label_sources[policy, slot["slot_id"]] = binding
                if policy == "S0" and slot["line"] in tape["normal_lines"]:
                    expected_labels.update((p, slot["slot_id"]) for p in ("B+", "B-"))
                    for bside, bpolicy in ((1, "B+"), (-1, "B-")):
                        label_sources[bpolicy, slot["slot_id"]] = {**binding, "policy": bpolicy, "side": bside, "role": "時刻基準"}
        actual = by_session[session]
        audit.check(session + ":全先着集合", {(r["policy"], r["slot_id"]) for r in actual}, expected_labels)
        audit.check(session + ":先着一意", len(actual), len(expected_labels))
        _, force, _, _ = calendar(session)
        for row in actual:
            binding = label_sources[row["policy"], row["slot_id"]]
            audit.check(session + ":先着要求出典", {k: row[k] for k in binding}, binding)
            expected = saved_label_expected(tape, row, force)
            for k, v in expected.items():
                audit.check(session + row["policy"] + row["slot_id"] + ":先着" + k, row.get(k), v)
        print(session + " 保存物照合", flush=True)
    audit.check("詳細全66場", visited, set(entries))
    check_periods(accounts, labels, result, audit)
    api = check_viewer_api(viewer_url, resources, accounts, audit)
    for relative, expected in before.items():
        audit.check("実行中不変:" + relative, sha(ROOT / relative), expected)
    payload = {"試行": 49, "確認日時": datetime.now(JST).isoformat(), "全件一致": audit.bad == 0,
               "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
               "市場戦略再生": False, "主モデルimport": False,
               "検証範囲": "保存注文/現金/全予定枠/保存追尾変化点/先着原BBO直接/Viewer保存全約定。指標と全tick保護の再生なし",
               "対象場数": len(visited), "対象運用数": len(accounts), "先着件数": {p: len(v) for p, v in labels.items()},
               "参照SHA256": before, "キャッシュSHA256": cache_pins, "Viewer約定SHA256": viewer_pins, "ViewerAPI": api}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def self_test() -> dict:
    """実入力を開かず、別式と分母の明示人工を検査する。

    引数: なし。
    返り値: dictは成功群数。結果正本へ保存しない。
    """
    audit = Audit()
    session = "2026-09-25_Day"
    start, force, end, times = calendar(session)
    audit.check("予定25", len(times), 25)
    audit.check("予定49", len(calendar("2026-09-25_Night")[3]), 49)
    audit.check("現金別式買", cash_pair(100, 120, 1, 5), Decimal(78))
    audit.check("現金鏡像売", cash_pair(900, 880, -1, 5), Decimal(78))
    t = times[0]
    source = {"now": np.array([t, t + 1, t + 2, force, force + 1]), "line": np.arange(1, 6),
              "bid": np.array([95, 95, 350, 95, 95]), "ask": np.array([100, 100, 355, 100, 100]), "valid": np.array([True] * 5)}
    tape = tape_from_arrays(source, session, audit)
    row = {"time": t, "line": 1, "side": 1}
    label = saved_label_expected(tape, row, force)
    audit.check("直接先着250", (label["filled"], label["outcome"], label["end_time"]), (True, "250", t + 2))
    source["valid"][1] = False
    tape = tape_from_arrays(source, session, audit)
    audit.check("数量flag除外", first_normal(tape, t, 1), 1)
    sample = [{**row, "session": session, "slot_id": "a", "policy": "S0", "role": "順行", **label},
              {**row, "session": session, "slot_id": "b", "policy": "S0", "role": "順行", **label}]
    expected = entry_summary(sample, "学習")
    audit.check("全分母と非重複", (expected["候補"], expected["約定"], expected["間引き約定"]), (2, 2, 1))
    audit.check("空率None", entry_summary([], "学習")["率"], None)
    source2 = {"now": np.array([t, t + 1, t + 2, t + 3, t + 3.5, t + 4]), "line": np.arange(1, 7),
               "bid": np.array([95, 95, 115, 100, 150, 100]), "ask": np.array([100, 100, 120, 105, 155, 105]), "valid": np.array([True] * 6)}
    tape2 = tape_from_arrays(source2, session, audit)
    p = {"id": "人工建玉", "side": 1, "entry_price": 100., "entry_atr": 20., "D": 20.,
         "h": 0., "L": -20., "arm": False, "arm_time": None, "arm_line": None, "arm_r": None, "arm_net": None}
    armed = {**p, "h": 15., "L": 0., "arm": True, "arm_time": t + 2, "arm_line": 3, "arm_r": 15., "arm_net": 28.}
    pending = {"kind": "exit", "id": "人工返済"}
    trail = [{"action": "新規約定", "line": 2, "time": t + 1, "state": {"position": p, "pending": None}},
             {"action": "保護更新", "line": 3, "time": t + 2, "r": 15., "mark": 115., "current_net": 28., "state": {"position": armed, "pending": None}},
             {"action": "返済要求", "line": 4, "time": t + 3, "reason": "連続追尾", "state": {"position": armed, "pending": pending}},
             {"action": "定時判断", "line": 5, "time": t + 3.5, "state": {"position": armed, "pending": pending}}]
    check_trail({"trail": trail}, tape2, audit)
    broken = [deepcopy(row) for row in trail]
    broken[-1]["state"]["position"]["L"] = -5.
    rejected = Audit()
    check_trail({"trail": broken}, tape2, rejected)
    audit.check("pending緩和破壊拒否", rejected.bad > 0, True)
    source2["now"][2] = t - 1
    reversed_tape = tape_from_arrays(source2, session, audit)
    audit.check("後退原行除外", 3 in reversed_tape["normal_lines"], False)
    if audit.bad:
        raise AssertionError(audit.examples)
    return {"人工成功": True, "照合項目数": audit.count, "市場入力読取": False}


def main() -> None:
    """人工又はroot実行後の保存物検査をCLIから選ぶ。

    引数: なし。argparseで--self-test/--run/--viewer-urlを受ける。
    返り値: None。不一致なら保存後に終了コード1。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    result = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps({k: v for k, v in result.items() if k in ("全件一致", "不一致数", "照合項目数", "人工成功", "市場入力読取")}, ensure_ascii=False))
    if result.get("全件一致") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
