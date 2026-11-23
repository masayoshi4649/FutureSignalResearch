"""固定47の精密Forceと、新15分の中心化H・EMA13を分けて構築する。"""

from collections import Counter
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("Force失敗確認の固定47数値", ROOT/"scripts/Force波/指標.py")
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
BASE = PREVIOUS.BASE
SOURCE_FIELDS, VALID = PREVIOUS.SOURCE_FIELDS, PREVIOUS.VALID
FRAME_FIELDS, FORCE_FIELDS, NUMERIC_FIELDS = PREVIOUS.FRAME_FIELDS, PREVIOUS.FORCE_FIELDS, PREVIOUS.NUMERIC_FIELDS
UPPER_FIELDS = ("場", *SOURCE_FIELDS, "macd_hist", "ema13_centered")
finite, exact, fraction_value = PREVIOUS.finite, PREVIOUS.exact, PREVIOUS.fraction_value
canonical_sha = PREVIOUS.canonical_sha
frame_projection, numeric_projection = PREVIOUS.frame_projection, PREVIOUS.numeric_projection
price_valid, build = PREVIOUS.price_valid, PREVIOUS.build
RULES = {
    **deepcopy(PREVIOUS.RULES),
    "上位数値": "旧28の15分OHLCだけから固定29NumericBank.updateの中心化MACD12/26/9と同じ原点のEMA13を新計算。同限月carry、限月/番号-endgap/missing/不正でH/EMAともclear。完全有効missing当足はclear後投入、完全NPも内部更新、部分900秒未満はclearし不投入、尾部欠枠でclear",
    "上位EMA": "ema13_centered=legacyAverage(13,2/14)へC-originをHと同順で投入。最初13値算術平均種、更新演算順もlegacyAverageそのまま。originはHと共通、絶対価格へ復元せず現前差Eに使用。b/T/監視取消へEMA準備を追加しない",
    "数値検算": "共有3分ATR/Q/Forceは固定47とstrict同式。新15分H/EMA正本定義の全内容SHAと独立生値のabs1e-10/rel0比較を分離。有限準備/差E/D/ImpulseI/全採否strict、H水準符号は未使用、epsilonなし",
}


def upper_projection(row: dict | None) -> dict | None:
    """新15分のH/中心化EMAと公開価格出典を写す。

    引数: row(dict|None)は数値足又は公開参照なし。
    返り値: dict|NoneはUPPER_FIELDSの15列。絶対価格EMAへ復元しない。
    """
    return None if row is None else {name: deepcopy(row[name]) for name in UPPER_FIELDS}


# ----------------------------------------
# HとEMAは同じ原点・投入・解除・carryを使い、公開選択は入口へ分離する。

class UpperBank:
    """15分中心化MACDとEMA13を同限月内でcarryする。"""

    def __init__(self) -> None:
        """固定式の新銀行と空のEMA13を用意する。

        引数: なし。
        返り値: None。固定47の銀行やglobalsは変更しない。
        """
        self.bank = BASE.NumericBank()
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """H/原点/EMA13を同時に初期化する。

        引数: なし。
        返り値: None。限月識別は維持する。
        """
        self.bank.clear()
        self.ema = BASE.W.OLD.shared.legacy.Average(13, 2/14)

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """旧15分OHLCを中心化H/EMAへ同じ順で投入する。

        引数: frames(list[dict])は旧28価格、session(str)は場、contract(tuple)は限月、
        tail_missing(int)は完全尾部欠枠数。
        返り値: tuple[list[dict],dict]は全15列数値と品質。市場資料は読まない。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        rows, previous, public_key = [], None, None
        clears, inputs, np_updates = int(changed), 0, 0
        reason_counts = Counter()
        for frame in frames:
            if frame["minutes"] != 15 or previous is not None and frame["index"] <= previous["index"]:
                raise ValueError("15分の足番号はstrict昇順だけです")
            key = frame["confirm"], frame["confirm_line"]
            if frame["publish"] and (frame["confirm"] < frame["end"] or public_key is not None and key < public_key):
                raise ValueError("上位公開key後退又は終了前公開")
            reasons = []
            if previous is None and frame["index"] != 0 or previous is not None and (
                    frame["index"] != previous["index"]+1 or frame["start"] != previous["end"]):
                reasons.append("番号又は終了非連続")
            if frame["missing"]:
                reasons.append("欠枠")
            numeric = price_valid(frame, 15)
            if not numeric:
                reasons.append("完全15分価格不正")
            if reasons:
                self.clear()
                clears += 1
                reason_counts.update(reasons)
            if numeric:
                row = self.bank.update(frame, session)
                row["ema13_centered"] = self.ema.update(frame["close"]-self.bank.origin)
                inputs += 1
                np_updates += not frame["publish"]
            else:
                row = {"場": session, **{name: deepcopy(frame[name]) for name in SOURCE_FIELDS},
                    "macd_hist": None, "ema13_centered": None}
            rows.append(upper_projection(row))
            previous = frame
            if frame["publish"]:
                public_key = key
        origin = self.bank.origin
        if tail_missing:
            self.clear()
            clears += 1
        return rows, {"場": session, "時間足分": 15, "入力足数": len(rows), "価格数値入力足数": inputs,
            "MACD準備足数": sum(finite(row["macd_hist"]) for row in rows),
            "EMA13準備足数": sum(finite(row["ema13_centered"]) for row in rows), "数値clear数": clears,
            "尾部完全欠枠": tail_missing, "非公開価格数値更新数": np_updates,
            "数値解除理由別": dict(reason_counts), "場末MACD原点": origin}
