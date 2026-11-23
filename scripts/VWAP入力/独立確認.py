"""00017の小列cacheを別処理で検算し、原板との対応は限定した標本で直接確認する。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00017_配信元VWAPと売買代金の入力監査"
WORK = ROOT / "work/VWAP入力/00017"
FIELDS = ("now", "line", "last", "volume", "volume_time", "native_vwap", "trading_value",
          "opening_price", "opening_time", "contract", "exchange", "repeat")
NUMERIC_FIELDS = ("last", "volume", "native_vwap", "trading_value", "opening_price")
TOLERANCE = 0.00010001
JST = timezone(timedelta(hours=9))


def read(path: Path) -> Any:
    """UTF-8のJSON資料を読む。

    引数: path (Path) は対象。
    返り値: Any は復元されたJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """小列cache・コード・資料の指紋を計算する。

    引数: path (Path) は対象。巨大原板の再全走査には使わない。
    返り値: str はSHA256。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def number(value: Any) -> float:
    """原板の有限数値だけをfloatへ正規化する。

    引数: value (Any) は原板値。
    返り値: float は有限数値、欠測/非数/非有限はNaN。boolは数値にしない。
    """
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else math.nan


def clock(value: Any) -> float:
    """時差付き原板時計だけをUnix秒へ変換する。

    引数: value (Any) は日時表記。
    返り値: float はUnix秒。欠測/時差なし/不正ならNaN。
    """
    if not isinstance(value, str) or not value:
        return math.nan
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.timestamp() if parsed.utcoffset() is not None else math.nan
    except (ValueError, OverflowError):
        return math.nan


def original_record(row: dict, line: int) -> dict:
    """主抽出を呼ばず原板一行を独立変換する。

    引数: row (dict) は原板、line (int) は物理行。
    返り値: dict は小列schemaの値。contractはコード文字列で保持する。
    """
    return {"line": line, "now": clock(row.get("CurrentPriceTime")), "last": number(row.get("CurrentPrice")),
        "volume": number(row.get("TradingVolume")), "volume_time": clock(row.get("TradingVolumeTime")),
        "native_vwap": number(row.get("VWAP")), "trading_value": number(row.get("TradingValue")),
        "opening_price": number(row.get("OpeningPrice")), "opening_time": clock(row.get("OpeningPriceTime")),
        "contract": str(row["Symbol"]) if row.get("Symbol") is not None else None,
        "exchange": {"Exchange": row.get("Exchange"), "ExchangeName": row.get("ExchangeName")}}


# ----------------------------------------
# 同一状態のrepeatを原行重みとし、分位点も全原行に展開せず順位から求める。

def weight(mask: np.ndarray, repeat: np.ndarray) -> int:
    """条件に該当する原行重みを数える。

    引数: mask (np.ndarray) は条件、repeat (np.ndarray) は連続同一状態の物理行数。
    返り値: int は該当原行数。
    """
    return int(np.sum(repeat[mask], dtype=np.int64))


def weighted_quantiles(values: np.ndarray, repeat: np.ndarray, fractions: list[float]) -> list[float | None]:
    """全repeat展開列の線形分位と同じ値を、累積順位で計算する。

    引数: values/repeat (np.ndarray) は有限値/正整数重み、fractions (list[float]) は0〜1の分位。
    返り値: list[float|None] は分位値。空列ではNone。
    """
    if not len(values):
        return [None] * len(fractions)
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    cumulative = np.cumsum(repeat[order], dtype=np.int64)
    count, output = int(cumulative[-1]), []
    for fraction in fractions:
        rank = fraction * (count - 1)
        lower, upper = math.floor(rank), math.ceil(rank)
        low = sorted_values[int(np.searchsorted(cumulative, lower + 1, side="left"))]
        high = sorted_values[int(np.searchsorted(cumulative, upper + 1, side="left"))]
        output.append(float(low + (high - low) * (rank - lower)))
    return output


def formula(columns: dict[str, np.ndarray]) -> dict:
    """配信値と代金/数量/1000を独立な配列式で比較する。

    引数: columns (dict[str,np.ndarray]) は小列。原板全状態がそのまま残るという前提は置かない。
    返り値: dict は原行重みの有効/一致/不整合数・誤差分位と代表state番号。
    """
    volume, value, native, repeat = (columns[k] for k in ("volume", "trading_value", "native_vwap", "repeat"))
    valid = np.isfinite(volume) & (volume > 0) & np.isfinite(value) & (value >= 0) & np.isfinite(native) & (native > 0)
    positions = np.flatnonzero(valid)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        calculated = value[valid] / volume[valid] / 1000
        differences = np.abs(native[valid] - calculated)
    ratio_finite = np.isfinite(differences)
    nonfinite = weight(~ratio_finite, repeat[valid])
    positions, differences = positions[ratio_finite], differences[ratio_finite]
    valid = np.zeros(len(volume), dtype=bool)
    valid[positions] = True
    matching = differences <= TOLERANCE
    first, maximum, failure = None, None, None
    if len(positions):
        first, maximum = int(positions[0]), int(positions[int(np.argmax(differences))])
        bad = np.flatnonzero(~matching)
        failure = int(positions[bad[0]]) if len(bad) else None
    return {"比率計算非有限原行数": nonfinite, "比較可能原行数": weight(valid, repeat), "許容内原行数": weight(matching, repeat[valid]),
        "不整合原行数": weight(~matching, repeat[valid]), "最大絶対差pt": float(np.max(differences)) if len(differences) else None,
        "絶対差分位": dict(zip(("p0", "p50", "p90", "p95", "p99", "p100"),
            weighted_quantiles(differences, repeat[valid], [0, .5, .9, .95, .99, 1]))),
        "最初比較state": first, "最大差state": maximum, "最初不整合state": failure}


def basic(columns: dict[str, np.ndarray], codes: list[str], start: float, finish: float) -> dict:
    """小列のshape・物理行順と、値/時計の原行重みを別計算する。

    引数: columns (dict[str,np.ndarray]) は小列、codes (list[str]) は限月コード表、start/finish (float) は場範囲。
    返り値: dict はschema整合と有限性・時計の基礎集計。VWAP固有時計を推定しない。
    """
    if set(columns) != set(FIELDS) or len({len(v) for v in columns.values()}) != 1:
        raise ValueError("小列schemaまたは列長が不一致")
    repeat, line, now = (columns[k] for k in ("repeat", "line", "now"))
    if np.any(repeat <= 0) or np.any(repeat != np.floor(repeat)) or np.any(line <= 0) or np.any(line != np.floor(line)):
        raise ValueError("repeat/物理行が正整数でない")
    if np.any(line[1:] < line[:-1] + repeat[:-1]):
        raise ValueError("連続省略区間の重複または物理行後退")
    contract = columns["contract"]
    if np.any((contract < -1) | (contract >= len(codes))) or np.any(contract != np.floor(contract)):
        raise ValueError("限月参照番号が不正")
    finite_now = np.isfinite(now)
    inside = finite_now & (start <= now) & (now < finish)
    outside = finite_now & ~inside
    result = {"小列state数": len(line), "小列が代表する原行数": int(np.sum(repeat, dtype=np.int64)),
        "場内原行数": weight(inside, repeat), "場外原行数": weight(outside, repeat),
        "価格時計欠測原行数": weight(~finite_now, repeat), "限月欠測原行数": weight(contract < 0, repeat)}
    for field in NUMERIC_FIELDS:
        values = columns[field]
        finite = np.isfinite(values)
        result[field] = {"欠測原行数": weight(~finite, repeat), "零原行数": weight(finite & (values == 0), repeat),
            "負原行数": weight(finite & (values < 0), repeat), "正原行数": weight(finite & (values > 0), repeat)}
    quantity_time = columns["volume_time"]
    both = finite_now & np.isfinite(quantity_time)
    result["時計対応"] = {"数量時計先行原行数": weight(both & (quantity_time > now), repeat),
        "数量時計遅延原行数": weight(both & (quantity_time < now), repeat),
        "数量時計同時計原行数": weight(both & (quantity_time == now), repeat),
        "数量時計欠測原行数": weight(~np.isfinite(quantity_time), repeat)}
    return result


def bounds(session: str) -> tuple[float, float, float]:
    """監査する半開範囲と、当日の閉場後接頭下限を別に定義する。

    引数: session (str) は開始日基準のDay/Night。
    返り値: tuple[float,float,float] は開始・終了・接頭下限のUnix秒。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        dates = day.replace(hour=8, minute=45), day.replace(hour=15, minute=40), day.replace(hour=6)
    elif session.endswith("_Night"):
        dates = day.replace(hour=17), (day + timedelta(days=1)).replace(hour=5, minute=55), day.replace(hour=15, minute=45)
    else:
        raise ValueError("不明な場名")
    return tuple(date.timestamp() for date in dates)


