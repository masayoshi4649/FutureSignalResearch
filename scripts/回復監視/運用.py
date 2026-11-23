"""固定34の30秒指値を保ち、180秒指値と到達後回復の局所監視を加える。"""

from collections import Counter
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("回復監視の固定34指値", ROOT / "scripts/突破指値/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
COST, M = BASE.BASE, BASE.M
METHODS = ("3分_E1_XF", "3分_E2_XF", "3分_E3_XF")
LIFETIME = 180
CONTEXT_FIELDS = ("元登録時計秒", "元登録原板行", "絶対失効時計秒", "監視水準価格", "監視登録出典",
    "初回到達出典", "初回回復出典", "新規実効TTL秒")


def snapshot(now: float, line: int, bid: float, ask: float) -> dict:
    """監視の根拠となった正常BBOを複写用辞書へ写す。

    引数: now/line(float/int)は価格時計/原行、bid/ask(float)は正常気配。
    返り値: dictは時計秒/原板行/bid/ask。受信秒へ変換しない。
    """
    return {"時計秒": now, "原板行": line, "bid": bid, "ask": ask}


class 長期指値状態(BASE.指値費用起動状態):
    """固定34の新規価格判定だけを再用し、寿命を状態局所の180秒へ延ばす。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict, role: str,
                 signals: list[dict], bounds: tuple | None = None) -> None:
        """E2の当時信号と局所TTLだけを初期化する。

        引数: session/method/role(str)は識別、config/policy(dict)は共通運用/XF、signals(list[dict])は純入口、bounds(tuple|None)は人工時計。
        返り値: None。固定34のclass制約やglobalsを改変しない。
        """
        if method != "3分_E2_XF":
            raise ValueError("長期指値はE2だけです")
        for signal in signals:
            BASE.limit_fields(signal, config)
        local = deepcopy(config)
        local["新規有効秒"] = LIFETIME
        COST.費用起動状態.__init__(self, session, method, local, policy, role, deepcopy(signals), bounds)

    def before(self, now: float) -> None:
        """180秒失効を先に処理し、返済期限の旧処理を維持する。

        引数: now(float)は次イベント時計。
        返り値: None。180秒の等号は有効、停止等号は取消。
        """
        if self.pending is not None and self.pending["kind"] == "新規":
            if now >= self.cutoff or now > self.pending["time"] + LIFETIME:
                self.cancel_entry("新規停止または180秒失効")
        super().before(now)


# ----------------------------------------
# E3の局所監視は注文pendingとは別。監視動作をXF追尾normal_logへ混ぜない。


class 回復監視状態(COST.費用起動状態):
    """一つの局所予約で到達と回復を待ち、回復時だけ市場新規を要求する。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict, role: str,
                 signals: list[dict], bounds: tuple | None = None) -> None:
        """純入口と監視用状態を複写して初期化する。

        引数: session/method/role(str)は識別、config/policy(dict)は共通運用/XF、signals(list[dict])は純入口、bounds(tuple|None)は人工時計。
        返り値: None。初回touch/回復を含む未来情報を受け取らない。
        """
        if method != "3分_E3_XF":
            raise ValueError("局所回復監視はE3だけです")
        for signal in signals:
            BASE.limit_fields(signal, config)
        self.watch, self.watch_signal = None, None
        self.watch_records, self.watch_counts, self.watch_reasons = [], Counter(), Counter()
        self.event_line, self._request_context, self._fill_context = 0, None, None
        local = deepcopy(config)
        local["新規有効秒"] = LIFETIME
        super().__init__(session, method, local, policy, role, deepcopy(signals), bounds)

    def watch_log(self, action: str, now: float, line: int, watch: dict | None = None, **data: Any) -> None:
        """監視の状態変化だけを独立した記録へ保存する。

        引数: action(str)は動作、now/line(float/int)は観測key、watch(dict|None)は終了時等の旧監視、data(Any)は理由等。
        返り値: None。通常のquote全行やXFの追尾logを複製しない。
        """
        value = self.watch if watch is None else watch
        self.watch_records.append(deepcopy({"場": self.session, "候補ID": self.method,
            "順序": len(self.watch_records) + 1, "動作": action, "時計秒": now, "原板行": line,
            "監視": value, **data}))

    def close_watch(self, now: float, line: int, reason: str, **data: Any) -> None:
        """現在の監視を一度だけ消費して終了する。

        引数: now/line(float/int)は終了を知ったkey、reason(str)は理由、data(Any)は詳細。
        返り値: None。新規要求へ移る場合は入口取扱の更新をpendingへ委ねる。
        """
        if self.watch is None:
            return
        if reason != "回復新規要求":
            self.watch_signal["取扱"] = reason
        self.watch_counts["監視終了数"] += 1
        self.watch_reasons[reason] += 1
        self.watch_log("監視終了", now, line, 終了理由=reason, **data)
        self.watch, self.watch_signal = None, None

    def before(self, now: float) -> None:
        """元登録の絶対期限と停止を、新しい監視・新規fillより先に適用する。

        引数: now(float)は次イベント時計。
        返り値: None。回復時から180秒へ延長しない。
        """
        if self.watch is not None:
            reason = "強制期限で監視終了" if now >= self.force else "新規停止で監視終了" if now >= self.cutoff else (
                ("未到達で180秒失効" if self.watch["初回到達出典"] is None else "未回復で180秒失効")
                if now > self.watch["絶対失効時計秒"] else None)
            if reason is not None:
                self.close_watch(now, self.event_line, reason)
        if self.pending is not None and self.pending["kind"] == "新規":
            if now >= self.cutoff or now > self.pending["絶対失効時計秒"]:
                self.cancel_entry("新規停止または元登録180秒失効")
        super().before(now)

    def signal_group(self, rows: list[dict]) -> None:
        """登録を局所予約として受理し、監視中の後続信号を消費する。

        引数: rows(list[dict])は同公開keyの純C0信号。
        返り値: None。回復前の新規注文は作らず、同判断複数も旧同様見送る。
        """
        now, line = rows[0]["要求時計秒"], rows[0]["要求原板行"]
        self.event_line = line
        self.before(now)
        for row in rows:
            record = {"イベントID": row["イベントID"], "場": self.session, "方向": row["方向"],
                "side": row["side"], "要求時計秒": now, "要求時計JST": M.O.iso(now), "要求原板行": line,
                "確認遅延秒": row["確認遅延秒"], "取扱": "監視受付",
                "新規要求時計秒": None, "新規要求原板行": None}
            self.signals.append(record)
            if len(rows) != 1:
                record["取扱"] = "同判断複数信号見送り"
            elif row["確認遅延秒"] > 30:
                record["取扱"] = "足確定確認遅延30秒超"
            elif now < self.start or now >= self.cutoff or now >= self.force:
                record["取扱"] = "新規停止時刻外"
            elif self.position is not None:
                record["取扱"] = "建玉中抑止"
            elif self.pending is not None:
                record["取扱"] = "注文待機中抑止"
            elif self.watch is not None:
                record["取扱"] = "監視中抑止"
                self.watch_counts["監視中抑止数"] += 1
                self.watch_log("監視中抑止", now, line, 被抑止イベントID=row["イベントID"])
            else:
                source = self.features[row["イベントID"]]
                self.watch = {"元登録イベントID": source["イベントID"], "side": source["side"],
                    "元登録時計秒": now, "元登録原板行": line, "絶対失効時計秒": now + LIFETIME,
                    "監視水準価格": source["新規指値価格"], "監視登録出典": deepcopy(source["指値根拠"]),
                    "初回到達出典": None, "初回回復出典": None}
                self.watch_signal = record
                self.watch_counts["監視予約数"] += 1
                self.watch_log("監視受理", now, line)

    def monitor_quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """有効化後の初到達とstrict後keyの初回復を一回ずつ消費する。

        引数: now/line(float/int)は正常BBOのkey、bid/ask(float)は現在気配。
        返り値: None。回復時刻不可でも初回復を取り直さない。
        """
        if self.watch is None or self.position is not None or self.pending is not None:
            return
        watch = self.watch
        if now < watch["元登録時計秒"] + 1:
            return
        side, level = watch["side"], watch["監視水準価格"]
        if watch["初回到達出典"] is None:
            if (ask <= level if side == 1 else bid >= level):
                watch["初回到達出典"] = snapshot(now, line, bid, ask)
                self.watch_counts["監視初回到達数"] += 1
                self.watch_log("初回到達", now, line)
            return
        touch = watch["初回到達出典"]
        if (now, line) <= (touch["時計秒"], touch["原板行"]):
            return
        if not (bid > level if side == 1 else ask < level):
            return
        watch["初回回復出典"] = snapshot(now, line, bid, ask)
        self.watch_counts["監視初回回復数"] += 1
        self.watch_log("初回回復", now, line)
        reasons = []
        if self.force - now < 3600:
            reasons.append("回復時残り60分未満")
        if now >= self.cutoff or now >= self.force:
            reasons.append("回復時新規停止または強制期限")
        if now + 1 > watch["絶対失効時計秒"]:
            reasons.append("回復後1秒が元期限外")
        if reasons:
            self.close_watch(now, line, "回復時刻不可", 除外理由=reasons)
            return
        record = self.watch_signal
        record.update(取扱="回復新規要求", 新規要求時計秒=now, 新規要求原板行=line)
        self.request("新規", side, now, line, "到達後の旧水準回復", watch["元登録イベントID"], record)
        self.close_watch(now, line, "回復新規要求", 注文ID=self.pending["id"])

    def request(self, kind: str, side: int, now: float, line: int, reason: str,
                event_id: str, signal: dict | None = None) -> None:
        """回復時の実要求へ元登録の期限・二段階出典を固定する。

        引数: kind/side(str/int)は区分/方向、now/line(float/int)は実要求key、reason/event_id(str)は理由/入口、signal(dict|None)は取扱。
        返り値: None。返済要求は固定XFへ渡す。
        """
        context = None
        if kind == "新規":
            if self.watch is None or self.watch["初回回復出典"] is None:
                raise ValueError("E3新規は現在監視の初回復だけです")
            context = {key: deepcopy(self.watch[key]) for key in CONTEXT_FIELDS if key != "新規実効TTL秒"}
            context["新規実効TTL秒"] = context["絶対失効時計秒"] - now
        self._request_context = context
        try:
            super().request(kind, side, now, line, reason, event_id, signal)
            if context is not None:
                self.pending.update(deepcopy(context))
                self.orders[-1].update(deepcopy(context))
        finally:
            self._request_context = None

    def log(self, action: str, now: float, line: int, position: dict | None = None, **data: Any) -> None:
        """XF動作だけを記録し、E3の回復要求出典を初期化時から添える。

        引数: action(str)はXF動作、now/line(float/int)はkey、position(dict|None)は旧建玉、data(Any)は補足。
        返り値: None。監視actionは別リストへ保存する。
        """
        pos = self.position if position is None else position
        context = pos.get("entry_recovery") if pos is not None else None
        context = context or self._fill_context or self._request_context
        if context is not None:
            data = {**data, **deepcopy(context)}
        super().log(action, now, line, position, **data)

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """回復後は市場新規として旧XF約定し、完結時も二段階出典を保存する。

        引数: now/line(float/int)は実在気配key、bid/ask(float)は現在正常BBO。
        返り値: None。旧水準へ価格をclampせず、最低+1秒を再用する。
        """
        is_entry = self.pending is not None and self.pending["kind"] == "新規"
        context = {key: deepcopy(self.pending[key]) for key in CONTEXT_FIELDS} if is_entry else None
        previous, count = self.position, len(self.trades)
        self._fill_context = context
        try:
            super().fill(now, line, bid, ask)
            if is_entry and self.pending is None and self.position is not None:
                self.position["entry_recovery"] = deepcopy(context)
            if len(self.trades) > count:
                self.trades[-1].update(deepcopy(previous["entry_recovery"]))
        finally:
            self._fill_context = None

    def quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """既存返済・新規fill・XFを先に処理し、その後で局所監視を進める。

        引数: now/line(float/int)はkey、bid/ask(float)は正常気配。
        返り値: None。回復quoteで新要求を即約定させない。
        """
        self.event_line = line
        super().quote(now, line, bid, ask)
        self.monitor_quote(now, line, bid, ask)

    def bar(self, frame: dict) -> None:
        """旧公開足処理へ原行を渡し、時計だけで失効を進める。

        引数: frame(dict)は公開済み足。
        返り値: None。足高安でtouch/回復を作らない。
        """
        self.event_line = frame["confirm_line"]
        super().bar(frame)

    def finish(self) -> dict:
        """監視を完了し、実注文の空白区間を元絶対期限で集計する。

        引数: なし。
        返り値: dictはXF会計とE3監視件数。注文/log/約定を後から書き換えない。
        """
        self.event_line = 0
        result = super().finish()
        waiting = sum(order["要求時計秒"] < right and (
            order["約定時計秒"] if order["約定時計秒"] is not None else
            min(order["絶対失効時計秒"], self.cutoff, self.force)) > left
            for left, right in self.gap_intervals for order in self.orders if order["区分"] == "新規")
        attention = bool(result["観測経路注意取引数"] or result["終了建玉"]
            or result["保有中空白区間数"] or waiting or result["EOF期限未達"])
        result.update(新規待機中空白区間数=waiting, 観測経路注意=attention,
            確定対象純損益円=None if attention else self.cash,
            **{key: self.watch_counts[key] for key in
                ("監視予約数", "監視初回到達数", "監視初回回復数", "監視終了数", "監視中抑止数")},
            監視終了理由数=dict(self.watch_reasons), 終了監視=int(self.watch is not None))
        return result


