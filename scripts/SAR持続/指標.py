"""固定24指標を読み取り、新規の鏡像SAR銀行だけを別に保持する。"""

from collections import deque
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("SAR持続の固定24指標", ROOT/"scripts/終値切替/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
W, Indicators, features, ChannelBank = BASE.W, BASE.Indicators, BASE.features, BASE.ChannelBank
SOURCE_FIELDS = BASE.SOURCE_FIELDS


def valid_ohlc(frame: dict) -> bool:
    """完全な足の価格が有限正で、高安が始終値を含むか検査する。

    引数: frame(dict)は3分足。
    返り値: boolはSAR数値銀行への投入可否。公開可否とは別にする。
    """
    fields = ("open", "high", "low", "close")
    return bool(all(isinstance(frame.get(k), (float, int)) and math.isfinite(frame[k]) and frame[k] > 0 for k in fields)
        and frame["high"] >= max(frame["open"], frame["close"]) >= min(frame["open"], frame["close"]) >= frame["low"])


def source_snapshot(frame: dict) -> dict:
    """非有限値を欠測へ正規化して足の出典を保存する。

    引数: frame(dict)は入力足。NaN/無限大は数値入力前の検査で不正として扱う。
    返り値: dictはSOURCE_FIELDSのJSON安全な写し。欠測を価格へ補完しない。
    """
    return {k: None if k in ("open", "high", "low", "close") and isinstance(frame[k], float)
        and not math.isfinite(frame[k]) else frame[k] for k in SOURCE_FIELDS}


class SARBank:
    """方向・表示線・次線・極値・AFを同限月内で逐次保持する。"""

    def __init__(self) -> None:
        """未初期化の銀行と、過去二足の出典を作る。

        引数: なし。
        返り値: None。同限月場間の履歴を保持し、build内の欠枠等でclearする。
        """
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """数値状態と直近二足を解除する。

        引数: なし。
        返り値: None。限月識別子はbuildが管理する。
        """
        self.history = deque(maxlen=2)
        self.direction = 0
        self.display = None
        self.next_line = None
        self.ep = None
        self.af = None

    def update(self, frame: dict, session: str, reasons: list[str] | None = None) -> dict:
        """当足のOHLCを一回だけ使い、三種類の線と観測後状態を返す。

        引数: frame(dict)は完全幅3分足、session(str)は場、reasons(list[str]|None)は直前reset理由。
        返り値: dictは全入力/出典/状態。未公開の数値更新を公開判定へ昇格しない。
        """
        prior_sources = deepcopy(list(self.history))
        active = self.next_line if self.direction else None
        before_direction, before_ep, before_af = self.direction, self.ep, self.af
        initial, reversed_now, numeric = False, False, valid_ohlc(frame)
        if numeric:
            if not self.direction:
                if self.history and frame["close"] != self.history[-1]["close"]:
                    previous = self.history[-1]
                    self.direction = 1 if frame["close"] > previous["close"] else -1
                    self.display = min(previous["low"], frame["low"]) if self.direction == 1 else max(previous["high"], frame["high"])
                    self.ep = frame["high"] if self.direction == 1 else frame["low"]
                    self.af = 0.02
                    initial = True
            else:
                reversed_now = frame["low"] < active if self.direction == 1 else frame["high"] > active
                if reversed_now:
                    self.direction *= -1
                    self.display = min(before_ep, frame["low"]) if self.direction == 1 else max(before_ep, frame["high"])
                    self.ep = frame["high"] if self.direction == 1 else frame["low"]
                    self.af = 0.02
                else:
                    limits = [f["low"] if self.direction == 1 else f["high"] for f in self.history]
                    self.display = min(active, *limits) if self.direction == 1 else max(active, *limits)
                    extreme = frame["high"] if self.direction == 1 else frame["low"]
                    if self.direction*(extreme-self.ep) > 0:
                        self.ep = extreme
                        self.af = min(0.2, self.af+0.02)
            if self.direction:
                self.next_line = self.display+self.af*(self.ep-self.display)
            self.history.append({"場": session, **source_snapshot(frame)})
        ready = bool(numeric and self.direction in (-1, 1) and all(v is not None and math.isfinite(v) for v in (self.display, self.next_line, self.ep, self.af)))
        return {"場": session, **source_snapshot(frame),
            "SAR準備済": ready, "SAR公開可": bool(ready and frame["publish"]),
            "SAR方向": self.direction if ready else 0, "SAR事前方向": before_direction,
            "SAR事前線": active, "SAR表示線": self.display if ready else None,
            "SAR次足線": self.next_line if ready else None, "SAR_EP": self.ep if ready else None,
            "SAR_AF": self.af if ready else None, "SAR事前EP": before_ep, "SAR事前AF": before_af,
            "SAR反転": reversed_now, "SAR初期化": initial, "SAR数値入力可": numeric,
            "SAR前二足": prior_sources, "SAR解除理由": list(reasons or [])}

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """一場の完全幅足を公開キー順に更新し、尾部欠枠のcarryを止める。

        引数: frames(list[dict])は3分足、session(str)は場、contract(tuple)は限月、tail_missing(int)は完全幅尾部欠枠。
        返り値: tuple[list[dict],dict]はNPを含む全足数値と品質。注文用局所前値は入口が同場で割り当てる。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        rows, previous_index, previous_key = [], None, None
        reset_count = int(changed)
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != 3 or previous_index is not None and index <= previous_index:
                raise ValueError("SARの足幅/足番号が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key):
                raise ValueError("SAR公開前足又は公開key後退")
            reasons = ["限月変更"] if changed and previous_index is None else []
            if previous_index is None and index != 0 or previous_index is not None and index != previous_index+1:
                reasons.append("3分番号欠枠")
            if frame["missing"]:
                reasons.append("3分欠枠")
            if not valid_ohlc(frame):
                reasons.append("3分OHLC不正")
            if any(r != "限月変更" for r in reasons):
                self.clear()
                reset_count += 1
            rows.append(self.update(frame, session, reasons))
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            reset_count += 1
        return rows, {"場": session, "SAR入力足数": len(rows), "SAR数値準備足数": sum(r["SAR準備済"] for r in rows),
            "SAR公開準備足数": sum(r["SAR公開可"] for r in rows), "SAR初期化数": sum(r["SAR初期化"] for r in rows),
            "SAR反転数": sum(r["SAR反転"] for r in rows), "SAR未公開数値更新数": sum(not r["publish"] and r["SAR数値入力可"] for r in rows),
            "SARclear数": reset_count, "SAR尾部完全欠枠": tail_missing, "SAR場末方向": self.direction,
            "SAR場末次線": self.next_line, "SAR場末EP": self.ep, "SAR場末AF": self.af,
            "SAR全足内容SHA256": hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()}
