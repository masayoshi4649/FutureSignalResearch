"""nativeを使わず、一建玉の固定幅と必須利益追尾を再生する。"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def module(path: Path, name: str) -> Any:
    """旧固定運用を変更せず読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: Any はモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


M = module(ROOT/"scripts/利益回収/運用.py", "異種発動の固定会計")


def trail_parameters(atr: float) -> tuple[float, float]:
    """一呼値の起動幅と、入口ATRを切り上げた追尾幅を返す。

    引数: atr (float) は新規要求時の有限正ATR。
    返り値: tuple[float,float] は固定5ptの起動A・ATR由来の距離D。
    """
    if not math.isfinite(atr) or atr <= 0:
        raise ValueError("入口ATRが不正")
    return 5, max(5, math.ceil(atr/5)*5)


class 切替状態(M.利益保護状態):
    """一注文・一建玉を保ち、固定幅と必須追尾だけを使う。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict,
                 role: str, signals: list[dict], bounds: tuple | None = None) -> None:
        """混合信号を受け、各建玉の固定役割と追尾を初期化する。

        引数: session/method/role (str) は場/候補/集合役割、config/policy (dict) は条件/出口、
        signals (list[dict]) はlabelなし入口、bounds (tuple|None) は合成時計。
        返り値: None。nativeを初期化せず全戦略を共通一出口で保護する。
        """
        if policy != {"出口ID": "X0"}:
            raise ValueError("固定X0だけ")
        M.利益保護状態.__init__(self, session, method, config, policy, "順行", signals, bounds)
        self.normal_log, self.last_bbo = [], None
        self.trail_updates = self.trail_armed = self.trail_requests = 0

    def log(self, action: str, now: float, line: int, position: dict | None = None, **data: Any) -> None:
        """追尾と注文の遷移を同一順序の小さい状態記録に保存する。

        引数: action (str) は動作、now/line (float/int) は根拠、position (dict|None) は対象、data (Any) は補足。
        返り値: None。正常板全件を複製しない。
        """
        pos = self.position if position is None else position
        fields = ("id", "event_id", "side", "price", "time", "line", "entry_role", "atr_entry", "mfe", "mae",
                  "armed", "trail_A", "trail_D", "trail_stop", "trail_arm_time", "trail_arm_line")
        details = {k: pos.get(k) for k in fields} if pos else None
        self.normal_log.append(deepcopy({"場": self.session, "候補ID": self.method,
            "順序": len(self.normal_log)+1, "動作": action, "時計秒": now, "原板行": line, "建玉": details, **data}))

    def request(self, kind: str, side: int, now: float, line: int, reason: str,
                event_id: str, signal: dict | None = None) -> None:
        """旧要求を保ち、追尾状態と注文理由を記録する。

        引数: kind/reason/event_id (str) は区分/理由/入口、side/line (int) は方向/原行、
        now (float) は時計、signal (dict|None) は入口取扱。
        返り値: None。要求時計で約定させない。
        """
        super().request(kind, side, now, line, reason, event_id, signal)
        self.log("注文要求", now, line, 区分=kind, 理由=reason, 注文ID=self.pending["id"])

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """旧会計約定を保ち、新規信号の役割・ATRを固定する。

        引数: now (float) は時計、line (int) は原行、bid/ask (float) は正常BBO。
        返り値: None。保有中に別信号の役割へ変えない。
        """
        is_entry = self.pending is not None and self.pending["kind"] == "新規"
        if is_entry:
            source = self.features[self.pending["event_id"]]
            if source["役割"] not in ("順行", "反転"):
                raise ValueError("信号役割が不正")
            self.role = source["役割"]
        previous, count = self.position, len(self.trades)
        super().fill(now, line, bid, ask)
        if is_entry and self.pending is None and self.position is not None:
            pos = self.position
            a, d = trail_parameters(pos["atr_entry"])
            pos.update(entry_role=self.features[pos["event_id"]]["役割"], trail_A=a, trail_D=d,
                       trail_stop=None, trail_arm_time=None, trail_arm_line=None)
            self.log("追尾初期化", now, line)
        if len(self.trades) > count:
            trade = self.trades[-1]
            trade.update(入口役割=previous["entry_role"], 固定利確使用=True, 通常出口使用=False,
                         必須追尾使用=True, 追尾起動幅pt=previous["trail_A"], 追尾距離pt=previous["trail_D"],
                         追尾起動=previous["armed"], 最終追尾価格=previous["trail_stop"],
                         追尾起動時計秒=previous["trail_arm_time"], 追尾起動原板行=previous["trail_arm_line"],
                         起動後純赤字=bool(previous["armed"] and trade["基準純損益円"] < 0),
                         最終追尾から実返済方向差pt=previous["side"]*(trade["返済価格"]-previous["trail_stop"]) if previous["trail_stop"] is not None else None)
            self.log("追尾建玉終了", now, line, previous, 返済理由=trade["返済理由"])
            if trade["起動後純赤字"]:
                self.log("起動済み純赤字約定", now, line, previous, 純損益円=trade["基準純損益円"])

    def trail_check(self, now: float, line: int, bid: float, ask: float) -> None:
        """正常返済気配のMFEから非緩和の最低同値追尾を更新し初着要求する。

        引数: now (float) は時計、line (int) は原行、bid/ask (float) は正常気配。
        返り値: None。閾値即時約定はせず、既存注文を優先する。
        """
        if self.position is None or self.pending is not None:
            return
        pos = self.position
        if pos["mfe"] < pos["trail_A"]:
            return
        if not pos["armed"]:
            pos.update(armed=True, trail_arm_time=now, trail_arm_line=line)
            self.trail_armed += 1
            self.log("追尾起動", now, line)
        raw = pos["price"]+pos["side"]*max(0, pos["mfe"]-pos["trail_D"])
        rounded = math.ceil(raw/5)*5 if pos["side"] == 1 else math.floor(raw/5)*5
        old = pos["trail_stop"]
        new = rounded if old is None else max(old, rounded) if pos["side"] == 1 else min(old, rounded)
        if old != new:
            pos["trail_stop"] = new
            self.trail_updates += 1
            self.log("追尾線更新", now, line, 旧追尾価格=old, 新追尾価格=new, 丸め前価格=raw)
        mark = bid if pos["side"] == 1 else ask
        if pos["side"]*(mark-pos["trail_stop"]) <= 0:
            self.trail_requests += 1
            self.log("追尾閾値初着", now, line, 返済気配=mark)
            self.request("返済", pos["side"], now, line, "必須利益追尾", pos["event_id"])

    def quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """期限・待機約定・hard125/250・追尾の順に監視する。

        引数: now/line (float/int) は価格時計/原行、bid/ask (float) は正常BBO。
        返り値: None。同秒の後続原行も独立に処理する。
        """
        self.last_bbo = now, line, bid, ask
        M.利益保護状態.quote(self, now, line, bid, ask)
        self.trail_check(now, line, bid, ask)

    def bar(self, frame: dict) -> None:
        """確定足では期限予約だけを処理する。

        引数: frame (dict) は同尺度の公開参照足。
        返り値: None。保有中の局面分類だけでは返済しない。
        """
        self.before(frame["confirm"])

    def signal_group(self, rows: list[dict]) -> None:
        """同判断の複数信号を全て見送り、単独信号だけ旧受付へ渡す。

        引数: rows (list[dict]) は同時計・原行の選択信号。
        返り値: None。通常は入口側で競合除外済みだが運用側も保守的に拒否する。
        """
        if len(rows) == 1:
            super().signal_group(rows)
            return
        self.before(rows[0]["要求時計秒"])
        for row in rows:
            self.signals.append({"イベントID": row["イベントID"], "場": self.session, "方向": row["方向"],
                "side": row["side"], "要求時計秒": row["要求時計秒"], "要求時計JST": M.O.iso(row["要求時計秒"]),
                "要求原板行": row["要求原板行"], "確認遅延秒": row["確認遅延秒"], "取扱": "同判断複数信号見送り"})

    def finish(self) -> dict:
        """通常会計に必須追尾・同時競合の件数を加える。

        引数: なし。
        返り値: dict は一場会計と診断。
        """
        result = super().finish()
        result.update(入口役割="取引ごと固定", 固定利確使用=True, 利益床使用=True, 必須追尾使用=True,
                      追尾起動取引数=self.trail_armed, 追尾線更新回数=self.trail_updates, 追尾要求数=self.trail_requests,
                      起動後純赤字取引数=sum(t["起動後純赤字"] for t in self.trades),
                      同判断複数見送り数=Counter(r["取扱"] for r in self.signals)["同判断複数信号見送り"])
        return result


# ----------------------------------------
# 固定19と同じ原順、時計後退除外、正常気配→公開足→入口を全出口に適用する。

def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[切替状態, dict]:
    """全役割・共通一出口を単一注文状態で再生する。

    引数: events (list[Any]) は気配、signals/frames (list[dict]) は入口/参照足、session/method/role (str) は場/候補/集合役割、
    config/policy (dict) は会計/出口、bounds (tuple|None) は合成時計。
    返り値: tuple[切替状態,dict] は状態と一場集計。
    """
    state = 切替状態(session, method, config, policy, role, signals, bounds)
    grouped, identities = defaultdict(list), set()
    for row in signals:
        if row["イベントID"] in identities or row["場"] != session or row["side"] not in (1, -1):
            raise ValueError("入口の一意性/場/方向不正")
        identities.add(row["イベントID"])
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
                raise ValueError("正常板フラグとBBO不一致")
            timeline.append((event.now, event.line, 0, event))
    for frame in frames:
        if frame["publish"] and state.start <= frame["confirm"] < state.end:
            if frame["confirm"] < frame["end"]:
                raise ValueError("足終了前公開")
            timeline.append((frame["confirm"], frame["confirm_line"], 1, frame))
    timeline.extend((now, line, 2, group) for (now, line), group in grouped.items())
    for now, line, kind, value in sorted(timeline, key=lambda r: r[:3]):
        if kind == 0:
            state.quote(now, line, value.bid, value.ask)
        elif kind == 1:
            state.bar(value)
        else:
            state.signal_group(value)
    result = state.finish()
    result["時計後退除外数"] = backwards
    return state, result
