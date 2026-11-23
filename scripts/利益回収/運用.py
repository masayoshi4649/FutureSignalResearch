"""固定入口の利益保護・チャート出口を、原板順で比較する共通運用処理。"""

from __future__ import annotations

from collections import defaultdict
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def module(path: Path, name: str) -> Any:
    """固定済み共有実装をパスから読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: Any はモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


O = module(ROOT / "scripts/広域研究/運用検証.py", "利益回収の固定運用")


# ----------------------------------------
# 正常板の逐次監視と、確定足の通常出口を一つの注文状態へ接続する。

class 利益保護状態(O.運用状態):
    """一建玉の原模型を継承し、追加の出口だけを記録する。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict, role: str,
                 signals: list[dict], bounds: tuple | None = None) -> None:
        """入口の特徴と出口規則を固定して初期化する。

        引数: session/method/role (str) は場・手法・順行/反転、config/policy (dict) は共通/出口条件、
        signals (list[dict]) は当時既知の入口特徴、bounds (tuple | None) は合成時計。
        返り値: None。
        """
        super().__init__(session, method, config, bounds)
        if role not in ("順行", "反転"):
            raise ValueError("入口役割は順行/反転だけを許可")
        self.policy, self.role = policy, role
        self.features = {r["イベントID"]: r for r in signals}
        self.protection_updates = 0
        self.center_disabled = 0
        self.equity_peak = 0.0
        self.equity_low = 0.0
        self.max_drawdown = 0.0

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """原模型の約定後に、入口時点の指標と構造を固定する。

        引数: now (float) は時計、line (int) は原行、bid/ask (float) は気配。
        返り値: None。指標の後日値で入口幅を作り直さない。
        """
        pending = self.pending
        closed_position = self.position
        is_entry = pending is not None and pending["kind"] == "新規"
        before_count = len(self.trades)
        super().fill(now, line, bid, ask)
        if is_entry and self.pending is None and self.position is not None:
            pos = self.position
            feature = self.features[pos["event_id"]]
            atr = feature.get("atr")
            if atr is None or not math.isfinite(atr) or atr <= 0:
                raise ValueError("入口ATRが未準備")
            pos.update(atr_entry=float(atr), armed=False, trailing=pos["stop"],
                       structure=feature["low"]-5 if pos["side"] == 1 else feature["high"]+5,
                       center=feature.get("bb_mean"), center_valid=False)
            pos["center_valid"] = pos["center"] is not None and pos["side"]*(pos["center"]-pos["price"]) > 0
            if self.role == "反転" and self.policy.get("指標出口") and not pos["center_valid"]:
                self.center_disabled += 1
        if len(self.trades) > before_count:
            self.trades[-1].update(出口ID=self.policy["出口ID"], 入口役割=self.role,
                                  利益床起動=bool(closed_position.get("armed")),
                                  入口ATR=closed_position["atr_entry"],
                                  入口中心線目標=closed_position["center"],
                                  中心線目標有効=closed_position["center_valid"])

    def equity(self, bid: float, ask: float) -> None:
        """将来返済手数料を含む観測時価と下落幅を記録する。

        引数: bid/ask (float) は現在の正常返済気配。
        返り値: None。約定判断や枚数へ影響させない。
        """
        value = self.cash
        if self.position is not None:
            pos = self.position
            mark = bid if pos["side"] == 1 else ask
            value += pos["side"]*(mark-pos["price"])*self.config["倍率"]-self.config["片道手数料円"]
        self.equity_peak = max(self.equity_peak, value)
        self.equity_low = min(self.equity_low, value)
        self.max_drawdown = max(self.max_drawdown, self.equity_peak-value)

    def quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """固定保護・TPの後に、利益床・ATR追尾・反転目標を監視する。

        引数: now (float) は時計、line (int) は原行、bid/ask (float) は正常気配。
        返り値: None。返済は原模型の要求後待機を経て行う。
        """
        super().quote(now, line, bid, ask)
        self.equity(bid, ask)
        if self.position is None or self.pending is not None:
            return
        pos = self.position
        side = pos["side"]
        mark = bid if side == 1 else ask
        profit = side*(mark-pos["price"])
        if self.policy.get("床起動pt") is not None and pos["mfe"] >= self.policy["床起動pt"]:
            pos["armed"] = True
            if profit <= self.policy["床利益pt"]:
                self.request("返済", side, now, line, "利益床", pos["event_id"])
                return
        if self.policy.get("ATR追尾") and pos["mfe"] >= pos["atr_entry"]:
            peak = pos["price"] + side*pos["mfe"]
            raw = peak-side*pos["atr_entry"]
            rounded = math.floor(raw/5)*5 if side == 1 else math.ceil(raw/5)*5
            new_stop = max(pos["trailing"], rounded) if side == 1 else min(pos["trailing"], rounded)
            self.protection_updates += int(new_stop != pos["trailing"])
            pos["trailing"] = new_stop
            if side*(mark-new_stop) <= 0:
                self.request("返済", side, now, line, "ATR利益追尾", pos["event_id"])
                return
        if self.policy.get("指標出口") and self.role == "反転" and pos["center_valid"] and side*(mark-pos["center"]) >= 0:
            self.request("返済", side, now, line, "入口時中心線目標", pos["event_id"])

    def bar(self, frame: dict) -> None:
        """保有後に確定した足で、通常の仮説失効を判定する。

        引数: frame (dict) は同じ判断尺度の確定足。
        返り値: None。入口を作った足や未確定足では決済しない。
        """
        self.before(frame["confirm"])
        if not self.policy.get("指標出口") or self.position is None or self.pending is not None:
            return
        pos = self.position
        if not frame["publish"] or frame["end"] <= pos["time"] or frame["confirm"]-frame["end"] > 30:
            return
        side = pos["side"]
        if self.role == "順行":
            failed = frame["ema20"] is not None and side*(frame["close"]-frame["ema20"]) < 0
            reason = "確定足EMA20失効"
        else:
            failed = side*(frame["close"]-pos["structure"]) < 0
            reason = "確定足復帰構造失効"
        if failed:
            self.request("返済", side, frame["confirm"], frame["confirm_line"], reason, pos["event_id"])

    def finish(self) -> dict:
        """共通会計へ出口設定と補助状態を付加する。

        引数: なし。
        返り値: dict は一場の基準会計と出口診断。
        """
        result = super().finish()
        result.update(出口ID=self.policy["出口ID"], 入口役割=self.role, 保護線更新回数=self.protection_updates,
                      中心線目標無効取引数=self.center_disabled, 観測含み込み最大DD円=self.max_drawdown,
                      観測最悪時価円=self.equity_low, 利益床使用=self.policy.get("床起動pt") is not None)
        return result