def snapshot(columns: dict, position: int | None) -> dict | None:
    """指定stateを有限値/nullの保存schemaへ写像する。

    引数: columns (dict) は小列、position (int|None) はstate配列位置。
    返り値: dict|None は元物理先頭行を持つ12列。repeatを原行へ展開しない。
    """
    if position is None:
        return None
    output = {}
    for field in FIELDS:
        value = columns[field][position]
        output[field] = int(value) if field in ("line", "contract", "exchange", "repeat") else (
            float(value) if math.isfinite(value) else None)
    return output


def epoch_analysis(columns: dict, session: str) -> dict:
    """採用累積を先に区間分割し、各区間の既知prefix/開始零だけで差分可否を再計算する。

    引数: columns (dict) は原順小列、session (str) は場。
    返り値: dict は原行重み件数・起算・区間変更。主抽出の逐次base状態処理は呼ばない。
    """
    start, finish, prefix_floor = bounds(session)
    now, repeat = columns["now"], columns["repeat"]
    finite = np.isfinite(now)
    scope_inside = finite & (now >= start) & (now < finish)
    scope_prefix = finite & (now < start)
    scope_after = finite & (now >= finish)
    counts = Counter({"保存状態数": len(now), "原行重み合計": int(np.sum(repeat, dtype=np.int64)),
        "価格時計欠測除外原行数": weight(~finite, repeat), "場内原行数": weight(scope_inside, repeat),
        "接頭原行数": weight(scope_prefix, repeat), "終端以後原行数": weight(scope_after, repeat)})
    valid_clock_positions = np.flatnonzero(finite)
    finite_clocks = now[valid_clock_positions]
    adjacent = finite[1:] & finite[:-1]
    counts["同一価格時計隣接原行数"] = int(np.sum(repeat[finite] - 1)) + int(np.count_nonzero(adjacent & (now[1:] == now[:-1])))
    counts["価格時計隣接後退回数"] = int(np.count_nonzero(adjacent & (now[1:] < now[:-1])))
    available = np.zeros(len(now), dtype=bool)
    if len(finite_clocks):
        selected = np.r_[True, finite_clocks[1:] >= np.maximum.accumulate(finite_clocks[:-1])]
        available[valid_clock_positions[selected]] = True
    counts["価格時計原行後退除外原行数"] = weight(finite & ~available, repeat)
    inside_indices = np.flatnonzero(available & scope_inside)
    first_inside = int(inside_indices[0]) if len(inside_indices) else None
    last_inside = int(inside_indices[-1]) if len(inside_indices) else None
    opening = columns["opening_time"]
    origins = Counter()
    for label, mask in (("当場前の始値時計", np.isfinite(opening) & (opening < start)),
                        ("当場内の始値時計", np.isfinite(opening) & (opening >= start) & (opening < finish)),
                        ("当場後の始値時計", np.isfinite(opening) & (opening >= finish)),
                        ("始値時計不明", ~np.isfinite(opening))):
        amount = weight(available & scope_inside & mask, repeat)
        if amount:
            origins[label] = amount
    quantity_clock = columns["volume_time"]
    clock_known = available & np.isfinite(quantity_clock)
    counts["数量時計欠測除外原行数"] = weight(available & ~np.isfinite(quantity_clock), repeat)
    for label, mask in (("数量時計先行原行数", quantity_clock > now), ("数量時計遅延原行数", quantity_clock < now),
                        ("数量時計同時計原行数", quantity_clock == now)):
        counts[label] = weight(clock_known & mask, repeat)
    causal = clock_known & (quantity_clock <= now)
    counts["場内だが数量時計は場開始前原行数"] = weight(causal & scope_inside & (quantity_clock < start), repeat)
    volume, value, native = columns["volume"], columns["trading_value"], columns["native_vwap"]
    paired = np.isfinite(volume) & (volume > 0) & np.isfinite(value) & (value >= 0) & np.isfinite(native) & (native > 0)
    consistent = np.zeros(len(now), dtype=bool)
    consistent[paired] = np.abs(native[paired] - value[paired] / volume[paired] / 1000) <= TOLERANCE
    counts["場内配信値観測参照候補原行数"] = weight(causal & scope_inside & consistent & (columns["last"] > 0)
        & (columns["contract"] >= 0) & (columns["exchange"] >= 0), repeat)
    cumulative_ok = np.isfinite(volume) & (volume >= 0) & np.isfinite(value) & (value >= 0)
    accepted = np.flatnonzero(causal & cumulative_ok)
    counts["累積量代金不正原行数"] = weight(causal & ~cumulative_ok, repeat)
    counts["採用累積原行数"] = int(np.sum(repeat[accepted], dtype=np.int64))
    transitions, epochs = {}, []
    if len(accepted):
        changes = np.zeros(len(accepted), dtype=bool)
        reasons_by_order = {}
        for order in range(1, len(accepted)):
            before, after = accepted[order - 1], accepted[order]
            reasons = []
            for field, label in (("volume", "累積数量減少"), ("trading_value", "累積代金減少"), ("volume_time", "数量時計後退")):
                if columns[field][after] < columns[field][before]:
                    reasons.append(label)
            if reasons:
                reasons_by_order[order] = reasons
        # 列ごとの既知値位置を先に抽出し、一時欠測を飛ばして既知不一致だけを区間境界にする。
        for field, label in (("contract", "限月変更"), ("exchange", "取引所変更"),
                              ("opening_time", "始値時計変更"), ("opening_price", "始値価格変更")):
            values = columns[field][accepted]
            present = values >= 0 if field in ("contract", "exchange") else np.isfinite(values) & (values > 0)
            known_orders = np.flatnonzero(present)
            differing = known_orders[1:][values[known_orders[1:]] != values[known_orders[:-1]]]
            for order in differing:
                reasons_by_order.setdefault(int(order), []).append(label)
        for order, reasons in sorted(reasons_by_order.items()):
            changes[order] = True
            transitions[int(accepted[order])] = reasons
        heads = np.r_[0, np.flatnonzero(changes)]
        tails = np.r_[heads[1:], len(accepted)]
        epochs = [accepted[head:tail] for head, tail in zip(heads, tails)]
    counts["累積区間変更状態数"] = len(transitions)
    for reasons in transitions.values():
        for reason in reasons:
            counts[reason + "状態数"] += 1
    prefix_indices = accepted[now[accepted] < start]
    prefix_last = int(prefix_indices[-1]) if len(prefix_indices) else None
    prefix_zeros = prefix_indices[(volume[prefix_indices] == 0) & (value[prefix_indices] == 0)]
    counts["接頭直接ゼロ観測原行数"] = int(np.sum(repeat[prefix_zeros], dtype=np.int64))
    inside_known = accepted[scope_inside[accepted] & (columns["contract"][accepted] >= 0)
        & (columns["exchange"][accepted] >= 0) & np.isfinite(opening[accepted]) & (opening[accepted] > 0)
        & (opening[accepted] <= now[accepted]) & np.isfinite(columns["opening_price"][accepted])
        & (columns["opening_price"][accepted] > 0)]
    rejected_prefix = prefix_indices[(now[prefix_indices] >= prefix_floor) & ~consistent[prefix_indices]
        & ~((volume[prefix_indices] == 0) & (value[prefix_indices] == 0))]
    counts["接頭内部不整合による基準更新見送り原行数"] = int(np.sum(repeat[rejected_prefix], dtype=np.int64))
    base_at_start, delta_rows, invalidations = None, [], []
    previous_epoch_base = None
    for epoch in epochs:
        first = int(epoch[0])
        if first in transitions and previous_epoch_base is not None:
            invalidations.append({"原行": int(columns["line"][first]), "価格時計": float(now[first]),
                "理由": transitions[first], "旧基準原行": int(columns["line"][previous_epoch_base])})
        prefix = epoch[(now[epoch] >= prefix_floor) & (now[epoch] < start)
            & (quantity_clock[epoch] >= prefix_floor) & (quantity_clock[epoch] < start)
            & np.isfinite(opening[epoch]) & (opening[epoch] > 0) & (opening[epoch] <= now[epoch])
            & (columns["opening_price"][epoch] > 0) & (columns["contract"][epoch] >= 0) & (columns["exchange"][epoch] >= 0)
            & (consistent[epoch] | ((volume[epoch] == 0) & (value[epoch] == 0)))]
        prefix_base = int(prefix[-1]) if len(prefix) else None
        # 各epochに独立な候補列を作る。現在までの開始零以外を後から過去へ配らない。
        identities_present = (columns["contract"][epoch] >= 0) & (columns["exchange"][epoch] >= 0)
        identities_present &= np.isfinite(opening[epoch]) & (opening[epoch] > 0) & np.isfinite(columns["opening_price"][epoch]) & (columns["opening_price"][epoch] > 0)
        zeros = epoch[(now[epoch] == start) & (volume[epoch] == 0) & (value[epoch] == 0)
            & identities_present & (opening[epoch] <= now[epoch])]
        base_candidates = sorted(([prefix_base] if prefix_base is not None else []) + [int(i) for i in zeros])
        local_base = prefix_base
        for index in epoch:
            index = int(index)
            if not start <= now[index] < finish:
                continue
            eligible_bases = [candidate for candidate in base_candidates if candidate <= index]
            candidate = eligible_bases[-1] if eligible_bases else None
            if base_at_start is None and candidate is not None:
                base_at_start = candidate
            if volume[index] == 0 and value[index] == 0:
                counts["場内直接ゼロ観測原行数"] += int(repeat[index])
                if index in zeros:
                    base_at_start = index
            if candidate is None:
                counts["場内差分基準不明原行数"] += int(repeat[index])
                local_base = None
                continue
            identity = (columns["contract"][index] >= 0 and columns["exchange"][index] >= 0
                and np.isfinite(opening[index]) and opening[index] > 0
                and np.isfinite(columns["opening_price"][index]) and columns["opening_price"][index] > 0)
            if not identity or opening[index] > now[index]:
                counts["場内差分基準一時未確認原行数"] += int(repeat[index])
                local_base = candidate
                continue
            local_base = candidate
            delta_volume, delta_value = volume[index] - volume[candidate], value[index] - value[candidate]
            if delta_volume <= 0 or delta_value < 0:
                counts["場内差分量非正原行数"] += int(repeat[index])
                continue
            delta = {**snapshot(columns, index), "基準原行": int(columns["line"][candidate]), "基準価格時計": float(now[candidate]),
                "基準数量時計": float(quantity_clock[candidate]), "基準累積数量": float(volume[candidate]),
                "基準累積代金": float(value[candidate]), "差分数量": float(delta_volume), "差分代金": float(delta_value),
                "差分VWAP": float(delta_value / delta_volume / 1000)}
            delta_rows.append(delta)
            counts["差分計算可能原行数"] += int(repeat[index])
            counts["差分価格正原行数"] += int(repeat[index]) if delta_value > 0 else 0
            counts["差分価格ゼロ原行数"] += int(repeat[index]) if delta_value == 0 else 0
            if consistent[index] and quantity_clock[index] >= start:
                counts["差分計算可能かつ内部整合かつ場内数量時計原行数"] += int(repeat[index])
                if columns["last"][index] > 0 and delta_value > 0:
                    counts["差分計算可能かつ場内観測参照候補原行数"] += int(repeat[index])
        previous_epoch_base = local_base
    examples = [{"種類": "累積区間変更", "理由": reasons, **snapshot(columns, index)}
                for index, reasons in list(transitions.items())[:6]]
    return {"件数": dict(counts), "起算": {"最初場内": snapshot(columns, first_inside),
        "最後場内": snapshot(columns, last_inside), "接頭最終": snapshot(columns, prefix_last),
        "最初場内既知起算": snapshot(columns, int(inside_known[0]) if len(inside_known) else None),
        "接頭直接零の最初": snapshot(columns, int(prefix_zeros[0]) if len(prefix_zeros) else None),
        "始値起算分類": dict(origins),
        "場内限月番号": sorted(set(int(v) for v in columns["contract"][inside_indices])),
        "場内取引所番号": sorted(set(int(v) for v in columns["exchange"][inside_indices])),
        "既知接頭基準": snapshot(columns, base_at_start),
        "差分計算可能原行数": counts["差分計算可能原行数"],
        "差分計算可能かつ内部整合かつ場内数量時計原行数": counts["差分計算可能かつ内部整合かつ場内数量時計原行数"],
        "差分計算可能かつ場内観測参照候補原行数": counts["差分計算可能かつ場内観測参照候補原行数"],
        "最初差分例": delta_rows[0] if delta_rows else None, "最後差分例": delta_rows[-1] if delta_rows else None,
        "基準無効化数": len(invalidations), "基準無効化例": invalidations[:6],
        "直接ゼロ観測原行数": counts["場内直接ゼロ観測原行数"], "推定ゼロを差分基準へ補完": False},
        "区間変更例": examples}


