"""固定25の更新順序を、元OHLCと整数AFによる精密SARへ移す。"""

from collections import deque
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("SAR追尾の固定25数値規約", ROOT / "scripts/SAR持続/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SOURCE_FIELDS, valid_ohlc, source_snapshot = BASE.SOURCE_FIELDS, BASE.valid_ohlc, BASE.source_snapshot


def pack(value: Fraction | None) -> dict | None:
    """長い精密分数を桁制限のない16進文字列へ保存する。

    引数: value(Fraction|None)は精密値。
    返り値: dict|Noneは正規化された分子/正分母。十進floatを介さない。
    """
    return None if value is None else {"分子16進": hex(value.numerator), "分母16進": hex(value.denominator)}


def unpack(value: dict | None) -> Fraction | None:
    """正規形16進分子/分母から精密値を復元する。

    引数: value(dict|None)はpackの保存値。
    返り値: Fraction|Noneは精密値。不正・非正分母・非正規表現は例外。
    """
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"分子16進", "分母16進"}:
        raise ValueError("精密SAR分数のschema不正")
    numerator, denominator = int(value["分子16進"], 16), int(value["分母16進"], 16)
    if denominator <= 0:
        raise ValueError("精密SARの分母は正")
    result = Fraction(numerator, denominator)
    if pack(result) != value:
        raise ValueError("精密SAR分数が正規形でない")
    return result