def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str, method: str,
           config: dict, policy: dict, role: str, bounds: tuple | None = None) -> tuple[利益保護状態, dict]:
    """気配・確定足・入口を原行順へ結合して再生する。

    引数: events (list[Any]) は観測、signals/frames (list[dict]) は当時既知の入口/足、
    session/method/role (str) は場・手法・役割、config/policy (dict) は条件、bounds (tuple | None) は合成時計。
    返り値: tuple[利益保護状態, dict] は約定等と一場会計。
    """
    state = 利益保護状態(session, method, config, policy, role, signals, bounds)
    grouped = defaultdict(list)
    ids = set()
    for row in signals:
        if row["イベントID"] in ids or row["場"] != session or int(row["side"]) not in (1, -1):
            raise ValueError("入口ID重複または場・方向不一致")
        ids.add(row["イベントID"])
        grouped[(row["要求時計秒"], row["要求原板行"])].append(row)
    timeline, previous = [], -math.inf
    backwards = 0
    for event in events:
        if not math.isfinite(event.now) or not state.start <= event.now < state.end:
            continue
        if event.now < previous:
            backwards += 1
            continue
        previous = event.now
        if event.valid:
            if not (math.isfinite(event.bid) and math.isfinite(event.ask) and 0 < event.bid <= event.ask):
                raise ValueError("正常板フラグと気配が不一致")
            timeline.append((event.now, event.line, 0, event))
    for frame in frames:
        if frame["publish"] and state.start <= frame["confirm"] < state.end:
            if frame["confirm"] < frame["end"]:
                raise ValueError("足終了前に確定した入力")
            timeline.append((frame["confirm"], frame["confirm_line"], 1, frame))
    for (now, line), group in grouped.items():
        timeline.append((now, line, 2, group))
    timeline.sort(key=lambda value: value[:3])
    for now, line, kind, value in timeline:
        if kind == 0:
            state.quote(now, line, value.bid, value.ask)
        elif kind == 1:
            state.bar(value)
        else:
            state.signal_group(value)
    result = state.finish()
    result["時計後退除外数"] = backwards
    return state, result