# ----------------------------------------
# 主コアを読み込まず、保存された全数値統計・起算結果へ独立結果を対応させる。

class Audit:
    """再帰比較と有限値の小さい誤差を記録する。"""

    def __init__(self) -> None:
        """空の比較先を作る。

        引数: なし。
        返り値: None。
        """
        self.count, self.mismatches, self.errors = 0, 0, []

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """辞書・列・数値を比較し、不一致の先頭100項目を保持する。

        引数: name (str) は項目、actual/expected (Any) は保存/独立値。
        返り値: None。数式の誤差分位は絶対1e-10、個数とboolは同値で検査する。
        """
        if isinstance(actual, dict) and isinstance(expected, dict):
            self.check(name + ":キー", sorted(actual), sorted(expected))
            for key in actual.keys() & expected.keys():
                self.check(name + ":" + key, actual[key], expected[key])
            return
        if isinstance(actual, list) and isinstance(expected, list):
            self.check(name + ":長さ", len(actual), len(expected))
            for i, (left, right) in enumerate(zip(actual, expected)):
                self.check(name + f":{i}", left, right)
            return
        self.count += 1
        if isinstance(expected, bool):
            same = isinstance(actual, bool) and actual == expected
        elif isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
            same = actual == expected if isinstance(actual, int) and isinstance(expected, int) else math.isclose(actual, expected, rel_tol=0, abs_tol=1e-10)
        else:
            same = actual == expected
        if not same:
            self.mismatches += 1
            if len(self.errors) < 100:
                self.errors.append({"項目": name, "保存": actual, "独立": expected})


