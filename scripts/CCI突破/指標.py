"""局所CCI20と、同限月carryするATR・15分BBを分けて保持する。"""

from collections import deque
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("CCI突破の固定30数値", ROOT/"scripts/PSY突破/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
W, SOURCE_FIELDS, VALID, SOURCE, finite = BASE.W, BASE.SOURCE_FIELDS, BASE.VALID, BASE.SOURCE, BASE.finite


def cci20(frames: list[dict]) -> dict | None:
    """元OHLCから20TP・同窓平均偏差・CCIを正確な分数で計算する。

    引数: frames(list[dict])は20本の有効公開足。
    返り値: dict|NoneはCCI分数/表示/出典。MD0は有効false、20本不足はNone。
    """
    if len(frames) != 20:
        return None
    typical = [sum(Fraction(f[k]) for k in ("high", "low", "close"))/3 for f in frames]
    mean = sum(typical)/20
    deviation = sum(abs(v-mean) for v in typical)/20
    value = (typical[-1]-mean)/(Fraction(3, 200)*deviation) if deviation > 0 else None
    return {"値": float(value) if value is not None else None,
        "分子": value.numerator if value is not None else None, "分母": value.denominator if value is not None else None,
        "平均分子": mean.numerator, "平均分母": mean.denominator,
        "MD分子": deviation.numerator, "MD分母": deviation.denominator,
        "現TP分子": typical[-1].numerator, "現TP分母": typical[-1].denominator,
        "足番号": [f["index"] for f in frames], "有効": value is not None}


class NumericBank:
    """ATR/上位BBの数値carryと、3分CCIの同場公開窓を分離する。"""

    def __init__(self, minutes: int) -> None:
        """固定3分又は15分の空銀行を作る。

        引数: minutes(int)は3又は15。
        返り値: None。局所CCIはbuildごとに初期化する。
        """
        if minutes not in (3, 15):
            raise ValueError("3分又は15分だけ")
        self.minutes, self.contract = minutes, None
        self.clear()

    def clear(self) -> None:
        """ATRと上位BBの数値状態を解除する。

        引数: なし。
        返り値: None。尺度と限月は保持する。
        """
        self.absolute = W.Indicators() if self.minutes == 3 else None
        self.closes = deque(maxlen=20)

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """完全幅足を数値更新し、CCIへは同場公開有効足だけを積む。

        引数: frames(list[dict])は尺度別OHLC、session(str)は場、contract(tuple)は限月、tail_missing(int)は尾部欠枠。
        返り値: tuple[list[dict],dict]は数値/出典と場別品質。NPはATR/BBの数値更新だけ。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        local, rows = deque(maxlen=21), []
        previous_index, previous_key, clears, local_clears = None, None, int(changed), 0
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
            valid = VALID(frame)
            if not valid:
                reasons.append("OHLC不正")
            if any(r != "限月変更" for r in reasons):
                self.clear()
                clears += 1
            row = {"場": session, **SOURCE(frame), "atr": None, "価格数値入力可": valid, "銀行解除理由": reasons}
            if self.minutes == 3:
                row["atr"] = self.absolute.update(frame)["atr"] if valid else None
                local_reasons = [*reasons, *(["非公開足"] if not frame["publish"] else [])]
                if local_reasons:
                    local.clear()
                    local_clears += 1
                current, previous = None, None
                if valid and frame["publish"] and not frame["missing"]:
                    local.append(frame)
                    current = cci20(list(local)[-20:])
                    previous = cci20(list(local)[:-1]) if len(local) == 21 else None
                row.update(CCI現=current, CCI前=previous,
                    CCI準備済=bool(current and previous and current["有効"] and previous["有効"]), CCI解除理由=local_reasons)
            else:
                if valid:
                    self.closes.append({"場": session, **SOURCE(frame)})
                ready = bool(valid and len(self.closes) == 20)
                mean, sd, variance = None, None, None
                if ready:
                    values = [f["close"] for f in self.closes]
                    mean, sd = float(W.np.mean(values)), float(W.np.std(values, ddof=0))
                    exact = [Fraction(v) for v in values]
                    variance = sum(v*v for v in exact)/20-(sum(exact)/20)**2
                    ready = finite(mean) and finite(sd) and finite(4*sd)
                    if not ready:
                        mean = mean if finite(mean) else None
                        sd = sd if finite(sd) else None
                row.update(BB平均=mean, BB標準偏差=sd, BB幅=4*sd if ready else None,
                    BB分散分子=variance.numerator if ready else None, BB分散分母=variance.denominator if ready else None,
                    BB窓出典=deepcopy(list(self.closes)), BB準備済=ready)
            rows.append(row)
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            clears += 1
        return rows, {"場": session, "時間足分": self.minutes, "入力足数": len(rows),
            "価格数値入力足数": sum(r["価格数値入力可"] for r in rows), "数値clear数": clears,
            "ATR正準備足数": sum(finite(r["atr"]) and r["atr"] > 0 for r in rows),
            "CCI現前準備足数": sum(r.get("CCI準備済", False) for r in rows), "CCI局所clear数": local_clears,
            "BB数値準備足数": sum(r.get("BB準備済", False) for r in rows), "尾部完全欠枠": tail_missing,
            "非公開数値更新数": sum(not r["publish"] and r["価格数値入力可"] for r in rows)}
