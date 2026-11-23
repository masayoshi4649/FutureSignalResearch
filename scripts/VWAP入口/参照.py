"""00017小列を価格足の公開原行までに結び、同場四点の共通準備を作る。"""

from __future__ import annotations

from collections import Counter, deque
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("VWAP入口の固定17小列", ROOT/"scripts/VWAP入力/抽出監査.py")
PREP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREP
SPEC.loader.exec_module(PREP)
Event = PREP.Event
FIELDS = ("配信VWAP", "当場差分VWAP", "配信3足前VWAP", "差分3足前VWAP",
          "補助epoch", "identity", "native有効", "差分有効", "N共通準備", "D共通準備",
          "補助参照", "N除外理由", "D除外理由")


def finite(*values: float | None) -> bool:
    """全数値が有限かを調べる。

    引数: values (float|None) は対象。
    返り値: bool は全て定義済み有限か。
    """
    return all(v is not None and math.isfinite(v) for v in values)


class Online:
    """場ごとの不変接頭基準・累積epoch・最新原行状態を持つ。"""

    def __init__(self, session: str, metadata: dict) -> None:
        """補助の同場状態を初期化する。

        引数: session (str) は場、metadata (dict) は限月/取引所対応表。
        返り値: None。前場の補助状態を持ち越さない。
        """
        self.start, self.finish, self.floor = PREP.bounds(session)
        self.meta = metadata
        self.maximum = None
        self.previous = self.base = self.current = None
        self.known = {}
        self.epoch = 0
        self.counts = Counter()
        self.reasons = []

    def identity(self, event: Event) -> dict:
        """場内番号を原値へ解決する。

        引数: event (Event) は状態。
        返り値: dict は限月・市場・始値時計/価格。未知はNone。
        """
        codes, markets = self.meta["contract_codes"], self.meta["exchange_values"]
        if event.contract < -1 or event.contract >= len(codes) or event.exchange < -1 or event.exchange >= len(markets):
            raise ValueError("補助対応表の範囲外")
        return {"限月": codes[event.contract] if event.contract >= 0 else None,
                "市場": markets[event.exchange] if event.exchange >= 0 else None,
                "始値時計": event.opening_time if finite(event.opening_time) and event.opening_time > 0 else None,
                "始値価格": event.opening_price if finite(event.opening_price) and event.opening_price > 0 else None}

    def ratio(self, event: Event) -> tuple[bool, float | None]:
        """固定1000換算・4桁余裕の内部整合を判定する。

        引数: event (Event) は現在状態。
        返り値: tuple[bool,float|None] は整合と絶対差。
        """
        if not finite(event.volume, event.native_vwap, event.trading_value) or event.volume <= 0 or event.native_vwap <= 0 or event.trading_value < 0:
            return False, None
        error = abs(event.native_vwap-event.trading_value/event.volume/1000)
        return finite(error) and error <= .00010001, error if finite(error) else None

    def apply(self, event: Event) -> None:
        """原順の状態を一回だけ処理し、基準と区間を更新する。

        引数: event (Event) は補助原行。
        返り値: None。後退行・先行数量を並べ替えたり遡及配分したりしない。
        """
        self.current, self.reasons = event, []
        self.counts["参照まで処理した状態数"] += 1
        if not finite(event.now):
            self.reasons.append("価格時計欠測")
            return
        key = event.now, event.line
        if self.maximum is not None and key < self.maximum:
            self.reasons.append("価格時計原行後退")
            self.counts["後退除外状態数"] += 1
            return
        self.maximum = key
        if not finite(event.volume_time) or event.volume_time > event.now:
            self.reasons.append("数量時計欠測または先行")
            return
        if not finite(event.volume, event.trading_value) or min(event.volume, event.trading_value) < 0:
            self.reasons.append("累積数量代金不正")
            return
        identity = self.identity(event)
        changes = []
        if self.previous is not None:
            for field, name in (("volume", "数量減少"), ("trading_value", "代金減少"), ("volume_time", "数量時計後退")):
                if getattr(event, field) < getattr(self.previous, field):
                    changes.append(name)
        for name, value in identity.items():
            if value is None:
                continue
            if name in self.known and self.known[name] != value:
                changes.append(name+"不一致")
            self.known[name] = value
        if changes:
            self.epoch += 1
            self.base = None
            self.counts["累積区間変更数"] += 1
        self.previous = event
        known = all(v is not None for v in identity.values()) and event.opening_time <= event.now
        consistent, _ = self.ratio(event)
        if (self.floor <= event.now < self.start and self.floor <= event.volume_time < self.start
                and known and (consistent or event.volume == event.trading_value == 0)):
            self.base = event
        if event.now == self.start and event.volume_time <= self.start and event.volume == event.trading_value == 0 and known:
            self.base = event

    def snapshot(self, key: tuple[float, int]) -> dict:
        """公開キーで最新状態の利用可否を評価する。

        引数: key (tuple[float,int]) は価格足の確認時計/原行。
        返り値: dict は現在値と基準参照、不可理由。古い正常値へfallbackしない。
        """
        e, reasons = self.current, list(self.reasons)
        empty = {"配信VWAP": None, "当場差分VWAP": None, "補助epoch": self.epoch,
                 "identity": None, "native有効": False, "差分有効": False, "補助参照": None,
                 "現在不可理由": ["参照原行なし"]}
        if e is None:
            return empty
        identity = self.identity(e)
        consistent, error = self.ratio(e)
        if not finite(e.now) or not self.start <= e.now < self.finish:
            reasons.append("価格時計場外または不明")
        if not finite(e.now) or (e.now, e.line) > key or e.line > key[1]:
            reasons.append("公開上限外")
        if not finite(e.volume_time) or not self.start <= e.volume_time <= e.now:
            reasons.append("数量時計場外先行または不明")
        if not finite(e.last) or e.last <= 0:
            reasons.append("Last非正または不明")
        if not consistent:
            reasons.append("配信内部比率不整合または未定義")
        if any(v is None for v in identity.values()) or not finite(e.opening_time) or e.opening_time > e.now:
            reasons.append("identity未確認")
        native_ok = not reasons
        differential, delta_q, delta_t = None, None, None
        base = self.base
        if base is not None and native_ok and identity == self.identity(base):
            delta_q, delta_t = e.volume-base.volume, e.trading_value-base.trading_value
            if delta_q > 0 and delta_t > 0:
                differential = delta_t/delta_q/1000
        difference_ok = native_ok and differential is not None and finite(differential) and differential > 0
        reference = {**PREP.snapshot(e), "内部比率整合": consistent, "内部絶対差pt": error,
                     "最大既知キー": list(self.maximum) if self.maximum is not None else None,
                     "基準": PREP.snapshot(base) if base is not None else None,
                     "差分数量": delta_q, "差分代金": delta_t, "現在不可理由": sorted(set(reasons))}
        return {"配信VWAP": e.native_vwap if native_ok else None,
                "当場差分VWAP": differential if difference_ok else None,
                "補助epoch": self.epoch, "identity": identity, "native有効": native_ok,
                "差分有効": difference_ok, "補助参照": reference, "現在不可理由": sorted(set(reasons))}


