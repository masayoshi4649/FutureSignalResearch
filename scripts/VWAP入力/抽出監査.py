"""配信VWAP・累積売買代金を原板から小列へ抽出し、損益なしで入力の意味を監査する。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any, Iterable, Iterator, NamedTuple

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00017_配信元VWAPと売買代金の入力監査"
WORK = ROOT/"work/VWAP入力/00017"
INPUT = ROOT/"study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
JST = timezone(timedelta(hours=9))
sys.path.insert(0, str(ROOT/"work/pythonlibs"))
try:
    import orjson
except ImportError:
    orjson = None

FIELDS = ("now", "line", "last", "volume", "volume_time", "native_vwap", "trading_value",
          "opening_price", "opening_time", "contract", "exchange", "repeat")
NUMERIC_FIELDS = ("last", "volume", "native_vwap", "trading_value", "opening_price")
RAW_FIELDS = {"last": "CurrentPrice", "volume": "TradingVolume", "native_vwap": "VWAP",
              "trading_value": "TradingValue", "opening_price": "OpeningPrice"}
DTYPES = {k: np.int64 if k in ("line", "repeat") else np.int16 if k in ("contract", "exchange")
          else np.float64 for k in FIELDS}


class Event(NamedTuple):
    """一つの配信状態。repeatは連続完全同一状態の原行件数、lineはその先頭物理行。"""

    now: float
    line: int
    last: float
    volume: float
    volume_time: float
    native_vwap: float
    trading_value: float
    opening_price: float
    opening_time: float
    contract: int
    exchange: int
    repeat: int = 1


def finite_number(value: Any) -> float:
    """有限の数値だけを保持し、欠測・非数値・非有限をNaNへ正規化する。

    引数: value (Any) はJSON値。
    返り値: float は有限数またはNaN。負値と0は監査のため保持する。
    """
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else math.nan


def clock_seconds(value: Any, cache: dict) -> float:
    """時差付きISO時計をUnix秒へ変換する。

    引数: value (Any) は時計、cache (dict) は同じ文字列の変換再利用先。
    返り値: float はUnix秒。不正・欠測・時差なしはNaN。
    """
    if not isinstance(value, str) or not value:
        return math.nan
    if value not in cache:
        try:
            parsed = datetime.fromisoformat(value)
            cache[value] = parsed.timestamp() if parsed.utcoffset() is not None else math.nan
        except (ValueError, OverflowError):
            cache[value] = math.nan
    return cache[value]


def table_index(value: Any, values: list) -> int:
    """原文字列や取引所の値を小さな対応表の番号へ変換する。

    引数: value (Any) は保存値、values (list) は対応表。
    返り値: int は番号。欠測は−1。表を必要時に追加する。
    """
    if value is None:
        return -1
    if value not in values:
        if len(values) >= 32767:
            raise ValueError("識別対応表がint16の範囲を超過")
        values.append(value)
    return values.index(value)


def parse_record(row: dict, line: int, clock_cache: dict, codes: list,
                 exchanges: list) -> Event:
    """原板の対象列を時計と欠測を変造せず抽出する。

    引数: row (dict) は原板、line (int) は物理行、clock_cache (dict) は時計変換表、
    codes/exchanges (list) は限月文字列/取引所原値の対応表。
    返り値: Event は1原行の抽出状態。VWAP固有時計や受信時計は追加しない。
    """
    code = str(row["Symbol"]) if row.get("Symbol") is not None else None
    exchange = {"Exchange": row.get("Exchange"), "ExchangeName": row.get("ExchangeName")}
    if all(v is None for v in exchange.values()):
        exchange = None
    return Event(clock_seconds(row.get("CurrentPriceTime"), clock_cache), line,
                 finite_number(row.get("CurrentPrice")), finite_number(row.get("TradingVolume")),
                 clock_seconds(row.get("TradingVolumeTime"), clock_cache),
                 finite_number(row.get("VWAP")), finite_number(row.get("TradingValue")),
                 finite_number(row.get("OpeningPrice")), clock_seconds(row.get("OpeningPriceTime"), clock_cache),
                 table_index(code, codes), table_index(exchange, exchanges))


def state_key(event: Event) -> tuple:
    """欠測同士を等しいと扱い、全抽出状態の連続同一性を比較する。

    引数: event (Event) は状態。
    返り値: tuple はline/repeat以外の全状態。VWAP/代金だけの更新も区別する。
    """
    return tuple(None if isinstance(v, float) and math.isnan(v) else v
                 for k, v in zip(FIELDS, event) if k not in ("line", "repeat"))


def as_arrays(events: Iterable[Event]) -> dict[str, np.ndarray]:
    """同じschemaの抽出状態を型付き列へ変換する。

    引数: events (Iterable[Event]) は原順状態。
    返り値: dict[str,np.ndarray] は12列。ここでは重複省略や時計選別をしない。
    """
    columns = {k: [] for k in FIELDS}
    for event in events:
        for key, value in zip(FIELDS, event):
            columns[key].append(value)
    return {k: np.asarray(v, dtype=DTYPES[k]) for k, v in columns.items()}


def iter_arrays(arrays: dict) -> Iterator[Event]:
    """列の型・長さと原順を検査しPython標準型の状態を返す。

    引数: arrays (dict) は12列。
    返り値: Iterator[Event] は原順状態。欠測・場外状態も保持する。
    """
    if set(arrays) != set(FIELDS) or len({len(a) for a in arrays.values()}) != 1:
        raise ValueError("抽出列または列長が不一致")
    previous_line_end = 0
    for values in zip(*(arrays[k] for k in FIELDS)):
        event = Event(*(int(v) if k in ("line", "contract", "exchange", "repeat") else float(v)
                        for k, v in zip(FIELDS, values)))
        if event.line <= previous_line_end or event.repeat < 1:
            raise ValueError("物理行の後退/重複/repeat区間重複またはrepeat不正")
        previous_line_end = event.line+event.repeat-1
        yield event


def read_events(path: Path | str) -> Iterator[Event]:
    """NPZを読んで全状態を原順に返す。

    引数: path (Path|str) は補助キャッシュ。
    返り値: Iterator[Event] は12属性の状態。旧8列cacheとは別の形式。
    """
    with np.load(path, allow_pickle=False) as archive:
        yield from iter_arrays({k: archive[k] for k in archive.files})


def sha(path: Path) -> str:
    """保存内容を小さな塊で指紋化する。

    引数: path (Path) はファイル。
    返り値: str はSHA256。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024*1024):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    """UTF-8のJSONを読む。

    引数: path (Path) は入力。
    返り値: Any はJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    """非有限を許さないJSONを一時ファイルから保存する。

    引数: path (Path) は保存先、value (Any) はJSON値。
    返り値: None。既存原板を変更しない。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(path)


