"""共有3分価格/数量の精密Force2と、新15分中心化MACDを分離する。"""

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("Force波の固定29中心化数値", ROOT/"scripts/OBV反転/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SOURCE_FIELDS, VALID = BASE.SOURCE_FIELDS, BASE.VALID
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr", "数量参照")
FORCE_FIELDS = ("数量入力可", "Force価格基準足番号", "Force価格基準終値", "Force入力可", "Force素",
    "Force2", "Force前", "Force符号", "Force前符号", "Force連続X数", "Force解除理由")
NUMERIC_FIELDS = (*FRAME_FIELDS, *FORCE_FIELDS)
UPPER_FIELDS = ("場", *SOURCE_FIELDS, "macd_hist")
RULES = {
    "共有3分": "固定29の場/SOURCE12/ATR/数量参照15列をstrictコピー。数量は固定14の数量基準完全かつ有限非負観測差分量だけを使い、RVOL/CMF総量/3分MACDはgateにしない",
    "Force": "X=(Fraction(C現)-Fraction(C前))*Fraction(q現)。最初の連続X二つの算術平均をForce2種とし、以後(2X+前Force2)/3。0量/0値有効、符号は精密分子で比較",
    "Force局所": "同場公開有効完全180秒/missing0/index-end隣接。NP/missing/不正で価格基準とForceを解除し当足不投入。gap後missing0正常足は新価格種。q不完全はForceだけ解除し正常Cを次足基準に保持。基準前足q不要",
    "上位数値": "旧28の15分OHLCだけを共有し、固定29NumericBank.updateの中心化MACD12/26/9のfloat順で新Hを計算。同限月場間carry、限月/番号-endgap/missing/不正でclear。完全有効missing当足はclear後投入、完全NPも内部更新、部分900秒未満はclearし不投入、尾部欠枠でclear",
    "公開順": "下位公開keyはstrict増加・重複index拒否。上位公開keyは非後退で同key可、終了前公開拒否。内部数値更新と当場公開参照を分離する",
    "数値検算": "共有3分ATR/Qと新Force精密の正本整合はstrict。新15分H正本定義と独立生Hのabs1e-10/rel0比較、全H差方向/準備/採否strictを分け、epsilonを採否へ足さない",
}


def finite(value: object) -> bool:
    """真偽値・欠測・非有限を除く実数を検査する。

    引数: value(object)は観測値。
    返り値: boolは有限な整数又はfloatであること。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def exact(value: Fraction | None) -> dict:
    """精密分数と参考表示を分ける。

    引数: value(Fraction|None)は精密値又は未準備。
    返り値: dictは値/分子/分母/有効で、未準備を0へ補完しない。
    """
    return {"値": float(value) if value is not None else None,
        "分子": value.numerator if value is not None else None,
        "分母": value.denominator if value is not None else None, "有効": value is not None}


def fraction_value(value: dict) -> Fraction | None:
    """表示floatを使わず保存分数を復元する。

    引数: value(dict)はexact形式。
    返り値: Fraction|Noneは有効な精密値。
    """
    return Fraction(value["分子"], value["分母"]) if value["有効"] else None


def canonical_sha(value: object) -> str:
    """全末端と順序を厳密JSONの指紋へ写す。

    引数: value(object)はJSON互換値。
    返り値: strはSHA256。非有限値は拒否する。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def frame_projection(row: dict | None) -> dict | None:
    """共有3分から当試行の15列だけを写す。

    引数: row(dict|None)は共有足又は参照なし。
    返り値: dict|Noneは価格/ATR/Qで、旧H/OBV/BB/labelを含めない。
    """
    return None if row is None else {name: deepcopy(row[name]) for name in FRAME_FIELDS}


def numeric_projection(row: dict) -> dict:
    """共有15列と新Force11列を写す。

    引数: row(dict)は新数値足。
    返り値: dictはNUMERIC_FIELDSの26列。
    """
    return {name: deepcopy(row[name]) for name in NUMERIC_FIELDS}


def upper_projection(row: dict | None) -> dict | None:
    """新15分Hと価格出典だけを写す。

    引数: row(dict|None)は上位足又は未公開参照なし。
    返り値: dict|Noneは14列。3分H/数量/ATRを含めない。
    """
    return None if row is None else {name: deepcopy(row[name]) for name in UPPER_FIELDS}


def price_valid(row: dict, minutes: int = 3) -> bool:
    """完全幅と有限OHLCを公開可否から分けて調べる。

    引数: row(dict)は価格足、minutes(int)は3又は15。
    返り値: boolは完全幅かつOHLC有効であること。
    """
    return bool(row["minutes"] == minutes and row["end"]-row["start"] == minutes*60 and VALID(row))


# ----------------------------------------
# Forceは毎場reset。数量不完全と価格基準終値の継続を別々に処理する。

def build(frames: list[dict], session: str) -> tuple[list[dict], dict]:
    """当場の価格差と当足観測量からForce2を精密計算する。

    引数: frames(list[dict])は固定29の3分共有材料、session(str)は場。
    返り値: tuple[list[dict],dict]は26列全足と品質。市場入力や旧ATRの再更新はしない。
    """
    rows, previous, price_base, public_key = [], None, None, None
    seed, force, count = [], None, 0
    clears = 0
    for source in frames:
        row = frame_projection(source)
        if row["場"] != session or row["minutes"] != 3:
            raise ValueError("当場3分の共有材料だけです")
        key = row["confirm"], row["confirm_line"]
        if previous is not None and row["index"] <= previous["index"]:
            raise ValueError("3分足番号重複又は後退")
        if row["publish"] and (row["confirm"] < row["end"] or public_key is not None and key <= public_key):
            raise ValueError("下位公開key同値/後退又は終了前公開")
        reasons = []
        if previous is None and row["index"] != 0 or previous is not None and (
                row["index"] != previous["index"]+1 or row["start"] != previous["end"]):
            reasons.append("番号又は終了非連続")
        if row["missing"]: reasons.append("欠枠")
        if not row["publish"]: reasons.append("非公開")
        if not price_valid(row): reasons.append("完全3分価格不正")
        price_ok = bool(row["publish"] and not row["missing"] and price_valid(row))
        if reasons:
            price_base, seed, force, count = None, [], None, 0
        quantity = row["数量参照"]
        q = quantity.get("観測差分量") if isinstance(quantity, dict) else None
        quantity_ok = bool(isinstance(quantity, dict) and quantity.get("数量基準完全") is True and finite(q) and q >= 0)
        if not quantity_ok:
            reasons.append("数量基準完全非負未準備")
            seed, force, count = [], None, 0
        prior_force = force
        base_index = price_base["index"] if price_base is not None else None
        base_close = price_base["close"] if price_base is not None else None
        eligible = bool(price_ok and price_base is not None and quantity_ok)
        value = (Fraction(row["close"])-Fraction(base_close))*Fraction(q) if eligible else None
        if value is not None:
            count += 1
            if force is None:
                seed.append(value)
                if len(seed) == 2: force = sum(seed, Fraction(0))/2
            else:
                force = (2*value+force)/3
        rows.append({**row, "数量入力可": quantity_ok, "Force価格基準足番号": base_index,
            "Force価格基準終値": base_close, "Force入力可": eligible, "Force素": exact(value),
            "Force2": exact(force), "Force前": exact(prior_force),
            "Force符号": (force > 0)-(force < 0) if force is not None else None,
            "Force前符号": (prior_force > 0)-(prior_force < 0) if prior_force is not None else None,
            "Force連続X数": count, "Force解除理由": reasons})
        clears += bool(reasons)
        price_base = row if price_ok else None
        previous = row
        if row["publish"]: public_key = key
    quality = {"場": session, "時間足分": 3, "入力足数": len(rows), "Force解除足数": clears,
        "Force入力足数": sum(row["Force入力可"] for row in rows),
        "Force準備足数": sum(row["Force2"]["有効"] for row in rows),
        "完全0量足数": sum(row["数量入力可"] and row["数量参照"]["観測差分量"] == 0 for row in rows)}
    return rows, quality


# ----------------------------------------
# 新15分Hのモデル値は固定29update順。公開参照は入口側で毎場限定する。

class UpperBank:
    """15分だけの中心化MACDを同限月でcarryする。"""

    def __init__(self) -> None:
        """固定29式の新しい数値状態を用意する。

        引数: なし。
        返り値: None。3分銀行とは共有しない。
        """
        self.bank = BASE.NumericBank()
        self.contract = None

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """15分OHLCを固定29の中心化更新式へ順に投入する。

        引数: frames(list[dict])は旧28のOHLC、session(str)は場、contract(tuple)は限月、
        tail_missing(int)は完全尾部欠枠数。
        返り値: tuple[list[dict],dict]は14列全足と品質。旧保存15分Hとの同値は主張しない。
        """
        changed = self.contract is not None and self.contract != contract
        if changed: self.bank.clear()
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
            if frame["missing"]: reasons.append("欠枠")
            numeric = price_valid(frame, 15)
            if not numeric: reasons.append("完全15分価格不正")
            if reasons:
                self.bank.clear(); clears += 1; reason_counts.update(reasons)
            if numeric:
                row = self.bank.update(frame, session); inputs += 1; np_updates += not frame["publish"]
            else:
                row = {"場": session, **{name: deepcopy(frame[name]) for name in SOURCE_FIELDS}, "macd_hist": None}
            rows.append(upper_projection(row))
            previous = frame
            if frame["publish"]: public_key = key
        origin = self.bank.origin
        if tail_missing:
            self.bank.clear(); clears += 1
        return rows, {"場": session, "時間足分": 15, "入力足数": len(rows), "価格数値入力足数": inputs,
            "MACD準備足数": sum(finite(row["macd_hist"]) for row in rows), "数値clear数": clears,
            "尾部完全欠枠": tail_missing, "非公開価格数値更新数": np_updates,
            "数値解除理由別": dict(reason_counts), "場末MACD原点": origin}
