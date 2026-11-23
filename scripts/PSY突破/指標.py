"""固定ATRの数値carryと、場内PSY12現前の公開窓を分けて保持する。"""

from collections import deque
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("PSY突破の固定29数値", ROOT/"scripts/OBV反転/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
W, SOURCE_FIELDS, VALID, SOURCE, finite = BASE.W, BASE.SOURCE_FIELDS, BASE.VALID, BASE.SOURCE, BASE.finite


def psychological(rows: list[dict]) -> dict | None:
    """13終値から12変化の上昇・下落・同値を整数で数える。

    引数: rows(list[dict])は順序付きの13足。
    返り値: dict|Noneは計数・方向差・表示率・足番号。13本以外は未準備。
    """
    if len(rows) != 13:
        return None
    differences = [b["close"]-a["close"] for a, b in zip(rows, rows[1:])]
    up, down, flat = sum(v > 0 for v in differences), sum(v < 0 for v in differences), sum(v == 0 for v in differences)
    return {"上昇数": up, "下落数": down, "同値数": flat, "方向差整数": up-down,
        "上昇率": 100*up/12, "下落率": 100*down/12, "足番号": [r["index"] for r in rows]}


class NumericBank:
    """ATRだけを同限月carryし、PSYは同場の公開14終値へ限定する。"""

    def __init__(self) -> None:
        """空の3分ATR銀行を用意する。

        引数: なし。
        返り値: None。PSYの局所履歴はbuildごとに初期化する。
        """
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """固定Wの数値銀行を解除する。

        引数: なし。
        返り値: None。出力・採否に使う既存系列はATRだけ。
        """
        self.absolute = W.Indicators()

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """ATRの数値更新と、missingを含めない公開PSY窓を生成する。

        引数: frames(list[dict])は3分OHLC、session(str)は場、contract(tuple)は限月、tail_missing(int)は尾部欠枠。
        返り値: tuple[list[dict],dict]は全数値足と品質。NPはATRだけ更新する。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        local, rows = deque(maxlen=14), []
        previous_index, previous_key, clears, psy_clears = None, None, int(changed), 0
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
            valid = VALID(frame)
            if not valid:
                reasons.append("OHLC不正")
            if any(r != "限月変更" for r in reasons):
                self.clear()
                clears += 1
            atr = self.absolute.update(frame)["atr"] if valid else None
            local_reasons = list(reasons)
            if not frame["publish"]:
                local_reasons.append("非公開足")
            if local_reasons:
                local.clear()
                psy_clears += 1
            current, previous = None, None
            if valid and frame["publish"] and not frame["missing"]:
                local.append({"index": index, "close": frame["close"]})
                current = psychological(list(local)[-13:])
                previous = psychological(list(local)[:-1]) if len(local) == 14 else None
            rows.append({"場": session, **SOURCE(frame), "atr": atr, "価格数値入力可": valid,
                "PSY現": current, "PSY前": previous, "PSY準備済": current is not None and previous is not None,
                "銀行解除理由": reasons, "PSY解除理由": local_reasons})
            previous_index = index
            if frame["publish"]:
                previous_key = key
        if tail_missing:
            self.clear()
            clears += 1
        return rows, {"場": session, "時間足分": 3, "入力足数": len(rows),
            "価格数値入力足数": sum(r["価格数値入力可"] for r in rows), "ATR正準備足数": sum(finite(r["atr"]) and r["atr"] > 0 for r in rows),
            "PSY現在準備足数": sum(r["PSY現"] is not None for r in rows), "PSY現前準備足数": sum(r["PSY準備済"] for r in rows),
            "数値clear数": clears, "PSYclear数": psy_clears, "尾部完全欠枠": tail_missing,
            "非公開価格数値更新数": sum(not r["publish"] and r["価格数値入力可"] for r in rows)}
