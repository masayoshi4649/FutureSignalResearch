"""定時の条件登録と将来価格の発動を分け、固定49の約定と保護を再用する。"""

from copy import deepcopy
import heapq
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = ROOT / "scripts/定時帯反応/運用.py"
_SPEC = importlib.util.spec_from_file_location("価格発動67の固定49運用", LEGACY_PATH)
LEGACY = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = LEGACY
_SPEC.loader.exec_module(LEGACY)

EVENT_FIELDS, SLOT_FIELDS, ROLES = LEGACY.EVENT_FIELDS, LEGACY.SLOT_FIELDS, LEGACY.ROLES
finite, number, normal_bbo = LEGACY.finite, LEGACY.number, LEGACY.normal_bbo
session_bounds, scheduled_times = LEGACY.session_bounds, LEGACY.scheduled_times
signed_distance, current_net = LEGACY.signed_distance, LEGACY.current_net
RULES = {
    "設定": "原定時の正常BBOと有限正Last。既strict外側は拒否、等号可",
    "発動": "設定keyよりstrict後の買Last>high又は売Last<low。線価格で約定しない",
    "寿命": "scheduled+900。次定時等号はwatchと出自新規pending取消が約定より先",
    "観測": "設定timeから正常BBOかつ有限正Lastの間隔300秒超を突破より先に取消。満了時計も検査",
    "凍結": "元slotのside/role/ATR/D。監視中の指標更新と否定価格線は追加しない",
    "保護": "固定49の要求+1秒、TTL30、現在122円strict起動、非緩和、最低名目新規床",
    "活動": "主待ちはWAITのみ。保守はWAIT+判定不能+登録したが新規約定なしを全予定枠で割る",
}


def normal_observation(event: dict) -> bool:
    """条件監視に必要な気配とLastの両方を確認する。

    引数: event(dict)は価格時計の最小6フィールド。
    返り値: boolは元valid旗を含む正常BBOかつ有限正LastならTrue。
    """
    return normal_bbo(event) and finite(event["last"]) and event["last"] > 0


def activity_metrics(decisions: list[dict], conditions: dict) -> dict:
    """当時の行動と、登録後の未約定を異なる分母欄で集計する。

    引数: decisions(list[dict])は全予定枠、conditions(dict)は条件結果。
    返り値: dictは主待ちと保守待ち、条件登録数・条件未約定数。
    """
    actions = ("条件登録", "待ち", "保有継続", "処理中", "判定不能")
    if any(row["action"] not in actions for row in decisions):
        raise ValueError("未知の定時分類")
    counts = {name: sum(row["action"] == name for row in decisions) for name in actions}
    count = len(decisions)
    registered = sum(row["registered"] for row in conditions.values())
    unfilled = sum(row["registered"] and not row["entry_filled"] for row in conditions.values())
    wait, invalid = counts["待ち"], counts["判定不能"]
    conservative = wait + invalid + unfilled
    if registered != counts["条件登録"] or conservative > count:
        raise ValueError("条件登録と予定枠の活動集計に不整合")
    return {"予定枠数": count, "判断別数": counts, "待ち数": wait,
        "主待ち率": wait / count if count else None,
        "保守待ち率上限": conservative / count if count else None,
        "全枠判定可能": invalid == 0,
        "待ち率条件適格": bool(count) and 2 * conservative <= count,
        "条件登録数": registered, "条件未約定": unfilled}


# ----------------------------------------