def independently_audit(columns: dict, entry: dict) -> dict:
    """全小列の正規化統計と式・epoch起算を一つの独立結果へまとめる。

    引数: columns (dict) は12列、entry (dict) は対応表と場名を持つ抽出台帳。
    返り値: dict は主保存値と比較できる数値部分。説明文の文字列一致は求めない。
    """
    start, finish, _ = bounds(entry["session"])
    basic(columns, entry["contract_codes"], start, finish)
    exchange = columns["exchange"]
    if np.any(exchange < -1) or np.any(exchange >= len(entry["exchange_values"])):
        raise ValueError("取引所対応表番号が不正")
    for key, values in columns.items():
        expected_dtype = np.dtype(np.int64 if key in ("line", "repeat") else np.int16 if key in ("contract", "exchange") else np.float64)
        if values.dtype != expected_dtype:
            raise ValueError("列dtypeが不一致:" + key)
    arithmetic, result = formula(columns), epoch_analysis(columns, entry["session"])
    result["件数"].update({"内部比較原行数": arithmetic["比較可能原行数"], "内部不整合原行数": arithmetic["不整合原行数"],
                            "内部比率計算非有限原行数": arithmetic["比率計算非有限原行数"]})
    field_counts, clock_counts = {}, {}
    repeat = columns["repeat"]
    for field in NUMERIC_FIELDS:
        values = columns[field]
        counts = {"欠測または非有限": weight(~np.isfinite(values), repeat),
            "負": weight(np.isfinite(values) & (values < 0), repeat),
            "ゼロ": weight(np.isfinite(values) & (values == 0), repeat),
            "正": weight(np.isfinite(values) & (values > 0), repeat)}
        field_counts[field] = {k: v for k, v in counts.items() if v}
    for field in ("now", "volume_time", "opening_time"):
        counts = {"有限": weight(np.isfinite(columns[field]), repeat),
                  "欠測または非有限": weight(~np.isfinite(columns[field]), repeat)}
        clock_counts[field] = {k: v for k, v in counts.items() if v}
    result["数値列"], result["時計列"] = field_counts, clock_counts
    examples = {}
    for label, at in (("最初不整合", arithmetic["最初不整合state"]), ("最大差例", arithmetic["最大差state"])):
        row = snapshot(columns, at)
        if row is not None:
            calculated = float(columns["trading_value"][at] / columns["volume"][at] / 1000)
            row.update(代金数量比VWAP=calculated, 絶対差pt=abs(float(columns["native_vwap"][at]) - calculated))
        examples[label] = row
    result["内部整合"] = {"比較原行数": arithmetic["比較可能原行数"], "不整合原行数": arithmetic["不整合原行数"],
        "最大絶対差pt": arithmetic["最大絶対差pt"],
        "分位点": dict(zip(("0.5", "0.95", "0.99", "1.0"),
            [arithmetic["絶対差分位"][key] for key in ("p50", "p95", "p99", "p100")])),
        **examples, "許容pt": TOLERANCE}
    return result


