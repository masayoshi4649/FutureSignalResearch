"""順行・反転の通常出口とATR保護を、固定幅対照と同じ原行順で再生する。"""

from collections import defaultdict
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("循環の既存運用", ROOT / "scripts/利益回収/運用.py")
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
O = M.O


class チャート状態(M.利益保護状態):
    """既存の約定・会計を保ち、24案の出口定義だけを持つ。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict, role: str,
                 signals: list[dict], bounds: tuple | None = None) -> None:
        """X0/X1/X2と入口時特徴を固定する。

        引数: session/method/role (str) は場・手法・順行/反転、config/policy (dict) は条件、
        signals (list[dict]) は入口、bounds (tuple | None) は合成用時計。
        返り値: None。
        """
        if policy["出口ID"] not in ("X0", "X1", "X2"):
            raise ValueError("未知の出口")
        super().__init__(session, method, config, policy, role, signals, bounds)
        self.center_crossed_entries = 0

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """約定後の最初の返済気配と、中心超過新規を記録する。

        引数: now (float) は時計、line (int) は原行、bid/ask (float) は気配。
        返り値: None。建玉前の高安を追尾峰へ混ぜない。
        """
        entry = self.pending is not None and self.pending["kind"] == "新規"
        old_pos, count = self.position, len(self.trades)
        super().fill(now, line, bid, ask)
        if entry and self.pending is None and self.position is not None:
            pos = self.position
            mark = bid if pos["side"] == 1 else ask
            pos["observed_peak"] = pos["side"]*(mark-pos["price"])
            if self.role == "反転" and self.policy["出口ID"] != "X0":
                if pos["center"] is None or not math.isfinite(pos["center"]):
                    raise ValueError("反転の入口中心が未準備")
                pos["center_crossed"] = pos["side"]*(pos["price"]-pos["center"]) >= 0
                pos["center_valid"] = True
                self.center_crossed_entries += int(pos["center_crossed"])
        if len(self.trades) > count:
            trade = self.trades[-1]
            trade["固定利確使用"] = self.policy["出口ID"] == "X0"
            if not trade["固定利確使用"]:
                trade["利確価格"] = None
            trade["中心線超過新規"] = bool(old_pos.get("center_crossed"))

    def quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """気配・待機約定・非常保護・役割別出口を逐次処理する。

        引数: now (float) は時計、line (int) は原行、bid/ask (float) は正常気配。
        返り値: None。X1/X2には固定250pt利確を重ねない。
        """
        self.before(now)
        previous = self.previous_quote if self.previous_quote is not None else self.start
        if now > previous:
            gap = now-previous
            self.maximum_gap = max(self.maximum_gap, gap)
            if gap > self.config["正常板空白注意秒"]:
                self.gap_intervals.append((previous, now))
                self.counts["場内正常板空白区間数"] += 1
                if self.position is not None:
                    self.position["gap"] = True
                    self.counts["保有中空白区間数"] += 1
                if self.pending is not None and self.pending["kind"] == "新規":
                    self.pending["gap"] = True
                    self.counts["新規待機中空白区間数"] += 1
        self.previous_quote = now
        self.counts["正常板数"] += 1
        self.mark(bid, ask)
        self.fill(now, line, bid, ask)
        self.mark(bid, ask)
        self.equity(bid, ask)
        if self.position is None:
            return
        pos, variant = self.position, self.policy["出口ID"]
        side = pos["side"]
        mark = bid if side == 1 else ask
        profit = side*(mark-pos["price"])
        pos["observed_peak"] = max(pos["observed_peak"], profit)
        if self.pending is not None:
            return
        reason = None
        if profit <= -self.config["保護逆行pt"]:
            reason = "保護"
        elif variant == "X0" and profit >= self.config["利確pt"]:
            reason = "利確"
        elif variant != "X0" and self.role == "反転" and (pos["center_crossed"] or side*(mark-pos["center"]) >= 0):
            reason = "中心線超過新規" if pos["center_crossed"] else "入口時中心線目標"
        elif variant == "X2":
            if self.role == "順行":
                raw = pos["price"]+side*(pos["observed_peak"]-2*pos["atr_entry"])
                rounded = math.floor(raw/5)*5 if side == 1 else math.ceil(raw/5)*5
                new_stop = max(pos["trailing"], rounded) if side == 1 else min(pos["trailing"], rounded)
                self.protection_updates += int(new_stop != pos["trailing"])
                pos["trailing"] = new_stop
                if side*(mark-new_stop) <= 0:
                    reason = "2ATR追尾保護"
            else:
                if pos["mfe"] >= pos["atr_entry"]:
                    pos["armed"] = True
                if pos["armed"]:
                    raw = pos["price"]+side*0.5*pos["atr_entry"]
                    floor = math.floor(raw/5)*5 if side == 1 else math.ceil(raw/5)*5
                    if side*(mark-floor) <= 0:
                        reason = "反転ATR利益床"
        if reason is not None:
            self.request("返済", side, now, line, reason, pos["event_id"])

    def bar(self, frame: dict) -> None:
        """保有後の確定足で、順行のEMA仮説失効だけを監視する。

        引数: frame (dict) は当該判断尺度の足。
        返り値: None。反転は固定中心・非常保護・利益床で返済する。
        """
        self.before(frame["confirm"])
        if self.policy["出口ID"] == "X0" or self.role != "順行" or self.position is None or self.pending is not None:
            return
        pos = self.position
        if not frame["publish"] or frame["end"] <= pos["time"] or frame["confirm"]-frame["end"] > 30:
            return
        if frame["ema20"] is not None and pos["side"]*(frame["close"]-frame["ema20"]) <= 0:
            self.request("返済", pos["side"], frame["confirm"], frame["confirm_line"], "確定足EMA20失効", pos["event_id"])

    def finish(self) -> dict:
        """原会計へ出口使用区分と中心超過件数を付ける。

        引数: なし。
        返り値: dict は場別会計・品質。
        """
        result = super().finish()
        result.update(利益床使用=self.role == "反転" and self.policy["出口ID"] == "X2",
                      固定利確使用=self.policy["出口ID"] == "X0", 中心線超過新規数=self.center_crossed_entries)
        return result


def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str, method: str,
           config: dict, policy: dict, role: str, bounds: tuple | None = None) -> tuple[チャート状態, dict]:
    """気配・確定足・新規要求を原行順へ統合する。

    引数: events (list[Any]) は観測、signals/frames (list[dict]) は入口/足、session/method/role (str) は場/手法/役割、
    config/policy (dict) は共通/出口条件、bounds (tuple | None) は合成時計。
    返り値: tuple[チャート状態, dict] は状態と場別集計。
    """
    state = チャート状態(session, method, config, policy, role, signals, bounds)
    grouped, ids = defaultdict(list), set()
    for row in signals:
        if row["イベントID"] in ids or row["場"] != session or row["side"] not in (1, -1):
            raise ValueError("入口ID重複または場・方向不一致")
        ids.add(row["イベントID"])
        grouped[(row["要求時計秒"], row["要求原板行"])].append(row)
    timeline, previous, backwards = [], -math.inf, 0
    for event in events:
        if not math.isfinite(event.now) or not state.start <= event.now < state.end:
            continue
        if event.now < previous:
            backwards += 1
            continue
        previous = event.now
        if event.valid:
            if not (math.isfinite(event.bid) and math.isfinite(event.ask) and 0 < event.bid <= event.ask):
                raise ValueError("正常板フラグと不正気配が矛盾")
            timeline.append((event.now, event.line, 0, event))
    for frame in frames:
        if frame["publish"] and state.start <= frame["confirm"] < state.end:
            if frame["confirm"] < frame["end"]:
                raise ValueError("足終了前の公開")
            timeline.append((frame["confirm"], frame["confirm_line"], 1, frame))
    timeline.extend((now, line, 2, group) for (now, line), group in grouped.items())
    for now, line, kind, value in sorted(timeline, key=lambda v: v[:3]):
        if kind == 0:
            state.quote(now, line, value.bid, value.ask)
        elif kind == 1:
            state.bar(value)
        else:
            state.signal_group(value)
    result = state.finish()
    result["時計後退除外数"] = backwards
    return state, result