# ----------------------------------------
# E1は固定34完全直呼出し、E2/E3だけ独立した状態で同じquote/bar/signal順へ接続する。


def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """同登録の30秒指値・180秒指値・到達後回復を分けて再生する。

    引数: events(list[Any])は気配、signals/frames(list[dict])は当時情報/公開足、session/method/role(str)は識別、config/policy(dict)は共通/XF、bounds(tuple|None)は人工時計。
    返り値: tuple[Any,dict]は状態と場別会計。市場入力の読取や先着計算は行わない。
    """
    if policy != {"出口ID": "XF"} or method not in METHODS:
        raise ValueError("E1/E2/E3とXFだけです")
    if method == "3分_E1_XF":
        return BASE.replay(events, signals, frames, session, method, config, policy, role, bounds)
    cls = 長期指値状態 if method == "3分_E2_XF" else 回復監視状態
    state = cls(session, method, config, policy, role, signals, bounds)
    timeline, previous, backwards, grouped, seen = [], -math.inf, 0, {}, set()
    for signal in signals:
        if signal["イベントID"] in seen or signal["場"] != session or signal["side"] not in (-1, 1):
            raise ValueError("入口一意性/場/方向が不正")
        seen.add(signal["イベントID"])
        grouped.setdefault((signal["要求時計秒"], signal["要求原板行"]), []).append(signal)
    for event in events:
        if not math.isfinite(event.now) or not state.start <= event.now < state.end:
            continue
        if event.now < previous:
            backwards += 1
            continue
        previous = event.now
        if event.valid:
            if not (math.isfinite(event.bid) and math.isfinite(event.ask) and 0 < event.bid <= event.ask):
                raise ValueError("正常板フラグとBBO不一致")
            timeline.append((event.now, event.line, 0, event))
    for frame in frames:
        if frame["publish"] and state.start <= frame["confirm"] < state.end:
            if frame["confirm"] < frame["end"]:
                raise ValueError("足終了前公開")
            timeline.append((frame["confirm"], frame["confirm_line"], 1, frame))
    timeline.extend((now, line, 2, rows) for (now, line), rows in grouped.items())
    for now, line, kind, value in sorted(timeline, key=lambda row: row[:3]):
        if kind == 0:
            state.quote(now, line, value.bid, value.ask)
        elif kind == 1:
            state.bar(value)
        else:
            state.signal_group(value)
    result = state.finish()
    result["時計後退除外数"] = backwards
    return state, result
