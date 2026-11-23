"""旧A5対照を保ち、現在の費用控除後含み益で初起動するATR追尾を加える。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("終値位置の固定A5運用", ROOT / "scripts/反転確認時計/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
M = BASE.M
REFERENCE_SLIP = 5


def cost_parameters(config: dict) -> tuple[Fraction, Fraction]:
    """往復参照費用と名目利益ptのstrict境界を計算する。

    引数: config(dict)は倍率/数量/片道手数料。想定滑りは固定片道5pt。
    返り値: tuple[Fraction,Fraction]は参照費用円と名目利益境界pt。呼値へ丸めない。
    """
    quantity, multiple, fee = (Fraction(str(config[k])) for k in ("数量", "倍率", "片道手数料円"))
    if quantity <= 0 or multiple <= 0 or fee < 0:
        raise ValueError("費用起動の数量/倍率/手数料が不正")
    cost = 2 * quantity * fee + 2 * quantity * multiple * REFERENCE_SLIP
    return cost, cost / (quantity * multiple)


def current_net(mark: float, entry: float, side: int, config: dict) -> dict:
    """保存表示価格の現在含み益から往復費用を厳密控除する。

    引数: mark/entry(float)は返済BBO/新規価格、side(int)は方向、config(dict)は共通運用値。
    返り値: dictは円分数/表示/strict符号。スプレッドはBBOに含み二重控除しない。
    """
    if side not in (-1, 1) or not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (mark, entry)):
        raise ValueError("費用起動の価格/方向が不正")
    cost, boundary = cost_parameters(config)
    point = side * (Fraction(str(mark)) - Fraction(str(entry)))
    gross = point * Fraction(str(config["倍率"])) * Fraction(str(config["数量"]))
    net = gross - cost
    return {"返済気配": mark, "新規価格": entry, "実side": side,
        "名目利益pt": float(point), "粗含み益円": float(gross), "控除後含み益円": float(net),
        "控除後含み益円分子": net.numerator, "控除後含み益円分母": net.denominator,
        "strict正": net > 0, "起動参照費用円": float(cost),
        "起動参照片道滑りpt": REFERENCE_SLIP, "境界pt": float(boundary)}


class 費用起動状態(BASE.切替状態):
    """現在費用後のstrict正で起動し、以後は旧MFE-D追尾を維持する。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict, role: str,
                 signals: list[dict], bounds: tuple | None = None) -> None:
        """共通会計を初期化し、当運用だけをXFへ固定する。

        引数: session/method/role(str)は識別、config/policy(dict)は運用/XF、signals(list[dict])は純入口、bounds(tuple|None)は人工時計。
        返り値: None。旧モジュールglobalsや旧trail_parametersを変更しない。
        """
        if policy != {"出口ID": "XF"}:
            raise ValueError("費用起動はXFだけ")
        super().__init__(session, method, config, {"出口ID": "X0"}, role, signals, bounds)
        self.policy = deepcopy(policy)
        self.reference_cost, self.reference_boundary = cost_parameters(config)

    def log(self, action: str, now: float, line: int, position: dict | None = None, **data: Any) -> None:
        """初期化から費用後起動の境界と出典を正しく記録する。

        引数: action(str)は動作、now/line(float/int)は出典、position(dict|None)は建玉、data(Any)は補足。
        返り値: None。旧A5ログを後から書き換えない。
        """
        pos = self.position if position is None else position
        fields = ("id", "event_id", "side", "price", "time", "line", "entry_role", "atr_entry", "mfe", "mae",
            "armed", "trail_A", "trail_D", "trail_stop", "trail_arm_time", "trail_arm_line", "cost_arm")
        self.normal_log.append(deepcopy({"場": self.session, "候補ID": self.method,
            "順序": len(self.normal_log) + 1, "動作": action, "時計秒": now, "原板行": line,
            "建玉": {k: pos.get(k) for k in fields} if pos else None, **data}))

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """旧約定会計を保ち、新規時から費用後起動境界を固定する。

        引数: now/line(float/int)は時計/原行、bid/ask(float)は正常BBO。
        返り値: None。ATRのDだけは固定旧関数で算出する。
        """
        is_entry = self.pending is not None and self.pending["kind"] == "新規"
        if is_entry:
            source = self.features[self.pending["event_id"]]
            if source["役割"] not in ("順行", "反転"):
                raise ValueError("入口役割が不正")
            self.role = source["役割"]
        previous, count = self.position, len(self.trades)
        M.利益保護状態.fill(self, now, line, bid, ask)
        if is_entry and self.pending is None and self.position is not None:
            pos = self.position
            _, distance = BASE.trail_parameters(pos["atr_entry"])
            pos.update(entry_role=self.features[pos["event_id"]]["役割"], trail_A=float(self.reference_boundary),
                trail_D=distance, trail_stop=None, trail_arm_time=None, trail_arm_line=None, cost_arm=None)
            self.log("追尾初期化", now, line, 起動定義="現在費用控除後strict正", 起動参照費用円=float(self.reference_cost),
                起動参照片道滑りpt=REFERENCE_SLIP, 起動境界strict=True)
        if len(self.trades) > count:
            trade = self.trades[-1]
            trade.update(入口役割=previous["entry_role"], 固定利確使用=True, 通常出口使用=False, 必須追尾使用=True,
                追尾起動幅pt=previous["trail_A"], 追尾距離pt=previous["trail_D"], 追尾起動=previous["armed"],
                最終追尾価格=previous["trail_stop"], 追尾起動時計秒=previous["trail_arm_time"],
                追尾起動原板行=previous["trail_arm_line"],
                起動後純赤字=bool(previous["armed"] and trade["基準純損益円"] < 0),
                最終追尾から実返済方向差pt=previous["side"] * (trade["返済価格"] - previous["trail_stop"]) if previous["trail_stop"] is not None else None,
                起動定義="現在費用控除後strict正", 起動境界strict=True,
                起動参照費用円=float(self.reference_cost), 起動参照片道滑りpt=REFERENCE_SLIP,
                起動判定出典=deepcopy(previous["cost_arm"]))
            self.log("追尾建玉終了", now, line, previous, 返済理由=trade["返済理由"])
            if trade["起動後純赤字"]:
                self.log("起動済み純赤字約定", now, line, previous, 純損益円=trade["基準純損益円"])

    def trail_check(self, now: float, line: int, bid: float, ask: float) -> None:
        """現在の費用後正で一度だけ起動し、その後の旧追尾を継続する。

        引数: now/line(float/int)は時計/原行、bid/ask(float)は正常BBO。
        返り値: None。過去MFEだけでは起動せず、起動後の純損益低下では解除しない。
        """
        if self.position is None or self.pending is not None:
            return
        pos = self.position
        mark = bid if pos["side"] == 1 else ask
        if not pos["armed"]:
            decision = current_net(mark, pos["price"], pos["side"], self.config)
            if not decision["strict正"]:
                return
            decision.update(価格時計秒=now, 原板行=line, 元bid=bid, 元ask=ask)
            pos.update(armed=True, trail_arm_time=now, trail_arm_line=line, cost_arm=decision)
            self.trail_armed += 1
            self.log("追尾起動", now, line, 起動定義="現在費用控除後strict正", 起動判定出典=decision)
        raw = pos["price"] + pos["side"] * max(0, pos["mfe"] - pos["trail_D"])
        rounded = math.ceil(raw / 5) * 5 if pos["side"] == 1 else math.floor(raw / 5) * 5
        old = pos["trail_stop"]
        new = rounded if old is None else max(old, rounded) if pos["side"] == 1 else min(old, rounded)
        if old != new:
            pos["trail_stop"] = new
            self.trail_updates += 1
            self.log("追尾線更新", now, line, 旧追尾価格=old, 新追尾価格=new, 丸め前価格=raw)
        if pos["side"] * (mark - pos["trail_stop"]) <= 0:
            self.trail_requests += 1
            self.log("追尾閾値初着", now, line, 返済気配=mark)
            self.request("返済", pos["side"], now, line, "必須利益追尾", pos["event_id"])

    def quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """旧期限/pending/hard/TPを先に処理し、XFを後置する。

        引数: now/line(float/int)は根拠、bid/ask(float)は正常BBO。
        返り値: None。旧A5版quoteの追尾は二重実行しない。
        """
        self.last_bbo = now, line, bid, ask
        M.利益保護状態.quote(self, now, line, bid, ask)
        self.trail_check(now, line, bid, ask)

    def finish(self) -> dict:
        """共通会計へ新しい起動定義を付加する。

        引数: なし。
        返り値: dictは一場品質・会計。0/5/10感度で起動を再選択しない。
        """
        result = super().finish()
        result.update(起動定義="現在費用控除後strict正", 起動境界strict=True,
            起動参照費用円=float(self.reference_cost), 起動参照片道滑りpt=REFERENCE_SLIP)
        return result


def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """旧X0を直呼出しし、XFだけ新派生クラスで逐次再生する。

    引数: events(list[Any])は気配、signals/frames(list[dict])は純入口/足、session/method/role(str)は識別、config/policy(dict)は共通運用/出口、bounds(tuple|None)は人工時計。
    返り値: tuple[Any,dict]は状態と一場会計。モデルglobalsは変更しない。
    """
    if policy == {"出口ID": "X0"}:
        return BASE.replay(events, signals, frames, session, method, config, policy, role, bounds)
    state = 費用起動状態(session, method, config, policy, role, signals, bounds)
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
