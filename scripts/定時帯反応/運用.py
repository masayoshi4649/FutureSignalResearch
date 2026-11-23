"""定時の新規判断と、定時外の連続保護を分ける標準ライブラリ運用。"""

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import heapq
import math


JST = timezone(timedelta(hours=9))
EVENT_FIELDS = {"now", "line", "last", "bid", "ask", "valid"}
SLOT_FIELDS = {"scheduled", "time", "line", "side", "role", "atr", "D", "reason", "ready", "slot_id"}
ROLES = {"順行", "反転"}
POINT_VALUE, FEE, ARM_COST = 10, 11, Decimal(122)


def finite(value: object) -> bool:
    """真偽値を除いた有限の数値を判定する。

    引数: value(object)は入力値。
    返り値: boolは有限数値ならTrue。文字列で数値を補完しない。
    """
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and math.isfinite(value)


def number(value: object, name: str) -> float:
    """有限数値を浮動値へ写し、入力違反を拒否する。

    引数: value(object)は値、name(str)は項目名。
    返り値: floatは有限値。不正値ならValueError。
    """
    if not finite(value):
        raise ValueError(name + "は有限数値が必要")
    return float(value)


def session_bounds(session: str) -> dict:
    """場名からJSTの開始・強制要求・連続終了時計を作る。

    引数: session(str)はYYYY-MM-DD_Day又はNight。
    返り値: dictはstart/force/endのepoch秒。ナイトは翌日へ進める。
    """
    day_text, kind = session.rsplit("_", 1)
    day = datetime.strptime(day_text, "%Y-%m-%d").date()
    if kind == "Day":
        clocks = (datetime.combine(day, time(8, 45), JST), datetime.combine(day, time(15, 35), JST), datetime.combine(day, time(15, 40), JST))
    elif kind == "Night":
        following = day + timedelta(days=1)
        clocks = (datetime.combine(day, time(17), JST), datetime.combine(following, time(5, 50), JST), datetime.combine(following, time(5, 55), JST))
    else:
        raise ValueError("場名のDay/Nightが不正")
    return dict(zip(("start", "force", "end"), (v.timestamp() for v in clocks)))


