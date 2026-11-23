"""固定250/125対照と、設定足の構造価格を用いる新規取消・保護を再生する。"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from bisect import bisect_right
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("反転確認の固定十一運用", ROOT / "scripts/テクニカル循環/運用.py")
U = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = U
SPEC.loader.exec_module(U)


class 反転確認状態(U.チャート状態):
    """固定対照の会計を継承し、構造無効取消と有利側の保護だけを加える。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict, role: str,
                 signals: list[dict], bounds: tuple | None = None) -> None:
        """既存X0と、外部へ記録する固定/構造の区分を初期化する。

        引数: session/method/role (str) は場・候補・役割、config/policy (dict) は共通条件/固定または構造、
        signals (list[dict]) は設定足と構造価格を持つ入口、bounds (tuple|None) は合成時計。
        返り値: None。旧コードとその設定は変更しない。
        """
        if policy.get("出口ID") not in ("固定", "構造"):
            raise ValueError("出口IDは固定/構造だけを許可")
        self.exit_policy = deepcopy(policy)
        self.structure_cancel_count = 0
        self.structure_unknown_count = 0
        self.structure_cancellations = []
        self.normal_quote_keys, self.normal_quotes = [], []
        super().__init__(session, method, config, {"出口ID": "X0"}, role, signals, bounds)

    def request(self, kind: str, side: int, now: float, line: int, reason: str,
                event_id: str, signal: dict | None = None) -> None:
        """構造の新規送信前だけ、要求時点までに既知の正常BBOで審査する。

        引数: kind (str) は新規/返済、side (int) は方向、now (float)/line (int) は要求キー、
        reason/event_id (str) は理由/入口ID、signal (dict|None) は入口取扱記録。
        返り値: None。送信前拒否の記録は残すが手数料や建玉は作らない。
        """
        if kind != "新規" or self.exit_policy["出口ID"] == "固定":
            super().request(kind, side, now, line, reason, event_id, signal)
            return
        feature = self.features[event_id]
        structure = feature.get("構造価格")
        if structure is None or not math.isfinite(structure) or structure <= 0:
            raise ValueError("構造の新規要求に有限正値の構造価格が必要")
        index = bisect_right(self.normal_quote_keys, (now, line)) - 1
        known = self.normal_quotes[index] if index >= 0 else None
        missing = known is None or now - known[0] > 30
        mark = None if missing else known[2] if side == 1 else known[3]
        invalid = not missing and side * (mark - structure) <= 0
        super().request(kind, side, now, line, reason, event_id, signal)
        if not (missing or invalid):
            self.orders[-1].update(送信前構造確認=True, 構造価格=float(structure),
                                   構造参照時計秒=known[0], 構造参照原板行=known[1],
                                   構造参照Bid=known[2], 構造参照Ask=known[3],
                                   構造参照板の古さ秒=now-known[0])
            return
        cancel_reason = "構造未確認で送信前取消" if missing else "構造無効で送信前取消"
        record = {"注文ID": self.pending["id"], "入口イベントID": event_id,
                  "送信前取消": True, "取消時計秒": now, "取消原板行": line,
                  "取消判定気配": mark, "構造価格": float(structure), "取消理由": cancel_reason,
                  "構造参照時計秒": None if known is None else known[0],
                  "構造参照原板行": None if known is None else known[1],
                  "構造参照Bid": None if known is None else known[2],
                  "構造参照Ask": None if known is None else known[3],
                  "構造参照板の古さ秒": None if known is None else now-known[0]}
        self.orders[-1].update(record)
        if signal is not None:
            signal.update({k: v for k, v in record.items() if k != "注文ID"})
        self.structure_cancellations.append(record)
        self.structure_unknown_count += int(missing)
        self.structure_cancel_count += int(invalid)
        self.cancel_entry(cancel_reason)

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """送信済み新規を旧待機模型で約定させ、その時点の保護を設定する。

        引数: now (float) は価格時計、line (int) は原行、bid/ask (float) は正常気配。
        返り値: None。送信後の構造破れで新規を無償取消せず、実約定を記録する。
        """
        pending = self.pending
        opening = pending is not None and pending["kind"] == "新規"
        old_position, count = self.position, len(self.trades)
        super().fill(now, line, bid, ask)
        if opening and self.pending is None and self.position is not None:
            pos = self.position
            feature = self.features[pos["event_id"]]
            structure = feature.get("構造価格")
            hard_stop = pos["stop"]
            if self.exit_policy["出口ID"] == "構造":
                chartstop = max(hard_stop, structure) if pos["side"] == 1 else min(hard_stop, structure)
            else:
                chartstop = hard_stop
            pos.update(chartstop=float(chartstop), initial_hard_stop=hard_stop,
                       structure_price=structure, setup=deepcopy(feature.get("設定足")),
                       confirmation=feature.get("確認方式"))
        if len(self.trades) > count:
            self.trades[-1].update(出口ID=self.exit_policy["出口ID"],
                                  構造保護使用=self.exit_policy["出口ID"] == "構造",
                                  保護価格=old_position["chartstop"],
                                  初期125保護価格=old_position["initial_hard_stop"],
                                  構造価格=old_position["structure_price"],
                                  設定足=old_position["setup"],
                                  確認方式=old_position["confirmation"])

    def quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """期限・既存約定・固定非常保護・構造保護・TPの順で監視する。

        引数: now (float) は価格時計、line (int) は原行、bid/ask (float) は正常気配。
        返り値: None。構造線は要求の根拠であり、指定価格での即約定ではない。
        """
        if self.exit_policy["出口ID"] == "固定":
            super().quote(now, line, bid, ask)
            return
        key = now, line
        if self.normal_quote_keys and key < self.normal_quote_keys[-1]:
            raise ValueError("正常BBOの時計・原行が後退")
        self.normal_quote_keys.append(key)
        self.normal_quotes.append((now, line, bid, ask))
        self.before(now)
        previous = self.previous_quote if self.previous_quote is not None else self.start
        if now > previous:
            gap = now - previous
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
        pos = self.position
        side = pos["side"]
        mark = bid if side == 1 else ask
        profit = side * (mark - pos["price"])
        pos["observed_peak"] = max(pos["observed_peak"], profit)
        if self.pending is not None:
            return
        if profit <= -self.config["保護逆行pt"]:
            reason = "保護"
        elif side * (mark - pos["chartstop"]) <= 0:
            reason = "構造保護"
        elif profit >= self.config["利確pt"]:
            reason = "利確"
        else:
            return
        self.request("返済", side, now, line, reason, pos["event_id"])

    def finish(self) -> dict:
        """既存会計へ構造取消と構造保護の件数を追加する。

        引数: なし。
        返り値: dict は一場の会計・品質。未解消と観測注意の扱いを維持する。
        """
        result = super().finish()
        result.update(出口ID=self.exit_policy["出口ID"],
                      構造保護使用=self.exit_policy["出口ID"] == "構造",
                      構造無効新規取消数=self.structure_cancel_count,
                      構造未確認新規取消数=self.structure_unknown_count,
                      構造保護返済数=sum(t["返済理由"] == "構造保護" for t in self.trades))
        return result