def round_stop(value: Fraction, side: int) -> int:
    """精密線を実方向へ5pt呼値で切り上げる。

    引数: value(Fraction)は元精密線、side(int)は買1/売-1。
    返り値: intは買ceil/売floorの5pt倍数。任意epsilonは使わない。
    """
    if side not in (-1, 1) or not isinstance(value, Fraction):
        raise ValueError("精密線又は方向が不正")
    ratio = value / 5
    return 5 * (-((-ratio.numerator) // ratio.denominator) if side == 1 else ratio.numerator // ratio.denominator)


def canonical_sha(rows: list) -> str:
    """精密保存列をJSON正規形で指紋化する。

    引数: rows(list)は精密SAR行又は信号射影。
    返り値: strはUTF-8内容SHA256。
    """
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class SARBank:
    """同限月の数値carryと、公開可否を分けた精密SAR銀行。"""

    def __init__(self) -> None:
        """未初期化の銀行を作る。

        引数: なし。
        返り値: None。AFは分母100の整数で保持する。
        """
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """限月識別子を残して数値と前二足を解除する。

        引数: なし。
        返り値: None。方向0では公開候補を作らない。
        """
        self.history = deque(maxlen=2)
        self.direction, self.af = 0, 0
        self.display = self.next_line = self.ep = None

    def update(self, frame: dict, session: str, reasons: list | None = None) -> dict:
        """固定25と同順序で当足を一度更新する。

        引数: frame(dict)は完全幅3分足、session(str)は場、reasons(list|None)は直前解除理由。
        返り値: dictは精密値/float表示/出典/反転状態。NPの公開昇格はしない。
        """
        prior = deepcopy(list(self.history))
        active = self.next_line if self.direction else None
        before_direction, before_ep, before_af = self.direction, self.ep, self.af
        initial, reversed_now, numeric = False, False, valid_ohlc(frame)
        if numeric:
            current = {key: Fraction(frame[key]) for key in ("open", "high", "low", "close")}
            if not self.direction:
                if self.history and current["close"] != Fraction(self.history[-1]["close"]):
                    previous = self.history[-1]
                    self.direction = 1 if current["close"] > Fraction(previous["close"]) else -1
                    self.display = min(Fraction(previous["low"]), current["low"]) if self.direction == 1 else max(Fraction(previous["high"]), current["high"])
                    self.ep = current["high"] if self.direction == 1 else current["low"]
                    self.af, initial = 2, True
            else:
                reversed_now = current["low"] < active if self.direction == 1 else current["high"] > active
                if reversed_now:
                    self.direction *= -1
                    self.display = min(before_ep, current["low"]) if self.direction == 1 else max(before_ep, current["high"])
                    self.ep = current["high"] if self.direction == 1 else current["low"]
                    self.af = 2
                else:
                    limits = [Fraction(f["low"] if self.direction == 1 else f["high"]) for f in self.history]
                    self.display = min(active, *limits) if self.direction == 1 else max(active, *limits)
                    extreme = current["high"] if self.direction == 1 else current["low"]
                    if self.direction * (extreme - self.ep) > 0:
                        self.ep = extreme
                        self.af = min(20, self.af + 2)
            if self.direction:
                self.next_line = self.display + Fraction(self.af, 100) * (self.ep - self.display)
            self.history.append({"場": session, **source_snapshot(frame)})
        ready = bool(numeric and self.direction in (-1, 1) and all(v is not None for v in (self.display, self.next_line, self.ep)))
        return {"場": session, **source_snapshot(frame),
            "SAR準備済": ready, "SAR公開可": bool(ready and frame["publish"]),
            "SAR方向": self.direction if ready else 0, "SAR事前方向": before_direction,
            "SAR事前線": float(active) if active is not None else None,
            "SAR表示線": float(self.display) if ready else None,
            "SAR次足線": float(self.next_line) if ready else None,
            "SAR_EP": float(self.ep) if ready else None, "SAR_AF": self.af / 100 if ready else None,
            "SAR事前EP": float(before_ep) if before_ep is not None else None,
            "SAR事前AF": before_af / 100 if before_direction else None,
            "SAR_AF整数": self.af if ready else None, "SAR事前AF整数": before_af if before_direction else None,
            "SAR精密事前線": pack(active), "SAR精密表示線": pack(self.display) if ready else None,
            "SAR精密次足線": pack(self.next_line) if ready else None, "SAR精密EP": pack(self.ep) if ready else None,
            "SAR精密事前EP": pack(before_ep), "SAR反転": reversed_now, "SAR初期化": initial,
            "SAR数値入力可": numeric, "SAR前二足": prior, "SAR解除理由": list(reasons or [])}

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """完全幅足の精密状態を更新し、欠枠/限月/尾部で数値を解除する。

        引数: frames(list[dict])は3分足、session(str)は場、contract(tuple)は限月、tail_missing(int)は尾部欠枠。
        返り値: tuple[list[dict],dict]は全精密行と数値品質。公開の局所参照は運用側が毎場初期化する。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        rows, previous_index, previous_key, clears = [], None, None, int(changed)
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != 3 or previous_index is not None and index <= previous_index:
                raise ValueError("SARの足幅/足番号が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key):
                raise ValueError("SAR公開前足又は公開key後退")
            reasons = ["限月変更"] if changed and previous_index is None else []
            if previous_index is None and index != 0 or previous_index is not None and index != previous_index + 1:
                reasons.append("3分番号欠枠")
            if frame["missing"]:
                reasons.append("3分欠枠")
            if not valid_ohlc(frame):
                reasons.append("3分OHLC不正")
            if any(r != "限月変更" for r in reasons):
                self.clear()
                clears += 1
            rows.append(self.update(frame, session, reasons))
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            clears += 1
        values = [unpack(r[name]) for r in rows for name in
            ("SAR精密事前線", "SAR精密表示線", "SAR精密次足線", "SAR精密EP", "SAR精密事前EP") if r[name] is not None]
        return rows, {"場": session, "SAR入力足数": len(rows), "SAR数値準備足数": sum(r["SAR準備済"] for r in rows),
            "SAR公開準備足数": sum(r["SAR公開可"] for r in rows), "SAR初期化数": sum(r["SAR初期化"] for r in rows),
            "SAR反転数": sum(r["SAR反転"] for r in rows), "SAR未公開数値更新数": sum(not r["publish"] and r["SAR数値入力可"] for r in rows),
            "SARclear数": clears, "SAR尾部完全欠枠": tail_missing, "SAR場末方向": self.direction,
            "SAR場末次線精密": pack(self.next_line), "SAR場末EP精密": pack(self.ep), "SAR場末AF整数": self.af if self.direction else None,
            "最大分子bit長": max((abs(v.numerator).bit_length() for v in values), default=0),
            "最大分母bit長": max((v.denominator.bit_length() for v in values), default=0),
            "最大分数保存文字数": max((len(hex(v.numerator)) + len(hex(v.denominator)) for v in values), default=0),
            "精密分数表現": "符号付き正規形16進文字列/正分母", "SAR全足内容SHA256": canonical_sha(rows)}