def bounds(session: str) -> tuple[float, float, float]:
    """場内半開範囲と前セッションの通常終了後の基準候補下限を返す。

    引数: session (str) は開始日_Day/Night。
    返り値: tuple[float,float,float] は開始/ザラバ終了/閉場後基準下限のUnix秒。
    """
    date = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        return ((date+timedelta(hours=8, minutes=45)).timestamp(),
                (date+timedelta(hours=15, minutes=40)).timestamp(), (date+timedelta(hours=6)).timestamp())
    if session.endswith("_Night"):
        return ((date+timedelta(hours=17)).timestamp(),
                (date+timedelta(days=1, hours=5, minutes=55)).timestamp(),
                (date+timedelta(hours=15, minutes=45)).timestamp())
    raise ValueError("Day/Night以外の場名")


def snapshot(event: Event) -> dict:
    """具体例をJSONの有限値/nullへ写像する。

    引数: event (Event) は抽出状態。
    返り値: dict は原行を含む全12列。NaNをnullとする。
    """
    return {k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in zip(FIELDS, event)}


def weighted_quantiles(values: list[float], weights: list[int]) -> dict:
    """原行repeatを展開せず線形補間の分位点を計算する。

    引数: values (list[float]) は有限絶対差、weights (list[int]) は原行重み。
    返り値: dict は50/95/99/100百分位。比較行なしはnull。
    """
    if not values:
        return {str(p): None for p in (0.5, 0.95, 0.99, 1.0)}
    order = np.argsort(np.asarray(values), kind="stable")
    x, w = np.asarray(values)[order], np.asarray(weights, dtype=np.int64)[order]
    cumulative, total = np.cumsum(w), int(sum(weights))
    result = {}
    for p in (0.5, 0.95, 0.99, 1.0):
        position = (total-1)*p
        low, high = math.floor(position), math.ceil(position)
        a, b = x[np.searchsorted(cumulative, low, side="right")], x[np.searchsorted(cumulative, high, side="right")]
        result[str(p)] = float(a+(b-a)*(position-low))
    return result


