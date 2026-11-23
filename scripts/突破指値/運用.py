"""固定33の費用後起動を保ち、新規だけ旧突破境界の指値へ限定する。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("突破指値の固定33費用運用", ROOT / "scripts/終値位置/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
M, current_net, cost_parameters = BASE.M, BASE.current_net, BASE.cost_parameters
METHODS = ("3分_E0_XF", "3分_E1_XF")


def limit_fields(source: dict, config: dict) -> dict:
    """指値の価格と登録時出典を検証して独立複写する。

    引数: source(dict)は当時既知の入口、config(dict)は呼値を含む共通運用値。
    返り値: dictは新規指値価格/指値根拠。範囲やCCIを後から再計算しない。
    """
    price, basis = source.get("新規指値価格"), source.get("指値根拠")
    if isinstance(price, bool) or not isinstance(price, (float, int)) or not math.isfinite(price) or price <= 0:
        raise ValueError("新規指値価格が有限正値ではありません")
    tick = Fraction(str(config["呼値pt"]))
    if tick <= 0 or (Fraction(price) / tick).denominator != 1:
        raise ValueError("新規指値価格が固定呼値と一致しません")
    if not isinstance(basis, dict) or not basis:
        raise ValueError("指値の登録出典がありません")
    return {"新規指値価格": float(price), "指値根拠": deepcopy(basis)}


class 指値費用起動状態(BASE.費用起動状態):
    """新規の価格成立だけを変更し、返済・費用起動・追尾を継承する。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict, role: str,
                 signals: list[dict], bounds: tuple | None = None) -> None:
        """純入口を複写し、後続信号から指値や期限を改訂させない。

        引数: session/method/role(str)は識別、config/policy(dict)は運用/XF、signals(list[dict])は純入口、bounds(tuple|None)は人工時計。
        返り値: None。旧モジュールのglobalsや固定済みファイルは変更しない。
        """
        if method != "3分_E1_XF":
            raise ValueError("指値状態の候補IDが不正です")
        for signal in signals:
            limit_fields(signal, config)
        super().__init__(session, method, config, policy, role, deepcopy(signals), bounds)

    def request(self, kind: str, side: int, now: float, line: int, reason: str,
                event_id: str, signal: dict | None = None) -> None:
        """新規要求へ固定指値と登録出典を初回から保存する。

        引数: kind/side(str/int)は区分/方向、now/line(float/int)は要求key、reason/event_id(str)は理由/入口、signal(dict|None)は入口取扱。
        返り値: None。返済要求は固定33へそのまま渡す。
        """
        fields = limit_fields(self.features[event_id], self.config) if kind == "新規" else None
        super().request(kind, side, now, line, reason, event_id, signal)
        if fields is not None:
            self.pending.update(deepcopy(fields))
            self.orders[-1].update(deepcopy(fields))

    def log(self, action: str, now: float, line: int, position: dict | None = None, **data: Any) -> None:
        """旧追尾snapshotを保ち、E1だけ指値登録出典を添える。

        引数: action(str)は動作、now/line(float/int)は出典、position(dict|None)は建玉、data(Any)は補足。
        返り値: None。建玉内の旧字段や動作の順番は変更しない。
        """
        pos = self.position if position is None else position
        if pos is not None:
            if "entry_limit_price" in pos:
                fields = {"新規指値価格": pos["entry_limit_price"], "指値根拠": deepcopy(pos["entry_limit_basis"])}
            else:
                fields = limit_fields(self.features[pos["event_id"]], self.config)
            data = {**data, **fields}
        elif self.pending is not None and self.pending["kind"] == "新規":
            data = {**data, **limit_fields(self.features[self.pending["event_id"]], self.config)}
        super().log(action, now, line, position, **data)

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """新規は最初の指値内の対当側BBOだけを旧約定へ通す。

        引数: now/line(float/int)は正常BBOのkey、bid/ask(float)はその時点の気配。
        返り値: None。+1秒・TTL・停止の旧境界を保ち、成立後の追加待機を置かない。
        """
        pending = self.pending
        is_entry = pending is not None and pending["kind"] == "新規"
        fields = None
        if is_entry:
            fields = {"新規指値価格": pending["新規指値価格"], "指値根拠": deepcopy(pending["指値根拠"])}
            mark = ask if pending["side"] == 1 else bid
            if pending["side"] * (mark - fields["新規指値価格"]) > 0:
                return
        previous, count = self.position, len(self.trades)
        super().fill(now, line, bid, ask)
        if is_entry and self.pending is None and self.position is not None:
            self.position.update(entry_limit_price=fields["新規指値価格"], entry_limit_basis=deepcopy(fields["指値根拠"]))
        if len(self.trades) > count:
            self.trades[-1].update(新規指値価格=previous["entry_limit_price"], 指値根拠=deepcopy(previous["entry_limit_basis"]))


# ----------------------------------------
# E0は固定33の直呼出し、E1は新規の指値成立だけを変えた逐次再生。


def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """同じXF出口で即時代理と固定指値代理を分けて逐次再生する。

    引数: events(list[Any])は正常判定付き気配、signals/frames(list[dict])は純入口/足、session/method/role(str)は識別、config/policy(dict)は共通運用/XF、bounds(tuple|None)は人工時計。
    返り値: tuple[Any,dict]は状態と場別会計。主/数値/先着を呼び出さない。
    """
    if policy != {"出口ID": "XF"} or method not in METHODS:
        raise ValueError("突破指値はE0/E1とXFの二案だけです")
    if method == "3分_E0_XF":
        return BASE.replay(events, signals, frames, session, method, config, policy, role, bounds)
    state = 指値費用起動状態(session, method, config, policy, role, signals, bounds)
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
