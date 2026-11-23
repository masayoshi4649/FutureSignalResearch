"""保存済み定時slotの当時出典だけから、売買対称な技法特徴を作る。

市場ファイル、教師、約定、保有、損益を読まない。旧候補の採用・待機旗を
特徴準備へ流用せず、必要な出典と数値を個別に検査する。
"""

from __future__ import annotations

from fractions import Fraction
import importlib.util
import math
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "技法分岐学習が固定参照する49価格補助",
    Path(__file__).resolve().parents[1] / "定時帯反応/入口.py",
)
I49 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(I49)

FEATURES = [
    {"id": "F01", "name": "実方向のDI優勢差", "method": "I08", "family": "trend", "scale": "m15"},
    {"id": "F02", "name": "実方向のFastK中央差", "method": "I07", "family": "osc", "scale": "m03"},
    {"id": "F03", "name": "実方向のFastK進行", "method": "I07", "family": "osc", "scale": "m03"},
    {"id": "F04", "name": "ATR対125pt", "method": "I09", "family": "vol", "scale": "m03"},
    {"id": "F05", "name": "開始帯幅対ATR", "method": "P03", "family": "price", "scale": "m30"},
    {"id": "F06", "name": "実方向の開始帯中央距離", "method": "P06", "family": "price", "scale": "m03+m30"},
    {"id": "F07", "name": "実方向の終値変化", "method": "P05", "family": "price", "scale": "m03"},
    {"id": "F08", "name": "実方向の3分実体", "method": "P01", "family": "price", "scale": "m03"},
    {"id": "F09", "name": "3分高安幅対ATR", "method": "P01", "family": "price", "scale": "m03"},
    {"id": "F10", "name": "実方向の3分足内終値位置", "method": "P01", "family": "price", "scale": "m03"},
    {"id": "F11", "name": "実方向端の進行", "method": "P02", "family": "price", "scale": "m03"},
    {"id": "F12", "name": "反対端の実方向進行", "method": "P02", "family": "price", "scale": "m03"},
    {"id": "F13", "name": "実方向の15分実体対3分ATR", "method": "P01", "family": "price", "scale": "m15"},
    {"id": "F14", "name": "15分高安幅対3分ATR", "method": "P01", "family": "price", "scale": "m15"},
    {"id": "F15", "name": "実方向の15分足内終値位置", "method": "P01", "family": "price", "scale": "m15"},
]
SOURCE_FIELDS = ("session", *I49.SOURCE_FIELDS)


def _source_reason(row: object, session: str, minutes: int, scheduled: float,
                   limit: tuple[float, int]) -> str:
    """足の完全性・当場性・公開時点を検査する。

    引数: row(object)は保存SOURCE、session(str)は当場、minutes(int)は足幅、
        scheduled(float)は予定秒、limit(tuple[float,int])は実判断key。
    返り値: strは不正理由。空文字なら有効。古い出典へ代替しない。
    """
    if not isinstance(row, dict) or any(name not in row for name in SOURCE_FIELDS):
        return "出典なし又はフィールド不足"
    if row["session"] != session or row["minutes"] != minutes:
        return "当場又は足幅不一致"
    if type(row["index"]) is not int or row["index"] < 0:
        return "足番号不正"
    if type(row["confirm_line"]) is not int or row["confirm_line"] < 0:
        return "公開原行不正"
    if any(not I49.finite(row[name]) for name in ("start", "end", "confirm")):
        return "出典時計不正"
    if not I49.eligible_price(row):
        return "非公開又は価格不正・欠枠・不完全"
    if row["end"] > scheduled or I49.key(row) > limit:
        return "当時公開参照なし"
    return ""