# ----------------------------------------
# 時計利用可否・内部比率・累積区間・当場の既知基準を別々に判定する。

def audit_arrays(arrays: dict, session: str, codes: list, config: dict) -> dict:
    """全抽出状態から原行重みの内部整合と起算・差分可否を集計する。

    引数: arrays (dict) は12列、session (str) は場、codes (list) は限月対応表、config (dict) は固定条件。
    返り値: dict は件数/内部整合/起算/具体例。損益や売買シグナルは生成しない。
    """
    factor = config["ラージ換算係数"]
    tolerance = config["絶対許容pt"]+config["浮動余裕pt"]
    if (factor, config["絶対許容pt"], config["浮動余裕pt"]) != (1000, .0001, .00000001):
        raise ValueError("換算1000・許容0.0001+0.00000001を変更しない")
    start, finish, prefix_floor = bounds(session)
    counts, errors, weights = Counter(), [], []
    previous_adjacent, maximum_key, previous_cumulative = None, None, None
    prefix_last = first_inside = last_inside = first_mismatch = largest = None
    first_known_origin = first_prefix_zero = None
    base = base_at_start = None
    first_delta = last_delta = None
    origin_kinds, invalidations, examples = Counter(), [], []
    field_counts = {k: Counter() for k in NUMERIC_FIELDS}
    clock_counts = {k: Counter() for k in ("now", "volume_time", "opening_time")}
    known_identity = {}
    accepted_codes, accepted_exchanges = set(), set()
    for event in iter_arrays(arrays):
        weight, now = event.repeat, event.now
        counts["保存状態数"] += 1
        counts["原行重み合計"] += weight
        if event.contract >= len(codes) or event.contract < -1:
            raise ValueError("限月対応表番号が不正")
        for field in NUMERIC_FIELDS:
            value = getattr(event, field)
            kind = "欠測または非有限" if not math.isfinite(value) else "負" if value < 0 else "ゼロ" if value == 0 else "正"
            field_counts[field][kind] += weight
        for field in clock_counts:
            clock_counts[field]["有限" if math.isfinite(getattr(event, field)) else "欠測または非有限"] += weight
        # ----------------------------------------
        # 内部比率は時計や場内可否と独立して、有限正量/VWAPと非負代金だけで比較する。
        comparable = all(math.isfinite(v) for v in (event.volume, event.native_vwap, event.trading_value)) and event.volume > 0 and event.native_vwap > 0 and event.trading_value >= 0
        consistent = False
        if comparable:
            calculated = event.trading_value/event.volume/factor
            error = abs(event.native_vwap-calculated)
            if not math.isfinite(error):
                counts["内部比率計算非有限原行数"] += weight
                comparable = False
            consistent = comparable and error <= tolerance
        if comparable:
            counts["内部比較原行数"] += weight
            counts["内部不整合原行数"] += weight if not consistent else 0
            errors.append(error)
            weights.append(weight)
            example = {**snapshot(event), "代金数量比VWAP": calculated, "絶対差pt": error}
            if first_mismatch is None and not consistent:
                first_mismatch = example
            if largest is None or error > largest["絶対差pt"]:
                largest = example
        if not math.isfinite(now):
            counts["価格時計欠測除外原行数"] += weight
            previous_adjacent = None
            continue
        scope = "場内" if start <= now < finish else "接頭" if now < start else "終端以後"
        counts[scope+"原行数"] += weight
        counts["同一価格時計隣接原行数"] += weight-1
        if previous_adjacent is not None:
            counts["同一価格時計隣接原行数"] += int(now == previous_adjacent)
            counts["価格時計隣接後退回数"] += int(now < previous_adjacent)
        previous_adjacent = now
        key = now, event.line
        if maximum_key is not None and key < maximum_key:
            counts["価格時計原行後退除外原行数"] += weight
            continue
        maximum_key = key
        if scope == "場内":
            first_inside = event if first_inside is None else first_inside
            last_inside = event
            accepted_codes.add(event.contract)
            accepted_exchanges.add(event.exchange)
            if math.isfinite(event.opening_time):
                kind = "当場前の始値時計" if event.opening_time < start else "当場内の始値時計" if event.opening_time < finish else "当場後の始値時計"
            else:
                kind = "始値時計不明"
            origin_kinds[kind] += weight
        if not math.isfinite(event.volume_time):
            counts["数量時計欠測除外原行数"] += weight
            continue
        offset = event.volume_time-now
        counts["数量時計先行原行数" if offset > 0 else "数量時計遅延原行数" if offset < 0 else "数量時計同時計原行数"] += weight
        if offset > 0:
            continue
        if scope == "場内" and event.volume_time < start:
            counts["場内だが数量時計は場開始前原行数"] += weight
        cumulative_ok = all(math.isfinite(v) and v >= 0 for v in (event.volume, event.trading_value))
        if scope == "場内" and consistent and event.last > 0 and event.contract >= 0 and event.exchange >= 0:
            counts["場内配信値観測参照候補原行数"] += weight
        if not cumulative_ok:
            counts["累積量代金不正原行数"] += weight
            continue
        counts["採用累積原行数"] += weight
        # ----------------------------------------
        # 採用累積の区間を切り、基準以後のresetを後の値で修正しない。
        reasons = []
        if previous_cumulative is not None:
            previous = previous_cumulative
            for field, label in (("volume", "累積数量減少"), ("trading_value", "累積代金減少"), ("volume_time", "数量時計後退")):
                if getattr(event, field) < getattr(previous, field):
                    reasons.append(label)
        identity_present = {}
        for field, label in (("contract", "限月変更"), ("exchange", "取引所変更"),
                              ("opening_time", "始値時計変更"), ("opening_price", "始値価格変更")):
            current = getattr(event, field)
            present = current >= 0 if field in ("contract", "exchange") else math.isfinite(current) and current > 0
            identity_present[field] = present
            if not present:
                continue
            if field in known_identity and known_identity[field] != current:
                reasons.append(label)
            known_identity[field] = current
        if scope == "場内" and first_known_origin is None and all(identity_present.values()) and event.opening_time <= now:
            first_known_origin = event
        if reasons:
            counts["累積区間変更状態数"] += 1
            for reason in reasons:
                counts[reason+"状態数"] += 1
            if base is not None:
                invalidations.append({"原行": event.line, "価格時計": now, "理由": reasons, "旧基準原行": base.line})
            base = None
            if len(examples) < 6:
                examples.append({"種類": "累積区間変更", "理由": reasons, **snapshot(event)})
        previous_cumulative = event
        if scope == "接頭":
            prefix_last = event
            if event.volume == 0 and event.trading_value == 0:
                counts["接頭直接ゼロ観測原行数"] += weight
                first_prefix_zero = event if first_prefix_zero is None else first_prefix_zero
            # 前場の通常取引が終了した後の既知累積だけを当場開始前の基準にする。
            if prefix_floor <= now < start and prefix_floor <= event.volume_time < start and all(identity_present.values()) and event.opening_time <= now and (consistent or event.volume == event.trading_value == 0):
                base = event
            elif prefix_floor <= now < start and not consistent and not event.volume == event.trading_value == 0:
                counts["接頭内部不整合による基準更新見送り原行数"] += weight
            continue
        if scope != "場内":
            continue
        if base_at_start is None and base is not None:
            base_at_start = base
        if event.volume == 0 and event.trading_value == 0:
            counts["場内直接ゼロ観測原行数"] += weight
            # 開始秒ちょうどの直接ゼロ以外は、場全体の基準へ補わない。
            if now == start and event.volume_time <= start and all(identity_present.values()) and event.opening_time <= now:
                base = event
                base_at_start = event
        if base is None:
            counts["場内差分基準不明原行数"] += weight
            continue
        known_mismatch = any(identity_present[field] and getattr(base, field) != getattr(event, field)
                             for field in identity_present)
        if known_mismatch:
            base = None
            counts["場内差分基準不明原行数"] += weight
            continue
        if not all(identity_present.values()) or event.opening_time > now:
            counts["場内差分基準一時未確認原行数"] += weight
            continue
        delta_volume, delta_value = event.volume-base.volume, event.trading_value-base.trading_value
        if delta_volume <= 0 or delta_value < 0:
            counts["場内差分量非正原行数"] += weight
            continue
        difference = {**snapshot(event), "基準原行": base.line, "基準価格時計": base.now,
                      "基準数量時計": base.volume_time, "基準累積数量": base.volume,
                      "基準累積代金": base.trading_value, "差分数量": delta_volume,
                      "差分代金": delta_value, "差分VWAP": delta_value/delta_volume/factor}
        counts["差分計算可能原行数"] += weight
        counts["差分価格正原行数"] += weight if delta_value > 0 else 0
        counts["差分価格ゼロ原行数"] += weight if delta_value == 0 else 0
        # 計算可能性と、当場数量時計・整合配信値の観測参照候補を交差して別掲する。
        counts["差分計算可能かつ内部整合かつ場内数量時計原行数"] += weight if consistent and start <= event.volume_time <= now else 0
        counts["差分計算可能かつ場内観測参照候補原行数"] += weight if consistent and start <= event.volume_time <= now and event.last > 0 and delta_value > 0 else 0
        first_delta = difference if first_delta is None else first_delta
        last_delta = difference
    return {"件数": dict(counts), "数値列": {k: dict(v) for k, v in field_counts.items()},
            "時計列": {k: dict(v) for k, v in clock_counts.items()},
            "内部整合": {"比較原行数": counts["内部比較原行数"], "不整合原行数": counts["内部不整合原行数"],
                        "最大絶対差pt": largest["絶対差pt"] if largest else None,
                        "分位点": weighted_quantiles(errors, weights), "最初不整合": first_mismatch, "最大差例": largest,
                        "許容pt": tolerance, "分母": "連続同一状態のrepeatで原行を加重。時計・場内採否とは独立"},
            "起算": {"最初場内": snapshot(first_inside) if first_inside else None,
                     "最後場内": snapshot(last_inside) if last_inside else None,
                     "接頭最終": snapshot(prefix_last) if prefix_last else None,
                     "最初場内既知起算": snapshot(first_known_origin) if first_known_origin else None,
                     "接頭直接零の最初": snapshot(first_prefix_zero) if first_prefix_zero else None,
                     "始値起算分類": dict(origin_kinds),
                     "場内限月番号": sorted(accepted_codes), "場内取引所番号": sorted(accepted_exchanges),
                     "既知接頭基準": snapshot(base_at_start) if base_at_start else None,
                     "差分計算可能原行数": counts["差分計算可能原行数"],
                     "差分計算可能かつ内部整合かつ場内数量時計原行数": counts["差分計算可能かつ内部整合かつ場内数量時計原行数"],
                     "差分計算可能かつ場内観測参照候補原行数": counts["差分計算可能かつ場内観測参照候補原行数"],
                     "最初差分例": first_delta, "最後差分例": last_delta,
                     "基準無効化数": len(invalidations), "基準無効化例": invalidations[:6],
                     "直接ゼロ観測原行数": counts["場内直接ゼロ観測原行数"],
                     "推定ゼロを差分基準へ補完": False,
                     "基準規則": "当日Day06:00/Night15:45以後かつ場開始前の価格/数量時計・正始値/有限始値時計・限月/取引所既知で、内部比率整合する非ゼロ累積または直接零量零代金だけ。接頭不整合行は基準更新に使わない。以後の採用累積減少/数量時計後退/既知始値/限月/取引所不一致で永久破棄。一時欠測は基準を不変保持し当該行を参照不可、同じ既知identityを再確認した後の行だけ再開。開始秒ちょうどの直接ゼロも同一identity確認可能時だけ別に採用。古い接頭や始値のみのゼロ推定はunknown"},
            "区間変更例": examples,
            "限界": "内部比率一致は全約定からの独立VWAP復元ではない。VWAP/売買代金固有時計と受信時計は未収録。数量時計<=価格時計は必要条件だけで、同時生成/受信済み/公表時刻を保証しない。数学的差分計算可能は使用可能認定でなく、0差分価格も正価格候補と分ける。identity一時欠測から再確認する間の未観測resetまで否定する保証はない。"}


