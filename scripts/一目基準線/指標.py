"""固定26の数値更新へ、一目均衡表の高安窓と公開出典を追加する。"""

from collections import deque
from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("一目基準線の固定26指標", ROOT/"scripts/反転確認時計/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
W, SOURCE_FIELDS = BASE.W, BASE.SOURCE_FIELDS
VALID = BASE.BASE.valid_ohlc
SOURCE = BASE.BASE.source_snapshot
ICHI_FIELDS = ("ichimoku_tenkan", "ichimoku_kijun", "ichimoku_a", "ichimoku_b",
               "cloud_a", "cloud_b", "cloud_upper", "cloud_lower")
LEGACY_FIELDS = ("atr", "stoch_raw", "stoch_k")
EXACT_FIELDS = ("Fast差厳密符号", "Fast差厳密分子", "Fast差厳密分母")


def finite(value: object) -> bool:
    """欠測と非有限値を除いた実数か検査する。

    引数: value(object)は任意の末端値。
    返り値: boolは有限な数値。真偽値は価格として扱わない。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class NumericBank:
    """完全幅OHLCを同限月で引き継ぎ、公開と数値更新を分ける。"""

    def __init__(self, minutes: int) -> None:
        """固定尺度の空銀行を作る。

        引数: minutes(int)は3又は15。
        返り値: None。場内の公開前足はこの銀行へ保持しない。
        """
        if minutes not in (3, 15):
            raise ValueError("3分又は15分だけ")
        self.minutes, self.contract = minutes, None
        self.clear()

    def clear(self) -> None:
        """高安窓と固定26の全数値系列を解除する。

        引数: なし。
        返り値: None。尺度と限月識別は保持する。
        """
        self.legacy = BASE.Indicators()
        self.history = deque(maxlen=78)
        self.fast_exact = deque(maxlen=3)

    def update(self, frame: dict, session: str, reasons: list[str] | None = None) -> dict:
        """有効OHLCを一回投入し、26本前計算の現在雲を返す。

        引数: frame(dict)は完全幅足、session(str)は場、reasons(list[str]|None)は解除理由。
        返り値: dictは既存系列・一目・出典。OHLC不正は解除済として投入しない。
        """
        numeric = VALID(frame)
        original = self.legacy.update(frame) if numeric else {k: None for k in LEGACY_FIELDS}
        empty = {k: original[k] for k in LEGACY_FIELDS}
        values = {k: None for k in ICHI_FIELDS}
        origin = None
        exact = {k: None for k in EXACT_FIELDS}
        if numeric:
            source = {"場": session, **SOURCE(frame)}
            history = [*self.history, {"出典": source}]
            raw_exact = None
            if len(history) >= 14:
                fourteen = history[-14:]
                high = max(r["出典"]["high"] for r in fourteen)
                low = min(r["出典"]["low"] for r in fourteen)
                if high > low:
                    raw_exact = 100*(Fraction(frame["close"])-Fraction(low))/(Fraction(high)-Fraction(low))
            if raw_exact is None:
                self.fast_exact.clear()
            else:
                self.fast_exact.append(raw_exact)
                if len(self.fast_exact) == 3:
                    delta = raw_exact-sum(self.fast_exact)/3
                    exact = {"Fast差厳密符号": (delta > 0)-(delta < 0),
                        "Fast差厳密分子": delta.numerator, "Fast差厳密分母": delta.denominator}
            for length, name in ((9, "ichimoku_tenkan"), (26, "ichimoku_kijun"), (52, "ichimoku_b")):
                if len(history) >= length:
                    prior = history[-length:]
                    values[name] = (max(r["出典"]["high"] for r in prior)+min(r["出典"]["low"] for r in prior))/2
            if values["ichimoku_tenkan"] is not None and values["ichimoku_kijun"] is not None:
                values["ichimoku_a"] = (values["ichimoku_tenkan"]+values["ichimoku_kijun"])/2
            if len(self.history) >= 26:
                past = self.history[-26]
                values["cloud_a"], values["cloud_b"] = past["A"], past["B"]
                origin = deepcopy(past["出典"])
                if finite(values["cloud_a"]) and finite(values["cloud_b"]):
                    values["cloud_upper"] = max(values["cloud_a"], values["cloud_b"])
                    values["cloud_lower"] = min(values["cloud_a"], values["cloud_b"])
            self.history.append({"出典": source, "A": values["ichimoku_a"], "B": values["ichimoku_b"]})
        ready = bool(numeric and all(finite(values[k]) for k in ("ichimoku_tenkan", "ichimoku_kijun", "cloud_upper", "cloud_lower")))
        return {"場": session, **SOURCE(frame), **empty, **exact, **values, "雲計算元足": origin,
            "一目数値入力可": numeric, "一目準備済": ready, "一目公開可": bool(ready and frame["publish"]),
            "一目窓本数": len(self.history), "銀行解除理由": list(reasons or [])}

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """一場の全完全幅足を更新し、欠枠後の有効当足から再蓄積する。

        引数: frames(list[dict])はOHLC、session(str)は場、contract(tuple)は限月、tail_missing(int)は尾部欠枠数。
        返り値: tuple[list[dict],dict]は全数値足と場別品質。末尾非公開足も数値だけ更新する。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        result, previous_index, previous_key = [], None, None
        clears = int(changed)
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != self.minutes or previous_index is not None and index <= previous_index:
                raise ValueError("足幅又は番号順が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or previous_key is not None and key < previous_key):
                raise ValueError("公開前足又は公開キー後退")
            reasons = ["限月変更"] if changed and previous_index is None else []
            if previous_index is None and index != 0 or previous_index is not None and index != previous_index+1:
                reasons.append("足番号欠枠")
            if frame["missing"]:
                reasons.append("欠枠")
            if not VALID(frame):
                reasons.append("OHLC不正")
            if any(r != "限月変更" for r in reasons):
                self.clear()
                clears += 1
            result.append(self.update(frame, session, reasons))
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            clears += 1
        return result, {"場": session, "時間足分": self.minutes, "入力足数": len(result),
            "数値入力足数": sum(r["一目数値入力可"] for r in result), "基準線準備足数": sum(finite(r["ichimoku_kijun"]) for r in result),
            "一目準備足数": sum(r["一目準備済"] for r in result), "一目公開準備足数": sum(r["一目公開可"] for r in result),
            "Fast準備足数": sum(finite(r["stoch_raw"]) and finite(r["stoch_k"]) for r in result),
            "非公開数値更新数": sum(not r["publish"] and r["一目数値入力可"] for r in result),
            "clear数": clears, "尾部完全欠枠": tail_missing, "場末窓本数": len(self.history)}