def compare_summary(audit: Audit, session: str, saved: dict, expected: dict) -> None:
    """省略され得る零counterと、必須の起算/式の値を分けて照合する。

    引数: audit (Audit) は比較先、session (str) は場、saved/expected (dict) は保存/独立監査。
    返り値: None。説明文だけを検査対象外にする。
    """
    for key in saved["件数"].keys() | expected["件数"].keys():
        audit.check(session + ":件数:" + key, saved["件数"].get(key, 0), expected["件数"].get(key, 0))
    for section in ("数値列", "時計列", "区間変更例"):
        audit.check(session + ":" + section, saved[section], expected[section])
    for section in ("内部整合", "起算"):
        for key, value in expected[section].items():
            audit.check(session + ":" + section + ":" + key, saved[section].get(key), value)


def select_samples(entries: list[dict], summaries: dict[str, dict]) -> dict[str, dict[int, list[str]]]:
    """全場first/first-in-sessionと、全体最大差/最初不整合の代表を事前規則で選ぶ。

    引数: entries (list[dict]) は抽出台帳、summaries (dict[str,dict]) は全独立結果。
    返り値: dict[str,dict[int,list[str]]] は場別の物理行と選定理由。各場最大行を全65で再走査しない。
    """
    selections = {e["session"]: {1: ["原板最初の物理行"]} for e in entries}
    largest, first_bad = None, None
    for entry in entries:
        session, own = entry["session"], summaries[entry["session"]]
        first = own["起算"]["最初場内"]
        if first is not None:
            selections[session].setdefault(first["line"], []).append("最初の非後退場内状態")
        maximum = own["内部整合"]["最大差例"]
        if maximum is not None and (largest is None or maximum["絶対差pt"] > largest[1]["絶対差pt"]):
            largest = session, maximum
        bad = own["内部整合"]["最初不整合"]
        if bad is not None and first_bad is None:
            first_bad = session, bad
    for label, selected in (("全65場の最大絶対差代表", largest), ("場順で最初の内部不整合代表", first_bad)):
        if selected is not None:
            session, row = selected
            selections[session].setdefault(row["line"], []).append(label)
    return selections