# ----------------------------------------
# 原板は一回stream読取し、既存展開SHAと一致した小列だけを公開する。

def extract_one(entry: dict, source_root: Path, target: Path, config: dict) -> dict:
    """一原板を指紋照合し、原順の12列NPZと入力監査を作る。

    引数: entry (dict) は旧固定台帳行、source_root/target (Path) は原板根/新NPZ、config (dict) は固定条件。
    返り値: dict は出典・SHA・件数・対応表・純粋監査結果。旧cacheと原板は変更しない。
    """
    source = source_root/entry["source_path"]
    before = source.stat()
    if (before.st_size, before.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
        raise ValueError("固定原板stat不一致: "+str(source))
    if target.exists():
        raise FileExistsError("補助NPZを上書きしません: "+str(target))
    digest, clock_cache, codes, exchanges, events = hashlib.sha256(), {}, [], [], []
    names, quality, raw_fields = set(), Counter(), {k: Counter() for k in RAW_FIELDS}
    previous, decoded, raw_lines = None, 0, 0
    opener = gzip.open if source.suffix.lower() == ".gz" else open
    for_stream = opener(source, "rb")
    with for_stream as stream:
        for raw_lines, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                quality["空行数"] += 1
                previous = None
                continue
            row = orjson.loads(raw) if orjson else json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError("原板オブジェクト以外")
            decoded += 1
            for field, key in RAW_FIELDS.items():
                value = row.get(key)
                kind = "欠測" if value is None else "非数値" if not isinstance(value, (int, float)) or isinstance(value, bool) else "非有限" if not math.isfinite(value) else "有限"
                raw_fields[field][kind] += 1
            event = parse_record(row, raw_lines, clock_cache, codes, exchanges)
            if row.get("SymbolName") is not None:
                names.add(str(row["SymbolName"]))
            key = state_key(event)
            if key == previous:
                events[-1] = events[-1]._replace(repeat=events[-1].repeat+1)
                quality["連続完全同一省略原行数"] += 1
                continue
            if previous is not None:
                # 同じ価格/数量状態でもVWAP・代金だけが変わった行を必ず残す。
                positions = [FIELDS.index(k)-(FIELDS.index(k) > FIELDS.index("line")) for k in ("native_vwap", "trading_value")]
                other = [i for i in range(len(key)) if i not in positions]
                if all(key[i] == previous[i] for i in other) and any(key[i] != previous[i] for i in positions):
                    quality["VWAP代金だけ更新した保存状態数"] += 1
            events.append(event)
            previous = key
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("原板が読取中に変化")
    content_sha = digest.hexdigest()
    if content_sha != entry["sha256_uncompressed"] or raw_lines != entry["raw_lines"] or decoded != entry["decoded_rows"]:
        raise ValueError("旧固定台帳の展開SHA/行数と不一致: "+entry["session"])
    arrays = as_arrays(events)
    audited = audit_arrays(arrays, entry["session"], codes, config)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name+".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    temporary.replace(target)
    return {"symbol": entry["symbol"], "session": entry["session"], "source_path": entry["source_path"],
            "source_size": before.st_size, "source_mtime_ns": before.st_mtime_ns,
            "sha256_uncompressed": content_sha, "旧展開SHA一致": True,
            "raw_lines": raw_lines, "decoded_rows": decoded, "events": len(events),
            "cache_path": target.relative_to(ROOT).as_posix(), "cache_size": target.stat().st_size,
            "sha256_cache": sha(target), "contract_codes": codes, "contract_names": sorted(names),
            "exchange_values": exchanges, "原行品質": dict(quality),
            "原行数値列": {k: dict(v) for k, v in raw_fields.items()}, "監査": audited}


def freeze(study: Path) -> dict:
    """条件・コード・入力参照を全量読取の前に固定する。

    引数: study (Path) は正式試行。
    返り値: dict はSHA一覧。既存結果や固定後変更を拒否する。
    """
    if (study/"結果.json").exists():
        raise ValueError("正式結果を上書きしません")
    pointer = read_json(study/"入力台帳.json")
    source = (study/pointer["参照"]).resolve()
    if source != INPUT or sha(source) != pointer["SHA256"]:
        raise ValueError("入力台帳の固定参照が不一致")
    synthetic = ROOT/"work/VWAP入力/合成検証.json"
    proof = read_json(synthetic)
    if proof["全件成功"] is not True:
        raise ValueError("合成が成功していません")
    paths = [Path(__file__), Path(__file__).with_name("合成検証.py"), study/"計画.md",
             study/"条件.json", study/"入力台帳.json", INPUT]
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    for name in (Path(__file__).relative_to(ROOT).as_posix(), Path(__file__).with_name("合成検証.py").relative_to(ROOT).as_posix(),
                 (study/"条件.json").relative_to(ROOT).as_posix()):
        if proof["ファイルSHA256"][name] != pins[name]:
            raise ValueError("合成確認後に対象コードが変更")
    target = study/"固定.json"
    if target.exists() and read_json(target)["ファイルSHA256"] != pins:
        raise ValueError("実行前固定後に変更")
    result = {"固定日時": datetime.now(JST).isoformat(), "ファイルSHA256": pins,
              "Python": platform.python_version(), "numpy": np.__version__,
              "JSON読取": "orjson "+orjson.__version__ if orjson else "標準json"}
    if not target.exists():
        write_json(target, result)
    return result


def run(study: Path, work: Path) -> dict:
    """固定65原板を一回ずつ抽出し、入力監査だけを保存する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は損益を含まない監査結果。
    """
    config, manifest = read_json(study/"条件.json"), read_json(INPUT)
    if len(manifest["entries"]) != 65 or {e["symbol"] for e in manifest["entries"]} != {"NK225"}:
        raise ValueError("固定NK22565場以外")
    freeze(study)
    work.mkdir(parents=True, exist_ok=True)
    cache_manifest = work/"抽出台帳.json"
    identity = {"schema_version": 1, "入力台帳SHA256": sha(INPUT), "抽出コードSHA256": sha(Path(__file__)),
                "条件SHA256": sha(study/"条件.json"), "列dtype": {k: np.dtype(v).str for k, v in DTYPES.items()}}
    completed = read_json(cache_manifest) if cache_manifest.exists() else {**identity, "entries": []}
    if any(completed.get(k) != v for k, v in identity.items()):
        raise ValueError("既存作業台帳のschema/入力/抽出コード/条件変更")
    prior = {e["session"]: e for e in completed["entries"]}
    for index, entry in enumerate(manifest["entries"], 1):
        if entry["session"] in prior:
            saved = prior[entry["session"]]
            status = (Path(manifest["source_root"])/entry["source_path"]).stat()
            if ((status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"])
                    or saved["sha256_uncompressed"] != entry["sha256_uncompressed"]
                    or saved["source_path"] != entry["source_path"]
                    or sha(ROOT/saved["cache_path"]) != saved["sha256_cache"]):
                raise ValueError("再開NPZ指紋不一致")
        else:
            target = work/"キャッシュ"/"NK225"/(entry["session"]+".npz")
            saved = extract_one(entry, Path(manifest["source_root"]), target, config)
            completed["entries"].append(saved)
            write_json(cache_manifest, completed)
        print(f"00017 {index}/65 {entry['session']} 原行{saved['raw_lines']} 小列状態{saved['events']} 内部不整合{saved['監査']['内部整合']['不整合原行数']}", flush=True)
    entries = completed["entries"]
    counts = sum((Counter(e["監査"]["件数"]) for e in entries), Counter())
    report = {"入力監査": True, "全65場既使用": True, "損益を計算": False,
              "入力場数": len(entries), "原板保存バイト": sum(e["source_size"] for e in entries),
              "補助NPZバイト": sum(e["cache_size"] for e in entries), "原板複製": False,
              "展開SHA全場一致": all(e["旧展開SHA一致"] for e in entries),
              "原行数": sum(e["raw_lines"] for e in entries), "保存状態数": sum(e["events"] for e in entries),
              "件数": dict(counts), "場別": entries, "抽出台帳": cache_manifest.relative_to(ROOT).as_posix(),
              "コードSHA256": sha(Path(__file__)), "入力台帳SHA256": sha(INPUT),
              "時計と起算の限界": "VWAP/代金固有時計や受信時計は未収録。始値時計は起算を示唆する観測で、全約定を独立復元していない。場開始前の既知累積基準が不明なら0を補わない。内部整合・観測参照候補・当場差分計算可能性は別の判定。"}
    write_json(study/"結果.json", report)
    return report


def main() -> None:
    """root静読と合成後の明示指定だけで全量読取を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不許可時は原板全量を開かない。
    """
    parser = argparse.ArgumentParser(description="配信VWAPと売買代金の入力監査")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("合成・root静読後に --実行許可 を指定")
    result = run(args.study.resolve(), args.work.resolve())
    print(json.dumps({k: result[k] for k in ("入力場数", "原行数", "保存状態数", "補助NPZバイト", "展開SHA全場一致")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
