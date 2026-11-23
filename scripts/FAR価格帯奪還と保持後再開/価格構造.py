"""公開Recordだけで価格構造を計算する純モジュール。

損益・Source・金融・原板の入力を持たない。公開品質検証だけ固定88を再用する。
可用性前検査の価格式を分離し、Go保存schemaのreason/counterを明示する。
分離元SHA256: 5fefd139c883cf82a2fdd3c4659fe58981fb242c324fbb7530c3511174936785
"""

from __future__ import annotations
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts/FAR背景維持と押戻し再開/イベント保存照合.py"
_SPEC = importlib.util.spec_from_file_location("固定88公開品質", AUDIT_PATH)
BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(BASE)
require = BASE.require


def level_status(i: dict, p: dict, side: int, window: str, epoch: float, feet: dict) -> tuple:
    """
    機能: iからpの全確定Closeの既知性とH/L配列を確認する。
    引数: i/p(dict)、side(int)、window(str)、epoch(float)、feet(dict)は当時値。
    返り値: tuple[str,float|None,float|None]は可用区分・H・L。
    """
    ends = list(range(int(i["bar_end"]), int(p["bar_end"]) + 1, 180))
    if not ends or ends[0] != i["bar_end"] or ends[-1] != p["bar_end"]:
        return "足不足", None, None
    if len(ends) < 2:
        return "足不足", None, None
    keys = [(window, epoch, end) for end in ends]
    if any(key not in feet for key in keys):
        return "連続足欠落", None, None
    rows = [feet[k] for k in keys]
    if any(r["point"]["published_at"] > p["published_at"] or r["close"] <= 0 for r in rows):
        return "公開又はClose未知", None, None
    if rows[0]["point"]["observation_id"] != i["observation_id"] or rows[-1]["point"]["observation_id"] != p["observation_id"]:
        return "point出典不一致", None, None
    high, low = max(side * r["close"] for r in rows[:-1]), side * rows[-1]["close"]
    return ("可用" if high > low else "構造H<=L"), high, low



def event_point(record: dict) -> dict:
    """
    機能: 既存観測を共通の小型Pointへ結ぶ。
    引数: record(dict)は公開済み足。
    返り値: dictはID・足終端・公開時刻だけの値。
    """
    x = record["input"]
    return {"observation_id": record["id"], "bar_end": x["technical"]["bar3_end"], "published_at": x["at"]}


@dataclass
class IndependentEpisode:
    """旧kと金融へ依存しない固定i/pと価格attempt。"""

    session: str
    side: int
    window: str
    epoch: float
    i: dict
    p: dict
    i_birth: str
    high: dict | None
    low: dict | None
    status: str
    attempt: int = 1
    b: dict | None = None
    peak: dict | None = None
    h: dict | None = None
    v: dict | None = None
    h_first: dict | None = None
    completion: dict | None = None
    ended: str | None = None
    reason: str = "平均側でない最新押しを更新"
    expired_counted: bool = False
    counts: Counter = field(default_factory=Counter)

    @property
    def identity(self) -> str:
        """
        機能: 価格文脈だけからepisodeを識別する。
        引数: なし。
        返り値: strは場・方向・i/p観測ID。
        """
        return f"{self.session}|S{self.side}|I{self.i['observation_id']}|P{self.p['observation_id']}"

    def lose(self, reason: str, all_context: bool) -> None:
        """
        機能: 完成の失効理由を保存し、価格段階を破棄する。
        引数: reason(str)、all_context(bool)は理由と全文脈消去。
        返り値: None。破棄したvを隠し保持しない。
        """
        if self.completion is not None:
            self.completion["失効"] = reason
        if all_context:
            self.ended = reason
        else:
            self.counts["H以下reset"] += 1
            self.attempt += 1
            self.b = self.peak = self.h = self.h_first = self.v = self.completion = None
            self.expired_counted = False
            self.reason = "押し前終値基準以下で価格attemptを破棄"

    def step(self, record: dict, next_grid: int | None) -> dict | None:
        """
        機能: EMA同方向の正常新足で修正版のb/P/h/vを進める。
        引数: record(dict)、next_grid(int|None)は当足と次定時。
        返り値: dict|Noneは初回完成の出典。vに勢いgateを足さない。
        """
        if self.status != "可用":
            self.reason = "押し前終値基準が押し終値以下"
            return None
        q, close = event_point(record), record["input"]["technical"]["close3"]
        x, high = self.side*close, self.side*self.high["close"]
        require(q["bar_end"] > self.p["bar_end"], "pとbは別足")
        if x <= high:
            if self.b is not None:
                self.lose("H以下へ回帰", False)
            self.reason = "押し前終値基準以下で価格attemptを破棄"
            return None
        if self.b is None:
            self.b, self.peak = q, {"point": q, "close": close}
            self.counts["b"] += 1
            self.reason = "押し前終値基準を初めて奪還"
            return None
        if self.v is not None:
            return None
        peak_x = self.side*self.peak["close"]
        if self.h is None:
            if x > peak_x:
                self.peak = {"point": q, "close": close}
                self.counts["P更新"] += 1
                self.reason = "保持前の方向側最高終値を更新"
            elif x < peak_x:
                self.h = {"point": q, "close": close}
                self.h_first = q
                self.counts["h開始"] += 1
                self.reason = "突破後の調整を観測"
            return None
        require(q["bar_end"] > self.h["point"]["bar_end"], "hとvは別足")
        if x < self.side*self.h["close"]:
            self.h = {"point": q, "close": close}
            self.counts["h低下更新"] += 1
            self.reason = "保持中の方向側最低終値を更新"
        if x <= peak_x:
            return None
        self.v = q
        self.counts["v"] += 1
        self.reason = "固定最高終値を越え価格再開を確認"
        self.expired_counted = False
        self.completion = {"session": self.session, "id": f"{self.identity}|A{self.attempt}",
                           "side": self.side, "window": self.window, "epoch_start": self.epoch,
                           "i_birth": self.i_birth, "i": self.i, "p": self.p,
                           "H": self.high, "L": self.low, "b": self.b, "P": self.peak,
                           "h_first": self.h_first, "h": self.h, "v": self.v,
                           "次定時番号": next_grid, "失効": None, "最初の定時": None}
        return self.completion