# ----------------------------------------
# 気配・足・新規の原順と元入力検査を保つ。通常足出口は内部X0により使用しない。

def replay(events: list[Any], signals: list[dict], frames: list[dict] | None,
           session: str, method: str, config: dict, policy: dict, role: str = "反転",
           bounds: tuple | None = None) -> tuple[反転確認状態, dict]:
    """正常板と入口を旧11と同じ原行順で再生する。

    引数: events (list[Any]) は観測、signals/frames (list[dict]|None) は入口/任意の足、
    session/method/role (str) は場・候補・役割、config/policy (dict) は条件、
    bounds (tuple|None) は合成時計。
    返り値: tuple[反転確認状態,dict] は約定・取消等の状態と場別集計。
    """
    state = 反転確認状態(session, method, config, policy, role, signals, bounds)
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
    for frame in frames or []:
        if frame["publish"] and state.start <= frame["confirm"] < state.end:
            if frame["confirm"] < frame["end"]:
                raise ValueError("足終了前の公開")
            timeline.append((frame["confirm"], frame["confirm_line"], 1, frame))
    timeline.extend((now, line, 2, group) for (now, line), group in grouped.items())
    for now, line, kind, value in sorted(timeline, key=lambda item: item[:3]):
        if kind == 0:
            state.quote(now, line, value.bid, value.ask)
        elif kind == 1:
            state.bar(value)
        else:
            state.signal_group(value)
    result = state.finish()
    result["時計後退除外数"] = backwards
    return state, result
