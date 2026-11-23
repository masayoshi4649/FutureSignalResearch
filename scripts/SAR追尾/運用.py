"""固定X0と、最低同値床を残す精密公開SAR追尾だけを比較する。"""

from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def module(path: Path, name: str) -> Any:
    """既存運用又は新精密数値をコマンド実行せず読む。

    引数: path(Path)はコード、name(str)は識別子。
    返り値: Anyは読取モジュール。旧コードを変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


BASE = module(ROOT / "scripts/反転確認時計/運用.py", "SAR追尾の固定X0運用")
J = module(Path(__file__).with_name("指標.py"), "SAR追尾の運用精密数値")
M = BASE.M


def reference(row: dict) -> dict:
    """公開参照へ必要な元足キーと精密次足線だけを写す。

    引数: row(dict)は精密SAR行。
    返り値: dictは未来値を含まない小型参照。OHLC全履歴を複製しない。
    """
    return {k: deepcopy(row[k]) for k in ("場", "index", "end", "confirm", "confirm_line", "publish", "missing",
        "SAR準備済", "SAR公開可", "SAR方向", "SAR次足線", "SAR精密次足線", "SAR_AF整数", "SAR解除理由")}


class SAR追尾状態(BASE.切替状態):
    """公開後の正常BBOだけで、同値床を非緩和に締める。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict,
                 role: str, signals: list[dict], bounds: tuple | None = None) -> None:
        """共通会計と空の当場公開参照を初期化する。

        引数: session/method/role(str)は場/候補/役割、config/policy(dict)は運用/XS、signals(list[dict])は純入口、bounds(tuple|None)は人工時計。
        返り値: None。旧クラスの初期化制約だけX0で通し、追尾処理は本クラスが全て置き換える。
        """
        if policy != {"出口ID": "XS"}:
            raise ValueError("精密SAR追尾はXSだけ")
        super().__init__(session, method, config, {"出口ID": "X0"}, role, signals, bounds)
        self.policy = deepcopy(policy)
        self.latest_sar = self.latest_publication = None
        self.sar_updates = 0
        self.sar_reasons = Counter()

    def log(self, action: str, now: float, line: int, position: dict | None = None, **data: Any) -> None:
        """注文・床・SAR適用を同じ小型状態列へ記録する。

        引数: action(str)は動作、now/line(float/int)は根拠、position(dict|None)は建玉、data(Any)は補足。
        返り値: None。全正常BBOは転記せず状態変更だけ残す。
        """
        pos = self.position if position is None else position
        fields = ("id", "event_id", "side", "price", "time", "line", "entry_role", "atr_entry", "mfe", "mae",
            "armed", "trail_A", "trail_D", "trail_stop", "trail_arm_time", "trail_arm_line", "sar_applied", "sar_updates")
        self.normal_log.append(deepcopy({"場": self.session, "候補ID": self.method,
            "順序": len(self.normal_log) + 1, "動作": action, "時計秒": now, "原板行": line,
            "建玉": {k: pos.get(k) for k in fields} if pos else None, **data}))

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """旧会計約定へ、ATR距離未使用のXS建玉状態を付ける。

        引数: now(float)は時計、line(int)は原行、bid/ask(float)は正常BBO。
        返り値: None。約定自体と手数料は固定の利益保護会計へ渡す。
        """
        is_entry = self.pending is not None and self.pending["kind"] == "新規"
        if is_entry:
            source = self.features[self.pending["event_id"]]
            if source["役割"] not in ("順行", "反転"):
                raise ValueError("信号役割が不正")
            self.role = source["役割"]
        previous, count = self.position, len(self.trades)
        M.利益保護状態.fill(self, now, line, bid, ask)
        if is_entry and self.pending is None and self.position is not None:
            self.position.update(entry_role=self.features[self.position["event_id"]]["役割"],
                trail_A=5, trail_D=None, trail_stop=None, trail_arm_time=None, trail_arm_line=None,
                sar_applied=None, sar_updates=0)
            self.log("追尾初期化", now, line, 追尾方式="公開SAR", ATR距離使用=False)
        if len(self.trades) > count:
            trade = self.trades[-1]
            trade.update(入口役割=previous["entry_role"], 固定利確使用=True, 通常出口使用=False,
                必須追尾使用=True, 追尾起動幅pt=5, 追尾距離pt=None, 追尾起動=previous["armed"],
                最終追尾価格=previous["trail_stop"], 追尾起動時計秒=previous["trail_arm_time"],
                追尾起動原板行=previous["trail_arm_line"], 起動後純赤字=bool(previous["armed"] and trade["基準純損益円"] < 0),
                最終追尾から実返済方向差pt=previous["side"] * (trade["返済価格"] - previous["trail_stop"]) if previous["trail_stop"] is not None else None,
                追尾方式="公開SAR", ATR距離使用=False, SAR締上げ回数=previous["sar_updates"],
                最終SAR適用参照=deepcopy(previous["sar_applied"]))
            self.log("追尾建玉終了", now, line, previous, 返済理由=trade["返済理由"])
            if trade["起動後純赤字"]:
                self.log("起動済み純赤字約定", now, line, previous, 純損益円=trade["基準純損益円"])

    def bar(self, frame: dict) -> None:
        """当場最新の公開参照だけを置換し、古い気配では要求しない。

        引数: frame(dict)は公開された精密SAR行。
        返り値: None。無効値は古正常値へ戻さず、建玉の旧床は保持する。
        """
        if frame["場"] != self.session or not frame["publish"] or frame["confirm"] < frame["end"]:
            raise ValueError("SARの公開/場が不正")
        self.before(frame["confirm"])
        current = reference(frame)
        if self.latest_publication is not None and (current["confirm"], current["confirm_line"]) < (self.latest_publication["confirm"], self.latest_publication["confirm_line"]):
            raise ValueError("SAR公開key後退")
        self.latest_publication = current
        self.latest_sar = current if current["SAR公開可"] else None
        self.log("SAR公開参照更新", frame["confirm"], frame["confirm_line"],
            最新SAR参照=current, SAR候補有効=self.latest_sar is not None, 建玉設定凍結=self.pending is not None)

    def trail_check(self, now: float, line: int, bid: float, ask: float) -> None:
        """初回A5床と精密SAR上締上げを行い、正常BBOの初着を要求する。

        引数: now(float)は時計、line(int)は原行、bid/ask(float)は正常BBO。
        返り値: None。pending中は建玉の起動/線/適用出典を凍結する。
        """
        if self.position is None or self.pending is not None:
            return
        pos = self.position
        if pos["mfe"] < 5:
            return
        if not pos["armed"]:
            pos.update(armed=True, trail_arm_time=now, trail_arm_line=line)
            self.trail_armed += 1
            self.log("追尾起動", now, line)
            pos["trail_stop"] = pos["price"]
            self.trail_updates += 1
            self.log("追尾線更新", now, line, 旧追尾価格=None, 新追尾価格=pos["price"],
                丸め前価格=pos["price"], 更新根拠="初回同値床")
        source = self.latest_sar
        reason = "当場公開SAR未準備"
        if source is not None:
            if (now, line) <= (source["confirm"], source["confirm_line"]):
                reason = "SAR公開key後でない"
            elif source["SAR方向"] != pos["side"]:
                reason = "SAR方向不一致"
            else:
                value = J.unpack(source["SAR精密次足線"])
                if value is None:
                    raise ValueError("有効SARに精密次足線がない")
                if pos["side"] * (value - Fraction(pos["price"])) <= 0:
                    reason = "SAR名目利益strict正でない"
                else:
                    rounded = J.round_stop(value, pos["side"])
                    old = pos["trail_stop"]
                    new = max(old, rounded) if pos["side"] == 1 else min(old, rounded)
                    reason = "SAR候補非緩和維持"
                    if new != old:
                        pos.update(trail_stop=new, sar_applied=deepcopy(source), sar_updates=pos["sar_updates"] + 1)
                        self.trail_updates += 1
                        self.sar_updates += 1
                        reason = "SAR上締上げ"
                        self.log("追尾線更新", now, line, 旧追尾価格=old, 新追尾価格=new,
                            丸め前価格=float(value), 精密候補=J.pack(value), 呼値候補=rounded,
                            更新根拠="公開SAR次足線", SAR適用参照=source)
        self.sar_reasons[reason] += 1
        mark = bid if pos["side"] == 1 else ask
        if pos["side"] * (mark - pos["trail_stop"]) <= 0:
            self.trail_requests += 1
            self.log("追尾閾値初着", now, line, 返済気配=mark)
            self.request("返済", pos["side"], now, line, "必須利益追尾", pos["event_id"])

    def quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """固定の期限/pending/hard/TP処理の後にだけXSを監視する。

        引数: now/line(float/int)は根拠、bid/ask(float)は正常BBO。
        返り値: None。旧ATR追尾のquoteは呼ばない。
        """
        self.last_bbo = now, line, bid, ask
        M.利益保護状態.quote(self, now, line, bid, ask)
        self.trail_check(now, line, bid, ask)

    def finish(self) -> dict:
        """共通会計にSAR上締上げの件数だけを付ける。

        引数: なし。
        返り値: dictは一場の品質・会計。ATR距離は未使用とする。
        """
        result = super().finish()
        result.update(追尾方式="公開SAR", ATR距離使用=False, SAR締上げ回数=self.sar_updates,
            SAR評価理由別=dict(self.sar_reasons))
        return result


# ----------------------------------------
# X0は旧関数直呼出し、XSは同じ原行順へ公開SARイベントだけ接続する。


def replay(events: list[Any], signals: list[dict], frames: list[dict], sar_rows: list[dict],
           session: str, method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """同一純入口で固定X0又は精密公開XSを再生する。

    引数: events(list[Any])は気配、signals/frames/sar_rows(list[dict])は純信号/旧3分足/SAR、session/method/role(str)は識別、config/policy(dict)は運用/出口、bounds(tuple|None)は人工時計。
    返り値: tuple[Any,dict]は状態と一場会計。ラベルを参照しない。
    """
    if policy == {"出口ID": "X0"}:
        return BASE.replay(events, signals, frames, session, method, config, policy, role, bounds)
    state = SAR追尾状態(session, method, config, policy, role, signals, bounds)
    grouped, identities = defaultdict(list), set()
    for row in signals:
        if row["イベントID"] in identities or row["場"] != session or row["side"] not in (-1, 1):
            raise ValueError("入口の一意性/場/方向が不正")
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
    for row in sar_rows:
        if row["publish"] and state.start <= row["confirm"] < state.end:
            timeline.append((row["confirm"], row["confirm_line"], 1, row))
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