def build(events: Iterable[Event], frames: list[dict], session: str, metadata: dict,
          config: dict) -> tuple[dict[int, dict], dict]:
    """全価格足を原板確認行までの補助状態へ結合し、同epoch四点を準備する。

    引数: events (Iterable[Event]) は原順小列、frames (list[dict]) は同場同尺度価格足、
    session (str) は場、metadata/config (dict) は対応表と固定条件。
    返り値: tuple[dict[int,dict],dict] は足別参照と品質。非公開足・欠枠で四点履歴を切る。
    """
    if config["参照条件"] != {"連続点数": 4, "傾き差本数": 3, "判断時点": True}:
        raise ValueError("同場四点と三足前だけを扱う")
    source, state = iter(events), Online(session, metadata)
    current = next(source, None)
    history, result, counts = deque(maxlen=4), {}, Counter()
    previous_index, previous_key = None, None
    for frame in frames:
        index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
        if index in result or (previous_index is not None and index <= previous_index):
            raise ValueError("価格足番号の重複/後退")
        gap = previous_index is not None and index != previous_index+1
        previous_index = index
        delayed = frame["confirm"]-frame["end"] > 30
        if gap or frame["missing"] or not frame["publish"] or delayed:
            history.clear()
        if not frame["publish"]:
            row = {"配信VWAP": None, "当場差分VWAP": None, "補助epoch": state.epoch,
                   "identity": None, "native有効": False, "差分有効": False,
                   "補助参照": None, "現在不可理由": ["非公開価格足"]}
        else:
            if frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key:
                raise ValueError("価格足公開キー不正")
            previous_key = key
            while current is not None and current.line <= key[1]:
                state.apply(current)
                current = next(source, None)
            row = state.snapshot(key)
            if delayed:
                row["native有効"] = row["差分有効"] = False
                row["現在不可理由"] = row["現在不可理由"]+["価格足確認遅延30秒超"]
        if history and row["補助epoch"] != history[-1]["補助epoch"]:
            history.clear()
        if not row["native有効"]:
            history.clear()
        if row["native有効"]:
            history.append(row)
        consecutive = len(history) == 4 and len({p["補助epoch"] for p in history}) == 1
        n_ready = consecutive and all(p["native有効"] for p in history)
        base_lines = {p["補助参照"]["基準"]["line"] for p in history
                      if p["補助参照"] is not None and p["補助参照"]["基準"] is not None}
        d_ready = n_ready and all(p["差分有効"] for p in history) and len(base_lines) == 1
        n_reasons = [] if n_ready else list(row["現在不可理由"])+(["同場四点未準備"] if len(history) < 4 else [])+(["四点nativeまたはepoch不成立"] if len(history) == 4 else [])
        d_reasons = [] if d_ready else n_reasons+(["四点差分基準または正増分未準備"] if not all(p["差分有効"] for p in history) else [])+(["四点差分基準不一致"] if len(base_lines) != 1 else [])
        result[index] = {k: row[k] for k in ("配信VWAP", "当場差分VWAP", "補助epoch", "identity", "native有効", "差分有効", "補助参照")}
        result[index].update({"配信3足前VWAP": history[0]["配信VWAP"] if n_ready else None,
                              "差分3足前VWAP": history[0]["当場差分VWAP"] if d_ready else None,
                              "N共通準備": bool(n_ready), "D共通準備": bool(d_ready),
                              "N除外理由": sorted(set(n_reasons)), "D除外理由": sorted(set(d_reasons))})
        for name, value in (("価格足数", True), ("公開足数", frame["publish"]),
                            ("native有効足数", row["native有効"]), ("差分有効足数", row["差分有効"]),
                            ("N共通準備足数", n_ready), ("D共通準備足数", d_ready)):
            counts[name] += int(value)
    return result, {**dict(counts), **dict(state.counts)}