def _exact_value(value: object) -> Fraction | None:
    """保存exact辞書の有効な既約値を読み取る。

    引数: value(object)はFastK又は変化の保存辞書。
    返り値: Fraction|Noneは表示値と分数が整合する精密値、又は欠測。
    """
    if not isinstance(value, dict) or value.get("valid") is not True:
        return None
    numerator, denominator = value.get("numerator"), value.get("denominator")
    if type(numerator) is not int or type(denominator) is not int or denominator <= 0:
        return None
    result = Fraction(numerator, denominator)
    if not I49.finite(value.get("value")):
        return None
    try:
        return result if value["value"] == float(result) else None
    except OverflowError:
        return None


def _band_reason(band: object, session: str, scheduled: float,
                 limit: tuple[float, int]) -> str:
    """固定開始帯とその10本出典の整合を検査する。

    引数: band(object)は保存OR、session(str)は当場、scheduled(float)は予定秒、
        limit(tuple[float,int])は実判断key。
    返り値: strは不正理由。帯中央は保存表示を使わず高安から再度作る。
    """
    if not isinstance(band, dict) or band.get("ready") is not True:
        return "開始30分OR未準備"
    if any(not I49.finite(band.get(name)) for name in ("low", "high")):
        return "開始帯価格不正"
    rows = band.get("sources")
    if not isinstance(rows, list) or len(rows) != 10:
        return "開始帯10本出典不足"
    for index, row in enumerate(rows):
        if _source_reason(row, session, 3, scheduled, limit) or row["index"] != index:
            return "開始帯10本の公開完全出典不一致"
    if not all(I49.adjacent(p, c) for p, c in zip(rows, rows[1:])):
        return "開始帯10本の隣接不一致"
    if (Fraction(band["low"]) != min(Fraction(row["low"]) for row in rows)
            or Fraction(band["high"]) != max(Fraction(row["high"]) for row in rows)):
        return "開始帯価格と出典不一致"
    return ""


def _clv(row: dict) -> Fraction:
    """足内終値位置を精密に求め、零幅だけ0と定義する。

    引数: row(dict)は有効なOHLC出典。
    返り値: Fractionは(2C−H−L)/(H−L)、又は零幅時の0。
    """
    high, low, close = (Fraction(row[name]) for name in ("high", "low", "close"))
    return (2 * close - high - low) / (high - low) if high > low else Fraction(0)


# ----------------------------------------
# 入力の選択と特徴計算を分け、旧候補や未来の教師を選択条件に使わない。