class Engine(LEGACY.Engine):
    """一つの条件監視と固定49の一注文・一建玉を時系列で管理する。"""

    def __init__(self, slots: list[dict], conditions: dict, session: str,
            candidate_id: str, bounds: dict | None = None):
        """原判断を変更せず条件と満了タイマーを検査する。

        引数: slots(list[dict])は固定49純判断、conditions(dict)はslot_id別条件、session/candidate_id(str)は識別、bounds(dict|None)は人工時計。
        返り値: None。sourceの当時可視性は呼出側が検査し、本関数は価格と寿命を検査する。
        """
        super().__init__(slots, session, candidate_id, bounds)
        self.watch = None
        self.conditions, self.condition_trace = {}, []
        self.quality["条件監視観測不足取消数"] = 0
        if not isinstance(conditions, dict):
            raise ValueError("conditionsはslot_id辞書が必要")
        by_id = {slot["slot_id"]: (index, slot) for index, slot in enumerate(self.slots)}
        for slot_id, condition in conditions.items():
            if slot_id not in by_id or not isinstance(condition, dict) or set(condition) != {"high", "low", "source", "expires"}:
                raise ValueError("未知slot又は条件schema違反")
            index, slot = by_id[slot_id]
            if not isinstance(condition["source"], dict):
                raise ValueError("条件sourceは不透明な出典辞書が必要")
            high, low = number(condition["high"], "high"), number(condition["low"], "low")
            expires = number(condition["expires"], "expires")
            if not 0 < low <= high or expires != slot["scheduled"] + 900 or not slot["time"] < expires < self.bounds["force"]:
                raise ValueError("条件は有限正high>=low、expires=scheduled+900<forceが必要")
            origin = {"slot_id": slot_id, "session": session,
                **{key: slot[key] for key in ("scheduled", "time", "line")}}
            self.conditions[slot_id] = {"condition": deepcopy(condition), "origin_slot": origin,
                "slot": deepcopy(slot), "registered": False, "watch_started": False,
                "status": "未評価", "condition_outcome": "未登録", "condition_reason": "未評価",
                "watch_quality": False, "last_observation_time": None,
                "trigger": None, "request_time": None, "request_line": None, "order_id": None,
                "entry_filled": False, "entry_time": None, "entry_line": None, "entry_price": None,
                "end_time": None, "end_line": None}
            heapq.heappush(self.timers, (expires, -1, "condition_expiry", index))

    def snapshot(self) -> dict:
        """注文と建玉に、出典を重複しない監視状態を添える。

        引数: なし。
        返り値: dictは固定49状態とwatchの深い複製。
        """
        return {**super().snapshot(), "watch": deepcopy(getattr(self, "watch", None))}

    def condition_log(self, action: str, slot_id: str, now: float,
            line: int | None, reason: str) -> None:
        """条件の状態遷移だけを小型の別追尾へ残す。

        引数: action/slot_id/reason(str)は動作・元枠・理由、now(float)/line(int|None)は出典。
        返り値: None。全tickやsource全文を各遷移へ転記しない。
        """
        self.condition_trace.append({"action": action, "slot_id": slot_id,
            "time": now, "line": line, "reason": reason})

    def end_watch(self, now: float, line: int | None, reason: str,
            insufficient: bool = False) -> None:
        """未発動監視を終了し、観測不足だけを損益注意へ接続する。

        引数: now(float)/line(int|None)は終了出典、reason(str)は理由、insufficient(bool)は監視不足。
        返り値: None。未登録のLast不正はこの関数を通さない。
        """
        if self.watch is None:
            return
        slot_id = self.watch["slot_id"]
        row = self.conditions[slot_id]
        outcome = "観測不足" if insufficient else "未発動"
        row.update(status="終了", condition_outcome=outcome, condition_reason=reason,
            watch_quality=insufficient, end_time=now, end_line=line)
        self.watch = None
        if insufficient:
            self.quality["条件監視観測不足取消数"] += 1
            self.caution("条件監視の正常BBOかつ有限正Lastの間隔300秒超")
        self.condition_log("条件取消", slot_id, now, line, reason)

    def cancel_entry(self, now: float, reason: str) -> None:
        """固定49の新規取消と、条件の発動未約定を一緒に保存する。

        引数: now(float)は取消時計、reason(str)は理由。
        返り値: None。返済pendingは維持する。
        """
        order = self.pending
        slot_id = order["slot"]["slot_id"] if order is not None and order["kind"] == "entry" else None
        super().cancel_entry(now, reason)
        if slot_id is not None:
            self.conditions[slot_id].update(status="終了", condition_outcome="発動未約定",
                condition_reason=reason, end_time=now, end_line=self.last_line)
            self.condition_log("条件新規取消", slot_id, now, self.last_line, reason)

    def fill_pending(self, event: dict) -> None:
        """固定49の最初正常BBO約定を、その元条件へ接続する。

        引数: event(dict)は正常BBO。
        返り値: None。Lastは発動までに使い、発動後の約定へ追加条件を課さない。
        """
        order = self.pending
        super().fill_pending(event)
        if order is not None and order["kind"] == "entry" and order["status"] == "filled":
            slot_id = order["slot"]["slot_id"]
            self.conditions[slot_id].update(status="終了", condition_outcome="約定",
                condition_reason="発動後の最初正常BBO", entry_filled=True,
                entry_time=order["fill_time"], entry_line=order["fill_line"],
                entry_price=order["fill_price"], end_time=event["now"], end_line=event["line"])
            self.condition_log("条件新規約定", slot_id, event["now"], event["line"], "発動後の最初正常BBO")

    def drain_timers(self, until: float, final: bool = False) -> None:
        """次定時満了を約定より先に処理し、固定49の独立強制を維持する。

        引数: until(float)は次原行又は終了時計、final(bool)は終了確定。
        返り値: None。TTL30等号だけは原行の正常BBOを先に処理する。
        """
        while self.timers:
            now, priority, kind, token = self.timers[0]
            if now > until or now == until and kind == "expiry" and not final:
                break
            heapq.heappop(self.timers)
            if kind == "condition_expiry":
                slot_id = self.slots[token]["slot_id"]
                if self.watch is not None and self.watch["slot_id"] == slot_id:
                    insufficient = now - self.watch["last_observation_time"] > 300
                    self.end_watch(now, self.last_line,
                        "満了時の発動監視間隔300秒超" if insufficient else "次定時まで未発動", insufficient)
                if self.pending is not None and self.pending["kind"] == "entry" and self.pending["slot"]["slot_id"] == slot_id:
                    self.cancel_entry(now, "次定時満了")
            elif kind == "missing":
                self.decide(token, None)
            elif kind == "force":
                if self.watch is not None:
                    self.end_watch(now, self.last_line, "強制時刻")
                self.forced = True
                self.cancel_entry(now, "強制時刻")
                if self.position is not None and self.pending is None:
                    self.request("exit", now, self.last_line, "場末強制")
                self.log("強制時計", now, self.last_line)
            elif self.pending is not None and self.pending["kind"] == "entry" and self.pending["id"].endswith(str(token).zfill(5)):
                self.cancel_entry(now, "新規TTL30秒")

    def observe_watch(self, event: dict) -> None:
        """設定より後の価格だけで観測不足とstrict突破を判定する。

        引数: event(dict)は有限非後退価格時計の当行。
        返り値: None。気配数量旗又はLast不正の行で監視時計を更新しない。
        """
        if self.watch is None:
            return
        watch = self.watch
        now, line = event["now"], event["line"]
        if (now, line) <= (watch["time"], watch["line"]):
            return
        if now - watch["last_observation_time"] > 300:
            self.end_watch(now, line, "発動監視の正常価格間隔300秒超", True)
            return
        if not normal_observation(event):
            return
        watch["last_observation_time"] = now
        slot_id = watch["slot_id"]
        row = self.conditions[slot_id]
        row["last_observation_time"] = now
        slot, condition = row["slot"], row["condition"]
        triggered = event["last"] > condition["high"] if slot["side"] == 1 else event["last"] < condition["low"]
        if not triggered:
            return
        self.watch = None
        trigger = {"time": now, "line": line, "last": event["last"]}
        self.request("entry", now, line, str(slot["reason"]), slot)
        row.update(status="注文待ち", condition_outcome="発動未約定",
            condition_reason="要求後の正常約定待ち", trigger=trigger,
            request_time=now, request_line=line, order_id=self.pending["id"])
        self.condition_log("条件発動", slot_id, now, line, "将来Lastのstrict突破")

    def decide(self, index: int, event: dict | None) -> None:
        """当時判断を条件登録・待ち・保有・処理中・判定不能へ一回分類する。

        引数: index(int)は予定枠番号、event(dict|None)は判断行又は欠測placeholder。
        返り値: None。後日の発動成否で原判断を上書きしない。
        """
        if index in self.done:
            raise ValueError("枠の再試行禁止")
        self.done.add(index)
        slot = self.slots[index]
        holding = self.position is not None
        pending = self.pending["kind"] if self.pending else None
        row = {**deepcopy(slot), "holding": holding, "pending_kind": pending,
            "position_id": self.position["id"] if holding else None,
            "watching": self.watch is not None}
        condition = self.conditions.get(slot["slot_id"])
        if event is None or not normal_bbo(event):
            action, reason = "判定不能", "判断時計欠測" if event is None else "判断BBO非正常"
        elif self.pending is not None:
            action, reason = "処理中", "新規又は返済の約定待ち"
        elif holding:
            action, reason = "保有継続", "保有中は指標ready不問"
        elif self.watch is not None:
            action, reason = "処理中", "既存条件の監視中"
        elif not slot["ready"]:
            action, reason = "判定不能", slot["reason"]
        elif self.forced:
            action, reason = "待ち", "強制時刻以降"
        elif slot["side"] == 0:
            action, reason = "待ち", slot["reason"]
        else:
            if slot["role"] not in ROLES or not finite(slot["atr"]) or slot["atr"] <= 0 or not finite(slot["D"]) or not 5 <= slot["D"] <= 125:
                raise ValueError("新規には実役割・有限正ATR・5<=D<=125が必要")
            if condition is None:
                raise ValueError("純候補の固定価格条件がない")
            if not normal_observation(event):
                action, reason = "判定不能", "設定Last又はBBO不正"
                condition.update(condition_outcome="観測不足")
            else:
                line_price = condition["condition"]["high" if slot["side"] == 1 else "low"]
                outside = slot["side"] * (event["last"] - line_price) > 0
                if outside:
                    action, reason = "待ち", "設定時に発動線を既超過"
                    condition.update(condition_outcome="既超過")
                else:
                    action, reason = "条件登録", slot["reason"]
                    self.watch = {"slot_id": slot["slot_id"], "time": slot["time"],
                        "line": slot["line"], "expires": condition["condition"]["expires"],
                        "last_observation_time": slot["time"]}
                    condition.update(registered=True, watch_started=True, status="監視中",
                        condition_outcome="未発動", last_observation_time=slot["time"])
                    self.condition_log("条件登録", slot["slot_id"], slot["time"], slot["line"], str(reason))
        if condition is not None:
            condition["condition_reason"] = str(reason)
            if action != "条件登録":
                condition.update(status="終了", end_time=slot["time"], end_line=slot["line"])
                if action == "判定不能":
                    condition["condition_outcome"] = "観測不足"
                self.condition_log("条件未登録", slot["slot_id"], slot["time"], slot["line"], str(reason))
        row.update(action=action, decision_reason=reason, wait=action == "待ち", activity_valid=action != "判定不能")
        if action == "判定不能":
            self.quality["判定不能枠数"] += 1
        self.decisions.append(row)
        self.log("定時判断", slot["time"], slot["line"], decision=row)

    # ----------------------------------------

    def run(self, events) -> dict:
        """原行順の固定49運用へ条件監視を挿入し、別の活動評価で終結する。

        引数: events(iterable[dict])は最小6フィールドの有限非後退価格時計列。
        返り値: dictは固定49互換の運用一式とconditions/condition_trace。
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
            for pending_index, slot in enumerate(self.slots):
                if pending_index not in self.done and slot["line"] is not None and slot["scheduled"] <= now and slot["line"] != event["line"]:
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
            self.observe_watch(event)
            if index is not None:
                if self.slots[index]["time"] != now:
                    raise ValueError("slotの判断時計と原行時計が不一致")
                self.decide(index, event)
        self.drain_timers(self.bounds["end"], final=True)
        if len(self.done) != len(self.slots):
            raise ValueError("実判断原行が見つからないslotがある")
        if self.watch is not None:
            raise ValueError("場末に条件満了の未処理がある")
        if self.position is not None or self.pending is not None:
            self.caution("場末の建玉又は返済pending未解消")
        activity = activity_metrics(self.decisions, self.conditions)
        earnings_valid = not self.quality["損益注意理由"]
        observed = {str(cost): sum(row["pnl" + str(cost)] for row in self.closed) for cost in (0, 5, 10)}
        ledger = {str(cost): observed[str(cost)] - (LEGACY.FEE + 10 * cost if self.position is not None else 0) for cost in (0, 5, 10)}
        self.quality.update(活動評価適格=activity["待ち率条件適格"], 全枠判定可能=activity["全枠判定可能"],
            損益確定可能=earnings_valid, 未解消建玉数=int(self.position is not None), 未解消注文数=int(self.pending is not None))
        metrics = {**activity, "完結数": len(self.closed), "完結取引観測純額円": observed,
            "約定台帳観測確定円": ledger,
            "全体確定対象円": {key: value if earnings_valid else None for key, value in ledger.items()}}
        return {"decisions": self.decisions, "trades": self.trades, "fills": deepcopy(self.trades),
            "closed": self.closed, "trail": self.trail, "orders": self.orders, "quality": self.quality,
            "metrics": metrics, "final_state": self.snapshot(), "session": self.session,
            "candidate_id": self.candidate, "bounds": self.bounds,
            "conditions": self.conditions, "condition_trace": self.condition_trace}


def replay(events, slots: list[dict], conditions: dict, session: str,
        candidate_id: str = "G0", bounds: dict | None = None) -> dict:
    """固定した定時候補を将来価格で発動する公開入口。

    引数: events(iterable[dict])は価格時計原行、slots(list[dict])は純判断、conditions(dict)は元枠別の価格条件、session/candidate_id(str)は識別、bounds(dict|None)は人工時計。
    返り値: dictは保存可能な運用一式。入力と固定49実装は変更しない。
    """
    return Engine(slots, conditions, session, candidate_id, bounds).run(events)
