# 89派生元SHA256: 506fd648cbca1861bb465ac5ed143f27a1ae7f66d2def54825b57f83d9727a12
"""89の全受理NK原行へSource通知と確定足出典を同じ一走査で結ぶ監査。

原板は一場一走査。保存した非Source保護注文を外部入力として、先行約定、
実所有、返済予約、取消をPythonで再構成し、Sourceの比率作用を別計算する。
Source戦略の通知生成は固定80同値driverの証拠に依拠し、独立再実装しない。
G1/G2・ATR・技法の注文発生義務と損益計算は別の原板監査.pyが担当する。
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
import gzip
import importlib.util
import json
from pathlib import Path
from zoneinfo import ZoneInfo


HELPER_PATH = Path(__file__).resolve().parent.parent / "FAR後期15分移植/原板照合.py"
HELPER_SHA = "132950b69a2a9497a79c6a464b877c61d2cf42a80d031591ffb81495786c61e9"
KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in ("E0G1", "E0G2", "E1G1", "E1G2"))
FIXED88_PATH = Path(__file__).resolve().parent.parent / "FAR背景維持と押戻し再開/Source通知監査.py"
FIXED88_SHA = "506fd648cbca1861bb465ac5ed143f27a1ae7f66d2def54825b57f83d9727a12"
OWNERSHIP_PATH = FIXED88_PATH.with_name("Source所有順の照合.py")
OWNERSHIP_SHA = "7449e7c73bd823778328a16572a4fbb53706353425f29f490956c1707aed43d1"
FIXED87_PATH = Path(__file__).resolve().parent.parent / "FAR参照玉と可変数量の比較/Source通知監査.py"
FIXED87_SHA = "d9e1a91c7f9fcdfb3a255348bb96e8cd190195a2f494e2195f6db62efabb76cb"
RAW_PATH = FIXED88_PATH.with_name("イベント原板結合.py")
EVENT_PATH = FIXED88_PATH.with_name("イベント保存照合.py")
METHODS = ("NK225_D164_15", "NK225_P164_06", "NK225_U165_03")
FORCE_REASONS = {"場末10分前", "米国前枠終了"}
QUOTE_KEYS = {"time", "index", "line", "last", "bid", "ask", "valid"}
EVENT_KEYS = {"at", "origin", "quote", "method", "source_at", "source_index", "source_line", "closes"}
CLOSE_KEYS = {"id", "reference_id", "before", "quantity", "reason"}
EFFECT_KEYS = {"id", "reference_id", "at", "quote_time", "quote_index", "quote_line", "origin", "before", "quantity", "reason", "pending_before", "cancelled", "unreserved_before", "exit_requested", "unreserved_after", "exit_order_id", "orders_before_count", "orders_after_count"}
LIMITS = [
    "Source通知生成戦略は固定80同値driverと停止Goに依拠する。通知と効果を同時に全削除した場合の戦略上の欠落を独立発見する証明ではない。",
    "非Source保護注文の時点・所有・予約は再構成するが、G1/G2・ATR・技法による注文発生義務と損益は別の原板監査.pyへ分担する。",
    "源Indexは正Last受理NK行、実Indexは全受理NK行から別計算する。badBBOも源Indexへ含め、Last不良では源Indexを進めない。",
]
spec = importlib.util.spec_from_file_location("source87_fixed80_raw", HELPER_PATH)
BASE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BASE)
if BASE.sha(HELPER_PATH) != HELPER_SHA or BASE.sha(FIXED87_PATH) != FIXED87_SHA:
    raise ValueError("固定80/87原板helperのSHA不一致")
raw_spec = importlib.util.spec_from_file_location("event88_raw_bind", RAW_PATH)
RAW = importlib.util.module_from_spec(raw_spec)
raw_spec.loader.exec_module(RAW)
if BASE.sha(FIXED88_PATH) != FIXED88_SHA or BASE.sha(OWNERSHIP_PATH) != OWNERSHIP_SHA:
    raise ValueError("固定88のSource/所有ID helperが変化")
own_spec = importlib.util.spec_from_file_location("source89_fixed88_ownership", OWNERSHIP_PATH)
OWN = importlib.util.module_from_spec(own_spec)
own_spec.loader.exec_module(OWN)
LIMITS.extend(["所有一覧は初版からID一意集合＋全11fieldで照合。通知/注文/約定等の時系列順は維持し、88旧失敗証拠や訂正特例を新89の成功証拠へ流用しない。", "新技法の元指標数値は固定数値器依存で、Close/TR/足時計/Last不良を同じ原板一走査から独立結合する。", "first3 TRの前CloseはBeginSession前seed_viewに依存し、元指標全前史の独立再実装とはしない。", "統合EOFがTOPIX由来の場合は固定Runtime/入力SHA/Source同値依存。NK終端以下不正とNK由来終端完全一致を検査し、TOPIX終端本文を追加走査しない。", "利益snapshotは同原行Quote/公開Close/TR/源時計を結び、未保存Windows等を含むCurrent全文の独立再計算ではない。"] )


def require(condition: bool, reason: str) -> None:
    """
    機能: 構造・型不正を未測定成功へ変換せず停止する。
    引数: condition (bool) は成立条件、reason (str) は日本語の理由。
    返り値: None。不成立ならValueErrorを送出する。
    """
    if not condition:
        raise ValueError(reason)


def number(value: object) -> bool:
    """
    機能: boolを除く有限JSON数値だけを許す。
    引数: value (object) は保存値。
    返り値: bool は有限int又はfloatなら真。
    """
    return BASE.finite(value)


def same(a: object, b: object) -> bool:
    """
    機能: boolとintを区別し、Go数値のint/float表記差だけを許す。
    引数: a/b (object) は保存値と独立期待値。
    返り値: bool は型付き再帰比較の結果。
    """
    if type(b) is bool:
        return type(a) is bool and a == b
    if type(b) is int:
        return type(a) is int and a == b
    if type(b) is float:
        return number(a) and a == b
    if isinstance(b, dict):
        return isinstance(a, dict) and a.keys() == b.keys() and all(same(a[k], v) for k, v in b.items())
    if isinstance(b, list):
        return isinstance(a, list) and len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def check(audit: object, label: str, actual: object, expected: object, **context) -> None:
    """
    機能: 型込みの差分を固定helperの件数・小型差分へ保存する。
    引数: audit (object)、label (str)、actual/expected (object)、context (dict) は照合情報。
    返り値: None。通常等値で隠れる型の差も不一致へ数える。
    """
    if label == "全玉の実初参加と最終所有・予約":
        actual, expected = OWN.ownership_map(actual), OWN.ownership_map(expected)
    if actual == expected and not same(actual, expected):
        audit.check(label + "の型", False, True, **context)
    else:
        audit.check(label, actual, expected, **context)


def schedule(session: str) -> tuple:
    """
    機能: 日本の15分定時とNYの境界を別式で構成する。
    引数: session (str) は場ID。
    返り値: tuple は全timer、定時集合、強制理由map、米国開始秒。
    """
    date, kind = session.rsplit("_", 1)
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=BASE.JST)
    first = day + timedelta(hours=9, minutes=15) if kind == "Day" else day + timedelta(hours=17, minutes=30)
    last = day + timedelta(hours=15, minutes=15) if kind == "Day" else day + timedelta(days=1, hours=5, minutes=30)
    grids = set()
    while first <= last:
        grids.add(first.timestamp())
        first += timedelta(minutes=15)
    forces = {BASE.bounds(session)[1] - 600: "場末10分前"}
    us = 0.0
    timers = set(grids) | set(forces)
    if kind == "Night":
        us = datetime.strptime(date, "%Y-%m-%d").replace(hour=9, minute=30, tzinfo=ZoneInfo("America/New_York")).timestamp()
        forces[us - 900] = "米国前枠終了"
        timers.update((us - 900, us + 900))
    return sorted(timers), grids, forces, us


def proportion(free: int, quantity: int, before: int) -> int:
    """
    機能: 源通知の末尾全残と整数floorを独立に計算する。
    引数: free/quantity/before (int) は実未予約残と源比率。
    返り値: int は0丸めを許した取消又は新返済量。
    """
    require(type(free) is int and free >= 0 and type(before) is int and 1 <= before <= 100 and type(quantity) is int and 1 <= quantity <= before, "Source比率の整数・範囲が不正")
    return free if quantity == before else free * quantity // before


class Ownership:
    """保存prefixに依存せず、作成済注文・所有・未予約量を時系列で持つ。"""

    def __init__(self, key: str, saved: dict, session: str, audit: object) -> None:
        """
        機能: 一会計の保存注文から未作成要求と独立所有状態を分離する。
        引数: key/session (str)、saved (dict)、audit (object) は対象会計と差分台帳。
        返り値: None。所有・予約は空から始める。
        """
        self.key, self.saved, self.session, self.audit = key, saved, session, audit
        self.orders, self.created, self.pending, self.lots, self.seen = saved["orders"], [], [], {}, set()
        self.reference_methods = {}
        self.effects, self.closed, self.trades, self.summary = [], [], [], Counter()
        self.entries, self.legacy = defaultdict(list), defaultdict(list)
        expected_mode = "S0" + key.split("_D")[0][-2:]
        self.mode = saved["mode"]
        require(saved["mode"] == expected_mode and expected_mode in ("S0G1", "S0G2") and saved["session"] == session and saved["source_policy"] == "S" and saved["hold_enabled"] is False and saved["confirm_enabled"] is False and saved["side_cap"] == 100, "Source会計の固定政策が不正")
        self.delay = int(key[-1])
        require(number(saved["fill_delay_seconds"]) and saved["fill_delay_seconds"] == self.delay, "Source会計の遅延が不正")
        require(isinstance(self.orders, list) and isinstance(saved["source_effects"], list), "Source注文又は効果が配列でない")
        for index, o in enumerate(self.orders, 1):
            require(o["id"] == f"{session}_{self.mode}_O{index:06d}" and o["kind"] in ("entry", "exit") and o["side"] in (-1, 1) and type(o["side"]) is int, "Source注文のID・種別・符号が不正")
            for k in ("quantity", "remaining", "filled_quantity", "cancelled_quantity", "request_index", "request_line", "fill_line"):
                require(type(o[k]) is int, "Source注文の整数列が不正:" + k)
            require(1 <= o["quantity"] <= 100 and o["remaining"] >= 0 and o["filled_quantity"] >= 0 and o["cancelled_quantity"] >= 0 and number(o["request_time"]), "Source注文の量又は時計が不正")
            require(o["quantity"] == o["remaining"] + o["filled_quantity"] + o["cancelled_quantity"], "保存注文量の恒等式が不正")
            if o["kind"] == "entry":
                self.entries[o["request_time"]].append(o)
            elif not o["reason"].startswith("参照返済:") and o["reason"] not in FORCE_REASONS:
                self.legacy[o["request_line"]].append(o)

    def take(self, kind: str, ref: str, pid: str, side: int, n: int, at: float, q: dict, reason: str) -> dict:
        """
        機能: 独立に必要となった要求を保存の次注文へ結ぶ。
        引数: kind/ref/pid/reason (str)、side/n (int)、at (float)、q (dict) は期待要求。
        返り値: dict は独立の残量状態。保存末尾から状態を補完しない。
        """
        require(len(self.created) < len(self.orders), "必要な通知作用の注文が保存にない:" + self.key)
        o = self.orders[len(self.created)]
        expected = {"kind": kind, "reference_id": ref, "position_id": pid, "side": side, "quantity": n, "request_time": float(at), "request_index": q["index"], "request_line": q["line"], "reason": reason}
        check(self.audit, "時系列の要求と所有・予約", {k: o[k] for k in expected}, expected, 会計=self.key, 注文=o["id"])
        state = {"saved": o, "remaining": n, "filled": 0, "cancelled": 0, "fill_time": None, "fill_line": 0, "fill_price": None}
        self.created.append(state)
        self.pending.append(state)
        if kind == "exit":
            p = self.lots.get(ref)
            require(p is not None and p["id"] == pid and p["side"] == side and 0 < n <= p["quantity"] - p["reserved"], "返済要求が実未予約量を超える")
            p["reserved"] += n
        return state

    def cancel(self, state: dict, quantity: int) -> None:
        """
        機能: 新規未約定だけを取り消し、実所有に変換しない。
        引数: state (dict)、quantity (int) は独立注文状態と取消量。
        返り値: None。seenは取消後も残る。
        """
        require(state["saved"]["kind"] == "entry" and 0 <= quantity <= state["remaining"], "取消量又は種別が不正")
        state["remaining"] -= quantity
        state["cancelled"] += quantity

    def fill(self, q: dict) -> None:
        """
        機能: 当原行より前の要求だけを、最初の正常後原行で全残fillする。
        引数: q (dict) は当原行の独立気配。
        返り値: None。先行fillをSource作用より前に所有へ反映する。
        """
        if not q["valid"]:
            return
        keep = []
        for s in self.pending:
            o, n = s["saved"], s["remaining"]
            if n == 0:
                continue
            if q["index"] <= o["request_index"] or q["time"] < o["request_time"] + self.delay:
                keep.append(s)
                continue
            price = q["ask"] if (o["kind"] == "entry") == (o["side"] > 0) else q["bid"]
            if o["kind"] == "entry":
                require(o["reference_id"] not in self.lots, "同じ参照IDへの再実新規")
                self.lots[o["reference_id"]] = {"id": o["position_id"], "reference_id": o["reference_id"], "side": o["side"], "quantity": n, "reserved": 0, "initial_quantity": n, "closed_quantity": 0, "entry_price": price, "entry_time": q["time"], "entry_index": q["index"], "entry_line": q["line"]}
            else:
                p = self.lots.get(o["reference_id"])
                require(p is not None and p["quantity"] >= n and p["reserved"] >= n, "先行fillが実所有・予約を超える")
                p["quantity"] -= n
                p["reserved"] -= n
                p["closed_quantity"] += n
                self.closed.append({"position_id": p["id"], "reference_id": p["reference_id"], "side": p["side"], "quantity": n, "entry_price": p["entry_price"], "exit_price": price, "entry_time": p["entry_time"], "exit_time": q["time"], "exit_line": q["line"], "request_time": float(o["request_time"]), "reason": o["reason"]})
            s.update(remaining=0, filled=n, fill_time=q["time"], fill_line=q["line"], fill_price=price)
            self.trades.append({"position_id": o["position_id"], "price": price, "qty": n, "source_line": q["line"], "reason": o["reason"], "type": ("Long" if o["side"] > 0 else "Short") + ("N" if o["kind"] == "entry" else "R"), "timestamp": BASE.stamp(q["time"]), "method_id": self.mode})
        self.pending = keep

    def force(self, at: float, q: dict, reason: str) -> None:
        """
        機能: 固定timerの実ForceをSource通知より先に再構成する。
        引数: at (float)、q (dict)、reason (str) は境界時計・直前原行・理由。
        返り値: None。timerではfillを起こさない。
        """
        for s in self.pending:
            if s["saved"]["kind"] == "entry":
                self.cancel(s, s["remaining"])
        for p in sorted(self.lots.values(), key=lambda x: (x["entry_time"], x["id"])):
            n = p["quantity"] - p["reserved"]
            if n:
                self.take("exit", p["reference_id"], p["id"], p["side"], n, at, q, reason)

    def source(self, event: dict) -> None:
        """
        機能: 全通知を未約定新規と実未予約量へ比率適用し0作用も記録する。
        引数: event (dict) は原板又はtimerへ結合済みの共有通知。
        返り値: None。独立効果18項目を保存効果へ順に照合する。
        """
        q, at = event["quote"], event["at"]
        for c in event["closes"]:
            if c["reference_id"] in self.reference_methods:
                require(self.reference_methods[c["reference_id"]] == event["method"], "所有履歴のSource手法と通知手法が不一致")
            effect = {"id": c["id"], "reference_id": c["reference_id"], "at": float(at), "quote_time": float(q["time"]), "quote_index": q["index"], "quote_line": q["line"], "origin": event["origin"], "before": c["before"], "quantity": c["quantity"], "reason": c["reason"], "pending_before": 0, "cancelled": 0, "unreserved_before": 0, "exit_requested": 0, "unreserved_after": 0, "exit_order_id": "", "orders_before_count": len(self.created), "orders_after_count": 0}
            for s in self.pending:
                o = s["saved"]
                if o["kind"] == "entry" and o["reference_id"] == c["reference_id"] and s["remaining"]:
                    require(o["source_entry"]["snapshot_method"] == event["method"], "Source取消の手法が要求時と不一致")
                    effect["pending_before"] += s["remaining"]
                    n = proportion(s["remaining"], c["quantity"], c["before"])
                    self.cancel(s, n)
                    effect["cancelled"] += n
            p = self.lots.get(c["reference_id"])
            if p is not None:
                effect["unreserved_before"] = p["quantity"] - p["reserved"]
                n = proportion(effect["unreserved_before"], c["quantity"], c["before"])
                if n:
                    s = self.take("exit", p["reference_id"], p["id"], p["side"], n, at, q, "参照返済:" + c["reason"])
                    require(s["saved"]["source_entry"]["snapshot_method"] == event["method"], "Source返済の手法が要求時と不一致")
                    effect["exit_requested"], effect["exit_order_id"] = n, s["saved"]["id"]
                effect["unreserved_after"] = p["quantity"] - p["reserved"]
            effect["orders_after_count"] = len(self.created)
            ordinal = len(self.effects)
            stored = self.saved["source_effects"]
            require(ordinal < len(stored), "無所有又は0丸めを含むSource効果の保存不足")
            check(self.audit, "Source通知の独立比率作用と全字段", stored[ordinal], effect, 会計=self.key, 通知=c["id"])
            self.effects.append(effect)
            self.summary["通知"] += 1
            self.summary["timer通知"] += event["origin"] == "timer"
            self.summary["取消枚数"] += effect["cancelled"]
            self.summary["返済要求枚数"] += effect["exit_requested"]
            self.summary["0作用通知"] += effect["cancelled"] + effect["exit_requested"] == 0
            self.summary["0丸め通知"] += (effect["pending_before"] + effect["unreserved_before"] > 0 and effect["cancelled"] + effect["exit_requested"] == 0)

    def grid(self, at: float, q: dict, present: bool) -> None:
        """
        機能: 保存された定時新規を所有なし・同ID再参加なしで受理する。
        引数: at (float)、q (dict)、present (bool) は定時・直前原行・shared定時の有無。
        返り値: None。Source入口選別自体は別保存監査へ分担する。
        """
        entries = self.entries.pop(at, [])
        require(len(entries) <= 1 and (not entries or present), "一枠複数新規又はshared定時がない")
        for o in entries:
            require(not any(s["remaining"] for s in self.pending) and not any(p["quantity"] for p in self.lots.values()), "実所有又は処理中の追加新規")
            require(o["reference_id"] not in self.seen, "要求受理済み参照IDへ再参加")
            self.seen.add(o["reference_id"])
            self.reference_methods[o["reference_id"]] = o["source_entry"]["snapshot_method"]
            check(self.audit, "定時新規の段階", o["real_entry_stage"], "初参加要求", 会計=self.key)
            self.take("entry", o["reference_id"], o["position_id"], o["side"], o["quantity"], at, q, "FAR参照の初参加要求")

    def protect(self, q: dict) -> None:
        """
        機能: Source後に保存された旧保護返済だけを予約へ反映する。
        引数: q (dict) は当原行気配。
        返り値: None。旧保護の発生義務や損益を独立再実装しない。
        """
        for o in self.legacy.pop(q["line"], []):
            require(o["request_time"] == q["time"], "旧保護要求の時計が当原行と不一致")
            p = self.lots.get(o["reference_id"])
            require(p is not None, "旧保護要求に実所有なし")
            if o["harvest"]:
                require(p["reserved"] == 0, "Source先行予約を無視したG1収穫")
            self.take("exit", o["reference_id"], o["position_id"], o["side"], o["quantity"], q["time"], q, o["reason"])

    def result(self) -> dict:
        """
        機能: 作成・取消・fill・最終所有・全片と全通知の計測完了を検査する。
        引数: なし。
        返り値: dict は一会計の小型通知要約。
        """
        require(not self.entries and not self.legacy and len(self.created) == len(self.orders), "未計測の注文が残存")
        check(self.audit, "全Source効果を一度ずつ計測", len(self.saved["source_effects"]), len(self.effects), 会計=self.key)
        for s in self.created:
            o = s["saved"]
            expected = {"remaining": s["remaining"], "filled_quantity": s["filled"], "cancelled_quantity": s["cancelled"], "status": "filled" if s["filled"] else ("pending" if s["remaining"] else "cancelled"), "fill_time": s["fill_time"], "fill_line": s["fill_line"], "fill_price": s["fill_price"]}
            check(self.audit, "注文の独立取消と最初の適格fill", {k: o[k] for k in expected}, expected, 会計=self.key, 注文=o["id"])
        expected_lots = []
        for p in sorted(self.lots.values(), key=lambda x: (x["entry_time"], x["id"])):
            item = {k: v for k, v in p.items() if k != "reserved"}
            item["reserved_exit"] = p["reserved"]
            expected_lots.append(item)
        fields = ("id", "reference_id", "side", "quantity", "initial_quantity", "reserved_exit", "closed_quantity", "entry_price", "entry_time", "entry_index", "entry_line")
        observed = [{k: x[k] for k in fields} for x in self.saved["lots"]]
        check(self.audit, "全玉の実初参加と最終所有・予約", observed, expected_lots, 会計=self.key)
        check(self.audit, "最終現在玉", [p["id"] for p in self.saved["positions"]], [p["id"] for p in expected_lots if p["quantity"]], 会計=self.key)
        observed_closed = [{k: x[k] for k in y} for x, y in zip(self.saved["closed"], self.closed)]
        check(self.audit, "各返済片のfill順序", observed_closed, self.closed, 会計=self.key)
        check(self.audit, "各返済片の全件計測", len(self.saved["closed"]), len(self.closed), 会計=self.key)
        observed_trades = [{k: x[k] for k in y} for x, y in zip(self.saved["trades"], self.trades)]
        check(self.audit, "全約定の要求と原行fill", observed_trades, self.trades, 会計=self.key)
        check(self.audit, "全約定計測", len(self.saved["trades"]), len(self.trades), 会計=self.key)
        pending = [s["saved"]["id"] for s in self.created if s["saved"]["kind"] == "entry" and s["remaining"]]
        check(self.audit, "最終新規待機", [o["id"] for o in self.saved["pending_entries"]], pending, 会計=self.key)
        unresolved = any(s["remaining"] for s in self.created) or any(p["quantity"] for p in self.lots.values())
        check(self.audit, "最終未解消の正直な保存", self.saved["unresolved"], unresolved, 会計=self.key)
        self.summary["未解消会計"] = int(unresolved)
        check(self.audit, "Source参照原板監査の完結", unresolved, False, 会計=self.key)
        return {"会計": self.key, "通知": 0, "timer通知": 0, "取消枚数": 0, "返済要求枚数": 0, "0作用通知": 0, "0丸め通知": 0, "未解消会計": 0, **dict(self.summary)}


# ----------------------------------------


def inspect_one(args: tuple[str, str, dict]) -> dict:
    """
    機能: 一場原板を1走査し、全通知・全効果・時系列実所有を独立照合する。
    引数: args (tuple) は結果根、原板根、一場入力台帳。人工にも同じAPIを使う。
    返り値: dict は前後指紋、通知数、差分、会計別小型要約。
    """
    result_root, data_root, entry = args
    path = Path(result_root) / (entry["id"] + ".json")
    before = BASE.sha(path)
    saved, audit = BASE.read_json(path), BASE.Audit()
    require(saved["session"] == entry["id"] and set(saved["books"]) == set(KEYS), "場ID又は8会計が不正")
    verified = {name: BASE.verify_file(Path(data_root), info) for name, info in entry["files"].items()}
    market = verified["NK225_book"]
    raw_before = entry["files"]["NK225_book"]["sha256"]
    books = [Ownership(k, saved["books"][k], saved["session"], audit) for k in KEYS]
    timers, grids, forces, us = schedule(saved["session"])
    grid_saved = {g["at"]: g for g in saved["grid_decisions"]}
    require(len(grid_saved) == len(saved["grid_decisions"]) and set(grid_saved) <= grids, "shared定時の重複又は場外時計")
    quote_events, timer_events = defaultdict(list), defaultdict(list)
    ids, event_keys = set(), set()
    events = saved["source_events"]
    require(isinstance(events, list), "Sourceイベントが配列でない")
    for e in events:
        require(set(e) == EVENT_KEYS and e["origin"] in ("quote", "timer") and e["method"] in METHODS and number(e["at"]) and number(e["source_at"]), "Sourceイベントのschema又は時計が不正")
        q = e["quote"]
        require(set(q) == QUOTE_KEYS and type(q["index"]) is int and type(q["line"]) is int and type(q["valid"]) is bool and all(number(q[k]) for k in ("time", "last", "bid", "ask")), "Sourceイベント気配のschemaが不正")
        require(type(e["source_index"]) is int and type(e["source_line"]) is int and isinstance(e["closes"], list) and len(e["closes"]) > 0, "Source出典整数又は通知配列が不正")
        token = (e["origin"], q["line"] if e["origin"] == "quote" else e["at"], e["method"])
        require(token not in event_keys, "同じSource当行・手法のイベント重複")
        event_keys.add(token)
        for c in e["closes"]:
            require(set(c) == CLOSE_KEYS and isinstance(c["id"], str) and c["id"] and c["id"] not in ids and isinstance(c["reference_id"], str) and c["reference_id"] and isinstance(c["reason"], str), "SourceCloseのID・schema・理由が不正")
            proportion(0, c["quantity"], c["before"])
            ids.add(c["id"])
        if e["origin"] == "quote":
            quote_events[q["line"]].append(e)
        else:
            require(e["at"] in forces, "Source timer通知が固定Force時計以外")
            timer_events[e["at"]].append(e)
    expected_event_order = []
    source_positions, last = {}, {"time": 0.0, "index": 0, "line": 0, "last": 0.0, "bid": 0.0, "ask": 0.0, "valid": False}
    start, end = BASE.bounds(saved["session"])
    core_timers = set(timers)
    raw_events = RAW.RawEvents(saved, start, end, core_timers, us, audit, check)
    timers = sorted(core_timers | {start+180*n for n in range(1, int((end-start)//180)+1)})
    last["index"] = -1
    previous, index, source_index, timer_cursor = start, -1, -1, 0
    counters = Counter()

    def active_methods(at: float) -> tuple:
        """
        機能: 生成済Source手法だけを時刻から別に選ぶ。
        引数: at (float) は原行又はtimer時計。
        返り値: tuple は元固定順の手法名。
        """
        if saved["session"].endswith("_Day"):
            return (METHODS[0],)
        return (METHODS[1], METHODS[2]) if at >= us + 900 else (METHODS[1],)

    def deliver(rows: list, at: float, q: dict, origin: str) -> None:
        """
        機能: 当行イベントを固定手法順・出典へ結んだ後、全会計へ一度配送する。
        引数: rows (list)、at (float)、q (dict)、origin (str) は当回の通知。
        返り値: None。元イベント順も最後に全件照合する。
        """
        require([METHODS.index(e["method"]) for e in rows] == sorted(METHODS.index(e["method"]) for e in rows), "Sourceイベントの手法順序が不正")
        for e in rows:
            require(e["method"] in active_methods(at), "未生成又は別セッションのSource通知")
            check(audit, "Source通知の原板気配全文と要求時計", {"quote": e["quote"], "at": e["at"], "origin": e["origin"]}, {"quote": q, "at": float(at), "origin": origin}, 手法=e["method"])
            require(e["method"] in source_positions, "Source通知より前に正Last原行がない")
            expected = source_positions[e["method"]]
            check(audit, "Source通知の源時計・別Index・最新有効Last物理行", (e["source_at"], e["source_index"], e["source_line"]), expected, 手法=e["method"])
            if origin == "quote":
                require(q["last"] > 0, "Last不良行でSourceをStepした通知")
            else:
                check(audit, "timerのSource返済理由", [c["reason"] for c in e["closes"]], [forces[at]] * len(e["closes"]))
            expected_event_order.append(e)
            for b in books:
                b.source(e)

    def timer(at: float) -> None:
        """
        機能: 同時計原行より前に実Force、SourceForce通知、定時の順を検査する。
        引数: at (float) は固定timer。
        返り値: None。lastとfillは進めない。
        """
        raw_events.clock(at, last)
        if at in forces:
            for b in books:
                b.force(at, last, forces[at])
        deliver(timer_events.pop(at, []), at, last, "timer")
        if at in grids:
            for b in books:
                b.grid(at, last, at in grid_saved)

    with gzip.open(market, "rt", encoding="utf-8") as stream:
        for line, text in enumerate(stream, 1):
            counters["全物理行"] += 1
            row = json.loads(text, parse_constant=BASE.bad_constant)
            require(isinstance(row, dict) and (row.get("Symbol") is None or isinstance(row["Symbol"], str)), "原板Symbolが不正")
            at = BASE.clock(row.get("CurrentPriceTime"))
            if at is None:
                counters["時計欠測"] += 1
                continue
            if not start <= at < end:
                counters["場外"] += 1
                continue
            if at < previous:
                counters["逆時計"] += 1
                continue
            previous, index = at, index + 1
            counters["全受理NK原行"] += 1
            values = {}
            for side in ("Buy", "Sell"):
                for level in range(1, 11):
                    field = side + str(level)
                    require(field in row and (row[field] is None or isinstance(row[field], dict)), "原板の10段schema不正")
                    cell = row[field] or {}
                    value = BASE.go_number(cell.get("Price"))
                    BASE.go_number(cell.get("Qty"))
                    if level == 1:
                        values[side] = value
            bid, ask, price = values["Buy"], values["Sell"], BASE.go_number(row.get("CurrentPrice"))
            q = {"time": float(at), "index": index, "line": line, "last": price, "bid": bid, "ask": ask, "valid": price > 0 and 0 < bid < ask}
            counters["Last不良"] += price <= 0
            counters["BBO不良"] += not 0 < bid < ask
            while timer_cursor < len(timers) and timers[timer_cursor] <= at:
                timer(timers[timer_cursor])
                timer_cursor += 1
            if price > 0:
                source_index += 1
                counters["正Last源原行"] += 1
                for method in active_methods(at):
                    source_positions[method] = (float(at), source_index, line)
            raw_events.quote(q, source_index)
            for b in books:
                b.fill(q)
            deliver(quote_events.pop(line, []), at, q, "quote")
            for b in books:
                b.protect(q)
            last = q
    while timer_cursor < len(timers):
        timer(timers[timer_cursor])
        timer_cursor += 1
    require(not quote_events and not timer_events, "未結合Sourceイベントが残存")
    check(audit, "共有Sourceイベントの全件・全原行順", expected_event_order, events)
    eq = saved["source_equivalence"]
    require(all(type(eq[k]) is int and eq[k] >= 0 for k in ("step_frames", "force_frames", "grid_frames", "mismatches")) and eq["step_frames"] + eq["force_frames"] + eq["grid_frames"] > 0, "固定80同値driverの計測が不正又は未計測")
    check(audit, "固定80同値driverの差分0", eq["mismatches"], 0)
    require(isinstance(eq["current_sha256"], str) and len(eq["current_sha256"]) == 64 and eq["current_sha256"] == eq["legacy_sha256"], "固定80全frame同値指紋が不一致又は未計測")
    summaries = [b.result() for b in books]
    event_summary = raw_events.finish(last)
    after = BASE.sha(path)
    for info in entry["files"].values():
        BASE.verify_file(Path(data_root), info)
    raw_after = entry["files"]["NK225_book"]["sha256"]
    check(audit, "結果入力の前後不変", after, before)
    check(audit, "原板入力の前後不変", raw_after, raw_before)
    return {"session": saved["session"], "処理完了": True, "再生結果SHA256": before, "再生結果SHA256前": before, "再生結果SHA256後": after, "原板SHA256前": raw_before, "原板SHA256後": raw_after, "入力前後不変": before == after and raw_before == raw_after,
        "会計数": len(books), "Sourceイベント数": len(events), "Source通知数": len(ids), "Source効果数": sum(len(b.effects) for b in books), "照合項目数": audit.checks, "不一致数": audit.errors, "不一致": audit.details,
        "原板観測": dict(counters), "各会計通知要約": summaries, "source_equivalence": eq, "入口足原板結合": event_summary}


def main() -> None:
    """
    機能: 明示された固定66場だけを独立並列読取し、小型監査正本を新規保存する。
    引数: --results/--manifest/--out (Path)、--workers (int) はCLIの必須対象と並列数。
    返り値: None。未完・例外・不一致は非0終了し既存先を上書きしない。
    """
    parser = argparse.ArgumentParser(description="89 Source通知/同一eventとG1G2の所有出典監査")
    for name in ("results", "manifest", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    require(not args.out.exists() and 1 <= args.workers <= 16, "既存出力又はworkers範囲が不正")
    ledger_before = BASE.sha(args.manifest)
    code_before = BASE.sha(Path(__file__))
    raw_code_before, event_code_before = BASE.sha(RAW_PATH), BASE.sha(EVENT_PATH)
    fixed88_before, ownership_before = BASE.sha(FIXED88_PATH), BASE.sha(OWNERSHIP_PATH)
    ledger = BASE.read_json(args.manifest)
    require(len(ledger["sessions"]) == 66 and len({e["id"] for e in ledger["sessions"]}) == 66, "正式Source通知監査は固定66場が必要")
    tasks = [(str(args.results.resolve()), ledger["source_root"], entry) for entry in ledger["sessions"]]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(inspect_one, tasks))
    require(BASE.sha(Path(__file__)) == code_before and BASE.sha(HELPER_PATH) == HELPER_SHA and BASE.sha(FIXED87_PATH) == FIXED87_SHA and BASE.sha(RAW_PATH) == raw_code_before and BASE.sha(EVENT_PATH) == event_code_before and BASE.sha(FIXED88_PATH) == fixed88_before == FIXED88_SHA and BASE.sha(OWNERSHIP_PATH) == ownership_before == OWNERSHIP_SHA, "実行中の監査コード変更")
    require(len(rows) == 66 and sum(r["会計数"] for r in rows) == 528, "正式66場528会計の不足")
    ledger_after = BASE.sha(args.manifest)
    errors = sum(r["不一致数"] for r in rows)
    unchanged = ledger_after == ledger_before and all(r["入力前後不変"] for r in rows)
    summary = Counter()
    for row in rows:
        for account in row["各会計通知要約"]:
            summary.update({k: v for k, v in account.items() if k != "会計"})
    value = {"試行": 89, "成功": errors == 0 and unchanged, "処理完了": True, "場数": len(rows), "会計数": sum(r["会計数"] for r in rows),
        "Sourceイベント数": sum(r["Sourceイベント数"] for r in rows), "Source通知数": sum(r["Source通知数"] for r in rows), "Source効果数": sum(r["Source効果数"] for r in rows), "照合項目数": sum(r["照合項目数"] for r in rows), "不一致数": errors, "入力前後不変": unchanged,
        "入力台帳SHA256": ledger_before, "入力台帳SHA256前": ledger_before, "入力台帳SHA256後": ledger_after, "監査コードSHA256": code_before, "固定80監査SHA256": HELPER_SHA, "固定87通知監査SHA256": FIXED87_SHA, "固定88通知監査SHA256": FIXED88_SHA, "固定88所有ID比較SHA256": OWNERSHIP_SHA, "イベント原板コードSHA256": raw_code_before, "イベント保存コードSHA256": event_code_before,
        "入口足原板結合": {"場数": len(rows), "原板結合trace": sum(r["入口足原板結合"]["原板結合trace"] for r in rows), "利益snapshot": sum(r["入口足原板結合"]["利益snapshot"] for r in rows), "全call": sum(r["入口足原板結合"]["全call"] for r in rows)},
        "原板本文走査回数毎場": 1, "新売買再生": 0, "要約": dict(summary), "限界": LIMITS, "不一致": [e for r in rows for e in r["不一致"]], "対象場": rows}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "場数", "会計数", "Source通知数", "不一致数", "照合項目数")}, ensure_ascii=False))
    if not value["成功"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
