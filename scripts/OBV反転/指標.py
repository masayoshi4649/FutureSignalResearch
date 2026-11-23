"""中心化MACD・固定ATRと、場内の観測数量OBVを別に更新する。"""

from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("OBV反転の固定26数値", ROOT/"scripts/反転確認時計/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
W, SOURCE_FIELDS = BASE.W, BASE.SOURCE_FIELDS
VALID, SOURCE = BASE.BASE.valid_ohlc, BASE.BASE.source_snapshot


def finite(value: object) -> bool:
    """欠測・真偽値・非有限を除いた数値かを調べる。

    引数: value(object)は観測値。
    返り値: boolは有限な実数。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class NumericBank:
    """価格数値は同限月carryし、OBVは同場の完全数量区間へ限定する。"""

    def __init__(self) -> None:
        """空の3分数値銀行を用意する。

        引数: なし。
        返り値: None。OBVはbuildごとに初期化する。
        """
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """絶対価格ATRと中心化MACDを初期化する。

        引数: なし。
        返り値: None。限月識別は維持する。
        """
        self.absolute = W.Indicators()
        average = W.OLD.shared.legacy.Average
        self.fast, self.slow, self.signal = average(12, 2/13), average(26, 2/27), average(9, 2/10)
        self.origin, self.origin_source = None, None

    def update(self, frame: dict, session: str) -> dict:
        """当時の初有効終値を原点にMACDを更新する。

        引数: frame(dict)は完全幅足、session(str)は場。
        返り値: dictは価格出典・ATR・中心化MACD。OHLC不正は投入しない。
        """
        numeric = VALID(frame)
        values = {"atr": None, "macd": None, "macd_signal": None, "macd_hist": None}
        if numeric:
            values["atr"] = self.absolute.update(frame)["atr"]
            if self.origin is None:
                self.origin = frame["close"]
                self.origin_source = {"場": session, **SOURCE(frame)}
            shifted = frame["close"]-self.origin
            fast, slow = self.fast.update(shifted), self.slow.update(shifted)
            macd = fast-slow if fast is not None and slow is not None else None
            signal = self.signal.update(macd) if macd is not None else None
            values.update(macd=macd, macd_signal=signal,
                macd_hist=macd-signal if macd is not None and signal is not None else None)
        return {"場": session, **SOURCE(frame), **values, "価格数値入力可": numeric,
            "MACD原点": self.origin, "MACD原点出典": deepcopy(self.origin_source)}

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0, quantities: dict | None = None) -> tuple[list[dict], dict]:
        """価格と数量の解除条件を分け、OBV区間の種と増分を保存する。

        引数: frames(list[dict])は3分OHLC、session(str)は場、contract(tuple)は限月、
        tail_missing(int)は尾部欠枠、quantities(dict|None)は固定14の番号別数量属性。
        返り値: tuple[list[dict],dict]は全入力足と品質。完全0量は有効で、RVOL準備を要求しない。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        rows, previous_index, previous_key = [], None, None
        segment, segment_count, obv, prior = None, 0, None, None
        numeric_clears, obv_clears, segments = int(changed), 0, 0
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != 3 or previous_index is not None and index <= previous_index:
                raise ValueError("3分足の番号順が不正")
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
                numeric_clears += 1
            row = self.update(frame, session)
            quantity = deepcopy((quantities or {}).get(index))
            q = quantity.get("観測差分量") if quantity is not None else None
            quantity_ok = bool(quantity is not None and quantity.get("数量基準完全") and finite(q) and q >= 0)
            obv_reasons = list(reasons)
            if not frame["publish"]:
                obv_reasons.append("非公開足")
            if not quantity_ok:
                obv_reasons.append("数量基準不完全又は不正")
            if obv_reasons:
                segment, segment_count, obv, prior = None, 0, None, None
                obv_clears += 1
            seed, delta = False, None
            if row["価格数値入力可"] and frame["publish"] and not frame["missing"] and quantity_ok:
                if prior is None:
                    segments += 1
                    segment, segment_count, obv = f"{session}_量区間{segments:04d}", 1, 0.0
                    seed, delta = True, 0.0
                else:
                    change = frame["close"]-prior["close"]
                    delta = ((change > 0)-(change < 0))*q
                    obv += delta
                    segment_count += 1
                prior = frame
            row.update(数量参照=quantity, 数量入力可=quantity_ok, OBV=obv, OBV増分=delta, OBV種=seed,
                OBV区間ID=segment, OBV区間足数=segment_count, OBV公開可=bool(segment is not None),
                銀行解除理由=reasons, OBV解除理由=obv_reasons)
            rows.append(row)
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            numeric_clears += 1
        return rows, {"場": session, "時間足分": 3, "入力足数": len(rows),
            "価格数値入力足数": sum(r["価格数値入力可"] for r in rows),
            "MACD準備足数": sum(finite(r["macd_hist"]) for r in rows),
            "数量入力可足数": sum(r["数量入力可"] for r in rows), "完全0量足数": sum(r["数量入力可"] and r["数量参照"]["観測差分量"] == 0 for r in rows),
            "OBV公開足数": sum(r["OBV公開可"] for r in rows), "OBV区間数": segments,
            "数値clear数": numeric_clears, "OBVclear数": obv_clears, "尾部完全欠枠": tail_missing,
            "非公開価格数値更新数": sum(not r["publish"] and r["価格数値入力可"] for r in rows),
            "場末MACD原点": self.origin}