@dataclass
class IndependentDirection:
    """未知・背景・独立i/pを分ける一方向の公開状態。"""

    side: int
    reason: str = "公開入力なし"
    required_unknown: bool = True
    i: dict | None = None
    i_birth: str | None = None
    episode: IndependentEpisode | None = None


class PriceTracker:
    """公開Recordだけを受ける価格器。Source・旧k・損益は入力しない。"""

    def __init__(self, session: str) -> None:
        """
        機能: 場間状態なしの独立器を初期化する。
        引数: session(str)は出典の場ID。
        返り値: None。金融・Sourceへの参照を持たない。
        """
        self.session, self.last, self.last_bar = session, None, None
        self.last_id = 0
        self.states = {side: IndependentDirection(side) for side in (1, -1)}
        self.feet, self.episodes, self.completions = {}, [], []
        self.diagnostic_counts = Counter()
        self.reset_calls = Counter()

    def clear(self, side: int, reason: str, unknown: bool) -> None:
        """
        機能: 方向文脈を全破棄し、既知不成立と未知を区別する。
        引数: side(int)、reason(str)、unknown(bool)は方向と失効。
        返り値: None。以前のvを次i候補として隠し保存しない。
        """
        old = self.states[side]
        if old.i is not None:
            self.diagnostic_counts[f"文脈破棄:{reason}"] += 1
        if old.episode is not None:
            old.episode.lose(reason, True)
        self.states[side] = IndependentDirection(side, reason, unknown)

    def make_episode(self, state: IndependentDirection, record: dict) -> None:
        """
        機能: 当足をpへ先に固定してからH/Lを構築する。
        引数: state(IndependentDirection)、record(dict)は独立iと公開足。
        返り値: None。旧k・Source有無でH区間を変えない。
        """
        x, p = record["input"], event_point(record)
        if state.episode is not None:
            state.episode.lose("新pへ更新", True)
        status, _, _ = level_status(state.i, p, state.side, x["window"], x["epoch_start"], self.feet)
        high = low = None
        if status in ("可用", "構造H<=L"):
            rows = [self.feet[(x["window"], x["epoch_start"], end)]
                    for end in range(int(state.i["bar_end"]), int(p["bar_end"]), 180)]
            selected = max(rows, key=lambda row: state.side*row["close"])
            high = {"point": deepcopy(selected["point"]), "close": selected["close"]}
            low = {"point": p, "close": x["technical"]["close3"]}
        state.episode = IndependentEpisode(self.session, state.side, x["window"], x["epoch_start"],
                                           deepcopy(state.i), p, state.i_birth, high, low, status)
        state.reason = "平均側でない最新押しを更新"
        self.episodes.append(state.episode)
        self.diagnostic_counts["p版"] += 1

    def feed(self, record: dict, next_grid: int | None = None) -> None:
        """
        機能: 全公開Recordの品質を見て、新足だけで独立段階を進める。
        引数: record(dict)、next_grid(int|None)は既存公開値と次定時番号。
        返り値: None。kindの旧期限通知は寿命条件に使わない。
        """
        x, v = record["input"], record["input"]["technical"]
        require(set(record) == BASE.RECORD_FIELDS and type(record["id"]) is int and record["id"] == self.last_id+1, "独立RecordIDの連続性")
        require(set(x) == BASE.INPUT_FIELDS and type(x["ordinal"]) is int and x["ordinal"] > 0 and type(x["after_eof"]) is bool, "独立入力schema")
        require(BASE.finite(x["at"]) and x["at"] > 0 and BASE.finite(x["epoch_start"]) and 0 <= x["epoch_start"] <= x["at"], "独立公開時計")
        q = x["quote"]
        require(set(q) == BASE.QUOTE_FIELDS and type(q["valid"]) is bool and type(q["index"]) is int and type(q["line"]) is int, "独立気配schema")
        require(all(BASE.finite(q[k]) for k in ("time", "last", "bid", "ask")) and q["time"] <= x["at"] and x["origin"] in ("quote", "three_timer", "core_timer"), "独立気配又は公開元")
        if self.last is not None:
            require(x["ordinal"] > self.last["ordinal"] and x["at"] >= self.last["at"], "独立入力の順序")
        BASE.validate_technical(x["at"], v)
        self.diagnostic_counts["Record"] += 1
        epoch_changed = self.last is None or (x["window"], x["epoch_start"]) != (self.last["window"], self.last["epoch_start"])
        changed = self.last is None or v["bar3_end"] != self.last["technical"]["bar3_end"]
        unknown = not BASE.technical_known(v) or v["bar3_end"] <= 0 or v["bar15_end"] <= 0 or x["at"]-v["bar3_end"] > 180 or x["at"]-v["bar15_end"] > 900
        bad_last = x["origin"] == "quote" and x["quote"]["last"] <= 0
        gap = changed and not epoch_changed and self.last_bar is not None and (v["bar3_end"]-self.last_bar["bar3_end"] != 180 or self.last_bar["histogram3"] != v["previous_histogram3"] or self.last_bar["rsi3"] != v["previous_rsi3"])
        reason = ("原板終端後のため失効" if x["after_eof"] else "静観又は場末のため失効" if x["window"] not in BASE.ACTIVE_WINDOWS else
                  "Source時間窓を開始" if epoch_changed else "Last不良で必要値を失効" if bad_last else
                  "確定足の必要値又は鮮度が未知" if unknown else "確定3分の欠足又は前値結合が不成立" if gap else None)
        if reason:
            self.reset_calls[reason] += 1
            u = unknown if epoch_changed else bad_last or unknown or gap
            if x["after_eof"] or x["window"] not in BASE.ACTIVE_WINDOWS:
                u = False
            for side in self.states:
                self.clear(side, reason, u)
        if changed and v["bar3_end"] > 0:
            self.diagnostic_counts["bars"] += 1
        if reason is None:
            for side, state in self.states.items():
                e = state.episode
                if e is not None and e.v is not None and not e.expired_counted and x["at"]-e.v["bar_end"] >= 900 and side*(v["ema8_15"]-v["ema21_15"]) > 0:
                    e.expired_counted = True
                    self.diagnostic_counts["expired_triggers"] += 1
        active = x["window"] in BASE.ACTIVE_WINDOWS and not x["after_eof"] and not unknown and not bad_last
        if changed and v["bar3_end"] > x["epoch_start"] and v["close3"] > 0:
            key = (x["window"], x["epoch_start"], v["bar3_end"])
            require(key not in self.feet, "独立の同足再追加")
            self.feet[key] = {"point": event_point(record), "close": v["close3"]}
            self.diagnostic_counts["新足Close"] += 1
        if active:
            for side in (1, -1):
                if not changed or v["bar3_end"] <= x["epoch_start"]:
                    continue
                if side*(v["ema8_15"]-v["ema21_15"]) <= 0:
                    self.clear(side, "15分背景が同方向を支持しない", False)
                    continue
                state = self.states[side]
                state.required_unknown = False
                price = side*(v["close3"]-v["ema8_3"]) > 0
                momentum = side*(v["histogram3"]-v["previous_histogram3"]) > 0 and side*(v["rsi3"]-v["previous_rsi3"]) > 0
                if state.i is None:
                    if price and momentum:
                        state.i, state.i_birth, state.reason = event_point(record), "fresh", "背景内の価格と勢いの推進を観測"
                        self.diagnostic_counts["i出生:fresh"] += 1
                    else:
                        state.reason = "背景支持下の推進を待つ"
                    continue
                e = state.episode
                if e is not None and e.v is not None and not price:
                    next_i = deepcopy(e.v)
                    e.lose("自身vを次iへ継承", True)
                    state.i, state.i_birth, state.episode = next_i, "completed_v", None
                    self.diagnostic_counts["i出生:completed_v"] += 1
                    self.make_episode(state, record)
                    continue
                if not price:
                    self.make_episode(state, record)
                    continue
                if e is not None:
                    completed = e.step(record, next_grid)
                    if completed is not None:
                        self.completions.append(completed)
        common_reset = x["after_eof"] or x["window"] not in BASE.ACTIVE_WINDOWS or epoch_changed or bad_last or unknown
        reset_without_reseed = common_reset and not (epoch_changed and active and v["bar3_end"] > x["epoch_start"])
        if reset_without_reseed:
            self.last_bar = None
        elif changed and v["bar3_end"] > 0:
            self.last_bar = deepcopy(v)
        self.last = deepcopy(x)
        self.last_id = record["id"]

    def snapshot(self, at: float) -> dict:
        """
        機能: 観測時計を変更せず定時状態とvの供給期限を返す。
        引数: at(float)は最後の公開時計以降。
        返り値: dictは共通Point/Levelと二方向の純snapshot。
        """
        require(BASE.finite(at) and at > 0 and (self.last is None or at >= self.last["at"]), "独立snapshot時計")
        window, epoch = (self.last["window"], self.last["epoch_start"]) if self.last else ("", 0)
        out = {"at": at, "window": window, "epoch_start": epoch, "directions": []}
        for side in (1, -1):
            s = self.states[side]
            e = s.episode
            stage = "背景待ち" if s.i is None else "推進" if e is None else "完成" if e.v is not None else "保持後" if e.h is not None else "奪還後" if e.b is not None else "押し"
            valid = e is not None and e.v is not None and not s.required_unknown and e.window == window and e.epoch == epoch and 0 <= at-e.v["bar_end"] < 900
            out["directions"].append({"side": side, "known": not s.required_unknown, "required_unknown": s.required_unknown,
                                      "stage": stage, "reason": s.reason if e is None else e.reason,
                                      "impulse": deepcopy(s.i), "pullback": deepcopy(e.p) if e else None,
                                      "impulse_origin": s.i_birth or "", "high": deepcopy(e.high) if e else None,
                                      "low": deepcopy(e.low) if e else None, "reclaim": deepcopy(e.b) if e else None,
                                      "peak": deepcopy(e.peak) if e else None, "hold": deepcopy(e.h["point"]) if e and e.h else None,
                                      "resume": deepcopy(e.v) if e else None, "trigger_valid": valid,
                                      "expires_at": e.v["bar_end"]+900 if e and e.v else None})
        return out

    def counts(self) -> dict:
        """
        機能: GoのPriceCountsと同じ小型counterを独立値で返す。
        引数: なし。
        返り値: dictは全feed/新BarEnd/各段階/期限/共通resetの整数値。
        """
        phase = sum((e.counts for e in self.episodes), Counter())
        return {"records": self.diagnostic_counts["Record"], "bars": self.diagnostic_counts["bars"],
                "fresh_impulses": self.diagnostic_counts["i出生:fresh"],
                "inherited_impulses": self.diagnostic_counts["i出生:completed_v"],
                "episodes": self.diagnostic_counts["p版"], "reclaims": phase["b"],
                "peak_updates": phase["P更新"], "holds": phase["h開始"],
                "hold_updates": phase["h低下更新"], "resumes": phase["v"],
                "attempt_resets": phase["H以下reset"], "expired_triggers": self.diagnostic_counts["expired_triggers"],
                "resets": deepcopy(dict(self.reset_calls))}


