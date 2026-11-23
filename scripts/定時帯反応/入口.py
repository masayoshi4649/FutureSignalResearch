"""定時判断へ、当場開始帯と価格反応・FastK・上位DMIを供給する。

原入力や正本ファイルを開かない純モジュール。公開SOURCEだけを受け取り、
注文、約定、先着ラベル、損益、保有判断を扱わない。
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from fractions import Fraction
import math


SOURCE_FIELDS = (
    "index", "minutes", "start", "end", "confirm", "confirm_line",
    "publish", "missing", "open", "high", "low", "close",
)
POLICIES = ("S0", "S1")
PERIOD = 14
BUFFER = 5


class InputError(ValueError):
    """入力形式・順序の矛盾を、売買の待機と区別する例外。"""


def finite(value: object) -> bool:
    """有限な実数かを調べる。

    引数: value(object)は任意の値。
    返り値: boolは真偽値を除く有限な数値ならTrue。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def exact(value: Fraction | None) -> dict:
    """精密値を表示値と既約分数へ分ける。

    引数: value(Fraction|None)は計算値又は欠測。
    返り値: dictは値、分子、分母、有効を持つJSON安全な表示。
    """
    return {"value": float(value) if value is not None else None,
            "numerator": value.numerator if value is not None else None,
            "denominator": value.denominator if value is not None else None,
            "valid": value is not None}


def fraction(value: dict) -> Fraction | None:
    """精密表示から値を復元する。

    引数: value(dict)はexactの返した辞書。
    返り値: Fraction|Noneは有効値又は欠測。
    """
    return Fraction(value["numerator"], value["denominator"]) if value["valid"] else None


def source(row: dict) -> dict:
    """数値列を含めず、足の当時出典を写す。

    引数: row(dict)はSOURCEを持つ足。
    返り値: dictは場とSOURCE12の深い写し。
    """
    return {name: deepcopy(row[name]) for name in ("session", *SOURCE_FIELDS)}


def valid_ohlc(row: dict) -> bool:
    """価格の有限正値とOHLCの包含を検査する。

    引数: row(dict)は元価格を持つ足。
    返り値: boolは補完せず数値へ投入できるか。
    """
    values = [row[name] for name in ("open", "high", "low", "close")]
    return all(finite(value) and value > 0 for value in values) and (
        row["low"] <= min(row["open"], row["close"])
        <= max(row["open"], row["close"]) <= row["high"])


def key(row: dict) -> tuple:
    """公開足の価格時計と原行を組にする。

    引数: row(dict)は公開時計を持つ足。
    返り値: tupleは公開順の比較用キー。
    """
    return row["confirm"], row["confirm_line"]


def eligible_price(row: dict) -> bool:
    """公開・完全幅・欠枠なしの有効価格足か調べる。

    引数: row(dict)はSOURCE足。
    返り値: boolは局所窓と数値銀行へ投入できるか。
    """
    return bool(row["publish"] and row["missing"] == 0 and valid_ohlc(row)
                and row["end"] - row["start"] == 60 * row["minutes"]
                and row["confirm"] >= row["end"])


def adjacent(previous: dict, current: dict) -> bool:
    """同じ場の番号・価格時刻・公開順の隣接を検査する。

    引数: previous(dict)は前足、current(dict)は現足。
    返り値: boolは完全に隣接するか。
    """
    return (previous["session"] == current["session"]
            and current["index"] == previous["index"] + 1
            and previous["end"] == current["start"]
            and key(previous) < key(current))


