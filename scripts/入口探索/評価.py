"""入口候補の全約定確認率と、未来を参照しない間引き感度を集計する。

Wilson区間は独立二項を仮定した参考値であり、重複経路の相関を補正しない。
式の確認先: https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm
確認日: 2026-11-01。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from functools import lru_cache
import math
import random
from typing import Any


LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")
Z95 = 1.959963984540054


# ----------------------------------------
# 入力選択と、ラベルから独立した時刻順の間引き

def _選択(rows: list[dict[str, Any]], mask: Any) -> list[tuple[int, dict[str, Any]]]:
    """同長の一次元真偽マスクで候補を選択する。

    引数: rows (list[dict[str, Any]]) は対象行、mask (Any) はNumPyのbool列またはPythonのbool列。
    返り値: list[tuple[int, dict[str, Any]]] は元の位置と選択行。不正な次元・長さ・型は例外にする。
    """
    if getattr(mask, "ndim", 1) != 1 or len(mask) != len(rows):
        raise ValueError("候補とマスクの長さまたは次元が一致しません")
    selected = []
    for index, (row, flag) in enumerate(zip(rows, mask)):
        python_bool = isinstance(flag, bool)
        numpy_bool = (getattr(getattr(flag, "dtype", None), "kind", None) == "b"
                      and getattr(flag, "ndim", 0) == 0)
        if not (python_bool or numpy_bool):
            raise TypeError("マスクには真偽値だけを指定してください")
        if bool(flag):
            selected.append((index, row))
    return selected


@lru_cache(maxsize=512)
def _開始日(session: str) -> str:
    """場名を検査し、ナイトも開始日基準のクラスタへ割り当てる。

    引数: session (str) はYYYY-MM-DD_DayまたはNight。
    返り値: str は検査済みの開始日。
    """
    day, part = session.rsplit("_", 1)
    if part not in ("Day", "Night"):
        raise ValueError(f"不正な場名: {session}")
    return date.fromisoformat(day).isoformat()


def _要求キー(item: tuple[int, dict[str, Any]]) -> tuple[Decimal, int, int]:
    """判断時点で既知の要求時計・原行だけで順序を作る。

    引数: item (tuple[int, dict[str, Any]]) は元の位置と行。
    返り値: tuple[Decimal, int, int] は要求秒・要求原行・元の位置。
    """
    index, row = item
    seconds = Decimal(str(row["要求時計秒"]))
    if not seconds.is_finite():
        raise ValueError("要求時計は有限値である必要があります")
    return seconds, int(row.get("要求原板行", 0)), index


def _方向(row: dict[str, Any]) -> int:
    """候補の方向を1または-1へ統一する。

    引数: row (dict[str, Any]) はsideまたは方向を持つ候補。
    返り値: int は買い1または売り-1。不明な値はValueErrorにする。
    """
    if "side" in row:
        value = Decimal(str(row["side"]))
        if value in (Decimal(1), Decimal(-1)):
            return int(value)
    elif row.get("方向") in ("買い", "売り"):
        return 1 if row["方向"] == "買い" else -1
    raise ValueError("候補の方向が1または-1ではありません")


def _間引き位置(selected: list[tuple[int, dict[str, Any]]]) -> list[int]:
    """場・方向ごとに、採用要求から30分以上離れた最初の要求を採用する。

    引数: selected (list[tuple[int, dict[str, Any]]]) は条件を満たす全候補。未約定も含む。
    返り値: list[int] は要求順で採用した元の位置。ラベル・新規時計・判定時計は参照しない。
    """
    previous = {}
    kept = []
    for item in sorted(selected, key=_要求キー):
        index, row = item
        session = str(row["場"])
        _開始日(session)
        key = (session, _方向(row))
        now = _要求キー(item)[0]
        if key not in previous or now - previous[key] >= Decimal(1800):
            kept.append(index)
            previous[key] = now
    return kept


def thin30_mask(rows: list[dict[str, Any]], mask: Any) -> list[bool]:
    """選択候補を要求時刻だけで30分間引きし、同長のPythonマスクを返す。

    引数: rows (list[dict[str, Any]]) は候補、mask (Any) は同長の一次元真偽列。
    返り値: list[bool] は採用位置が真のマスク。未約定の先行要求も間引きの起点になる。
    """
    result = [False] * len(rows)
    for index in _間引き位置(_選択(rows, mask)):
        result[index] = True
    return result


# ----------------------------------------
# 全約定分母、支持日数と、独立二項の参考区間

def wilson95(successes: int, total: int) -> tuple[float | None, float | None]:
    """独立二項を仮定するWilson両側95%参考区間を求める。

    引数: successes (int) は成功数、total (int) は全約定数。
    返り値: tuple[float | None, float | None] は下限・上限。分母0なら両方None。
    """
    if not 0 <= successes <= total:
        raise ValueError("成功数と分母が不正です")
    if total == 0:
        return None, None
    ratio = successes / total
    denominator = 1 + Z95 * Z95 / total
    center = (ratio + Z95 * Z95 / (2 * total)) / denominator
    radius = Z95 * math.sqrt(ratio * (1 - ratio) / total + Z95 * Z95 / (4 * total * total)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def _基本集計(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """五分類を保ったまま全約定確認率・場数・開始日数を集計する。

    引数: rows (list[dict[str, Any]]) は選択後の候補。
    返り値: dict[str, Any] はPython標準型のみの件数・率・支持範囲。
    """
    counts = Counter()
    sessions, filled_sessions, candidate_days, filled_days = set(), set(), set(), set()
    success_by_day = Counter()
    for row in rows:
        label = row["ラベル"]
        if label not in LABELS:
            raise ValueError(f"未知のラベル: {label}")
        session = str(row["場"])
        day = _開始日(session)
        counts[label] += 1
        sessions.add(session)
        candidate_days.add(day)
        if label != "未約定":
            filled_sessions.add(session)
            filled_days.add(day)
        if label == "順行先着":
            success_by_day[day] += 1
    filled = len(rows) - counts["未約定"]
    successes = counts["順行先着"]
    return {"候補数": len(rows), "約定候補数": filled,
            **{label: int(counts[label]) for label in LABELS},
            "確認率": successes / filled if filled else None,
            "候補場数": len(sessions), "約定場数": len(filled_sessions),
            "候補開始日数": len(candidate_days), "約定開始日数": len(filled_days),
            "成功開始日数": len(success_by_day),
            "最大成功日寄与率": max(success_by_day.values()) / successes if successes else None}


def evaluate(rows: list[dict[str, Any]], mask: Any, split_name: str) -> dict[str, Any]:
    """候補の五分類・支持範囲・30分間引き感度を集計する。

    引数: rows (list[dict[str, Any]]) は全行または一分割の行、mask (Any) は同長の真偽列、
    split_name (str) は学習・選択・後続等の表示名。
    返り値: dict[str, Any] はJSON保存できる平坦な集計。70%や最低支持基準の採否は判定しない。
    """
    selected = _選択(rows, mask)
    result = _基本集計([row for _, row in selected])
    lower, upper = wilson95(result["順行先着"], result["約定候補数"])
    kept = set(_間引き位置(selected))
    thin = _基本集計([row for index, row in selected if index in kept])
    result.update({"分割": str(split_name), "Wilson95下限_独立参考": lower,
                   "Wilson95上限_独立参考": upper,
                   "30分間引き_候補数": thin["候補数"],
                   "30分間引き_約定候補数": thin["約定候補数"],
                   "30分間引き_順行先着": thin["順行先着"],
                   "30分間引き_確認率": thin["確認率"],
                   "30分間引き_候補場数": thin["候補場数"],
                   "30分間引き_約定場数": thin["約定場数"],
                   "30分間引き_約定開始日数": thin["約定開始日数"]})
    return result


def group_by_day(rows: list[dict[str, Any]], mask: Any) -> list[dict[str, Any]]:
    """選択候補の開始日ごとに、デイ・ナイトをまとめた集計を作る。

    引数: rows (list[dict[str, Any]]) は全行または分割内の行、mask (Any) は同長の真偽列。
    返り値: list[dict[str, Any]] は開始日昇順の基本集計。選択候補がない日は含まない。
    """
    grouped = defaultdict(list)
    for _, row in _選択(rows, mask):
        grouped[_開始日(str(row["場"]))].append(row)
    return [{"開始日": day, **_基本集計(grouped[day])} for day in sorted(grouped)]


# ----------------------------------------
# 最終選択だけへ適用する、開始日単位の参考再標本化

def _分位点(sorted_values: list[float], probability: float) -> float | None:
    """昇順値の線形補間による経験分位点を返す。

    引数: sorted_values (list[float]) は昇順値、probability (float) は0～1の分位。
    返り値: float | None は経験分位点。空配列はNone。
    """
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * probability
    left = int(math.floor(position))
    right = int(math.ceil(position))
    weight = position - left
    return sorted_values[left] * (1 - weight) + sorted_values[right] * weight


def date_bootstrap(rows: list[dict[str, Any]], mask: Any, seed: int = 20261101,
                   draws: int = 2000) -> dict[str, Any]:
    """開始日内の成功数と全約定数を一組で再標本化する。

    引数: rows (list[dict[str, Any]]) は候補、mask (Any) は選択、seed (int) は固定乱数種、
    draws (int) は復元抽出回数。最終選択した候補だけへの適用を想定する。
    返り値: dict[str, Any] は日別再標本の95%参考区間と有効回数。1日以下は区間None。
    """
    if not isinstance(draws, int) or isinstance(draws, bool) or draws <= 0:
        raise ValueError("抽出回数は正の整数で指定してください")
    daily = group_by_day(rows, mask)
    ratios = []
    zero_draws = 0
    rng = random.Random(seed)
    if len(daily) >= 2:
        for _ in range(draws):
            chosen = [daily[rng.randrange(len(daily))] for _ in daily]
            filled = sum(row["約定候補数"] for row in chosen)
            if filled:
                ratios.append(sum(row["順行先着"] for row in chosen) / filled)
            else:
                zero_draws += 1
    ratios.sort()
    return {"再標本日数": len(daily), "抽出回数": draws, "有効抽出回数": len(ratios),
            "ゼロ約定抽出回数": zero_draws,
            "日別再標本95下限_参考": _分位点(ratios, 0.025),
            "日別再標本95上限_参考": _分位点(ratios, 0.975),
            "注意": "選択候補がある開始日を復元抽出し、同日のデイ・ナイトと候補をまとめて保持。1日以下は区間を計算しない。5日前後の少数日では区間も不安定。日をまたぐ依存・候補選択の多重性・既使用期間の選択偏りを補正せず、将来70%以上の保証ではない。"}