def direct_samples(entry: dict, columns: dict, selected: dict[int, list[str]], source_root: Path,
                   audit: Audit) -> dict:
    """選定原行までだけ原板を再読し、主抽出を呼ばず12列を直接照合する。

    引数: entry (dict) は出典/対応表、columns (dict) は小列、selected (dict[int,list[str]]) は標本行/理由、
    source_root (Path) は原板根、audit (Audit) は比較先。
    返り値: dict は原板例と読取範囲。全原板全行の変換正当性を再証明したとしない。
    """
    source = source_root / entry["source_path"]
    before = source.stat()
    if (before.st_size, before.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
        raise ValueError("固定原板statが変更")
    opener, results, scanned, byte_count = gzip.open if source.suffix.lower() == ".gz" else open, [], 0, 0
    maximum = max(selected) if selected else 0
    with opener(source, "rb") as stream:
        for scanned, raw in enumerate(stream, 1):
            byte_count += len(raw)
            if scanned in selected:
                value = json.loads(raw)
                independent = original_record(value, scanned)
                at = int(np.searchsorted(columns["line"], scanned, side="right")) - 1
                if at < 0 or scanned >= int(columns["line"][at] + columns["repeat"][at]):
                    raise ValueError("標本原行が小列の代表範囲に存在しない")
                stored = snapshot(columns, at)
                stored.pop("repeat")
                stored["line"] = scanned
                stored["contract"] = entry["contract_codes"][stored["contract"]] if stored["contract"] >= 0 else None
                stored["exchange"] = entry["exchange_values"][stored["exchange"]] if stored["exchange"] >= 0 else {"Exchange": None, "ExchangeName": None}
                finite_independent = {k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in independent.items()}
                audit.check(entry["session"] + f":原板抜取{scanned}", stored, finite_independent)
                # 金額比は標本ではDecimalでも計算し、float許容とは区別した参考値を残す。
                ratio_decimal = None
                if stored["volume"] is not None and stored["volume"] > 0 and stored["trading_value"] is not None:
                    ratio_decimal = str(Decimal(str(value["TradingValue"])) / Decimal(str(value["TradingVolume"])) / 1000)
                results.append({"原板物理行": scanned, "選定理由": selected[scanned], "独立原板値": finite_independent,
                                "代金数量比Decimal参考": ratio_decimal})
            if scanned >= maximum:
                break
    after = source.stat()
    audit.check(entry["session"] + ":原板読取中stat不変", (before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))
    audit.check(entry["session"] + ":原板標本取得数", len(results), len(selected))
    return {"場": entry["session"], "原板パス": entry["source_path"], "最終読取原行": scanned,
            "読取展開バイト": byte_count, "例": results}


def run(study: Path, work: Path) -> dict:
    """正式抽出後だけ小列全65場を独立再計算し、限定原板標本を直接照合する。

    引数: study/work (Path) は正式監査/作業先。
    返り値: dict は明示合否・範囲・指紋。損益や売買入口を計算しない。
    """
    for name in ("結果.json", "固定.json", "条件.json"):
        if not (study / name).is_file():
            raise ValueError("正式抽出の完了資料がないため実行しません")
    old_path = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
    manifest_path = work / "抽出台帳.json"
    old, manifest, formal = read(old_path), read(manifest_path), read(study / "結果.json")
    entries, originals, audit = manifest["entries"], {e["session"]: e for e in old["entries"]}, Audit()
    audit.check("固定入力65場", len(entries), 65)
    audit.check("入力台帳SHA", manifest["入力台帳SHA256"], sha(old_path))
    independently, caches, count_total = {}, [], Counter()
    for entry in entries:
        session, cache = entry["session"], ROOT / entry["cache_path"]
        audit.check(session + ":NPZ内容SHA", sha(cache), entry["sha256_cache"])
        audit.check(session + ":NPZサイズ", cache.stat().st_size, entry["cache_size"])
        for field in ("source_path", "source_size", "source_mtime_ns", "sha256_uncompressed", "raw_lines", "decoded_rows"):
            audit.check(session + ":旧固定入力:" + field, entry[field], originals[session][field])
        with np.load(cache, allow_pickle=False) as archive:
            columns = {key: archive[key] for key in archive.files}
        own = independently_audit(columns, entry)
        compare_summary(audit, session, entry["監査"], own)
        audit.check(session + ":圧縮前状態数", len(columns["line"]), entry["events"])
        audit.check(session + ":代表原行数とJSON件数", int(np.sum(columns["repeat"], dtype=np.int64)), entry["decoded_rows"])
        audit.check(session + ":連続同一省略原行数", entry["原行品質"].get("連続完全同一省略原行数", 0), entry["decoded_rows"] - entry["events"])
        independently[session] = own
        count_total.update(own["件数"])
        caches.append({"場": session, "パス": entry["cache_path"], "SHA256": entry["sha256_cache"]})
        print(json.dumps({"場": session, "独立確認": "全小列・比率・時計・起算epoch", "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    for key in formal["件数"].keys() | count_total.keys():
        audit.check("全場件数:" + key, formal["件数"].get(key, 0), count_total.get(key, 0))
    selections = select_samples(entries, independently)
    samples = []
    for entry in entries:
        with np.load(ROOT / entry["cache_path"], allow_pickle=False) as archive:
            columns = {key: archive[key] for key in archive.files}
        samples.append(direct_samples(entry, columns, selections[entry["session"]], Path(old["source_root"]), audit))
    output = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": len(entries), "保存小列状態数": sum(e["events"] for e in entries),
        "原行重み合計": sum(e["decoded_rows"] for e in entries), "独立件数合計": dict(count_total),
        "原板抜取場数": len(samples), "原板抜取例数": sum(len(s["例"]) for s in samples),
        "原板抜取の読取展開バイト": sum(s["読取展開バイト"] for s in samples), "原板抜取": samples,
        "場別独立再計算": [{"場": session, **value} for session, value in independently.items()],
        "コードSHA256": sha(Path(__file__)), "抽出台帳SHA256": sha(manifest_path),
        "入力台帳SHA256": sha(old_path), "正式結果SHA256": sha(study / "結果.json"),
        "主抽出コードSHA256": sha(Path(__file__).with_name("抽出監査.py")), "小列cache": caches,
        "損益と入口": "未検証・対象外。新約定・架空Viewer取引は生成しない。",
        "検証範囲": "主抽出コアをimportせず、全12列NPZのdtype/物理行/repeatと全原行重みの値・時計・内部比率/分位を別計算。採用累積を既知identity不一致/減少/時計後退でepochへ分け、epochごとの当時の整合prefix/直接零候補から差分可否と参照候補交差を再計算。原板は全65のfirst/最初場内と全体最大差/最初不整合の限定例を直接parseして対応確認。",
        "限界": "展開SHAは原入力の同一性であり、抽出変換全行の独立証明ではない。原板全3.52GBを別抽出実装で全行再比較した監査ではなく、小列全件数式/時点と限定原板例を別々に検算した。VWAP/売買代金固有時計と受信時計は未収録で、数量時計<=価格時計は同時生成・受信済み・公表時刻を保証しない。既知prefix差分も数学的比率で、全約定独立復元・使用可能認定ではない。未観測resetや一時欠測中の連続性まで保証しない。"}
    text = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    (work / "独立確認.json").write_text(text, encoding="utf-8")
    (study / "独立確認.json").write_text(text, encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数", "入力場数", "原板抜取例数")}, ensure_ascii=False))
    if audit.errors:
        print(json.dumps(audit.errors[:5], ensure_ascii=False))
    return output


def main() -> None:
    """正式抽出完了通知後の明示指定だけで独立監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不許可時は実データを開かない。
    """
    parser = argparse.ArgumentParser(description="配信元VWAP小列全件と原板標本の独立確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("正式抽出完了通知後に --実行許可 を指定してください")
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