def distance(atr: float) -> float:
    """保存ATRを上方呼値へ丸め、5〜125ptへ制限する。

    引数: atr(float)は有限正のATR14。
    返り値: floatは5pt単位の固定距離。保存floatそのものを精密化する。
    """
    if not finite(atr) or atr <= 0:
        raise InputError("ATRは有限正値が必要")
    ratio = Fraction(atr) / 5
    ticks = -(-ratio.numerator // ratio.denominator)
    return float(min(125, max(5, 5 * ticks)))


class WilderMean:
    """最初の14算術平均後、(13前値+当値)/14を更新する。"""

    def __init__(self) -> None:
        """空の算術種と未準備値を作る。

        引数: なし。
        返り値: None。
        """
        self.seed = []
        self.value = None

    def update(self, value: float) -> float | None:
        """一つの有限値をWilder平均へ投入する。

        引数: value(float)はTR、DM又はDX。
        返り値: float|Noneは14入力目以後の値。
        """
        if self.value is None:
            self.seed.append(value)
            if len(self.seed) == PERIOD:
                self.value = sum(self.seed) / PERIOD
        else:
            self.value = (13 * self.value + value) / PERIOD
        return self.value


class NumericBank:
    """同限月の数値だけを場間carryし、無効足・欠枠で解除する。"""

    def __init__(self, minutes: int) -> None:
        """3分ATR/Fast又は15分DMIの銀行を作る。

        引数: minutes(int)は3又は15。
        返り値: None。
        """
        if minutes not in (3, 15):
            raise InputError("足幅は3分又は15分")
        self.minutes = minutes
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """価格種、精密Fast窓、Wilder種を解除する。

        引数: なし。
        返り値: None。限月識別と足幅は保持する。
        """
        self.previous = None
        self.price_window = deque(maxlen=14)
        self.previous_k = None
        self.atr_mean = WilderMean()
        self.tr_mean = WilderMean()
        self.plus_mean = WilderMean()
        self.minus_mean = WilderMean()
        self.adx_mean = WilderMean()
        self.count = 0
        self.difference_count = 0

    def update(self, row: dict) -> dict:
        """一つの有効足からATR/Fast又はDI/ADXを計算する。

        引数: row(dict)は検証済みの完全公開足。
        返り値: dictは新数値。入力SOURCEを改変しない。
        """
        self.count += 1
        result = {"atr": None, "fast_k": exact(None), "fast_previous": exact(None),
                  "fast_change": exact(None), "plus_di": None, "minus_di": None,
                  "adx": None, "numeric_count": self.count, "dmi_count": self.difference_count}
        previous = self.previous
        if self.minutes == 3:
            tr = row["high"] - row["low"] if previous is None else max(
                row["high"] - row["low"], abs(row["high"] - previous["close"]),
                abs(row["low"] - previous["close"]))
            result["atr"] = self.atr_mean.update(tr)
            self.price_window.append(row)
            current_k = None
            if len(self.price_window) == 14:
                high = max(Fraction(item["high"]) for item in self.price_window)
                low = min(Fraction(item["low"]) for item in self.price_window)
                if high > low:
                    current_k = 100 * (Fraction(row["close"]) - low) / (high - low)
            old_k = self.previous_k
            result.update(fast_k=exact(current_k), fast_previous=exact(old_k),
                          fast_change=exact(current_k - old_k if current_k is not None and old_k is not None else None))
            self.previous_k = current_k
        elif previous is not None:
            self.difference_count += 1
            up, down = row["high"] - previous["high"], previous["low"] - row["low"]
            tr = max(row["high"] - row["low"], abs(row["high"] - previous["close"]),
                     abs(row["low"] - previous["close"]))
            tr_mean = self.tr_mean.update(tr)
            plus = self.plus_mean.update(up if up > 0 and up > down else 0.0)
            minus = self.minus_mean.update(down if down > 0 and down > up else 0.0)
            if tr_mean is not None and tr_mean > 0:
                plus_di, minus_di = 100 * plus / tr_mean, 100 * minus / tr_mean
                total = plus_di + minus_di
                dx = 100 * abs(plus_di - minus_di) / total if total > 0 else 0.0
                result.update(plus_di=plus_di, minus_di=minus_di, adx=self.adx_mean.update(dx))
            result["dmi_count"] = self.difference_count
        self.previous = row
        return result

    def build(self, frames: list[dict], session: str, contract: tuple,
              begin: float, end: float) -> tuple[list[dict], dict]:
        """一場を順に処理し、場間の時間間隔自体では銀行を解除しない。

        引数: frames(list[dict])はSOURCE、session(str)は場、contract(tuple)は限月、
            begin(float)/end(float)は場の開始/終了時計秒。
        返り値: tuple[list[dict],dict]は全数値足と切断品質。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        rows, previous, previous_key = [], None, None
        clear_count = int(changed)
        for frame in frames:
            _validate_source(frame, self.minutes)
            row = {"session": session, **{name: deepcopy(frame[name]) for name in SOURCE_FIELDS}}
            if previous is not None and row["index"] <= previous["index"]:
                raise InputError("足番号の重複又は後退")
            if row["publish"]:
                if previous_key is not None and key(row) <= previous_key:
                    raise InputError("公開キーの同値又は後退")
                previous_key = key(row)
            reasons = ["限月変更"] if changed and previous is None else []
            if previous is None and row["index"] != 0 or previous is not None and (
                    row["index"] != previous["index"] + 1 or row["start"] != previous["end"]):
                reasons.append("足番号又は終了時刻の欠枠")
            if row["start"] != begin + 60 * self.minutes * row["index"]:
                reasons.append("場内時刻格子不整合")
            if not row["publish"]:
                reasons.append("非公開足")
            if row["missing"]:
                reasons.append("欠枠")
            if row["end"] - row["start"] != 60 * self.minutes:
                reasons.append("部分幅")
            if not valid_ohlc(row):
                reasons.append("OHLC不正")
            if row["publish"] and row["confirm"] < row["end"]:
                reasons.append("足終了前公開")
            if row["start"] < begin or row["end"] > end:
                reasons.append("場外足")
            if any(reason != "限月変更" for reason in reasons):
                self.clear()
                clear_count += 1
            valid = eligible_price(row) and not any(
                reason in reasons for reason in ("場内時刻格子不整合", "場外足"))
            numeric = self.update(row) if valid else {
                "atr": None, "fast_k": exact(None), "fast_previous": exact(None),
                "fast_change": exact(None), "plus_di": None, "minus_di": None,
                "adx": None, "numeric_count": 0, "dmi_count": 0}
            row.update(numeric, valid=valid, reset_reasons=reasons)
            rows.append(row)
            previous = row
        full_count = int((end - begin) // (60 * self.minutes))
        tail = max(0, full_count - 1 - rows[-1]["index"]) if rows else full_count
        if tail:
            self.clear()
            clear_count += 1
        return rows, {"minutes": self.minutes, "rows": len(rows),
                      "valid_rows": sum(row["valid"] for row in rows),
                      "clear_count": clear_count, "tail_missing": tail}


def _validate_source(frame: dict, minutes: int) -> None:
    """SOURCEの型を検査し、価格不正は足単位の準備不足へ残す。

    引数: frame(dict)はSOURCE足、minutes(int)は期待する足幅。
    返り値: None。順序を比較できない不正型はInputError。
    """
    if not isinstance(frame, dict) or any(name not in frame for name in SOURCE_FIELDS):
        raise InputError("SOURCE12不足")
    if not isinstance(frame["index"], int) or isinstance(frame["index"], bool) or frame["index"] < 0:
        raise InputError("足番号不正")
    if frame["minutes"] != minutes or isinstance(frame["minutes"], bool):
        raise InputError("足幅の混在")
    if not isinstance(frame["publish"], bool):
        raise InputError("公開旗不正")
    if not isinstance(frame["missing"], int) or isinstance(frame["missing"], bool) or frame["missing"] < 0:
        raise InputError("欠枠数不正")
    if not finite(frame["start"]) or not finite(frame["end"]) or frame["end"] <= frame["start"]:
        raise InputError("開始終了時計不正")
    if frame["publish"] and (not finite(frame["confirm"]) or not isinstance(frame["confirm_line"], int)
                              or isinstance(frame["confirm_line"], bool) or frame["confirm_line"] < 0):
        raise InputError("公開時計又は原行不正")


def build_bank(sessions: list[dict]) -> dict:
    """SOURCE12だけの全場を、同限月carryの二銀行へ順に投入する。

    引数: sessions(list[dict])はsession/contract/begin/end/frames3/frames15を持つ。
    返り値: dictは場名からframes3/frames15/品質等への写像。
    """
    if not isinstance(sessions, list):
        raise InputError("sessionsは配列")
    lower, upper = NumericBank(3), NumericBank(15)
    output, previous_end = {}, None
    for item in sessions:
        name = item["session"]
        if not isinstance(name, str) or not name or name in output:
            raise InputError("場名不正又は重複")
        begin, end, contract = item["begin"], item["end"], item["contract"]
        if not finite(begin) or not finite(end) or end <= begin:
            raise InputError("場の開始終了不正")
        if previous_end is not None and begin < previous_end:
            raise InputError("場の時系列順不正")
        if not isinstance(contract, tuple) or not contract or not all(isinstance(part, str) for part in contract):
            raise InputError("限月は空でない文字列tuple")
        frames3, quality3 = lower.build(item["frames3"], name, contract, begin, end)
        frames15, quality15 = upper.build(item["frames15"], name, contract, begin, end)
        output[name] = {"session": name, "contract": contract, "begin": begin, "end": end,
                        "frames3": frames3, "frames15": frames15,
                        "quality": {"3": quality3, "15": quality15}}
        previous_end = end
    return output


# ----------------------------------------
# 当場の可視出典だけで、帯と定時の価格反応を判定する。

def choose_asof(rows: list[dict], scheduled: float, time: float, line: int) -> dict | None:
    """予定時刻以前に終わり、実判断keyまでに公開された最新足を選ぶ。

    引数: rows(list[dict])は当場数値足、scheduled(float)は予定秒、
        time(float)/line(int)は実判断の価格時計/原行。
    返り値: dict|Noneは最新end/indexの足。不正・数値不足を古い正常足へ代替しない。
    """
    visible = [row for row in rows if row["publish"] and row["end"] <= scheduled
               and key(row) <= (time, line)]
    return max(visible, key=lambda row: (row["end"], row["index"])) if visible else None


def opening_range(rows: list[dict], begin: float, scheduled: float,
                  time: float, line: int) -> dict:
    """当場のindex0〜9だけから、最初30分の固定帯を作る。

    引数: rows(list[dict])は当場3分足、begin(float)は場開始、
        scheduled(float)/time(float)/line(int)は予定と実判断key。
    返り値: dictはready/low/high/mid/出典/理由。未来の公開を補完しない。
    """
    indexed = {row["index"]: row for row in rows}
    selected = [indexed.get(index) for index in range(10)]
    ready = all(row is not None and row["valid"] and row["start"] == begin + 180 * index
                and row["end"] <= scheduled and key(row) <= (time, line)
                for index, row in enumerate(selected))
    if not ready:
        return {"ready": False, "low": None, "high": None, "mid": None,
                "sources": None, "reason": "開始30分OR未準備"}
    low = min(Fraction(row["low"]) for row in selected)
    high = max(Fraction(row["high"]) for row in selected)
    return {"ready": True, "low": float(low), "high": float(high), "mid": exact((low + high) / 2),
            "sources": [source(row) for row in selected], "reason": ""}


def local_window(rows: list[dict], current: dict, count: int,
                 time: float, line: int) -> list[dict] | None:
    """当場の指定本数を、公開・有効・完全隣接で取り出す。

    引数: rows(list[dict])は当場3分足、current(dict)は末尾、count(int)は本数、
        time(float)/line(int)は実判断key。
    返り値: list[dict]|Noneは過去順の窓。本数不足を他場で埋めない。
    """
    indexed = {row["index"]: row for row in rows}
    span = [indexed.get(index) for index in range(current["index"] - count + 1, current["index"] + 1)]
    if any(row is None or not row["valid"] or key(row) > (time, line) for row in span):
        return None
    return span if all(adjacent(p, c) for p, c in zip(span, span[1:])) else None


def structure(rows: list[dict], current: dict, band: dict, time: float, line: int) -> dict:
    """3終値の外側維持Tと、先行外到達から2終値復帰のRを分ける。

    引数: rows(list[dict])は当場3分足、current(dict)は最新、band(dict)は固定OR、
        time(float)/line(int)は実判断key。
    返り値: dictは候補一覧と不足理由。足内の高安発生順は推測しない。
    """
    recent = local_window(rows, current, 3, time, line)
    if recent is None:
        return {"candidates": [], "ready": False, "reason": "直近3本の公開完全隣接不足",
                "recent": None, "excursion": None}
    low, high, close = Fraction(band["low"]), Fraction(band["high"]), Fraction(current["close"])
    mid = (low + high) / 2
    candidates = []
    for side in (1, -1):
        limit = high + BUFFER if side == 1 else low - BUFFER
        if all(side * (Fraction(row["close"]) - limit) > 0 for row in recent):
            candidates.append({"kind": "T", "side": side, "role": "順行", "excursion": None})
    previous = recent[-2]
    # Rは最新位置と二終値の片端条件を先に調べ、必要な場合だけ10本窓を要求する。
    outward = 1 if mid < close < high else -1 if low < close < mid else 0
    excursion, missing = None, False
    if outward:
        inside_limit = high - BUFFER if outward == 1 else low + BUFFER
        returned = all(outward * (Fraction(row["close"]) - inside_limit) < 0
                       for row in (previous, current))
        if returned:
            ten = local_window(rows, current, 10, time, line)
            if ten is None:
                missing = True
            else:
                outside_limit = high + BUFFER if outward == 1 else low - BUFFER
                touched = [row for row in ten if row["index"] >= 10 and row["index"] < current["index"] - 1
                           and outward * (Fraction(row["high"] if outward == 1 else row["low"]) - outside_limit) > 0]
                if touched:
                    excursion = source(touched[-1])
                    candidates.append({"kind": "R", "side": -outward, "role": "反転",
                                       "excursion": excursion})
    return {"candidates": candidates, "ready": not missing or bool(candidates),
            "reason": "R過去10本の公開完全隣接不足" if missing and not candidates else "",
            "recent": [source(row) for row in recent], "excursion": excursion}


def evaluate_slot(bank: dict, session: str, scheduled: float, time: float,
                  line: int, policy: str) -> dict:
    """一つの予定枠を、最初の有効価格keyで入口候補又は待機へ分類する。

    引数: bank(dict)はbuild_bankの返り値、session(str)は場、scheduled(float)は予定秒、
        time(float)/line(int)は予定以後30秒以内の実判断key、policy(str)はS0又はS1。
    返り値: dictはside/role/atr/D/ready/reasonと当時出典・特徴。0方向は待機又は判定不能。
    """
    if policy not in POLICIES:
        raise InputError("候補ID不正")
    if not finite(scheduled) or not finite(time) or not scheduled <= time <= scheduled + 30:
        raise InputError("実判断は予定以後30秒以内")
    if not isinstance(line, int) or isinstance(line, bool) or line < 0:
        raise InputError("実判断原行不正")
    data = bank[session]
    result = {"session": session, "scheduled": scheduled, "time": time, "line": line, "policy": policy,
              "side": 0, "role": "待機", "atr": None, "D": None, "ready": False, "reason": "",
              "current": None, "previous": None, "upper": None, "OR": None,
              "fast_k": exact(None), "fast_previous": exact(None), "fast_change": exact(None),
              "plus_di": None, "minus_di": None, "adx": None,
              "structure": None, "kind": None, "excursion": None}
    if not data["begin"] <= scheduled < data["end"]:
        result["reason"] = "予定時刻が当場外"
        return result
    rows = data["frames3"]
    current = choose_asof(rows, scheduled, time, line)
    if current is None:
        result["reason"] = "当場公開3分参照なし"
        return result
    result["current"] = source(current)
    if scheduled - current["end"] > 180:
        result["reason"] = "最新3分足が180秒超過"
        return result
    if not current["valid"]:
        result["reason"] = "最新3分価格足不正又は不完全"
        return result
    band = opening_range(rows, data["begin"], scheduled, time, line)
    result["OR"] = band
    if not band["ready"]:
        result["reason"] = band["reason"]
        return result
    shape = structure(rows, current, band, time, line)
    result["structure"] = shape
    if shape["recent"] is not None:
        result["previous"] = shape["recent"][-2]
    result.update(atr=current["atr"], fast_k=deepcopy(current["fast_k"]),
                  fast_previous=deepcopy(current["fast_previous"]), fast_change=deepcopy(current["fast_change"]))
    if not shape["ready"]:
        result["reason"] = shape["reason"]
        return result
    if not finite(current["atr"]) or current["atr"] <= 0:
        result["reason"] = "ATR14正値未準備"
        return result
    result["D"] = distance(current["atr"])
    if not current["fast_k"]["valid"] or not current["fast_change"]["valid"]:
        result["reason"] = "FastK14現前未準備"
        return result
    upper = choose_asof(data["frames15"], scheduled, time, line)
    upper_ready = upper is not None and upper["valid"] and scheduled - upper["end"] <= 900 and (
        finite(upper["plus_di"]) and finite(upper["minus_di"]))
    if upper is not None:
        result.update(upper=source(upper), plus_di=upper["plus_di"],
                      minus_di=upper["minus_di"], adx=upper["adx"])
    if policy == "S1" and not upper_ready:
        result["reason"] = "当場15分DMI未準備又は900秒超過"
        return result
    result["ready"] = True
    candidates = shape["candidates"]
    if len(candidates) > 1:
        result["reason"] = "T/R同時候補WAIT"
        return result
    if not candidates:
        result["reason"] = "価格構造WAIT"
        return result
    selected = candidates[0]
    side, kind = selected["side"], selected["kind"]
    result.update(kind=kind, excursion=deepcopy(selected["excursion"]))
    k, change = fraction(current["fast_k"]), fraction(current["fast_change"])
    if kind == "T" and not (side * (k - 50) > 0 and side * change >= 0):
        result["reason"] = "順行FastK水準又は進行不一致"
        return result
    if kind == "R" and not side * change > 0:
        result["reason"] = "反転FastK進行不一致"
        return result
    if policy == "S1":
        direction = side * (upper["plus_di"] - upper["minus_di"])
        if kind == "T" and direction <= 0 or kind == "R" and direction < 0:
            result["reason"] = "上位DI方向不一致"
            return result
    result.update(side=side, role=selected["role"], reason="採用")
    return result
