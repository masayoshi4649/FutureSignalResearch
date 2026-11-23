"""保存29の価格とATRを共有し、方向優勢と場内Fastを新しく計算する。"""

from collections import Counter, deque
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("スイング突破の固定29価格", ROOT/"scripts/OBV反転/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SOURCE_FIELDS, VALID = BASE.SOURCE_FIELDS, BASE.VALID
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr")
DMI_FIELDS = ("plus_di", "minus_di", "DMI数値入力可", "DMI差分数", "DMI準備", "DMI解除理由")
FAST_FIELDS = ("FastK", "FastD", "Fast差", "Fast差厳密符号", "Fast準備",
               "Fast価格窓足番号", "FastK窓足番号", "Fast解除理由")
NUMERIC_FIELDS = (*FRAME_FIELDS, *DMI_FIELDS, *FAST_FIELDS)
RULES = {
    "DMI": "3分Wilder14。最初の有効足は前HLC種のみ、以後14差分の算術平均seed、15足目初DI。以後(13*前平均+当値)/14のfloat演算",
    "DM": "u=H-Hprev,d=Lprev-L。u>dかつu>0だけ+DM=u、d>uかつd>0だけ-DM=d。同値は両0",
    "TR": "max(H-L,abs(H-Cprev),abs(L-Cprev))。平滑TR0ならDIはNoneで平滑状態保持、TR正でDM両0ならDI0/0は準備済み",
    "数値継続": "DMIだけ同限月carry。欠枠/番号-end欠落/不正/限月/尾部でclearし、完全有効当足を新しい前HLC種にする。完全NPは内部更新",
    "Fast": "同場連続公開有効完全3分の当足含14HLCと連続rawK3。元HLC各floatをFraction化しrawK-SMA3rawKを厳密比較。最速16足",
    "Fast零幅": "14高安幅0はrawK未定義でK3だけclear、14価格窓は保持。個々のH=L足は有効。NP/missing/不正は両窓clearして不投入",
    "出典": "保存29のSOURCE12とATRをstrictコピー。MACD/ADX/RSI/数量/上位/TOPIXを新数値へ持ち込まない",
    "精度": "plus_di/minus_diの数値だけabs1e-10/rel0。DI優勢符号/準備/全採否は厳密、epsilonなし。正本4列定義と独立生値を二経路で検算",
}


def finite(value: object) -> bool:
    """欠測・真偽値・非有限を除く実数か調べる。

    引数: value(object)は観測値。
    返り値: boolは有限の整数又はfloatであること。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def exact(value: Fraction | None) -> dict:
    """精密値を表示と分子分母へ分離する。

    引数: value(Fraction|None)は精密値又は未準備。
    返り値: dictは値/分子/分母/有効。欠測を0へ補完しない。
    """
    return {"値": float(value) if value is not None else None,
            "分子": value.numerator if value is not None else None,
            "分母": value.denominator if value is not None else None, "有効": value is not None}


def canonical_sha(value: object) -> str:
    """全属性と順序を保持したJSON指紋を返す。

    引数: value(object)はJSON互換値。
    返り値: strはSHA256。非有限値は拒否する。
    """
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frame_projection(row: dict | None) -> dict | None:
    """固定29から価格出典と旧ATRだけを取り出す。

    引数: row(dict|None)は保存足又は参照なし。
    返り値: dict|Noneは場/SOURCE12/atrの14列。旧数値の再計算はしない。
    """
    return {key: deepcopy(row[key]) for key in FRAME_FIELDS} if row is not None else None


def numeric_projection(row: dict) -> dict:
    """新DMI/Fastと共有出典の正式列を深複写する。

    引数: row(dict)は計算済みの足。
    返り値: dictはNUMERIC_FIELDSだけを含む当時値。
    """
    return {key: deepcopy(row[key]) for key in NUMERIC_FIELDS}


def price_valid(row: dict) -> bool:
    """完全3分の有効OHLCを数値投入可能とする。

    引数: row(dict)は足出典。
    返り値: boolは公開の有無とは別の価格有効性。
    """
    return bool(row["minutes"] == 3 and row["end"]-row["start"] == 180 and VALID(row))


class DirectionalMovement:
    """当時の前HLCだけからWilder14を更新するfloatモデル。"""

    def __init__(self) -> None:
        """空の前足と平滑値を初期化する。

        引数: なし。
        返り値: None。内部TR/DM/RMAは人工検査に限り公開属性として保持する。
        """
        self.previous, self.count = None, 0
        self.seed, self.averages = [], None

    def update(self, row: dict) -> tuple[float | None, float | None]:
        """有効一足を投入し、方向の二つのDIだけを返す。

        引数: row(dict)は有限正の完全OHLC。
        返り値: tuple[float|None,float|None]は+DI/-DI。最初足とTR0はNone。
        """
        previous = self.previous
        self.previous = {key: row[key] for key in ("high", "low", "close")}
        if previous is None:
            return None, None
        up, down = row["high"]-previous["high"], previous["low"]-row["low"]
        plus = up if up > down and up > 0 else 0.0
        minus = down if down > up and down > 0 else 0.0
        tr = max(row["high"]-row["low"], abs(row["high"]-previous["close"]), abs(row["low"]-previous["close"]))
        values = (tr, plus, minus)
        self.count += 1
        if self.averages is None:
            self.seed.append(values)
            if len(self.seed) == 14:
                self.averages = tuple(sum(row[index] for row in self.seed)/14 for index in range(3))
                self.seed.clear()
        else:
            self.averages = tuple((13*old+value)/14 for old, value in zip(self.averages, values, strict=True))
        if self.averages is None or self.averages[0] <= 0:
            return None, None
        return 100*self.averages[1]/self.averages[0], 100*self.averages[2]/self.averages[0]


class NumericBank:
    """DMIの同限月銀行と、当場公開Fast窓を分離する。"""

    def __init__(self) -> None:
        """限月未指定の空DMI銀行を作る。

        引数: なし。
        返り値: None。Fast窓はbuildの各場で作り直す。
        """
        self.contract, self.dmi = None, DirectionalMovement()

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """保存3分足から新DMI/Fastを一回ずつ計算する。

        引数: frames(list[dict])は保存29足、session(str)は場、contract(tuple)は限月、
        tail_missing(int)は尾部の完全欠枠数。
        返り値: tuple[list[dict],dict]は限定数値全足と品質。先着/売買は計算しない。
        """
        changed = self.contract is not None and self.contract != tuple(contract)
        self.contract = tuple(contract)
        if changed:
            self.dmi = DirectionalMovement()
        prices, ks = deque(maxlen=14), deque(maxlen=3)
        rows, previous, published_key = [], None, None
        counts = Counter({"DMIclear数": int(changed), "Fastclear数": 0})
        for source in frames:
            row = frame_projection(source)
            if row["場"] != session or row["minutes"] != 3:
                raise ValueError("当場の固定3分足だけです")
            key = row["confirm"], row["confirm_line"]
            if previous is not None and row["index"] <= previous["index"]:
                raise ValueError("足番号重複又は後退")
            if row["publish"] and (row["confirm"] < row["end"] or published_key is not None and key <= published_key):
                raise ValueError("公開key重複/後退又は終了前公開")
            reasons = ["限月変更"] if changed and previous is None else []
            if previous is None and row["index"] != 0 or previous is not None and (
                    row["index"] != previous["index"]+1 or row["start"] != previous["end"]):
                reasons.append("番号又は終了非連続")
            if row["missing"]:
                reasons.append("欠枠")
            numeric = price_valid(row)
            if not numeric:
                reasons.append("完全3分価格不正")
            if any(reason != "限月変更" for reason in reasons):
                self.dmi = DirectionalMovement(); counts["DMIclear数"] += 1
            plus, minus = self.dmi.update(row) if numeric else (None, None)

            # ----------------------------------------
            # 公開Fast窓はDMI内部更新と分け、場内の連続した公開値だけを使う。
            fast_reasons = [reason for reason in reasons if reason != "限月変更"]
            if not row["publish"]:
                fast_reasons.append("非公開")
            eligible = bool(numeric and row["publish"] and not row["missing"])
            if fast_reasons:
                prices.clear(); ks.clear(); counts["Fastclear数"] += 1
            raw = smooth = difference = None
            if eligible:
                prices.append(row)
                if len(prices) == 14:
                    high, low = max(r["high"] for r in prices), min(r["low"] for r in prices)
                    if high > low:
                        raw = 100*(Fraction(row["close"])-Fraction(low))/(Fraction(high)-Fraction(low))
                if raw is None:
                    ks.clear()
                else:
                    ks.append((row["index"], raw))
                    if len(ks) == 3:
                        smooth = sum(value for _, value in ks)/3
                        difference = raw-smooth
            result = {**row, "plus_di": plus, "minus_di": minus, "DMI数値入力可": numeric,
                "DMI差分数": self.dmi.count, "DMI準備": finite(plus) and finite(minus), "DMI解除理由": reasons,
                "FastK": exact(raw), "FastD": exact(smooth), "Fast差": exact(difference),
                "Fast差厳密符号": (difference > 0)-(difference < 0) if difference is not None else None,
                "Fast準備": difference is not None, "Fast価格窓足番号": [r["index"] for r in prices],
                "FastK窓足番号": [index for index, _ in ks], "Fast解除理由": fast_reasons}
            rows.append(result)
            previous = row
            if row["publish"]:
                published_key = key
        if tail_missing:
            self.dmi = DirectionalMovement(); counts["DMIclear数"] += 1
        return rows, {"場": session, "時間足分": 3, "入力足数": len(rows), **dict(counts),
            "DMI準備足数": sum(r["DMI準備"] for r in rows), "Fast準備足数": sum(r["Fast準備"] for r in rows),
            "非公開DMI更新数": sum(not r["publish"] and r["DMI数値入力可"] for r in rows),
            "尾部完全欠枠": tail_missing}
