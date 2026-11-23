"""固定TP/SLを維持し、入口固定または公開足更新のnative通常出口を比較する。"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def module(path: Path, name: str) -> Any:
    """固定運用を変更せず読取利用する。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: Any はモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


CORE = module(ROOT/"scripts/テクニカル循環/運用.py", "VWAP復帰の旧11X0")
M = module(ROOT/"scripts/利益回収/運用.py", "VWAP復帰の固定幅会計")


class 通常状態(M.利益保護状態):
    """旧会計・hard125/250を保ち、native通常線だけを追加する。"""

    def __init__(self, session: str, method: str, config: dict, policy: dict, role: str,
                 signals: list[dict], bounds: tuple | None = None) -> None:
        """入口特徴と通常線のログを初期化する。

        引数: session/method/role (str) は場/候補/役割、config/policy (dict) は条件/出口、
        signals (list[dict]) は純入口、bounds (tuple|None) は合成時計。
        返り値: None。
        """
        if policy not in ({"出口ID": "X1"}, {"出口ID": "X2"}):
            raise ValueError("通常状態は固定X1/X2だけ")
        super().__init__(session, method, config, policy, role, signals, bounds)
        self.normal_log = []
        self.last_bbo = None
        self.normal_updates = self.normal_requests = self.epoch_requests = self.normal_unavailable = 0

    def log(self, action: str, now: float, line: int, position: dict | None = None, **data: Any) -> None:
        """通常線の全重要遷移を不変snapshotとして残す。

        引数: action (str) は動作、now/line (float/int) は公開キー、position (dict|None) は対象建玉、data (Any) は補足。
        返り値: None。非到達の全quoteは複製せず旧cacheから再検査できる。
        """
        pos = self.position if position is None else position
        details = {k: pos.get(k) for k in ("id", "event_id", "side", "price", "time", "line",
                  "native_entry", "native_level", "native_epoch", "native_updates")} if pos else None
        self.normal_log.append(deepcopy({"場": self.session, "候補ID": self.method,
            "順序": len(self.normal_log)+1, "動作": action, "時計秒": now, "原板行": line,
            "建玉": details, **data}))

    def request(self, kind: str, side: int, now: float, line: int, reason: str,
                event_id: str, signal: dict | None = None) -> None:
        """既存要求を作り、通常線の状態と要求理由を記録する。

        引数: kind/reason/event_id (str) は区分/理由/入口、side/line (int) は方向/原行、now (float) は時計、
        signal (dict|None) は元入口取扱。
        返り値: None。要求時計で即時約定させない。
        """
        super().request(kind, side, now, line, reason, event_id, signal)
        self.log("注文要求", now, line, 区分=kind, 理由=reason, 注文ID=self.pending["id"])

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """旧約定を実行し、要求時nativeを入口固定値として保持する。

        引数: now (float) は時計、line (int) は原行、bid/ask (float) は正常板。
        返り値: None。fill時の未来補助で入口nativeを引き直さない。
        """
        is_entry = self.pending is not None and self.pending["kind"] == "新規"
        previous, count = self.position, len(self.trades)
        super().fill(now, line, bid, ask)
        if is_entry and self.pending is None and self.position is not None:
            pos = self.position
            source = self.features[pos["event_id"]]
            native = source["配信VWAP"]
            if native is None or not math.isfinite(native) or native <= 0:
                raise ValueError("新規nativeが未定義")
            pos.update(native_entry=native, native_level=native,
                       native_epoch=source["補助epoch"], native_updates=0)
            self.log("通常線初期化", now, line, 入口要求時計=source["要求時計秒"],
                     入口要求原行=source["要求原板行"],
                     判断終値からnative方向距離pt=source.get("判断終値からnative方向距離pt"),
                     実新規から初期通常線方向距離pt=pos["side"]*(native-pos["price"]))
        if len(self.trades) > count:
            self.trades[-1].update(固定利確使用=True, 通常出口使用=True,
                入口配信VWAP=previous["native_entry"], 返済時通常線=previous["native_level"],
                入口補助epoch=previous["native_epoch"], 通常線更新数=previous["native_updates"],
                判断終値からnative方向距離pt=self.features[previous["event_id"]].get("判断終値からnative方向距離pt"),
                実新規から初期通常線方向距離pt=previous["side"]*(previous["native_entry"]-previous["price"]))
            self.log("通常建玉終了", now, line, previous, 返済理由=self.trades[-1]["返済理由"])

    def normal_check(self, now: float, line: int, bid: float, ask: float, origin: str) -> None:
        """現在の正常返済気配が通常線へ達したかを役割別に判定する。

        引数: now (float) は時計、line (int) は原行、bid/ask (float) は正常BBO、origin (str) はquote/更新直後。
        返り値: None。既存要求を上書きせず、等号を含めて+1秒後返済を要求する。
        """
        if self.position is None or self.pending is not None:
            return
        pos = self.position
        mark = bid if pos["side"] == 1 else ask
        distance = pos["side"]*(mark-pos["native_level"])
        hit = distance <= 0 if self.role == "順行" else distance >= 0
        if hit:
            reason = "VWAP通常逆抜け" if self.role == "順行" else "VWAP通常到達"
            self.log("通常閾値到達", now, line, 返済気配=mark, 判定元=origin, 理由=reason)
            self.normal_requests += 1
            self.request("返済", pos["side"], now, line, reason, pos["event_id"])

    def quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """期限/既存約定/hard125/hard250の後で通常線を判定する。

        引数: now (float) は時計、line (int) は原行、bid/ask (float) は正常板。
        返り値: None。Mの固定TPを保ち、非X0でTPを除く旧ChartStateは使用しない。
        """
        self.last_bbo = now, line, bid, ask
        super().quote(now, line, bid, ask)
        self.normal_check(now, line, bid, ask, "正常気配")

    def bar(self, frame: dict) -> None:
        """公開参照でepoch失効を優先し、X2だけ通常線を更新する。

        引数: frame (dict) は固定18参照を添えた同尺度価格足。
        返り値: None。古い正常BBOで新しい線への価格到達を作らない。
        """
        now, line = frame["confirm"], frame["confirm_line"]
        self.before(now)
        if self.position is None:
            return
        if self.pending is not None:
            self.log("通常足判定抑止", now, line, 理由="既存注文待機", 注文理由=self.pending["reason"])
            return
        pos = self.position
        if not frame["publish"] or frame["confirm"]-frame["end"] > 30 or not frame["native有効"]:
            self.normal_unavailable += 1
            self.log("通常線据置", now, line, 理由="有効公開native参照でない",
                     公開=frame["publish"], native有効=frame["native有効"])
            return
        if frame["補助epoch"] != pos["native_epoch"]:
            self.epoch_requests += 1
            self.log("起算不一致", now, line, 現epoch=frame["補助epoch"])
            self.request("返済", pos["side"], now, line, "VWAP起算失効", pos["event_id"])
            return
        if self.policy["出口ID"] == "X1":
            self.log("通常線据置", now, line, 理由="入口native固定")
            return
        if frame["end"] <= pos["time"]:
            self.log("通常更新抑止", now, line, 理由="足終了が新規約定後でない")
            return
        native = frame["配信VWAP"]
        if native is None or not math.isfinite(native) or native <= 0:
            raise ValueError("native有効と値が矛盾")
        old = pos["native_level"]
        pos["native_level"] = native
        pos["native_updates"] += 1
        self.normal_updates += 1
        self.log("通常線更新", now, line, 旧通常線=old, 新通常線=native)
        if self.last_bbo is not None and self.last_bbo[:2] == (now, line):
            self.normal_check(now, line, self.last_bbo[2], self.last_bbo[3], "同原行更新直後")
        else:
            self.log("通常価格判定待機", now, line, 理由="最新正常BBOが確認キーと異なる",
                     最新正常キー=list(self.last_bbo[:2]) if self.last_bbo else None)

    def finish(self) -> dict:
        """旧会計に通常出口の動作件数を付ける。

        引数: なし。
        返り値: dict は一場品質。未解消と通常線設定を混同しない。
        """
        result = super().finish()
        result.update(固定利確使用=True, 中心線超過新規数=0,
                      通常出口要求数=self.normal_requests, 起算失効要求数=self.epoch_requests,
                      通常線更新回数=self.normal_updates, 通常参照不可据置回数=self.normal_unavailable)
        return result


# ----------------------------------------
# X0は旧実装へ直接渡し、追加通常出口だけを新しい状態で原行再生する。

def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """気配→公開足→新規要求の順序を保ち三出口を再生する。

    引数: events (list[Any]) は旧気配、signals/frames (list[dict]) は純入口/参照付き価格足、
    session/method/role (str) は場/候補/役割、config/policy (dict) は会計/出口、bounds (tuple|None) は合成時計。
    返り値: tuple[Any,dict] は状態/場別会計。X0は旧CORE.replayそのもの。
    """
    if policy == {"出口ID": "X0"}:
        return CORE.replay(events, signals, frames, session, method, config, policy, role, bounds)
    state = 通常状態(session, method, config, policy, role, signals, bounds)
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
                raise ValueError("正常板フラグとBBOが不一致")
            timeline.append((event.now, event.line, 0, event))
    for frame in frames:
        if frame["publish"] and state.start <= frame["confirm"] < state.end:
            if frame["confirm"] < frame["end"]:
                raise ValueError("足終了前の公開")
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