def scheduled_times(session: str) -> list[float]:
    """初回を除いた定時判断の予定時計を作る。

    引数: session(str)は対象場。
    返り値: list[float]はDay09:15〜15:15の25枠、Night17:30〜翌05:30の49枠。
    """
    bounds = session_bounds(session)
    first = bounds["start"] + 30 * 60
    last = bounds["force"] - 20 * 60
    return [first + 900 * i for i in range(int((last - first) // 900) + 1)]


def normal_bbo(event: dict) -> bool:
    """価格時計とは別に、元の数量正常旗を含む正常BBOを判定する。

    引数: event(dict)は原行のnow/line/last/bid/ask/valid。
    返り値: boolはvalidかつ有限正bid<ask。数量旗を再生成しない。
    """
    return event["valid"] is True and finite(event["bid"]) and finite(event["ask"]) and 0 < event["bid"] < event["ask"]


def signed_distance(side: int, mark: float, entry: float) -> float:
    """十進表記の価格差を実方向ptへ写す。

    引数: side(int)は±1、mark/entry(float)は現在返済BBOと新規価格。
    返り値: floatは方向差。追尾線へ任意epsilonを加えない。
    """
    return float(Decimal(side) * (Decimal(str(mark)) - Decimal(str(entry))))


def current_net(side: int, mark: float, entry: float) -> Decimal:
    """現在返済BBOから参照5ptの正味含み益円を厳密に比較可能にする。

    引数: side(int)は±1、mark/entry(float)は価格。
    返り値: Decimalは実方向差×10−122円。過去MFEを代入しない。
    """
    return Decimal(side) * (Decimal(str(mark)) - Decimal(str(entry))) * POINT_VALUE - ARM_COST


def timestamp(now: float) -> str:
    """epoch秒をViewerのJST時刻へ写す。

    引数: now(float)は価格又は要求時計。
    返り値: strは時差付きISO8601。価格時計を受信時計と呼ばない。
    """
    return datetime.fromtimestamp(now, JST).isoformat()


def activity_metrics(decisions: list[dict]) -> dict:
    """全予定枠を分母に、主待ち率と判定不能を待ちへ含む保守上限を作る。

    引数: decisions(list[dict])は各枠一件のactionを持つ判断。
    返り値: dictは活動集計。保有継続/処理中は待ちでなく、欠測を達成へ利用しない。
    """
    actions = ("買い新規要求", "売り新規要求", "待ち", "保有継続", "処理中", "判定不能")
    if any(row["action"] not in actions for row in decisions):
        raise ValueError("未知の定時分類")
    count = len(decisions)
    counts = {name: sum(r["action"] == name for r in decisions) for name in actions}
    wait, invalid = counts["待ち"], counts["判定不能"]
    return {"予定枠数": count, "判断別数": counts, "待ち数": wait, "主待ち率": wait / count if count else None, "保守待ち率上限": (wait + invalid) / count if count else None, "全枠判定可能": invalid == 0, "待ち率条件適格": bool(count) and 2 * (wait + invalid) <= count}


class Engine:
    """一候補の一pending・一建玉と定時判断を管理する。"""

    def __init__(self, slots: list[dict], session: str, candidate_id: str, bounds: dict | None):
        """候補と予定枠を検査し、独立タイマーを準備する。

        引数: slots(list[dict])は純判断、session/candidate_id(str)は識別、bounds(dict|None)は時計。
        返り値: None。市場ファイル・旧エンジンを参照しない。
        """
        self.session, self.candidate = session, candidate_id
        self.bounds = session_bounds(session) if bounds is None else {k: number(bounds[k], k) for k in ("start", "force", "end")}
        if not self.bounds["start"] < self.bounds["force"] < self.bounds["end"]:
            raise ValueError("開始<強制<終了が必要")
        self.slots, self.by_line, self.done, self.timers = [], {}, set(), []
        self.decisions, self.trades, self.closed, self.trail, self.orders = [], [], [], [], []
        self.position = self.pending = None
        self.last_time = self.last_line = self.last_quote_time = None
        self.raw_line, self.forced, self.counter = 0, False, 0
        self.gap_had_entry_pending = False
        self.quality = {k: 0 for k in ("時計不正行数", "時計後退行数", "非正常BBO行数", "空き時間長気配間隔数", "新規待機長気配間隔数", "保有中長気配間隔数", "判定不能枠数")}
        self.quality["損益注意理由"] = []
        previous = None
        for i, source in enumerate(slots, 1):
            if not isinstance(source, dict) or set(source) - SLOT_FIELDS or not (SLOT_FIELDS - {"slot_id"}) <= set(source):
                raise ValueError("slotは純判断の既定字段だけが必要。未来label等を渡さない")
            row = deepcopy(source)
            row["scheduled"] = number(row["scheduled"], "scheduled")
            row["time"] = number(row["time"], "time")
            row["slot_id"] = row.get("slot_id", candidate_id + "_定時" + str(i).zfill(4))
            if not isinstance(row["slot_id"], str) or not (isinstance(row["reason"], str) or isinstance(row["reason"], list) and all(isinstance(v, str) for v in row["reason"])):
                raise ValueError("識別子/理由は文字列。理由へlabelやcontextを混ぜない")
            if previous is not None and row["scheduled"] <= previous:
                raise ValueError("予定時計は重複なし昇順")
            if not self.bounds["start"] <= row["scheduled"] < self.bounds["force"] or type(row["ready"]) is not bool or type(row["side"]) is not int or row["side"] not in (-1, 0, 1):
                raise ValueError("slot時計/ready/sideが不正")
            if row["line"] is None:
                if row["time"] != row["scheduled"] or row["ready"] is not False:
                    raise ValueError("欠測placeholderはtime=scheduled/line=None/ready=False")
                heapq.heappush(self.timers, (row["time"], 1, "missing", i - 1))
            else:
                if type(row["line"]) is not int or row["line"] < 1 or not 0 <= row["time"] - row["scheduled"] <= 30:
                    raise ValueError("実slotは後続原行と0〜30秒遅延が必要")
                if row["line"] in self.by_line:
                    raise ValueError("複数枠を同じ原行へ結合しない")
                self.by_line[row["line"]] = i - 1
            self.slots.append(row)
            previous = row["scheduled"]
        if len({r["slot_id"] for r in self.slots}) != len(self.slots):
            raise ValueError("slot_id重複")
        heapq.heappush(self.timers, (self.bounds["force"], 0, "force", 0))

    def snapshot(self) -> dict:
        """保護・注文・建玉の現在値を複製する。

        引数: なし。
        返り値: dictは循環参照や将来値を含まない現在状態。
        """
        return {"position": deepcopy(self.position), "pending": deepcopy(self.pending), "forced": self.forced}

    def log(self, action: str, now: float, line: int | None, **fields) -> None:
        """変化・要求・約定・定時判断を追尾へ保存する。

        引数: action(str)は動作、now(float)/line(int|None)は出典、fields(dict)は追加根拠。
        返り値: None。変化のない全tickを重複保存しない。
        """
        self.trail.append({"action": action, "time": now, "line": line, **deepcopy(fields), "state": self.snapshot()})

    def caution(self, reason: str) -> None:
        """損益確定を妨げる理由を重複なしで残す。

        引数: reason(str)は理由。
        返り値: None。空き時間の注意はこの関数へ渡さない。
        """
        if reason not in self.quality["損益注意理由"]:
            self.quality["損益注意理由"].append(reason)

    def request(self, kind: str, now: float, line: int | None, reason: str, slot: dict | None = None) -> None:
        """新規又は返済を一件だけ要求する。

        引数: kind(str)はentry/exit、now/lineは要求出典、reason(str)、slot(dict|None)は新規根拠。
        返り値: None。新規TTLだけ30秒、返済に架空の期限約定を作らない。
        """
        if self.pending is not None:
            raise ValueError("pendingの上書き禁止")
        self.counter += 1
        order = {"id": self.candidate + "_注文" + str(self.counter).zfill(5), "kind": kind, "request_time": now, "request_line": line, "eligible_time": now + 1, "expires": now + 30 if kind == "entry" else None, "reason": reason, "status": "pending"}
        if slot is not None:
            order["slot"] = deepcopy(slot)
        elif self.position is None:
            raise ValueError("返済対象なし")
        self.orders.append(order)
        self.pending = order
        if kind == "entry":
            self.gap_had_entry_pending = True
            heapq.heappush(self.timers, (order["expires"], 3, "expiry", self.counter))
        self.log("新規要求" if kind == "entry" else "返済要求", now, line, reason=reason, order_id=order["id"])

    def cancel_entry(self, now: float, reason: str) -> None:
        """未約定の新規だけを取消し、次枠まで取り直さない。

        引数: now(float)は取消時計、reason(str)は理由。
        返り値: None。既存返済pendingには触れない。
        """
        if self.pending is not None and self.pending["kind"] == "entry":
            order = self.pending
            order.update(status="cancelled", cancel_time=now, cancel_reason=reason)
            self.pending = None
            self.log("新規取消", now, self.last_line, reason=reason, order_id=order["id"])

    def drain_timers(self, until: float, final: bool = False) -> None:
        """原行の間にも欠測判断・強制・新規期限のタイマーを処理する。

        引数: until(float)は次原行又は終了時計、final(bool)は終了確定。
        返り値: None。TTL等号の正常BBOは先に約定できる。
        """
        while self.timers:
            now, priority, kind, token = self.timers[0]
            if now > until or now == until and kind == "expiry" and not final:
                break
            heapq.heappop(self.timers)
            if kind == "missing":
                self.decide(token, None)
            elif kind == "force":
                self.forced = True
                self.cancel_entry(now, "強制時刻")
                if self.position is not None and self.pending is None:
                    self.request("exit", now, self.last_line, "場末強制")
                self.log("強制時計", now, self.last_line)
            elif self.pending is not None and self.pending["kind"] == "entry" and self.pending["id"].endswith(str(token).zfill(5)):
                self.cancel_entry(now, "新規TTL30秒")

    def mark_actual(self, event: dict) -> None:
        """実保有のMFE/MAEを保護状態とは別に更新する。

        引数: event(dict)は正常BBO。
        返り値: None。返済pending中も実経路を測るがh/L/armを更新しない。
        """
        if self.position is not None:
            p = self.position
            mark = event["bid"] if p["side"] == 1 else event["ask"]
            r = signed_distance(p["side"], mark, p["entry_price"])
            p["mfe"], p["mae"] = max(p["mfe"], r), min(p["mae"], r)

    def fill_pending(self, event: dict) -> None:
        """要求+1秒かつ後原行の最初の正常BBOで約定する。

        引数: event(dict)は正常BBO。
        返り値: None。新規TTL30秒等号可、価格へ滑りを加算しない。
        """
        order = self.pending
        if order is None or event["now"] < order["eligible_time"] or order["request_line"] is not None and event["line"] <= order["request_line"]:
            return
        now, line = event["now"], event["line"]
        if order["kind"] == "entry":
            if now > order["expires"] or self.forced:
                self.cancel_entry(now, "新規期限又は強制")
                return
            slot = order["slot"]
            side = slot["side"]
            price = float(event["ask"] if side == 1 else event["bid"])
            position_id = self.candidate + "_建玉" + str(len(self.closed) + 1).zfill(5)
            self.position = {"id": position_id, "slot_id": slot["slot_id"], "side": side, "role": slot["role"], "entry_time": now, "entry_line": line, "entry_price": price, "entry_request_time": order["request_time"], "entry_request_line": order["request_line"], "entry_atr": float(slot["atr"]), "D": float(slot["D"]), "h": 0.0, "L": max(-125.0, -float(slot["D"])), "arm": False, "arm_time": None, "arm_line": None, "arm_r": None, "arm_net": None, "mfe": 0.0, "mae": 0.0}
            trade_type = "LongN" if side == 1 else "ShortN"
        else:
            p = self.position
            side, position_id = p["side"], p["id"]
            price = float(event["bid"] if side == 1 else event["ask"])
            cash = Decimal(side) * (Decimal(str(price)) - Decimal(str(p["entry_price"]))) * POINT_VALUE - 2 * FEE
            closed = {**deepcopy(p), "exit_time": now, "exit_line": line, "exit_price": price, "exit_request_time": order["request_time"], "exit_request_line": order["request_line"], "exit_reason": order["reason"], "pnl0": float(cash), "pnl5": float(cash - 100), "pnl10": float(cash - 200)}
            self.closed.append(closed)
            self.position = None
            trade_type = "LongR" if side == 1 else "ShortR"
        order.update(status="filled", fill_time=now, fill_line=line, fill_price=price)
        self.pending = None
        self.trades.append({"id": self.candidate + "_約定" + str(len(self.trades) + 1).zfill(5), "timestamp": timestamp(now), "type": trade_type, "position_id": position_id, "price": price, "qty": 1, "fee_yen": 61, "method_id": self.candidate, "source_line": line})
        self.log("新規約定" if order["kind"] == "entry" else "返済約定", now, line, order_id=order["id"], price=price)

    def protect(self, event: dict) -> None:
        """正常BBOで現在益起動と損失/利益の連続保護を更新する。

        引数: event(dict)は新規fill当行を含む正常BBO。
        返り値: None。返済pending後のh/L/armは凍結する。
        """
        if self.position is None or self.pending is not None:
            return
        p = self.position
        mark = float(event["bid"] if p["side"] == 1 else event["ask"])
        r = signed_distance(p["side"], mark, p["entry_price"])
        before = (p["h"], p["L"], p["arm"])
        p["h"] = max(0.0, p["h"], r)
        p["L"] = max(p["L"], -125.0, p["h"] - p["D"])
        net = current_net(p["side"], mark, p["entry_price"])
        if not p["arm"] and net > 0:
            p.update(arm=True, arm_time=event["now"], arm_line=event["line"], arm_r=r, arm_net=float(net))
        if p["arm"]:
            p["L"] = max(p["L"], 0.0)
        if before != (p["h"], p["L"], p["arm"]):
            self.log("保護更新", event["now"], event["line"], r=r, current_net=float(net), mark=mark)
        if r <= p["L"]:
            self.request("exit", event["now"], event["line"], "連続追尾")

    def decide(self, index: int, event: dict | None) -> None:
        """定時枠を欠測・処理中・保有・新規・待ちの一分類へ写す。

        引数: index(int)は枠番号、event(dict|None)は確定原行又は欠測placeholder。
        返り値: None。無効BBOを優先し、保有中は指標準備を課さない。
        """
        if index in self.done:
            raise ValueError("枠の再試行禁止")
        self.done.add(index)
        slot = self.slots[index]
        holding, pending = self.position is not None, self.pending["kind"] if self.pending else None
        row = {**deepcopy(slot), "holding": holding, "pending_kind": pending, "position_id": self.position["id"] if holding else None}
        if event is None or not normal_bbo(event):
            action, reason = "判定不能", "判断時計欠測" if event is None else "判断BBO非正常"
        elif self.pending is not None:
            action, reason = "処理中", "新規又は返済の約定待ち"
        elif holding:
            action, reason = "保有継続", "保有中は指標ready不問"
        elif not slot["ready"]:
            action, reason = "判定不能", slot["reason"]
        elif self.forced:
            action, reason = "待ち", "強制時刻以降"
        elif slot["side"] == 0:
            action, reason = "待ち", slot["reason"]
        else:
            if slot["role"] not in ROLES or not finite(slot["atr"]) or slot["atr"] <= 0 or not finite(slot["D"]) or not 5 <= slot["D"] <= 125:
                raise ValueError("新規には実役割・有限正ATR・5<=D<=125が必要")
            action, reason = "買い新規要求" if slot["side"] == 1 else "売り新規要求", slot["reason"]
            self.request("entry", slot["time"], slot["line"], str(reason), slot)
        row.update(action=action, decision_reason=reason, wait=action == "待ち", activity_valid=action != "判定不能")
        if action == "判定不能":
            self.quality["判定不能枠数"] += 1
        self.decisions.append(row)
        self.log("定時判断", slot["time"], slot["line"], decision=row)

    def run(self, events) -> dict:
        """原行順にタイマー・約定・連続保護・定時判断を一回走査する。

        引数: events(iterable[dict])は最小6字段の原行。
        返り値: dictは判断/Viewer約定/完結/追尾/注文/品質/集計と残状態。
        """
        for source in events:
            if not isinstance(source, dict) or set(source) != EVENT_FIELDS or type(source["valid"]) is not bool or type(source["line"]) is not int or source["line"] <= self.raw_line:
                raise ValueError("原行schema/昇順line違反。未来label等を含めない")
            self.raw_line = source["line"]
            index = self.by_line.get(source["line"])
            if not finite(source["now"]):
                self.quality["時計不正行数"] += 1
                if index is not None:
                    raise ValueError("slotを時計不正行へ結合している")
                continue
            now = float(source["now"])
            if self.last_time is not None and now < self.last_time:
                self.quality["時計後退行数"] += 1
                if index is not None:
                    raise ValueError("slotを後退時計へ結合している")
                continue
            if now < self.bounds["start"]:
                continue
            if now >= self.bounds["end"]:
                break
            self.drain_timers(now)
            event = {**source, "now": now}
            self.last_time, self.last_line = now, event["line"]
            for pending_index, row in enumerate(self.slots):
                if pending_index not in self.done and row["line"] is not None and row["scheduled"] <= now and row["line"] != event["line"]:
                    raise ValueError("slotはT以後最初の有限非後退時計の原行へ結合する")
            if normal_bbo(event):
                if self.last_quote_time is not None and now - self.last_quote_time > 300:
                    if self.position is not None:
                        self.quality["保有中長気配間隔数"] += 1
                        self.caution("建玉又は返済pending中に正常気配間隔300秒超")
                    elif self.pending is not None or self.gap_had_entry_pending:
                        self.quality["新規待機長気配間隔数"] += 1
                    else:
                        self.quality["空き時間長気配間隔数"] += 1
                self.last_quote_time = now
                self.gap_had_entry_pending = False
                self.mark_actual(event)
                self.fill_pending(event)
                self.mark_actual(event)
                self.protect(event)
            else:
                self.quality["非正常BBO行数"] += 1
            if index is not None:
                if self.slots[index]["time"] != now:
                    raise ValueError("slotの判断時計と原行時計が不一致")
                self.decide(index, event)
        self.drain_timers(self.bounds["end"], final=True)
        if len(self.done) != len(self.slots):
            raise ValueError("実判断原行が見つからないslotがある")
        if self.position is not None or self.pending is not None:
            self.caution("場末の建玉又は返済pending未解消")
        activity = activity_metrics(self.decisions)
        activity_valid = activity["待ち率条件適格"]
        earnings_valid = not self.quality["損益注意理由"]
        observed = {str(f): sum(r["pnl" + str(f)] for r in self.closed) for f in (0, 5, 10)}
        ledger = {str(f): observed[str(f)] - (FEE + 10 * f if self.position is not None else 0) for f in (0, 5, 10)}
        self.quality.update(活動評価適格=activity_valid, 全枠判定可能=activity["全枠判定可能"], 損益確定可能=earnings_valid, 未解消建玉数=int(self.position is not None), 未解消注文数=int(self.pending is not None))
        metrics = {**activity, "完結数": len(self.closed), "完結取引観測純額円": observed, "約定台帳観測確定円": ledger, "全体確定対象円": {k: v if earnings_valid else None for k, v in ledger.items()}}
        return {"decisions": self.decisions, "trades": self.trades, "fills": deepcopy(self.trades), "closed": self.closed, "trail": self.trail, "orders": self.orders, "quality": self.quality, "metrics": metrics, "final_state": self.snapshot(), "session": self.session, "candidate_id": self.candidate, "bounds": self.bounds}


def replay(events, slots: list[dict], session: str, candidate_id: str = "S0", bounds: dict | None = None) -> dict:
    """一候補を市場ファイルなしで再生する公開入口。

    引数: events(iterable[dict])は原行、slots(list[dict])は純判断、session/candidate_id(str)は識別、bounds(dict|None)は人工時計。
    返り値: dictは保存可能な運用結果。旧モデルをimportせず入力を変更しない。
    """
    return Engine(slots, session, candidate_id, bounds).run(events)