def extract(slot: dict) -> dict:
    """保存P0slot一件から、同じ木へ渡す二方向15特徴を作る。

    引数: slot(dict)は50の保存P0slot。予定時計とSOURCE、OR、upper、
        diagnostic.old_RのFast辞書を必要とする。
    返り値: dictはready/reason/vectors/atr/D/background_direction/sources等。
        判定不能は両方向空配列とし、補完・教師読取・入力改変を行わない。
    """
    result = {"ready": False, "reason": "", "vectors": {"1": [], "-1": []},
              "atr": None, "D": None, "background_direction": None,
              "sources": {"current": None, "previous": None, "upper": None, "OR": None},
              "diagnostic": {}}
    if not isinstance(slot, dict):
        result["reason"] = "slot辞書なし"
        return result
    session = slot.get("session")
    scheduled, time, line = (slot.get(name) for name in ("scheduled", "time", "line"))
    if (not isinstance(session, str) or not session
            or not I49.finite(scheduled) or not I49.finite(time)
            or not scheduled <= time <= scheduled + 30
            or type(line) is not int or line < 0):
        result["reason"] = "判断時計又は原行なし・不正"
        return result
    if slot.get("reason") == "判断BBO不正":
        result["reason"] = "判断BBO不正"
        return result
    limit = (time, line)
    current, previous = slot.get("current"), slot.get("previous")
    for name, row in (("current", current), ("previous", previous)):
        reason = _source_reason(row, session, 3, scheduled, limit)
        if reason:
            result["reason"] = ("現3分" if name == "current" else "前3分") + ": " + reason
            return result
        result["sources"][name] = I49.source(row)
    if not I49.adjacent(previous, current):
        result["reason"] = "現前3分の完全隣接不一致"
        return result
    if scheduled - current["end"] > 180:
        result["reason"] = "現3分足が180秒超過"
        return result
    band = slot.get("OR")
    reason = _band_reason(band, session, scheduled, limit)
    if reason:
        result["reason"] = reason
        return result
    result["sources"]["OR"] = {
        "low": band["low"], "high": band["high"],
        "indices": [row["index"] for row in band["sources"]],
        "latest_key": list(max(I49.key(row) for row in band["sources"])),
    }
    upper = slot.get("upper")
    if not isinstance(upper, dict) or upper.get("ready") is not True:
        result["reason"] = "当場15分DMI未準備"
        return result
    upper_source = upper.get("source")
    reason = _source_reason(upper_source, session, 15, scheduled, limit)
    if reason:
        result["reason"] = "上位15分: " + reason
        return result
    if scheduled - upper_source["end"] > 900:
        result["reason"] = "上位15分足が900秒超過"
        return result
    if any(not I49.finite(upper.get(name)) for name in ("plus_di", "minus_di")):
        result["reason"] = "上位DI数値不正"
        return result
    result["sources"]["upper"] = I49.source(upper_source)
    atr = slot.get("atr")
    if not I49.finite(atr) or atr <= 0:
        result["reason"] = "現ATR正値未準備"
        return result
    result.update(atr=atr, D=I49.distance(atr))
    diagnostic = slot.get("diagnostic")
    old = diagnostic.get("old_R") if isinstance(diagnostic, dict) else None
    if not isinstance(old, dict):
        result["reason"] = "Fast保存参照なし"
        return result
    old_source = old.get("current")
    if (not isinstance(old_source, dict)
            or any(name not in old_source for name in SOURCE_FIELDS)
            or I49.source(old_source) != I49.source(current)):
        result["reason"] = "Fastと現3分出典不一致"
        return result
    k, change = (_exact_value(old.get(name)) for name in ("fast_k", "fast_change"))
    if k is None or change is None:
        result["reason"] = "FastK又は現前差の精密値未準備"
        return result
    a = Fraction(atr)
    o, h, low, c = (Fraction(current[name]) for name in ("open", "high", "low", "close"))
    ph, pl, pc = (Fraction(previous[name]) for name in ("high", "low", "close"))
    uo, uh, ul, uc = (Fraction(upper_source[name]) for name in ("open", "high", "low", "close"))
    band_low, band_high = Fraction(band["low"]), Fraction(band["high"])
    midpoint = (band_low + band_high) / 2
    di = Fraction(upper["plus_di"]) - Fraction(upper["minus_di"])
    result["background_direction"] = int(di > 0) - int(di < 0)
    for side in (1, -1):
        direction_edge = h - ph if side == 1 else low - pl
        opposite_edge = low - pl if side == 1 else h - ph
        exact_values = [
            side * di / 100, side * (k - 50) / 50, side * change / 100,
            a / 125, (band_high - band_low) / a, side * (c - midpoint) / a,
            side * (c - pc) / a, side * (c - o) / a, (h - low) / a,
            side * _clv(current), side * direction_edge / a, side * opposite_edge / a,
            side * (uc - uo) / a, (uh - ul) / a, side * _clv(upper_source),
        ]
        try:
            vector = [float(value) for value in exact_values]
        except OverflowError:
            result.update(reason="特徴のfloat表示範囲外", vectors={"1": [], "-1": []})
            return result
        if not all(math.isfinite(value) for value in vector):
            result.update(reason="特徴の有限値不成立", vectors={"1": [], "-1": []})
            return result
        result["vectors"][str(side)] = vector
    result["diagnostic"] = {
        "fast_k": float(k), "fast_change": float(change),
        "plus_di": upper["plus_di"], "minus_di": upper["minus_di"],
        "current_age_seconds": scheduled - current["end"],
        "upper_age_seconds": scheduled - upper_source["end"],
        "zero_width_current": h == low, "zero_width_upper": uh == ul,
    }
    result.update(ready=True, reason="")
    return result
