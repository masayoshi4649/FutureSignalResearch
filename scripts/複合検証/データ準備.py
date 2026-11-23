"""原板を一度だけ走査し、原順のイベントキャッシュと数量の品質監査を作成する。"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, NamedTuple

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "work" / "pythonlibs"))
try:
    import orjson
except ImportError:
    orjson = None

JST = timezone(timedelta(hours=9))
FIELDS = ("now", "line", "last", "bid", "ask", "valid", "volume", "volume_time")
DTYPES = {key: (np.int64 if key == "line" else np.bool_ if key == "valid" else np.float64) for key in FIELDS}


class Event(NamedTuple):
    """価格時計と数量時計を分離した、原板物理行に対応する一つの状態。"""

    now: float
    line: int
    last: float
    bid: float
    ask: float
    valid: bool
    volume: float
    volume_time: float


def finite_number(value: Any) -> float:
    """
    機能: JSONの有限数値を返し、欠測・非数値・無限大をNaNへ統一する。
    引数: value (Any) はJSONから読み取った値。
    返り値: float は有限の数値またはNaN。負値と0は監査のため保持する。
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return math.nan


def clock_seconds(value: Any, cache: dict[str, float]) -> float:
    """
    機能: 時差付き時計をUnix秒へ変換し、同じ文字列の変換を再利用する。
    引数: value (Any) は時計、cache (dict[str, float]) は当ファイルだけの変換辞書。
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


def session_bounds(session: str) -> tuple[float, float]:
    """
    機能: 開始日基準の名前から価格足を形成するザラバ範囲を返す。
    引数: session (str) はYYYY-MM-DD_DayまたはNight。
    返り値: tuple[float, float] は開始・ザラバ終了のUnix秒。
    """
    date = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        return (date + timedelta(hours=8, minutes=45)).timestamp(), (date + timedelta(hours=15, minutes=40)).timestamp()
    if session.endswith("_Night"):
        return (date + timedelta(hours=17)).timestamp(), (date + timedelta(days=1, hours=5, minutes=55)).timestamp()
    raise ValueError(f"未知のセッション名: {session}")


def state_key(event: Event) -> tuple:
    """
    機能: NaN同士を同じ欠測と扱い、約定モデルに関係する状態だけを比較する。
    引数: event (Event) は原板から得た状態。
    返り値: tuple はlineを除く7項目の正規化済み状態。
    """
    return tuple(None if isinstance(value, float) and math.isnan(value) else value
                 for value in (event.now, event.last, event.bid, event.ask, event.valid, event.volume, event.volume_time))


def read_events(path: Path | str) -> Iterator[Event]:
    """
    機能: 固定済みnpzを読み、価格時計の選別をせず元の順序で状態を返す。
    引数: path (Path | str) は8列のイベントキャッシュ。
    返り値: Iterator[Event] はPython標準型による8属性の状態列。欠測時計等も保持する。
    """
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != set(FIELDS):
            raise ValueError(f"キャッシュの列が一致しません: {path}")
        arrays = [archive[field] for field in FIELDS]
        if len({len(array) for array in arrays}) != 1:
            raise ValueError(f"列の長さが一致しません: {path}")
        for now, line, last, bid, ask, valid, volume, volume_time in zip(*arrays):
            yield Event(float(now), int(line), float(last), float(bid), float(ask), bool(valid), float(volume), float(volume_time))


def hash_file(path: Path) -> str:
    """
    機能: ファイル全体を小さな塊でハッシュ化する。
    引数: path (Path) は検証対象。
    返り値: str はSHA256の16進文字列。
    """
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    """
    機能: 有効な日本語JSONを一時ファイルから公開する。
    引数: path (Path) は保存先、value (Any) はJSON化する値。
    返り値: None。NaNをJSONへ保存しない。
    """
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


# ----------------------------------------
# 価格時計で利用可能な数量差分の監査。実際の全約定数量とは区別する。

def audit_volume(events: Iterator[Event], session: str) -> dict[str, Any]:
    """
    機能: 数量時計が価格時計以下の観測だけで、5分の累積差分量と不完全理由を監査する。
    引数: events (Iterator[Event]) は原順の状態、session (str) はセッション名。
    返り値: dict[str, Any] は状態別件数・5分数量・連続利用可能本数。損益は扱わない。
    """
    start, end = session_bounds(session)
    counts = Counter()
    bars = {}
    previous_now = None
    previous_volume = None
    previous_volume_time = None
    previous_index = None
    previous_pair = None
    max_lead = max_lag = 0.0
    for event in events:
        counts["cached_events"] += 1
        if not math.isfinite(event.now):
            counts["price_clock_missing"] += 1
            continue
        if not start <= event.now < end:
            counts["price_clock_outside_regular_session"] += 1
            continue
        if previous_now is not None and event.now < previous_now:
            counts["price_clock_backward_ignored"] += 1
            continue
        previous_now = event.now
        counts["in_session_events"] += 1
        index = int((event.now - start) // 300)
        info = bars.setdefault(index, {"index": index, "time": datetime.fromtimestamp(start + 300 * index, JST).isoformat(),
                                      "observed_volume": 0.0, "accepted_states": 0, "positive_updates": 0,
                                      "has_price": False, "reasons": [], "future_states": 0, "missing_states": 0})
        if math.isfinite(event.last) and event.last > 0:
            info["has_price"] = True
        if previous_index is not None and index > previous_index + 1:
            counts["gaps"] += 1
            counts["missing_five_minute_buckets"] += index - previous_index - 1
            previous_volume = previous_volume_time = None
            info["reasons"].append("価格時計の足欠損後に累積基準を再設定")
        previous_index = index
        if not math.isfinite(event.volume) or event.volume < 0:
            counts["volume_missing_or_invalid"] += 1
            info["missing_states"] += 1
            continue
        if not math.isfinite(event.volume_time):
            counts["volume_clock_missing"] += 1
            info["missing_states"] += 1
            continue
        offset = event.volume_time - event.now
        max_lead, max_lag = max(max_lead, offset), max(max_lag, -offset)
        pair = (event.volume, event.volume_time)
        changed = pair != previous_pair
        previous_pair = pair
        counts["volume_pair_changes"] += changed
        counts["volume_clock_after_price"] += offset > 0
        counts["volume_clock_before_price"] += offset < 0
        counts["volume_clock_equal_price"] += offset == 0
        if int((event.volume_time - start) // 300) != index:
            counts["different_five_minute_bucket"] += 1
            counts["different_five_minute_bucket_pair_changes"] += changed
        if offset > 0:
            counts["held_future_pair_changes"] += changed
            info["future_states"] += 1
            continue
        info["accepted_states"] += 1
        if previous_volume is None:
            info["reasons"].append("初回の累積基準")
            counts["initial_baselines"] += 1
        elif event.volume < previous_volume or event.volume_time < previous_volume_time:
            if event.volume < previous_volume:
                counts["accepted_cumulative_decreases"] += 1
                info["reasons"].append("累積数量減少")
            if event.volume_time < previous_volume_time:
                counts["accepted_volume_clock_backwards"] += 1
                info["reasons"].append("数量時計後退")
        else:
            delta = event.volume - previous_volume
            info["observed_volume"] += delta
            if delta > 0:
                counts["positive_delta_updates"] += 1
                info["positive_updates"] += 1
        previous_volume, previous_volume_time = event.volume, event.volume_time
    # ----------------------------------------
    # 初足・基準切替足は外し、穴があれば量の履歴も連続と見なさない。
    rows = []
    run = longest = ready = 0
    previous_price_index = None
    for index, info in sorted(bars.items()):
        if not info["has_price"]:
            continue
        if index == 0:
            info["reasons"].append("セッション最初の足")
        if not info["accepted_states"]:
            info["reasons"].append("採用可能な数量観測なし")
        info["reasons"] = sorted(set(info["reasons"]))
        info["baseline_complete"] = not info["reasons"]
        if previous_price_index is not None and index != previous_price_index + 1:
            run = 0
        if info["baseline_complete"]:
            ready += run >= 20
            run += 1
            longest = max(longest, run)
        else:
            run = 0
        previous_price_index = index
        info["preceding_twenty_quantity_bars_available"] = info["baseline_complete"] and run >= 21
        rows.append(info)
    complete = sum(row["baseline_complete"] for row in rows)
    return {"counts": dict(counts), "maximum_volume_lead_seconds": max_lead,
            "maximum_volume_lag_seconds": max_lag, "price_bars": len(rows), "baseline_complete_bars": complete,
            "baseline_incomplete_bars": len(rows) - complete, "longest_complete_run": longest,
            "rvol_previous_twenty_available_bars": ready,
            "definition": "価格時計で数量時計以下の有限非負累積のみ受入れ。初回・減少・数量時計後退・足欠損後は再基準化して当足不完全。正常増分を採用時の価格時計足へ加算。遡及再配置しない。",
            "limitations": "baseline_completeはこの観測モデルの基準継続であり、真の全約定数量の完全性ではない。future行はskipし後続で採用できた累積から差分を得る。",
            "five_minute_bars": rows}


def build_one(source: Path, cache_path: Path, symbol: str, session: str, data_root: Path) -> dict[str, Any]:
    """
    機能: 一原板を一度だけ読み、同一状態だけ省いた圧縮キャッシュと監査を作る。
    引数: source/cache_path (Path) は入出力、symbol/session (str) は対象、data_root (Path) は原板ルート。
    返り値: dict[str, Any] は入力識別・件数・限月・品質・数量監査。
    """
    before = source.stat()
    digest = hashlib.sha256()
    columns = {key: [] for key in FIELDS}
    clocks, codes, names, active_codes = {}, set(), set(), set()
    quality = Counter()
    raw_lines = decoded_rows = omitted = 0
    previous_key = None
    previous_time = None
    start, end = session_bounds(session)
    opener = gzip.open if source.suffix.lower() == ".gz" else open
    with opener(source, "rb") as stream:
        for raw_lines, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                quality["blank_lines"] += 1
                continue
            row = orjson.loads(raw) if orjson else json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"オブジェクト以外の原板: {source}:{raw_lines}")
            decoded_rows += 1
            now = clock_seconds(row.get("CurrentPriceTime"), clocks)
            volume_time = clock_seconds(row.get("TradingVolumeTime"), clocks)
            last, volume = finite_number(row.get("CurrentPrice")), finite_number(row.get("TradingVolume"))
            buy, sell = row.get("Buy1") or {}, row.get("Sell1") or {}
            bid, ask = finite_number(buy.get("Price")), finite_number(sell.get("Price"))
            bid_qty, ask_qty = finite_number(buy.get("Qty")), finite_number(sell.get("Qty"))
            valid = bid > 0 and ask > bid and bid_qty >= 1 and ask_qty >= 1
            event = Event(now, raw_lines, last, bid, ask, valid, volume, volume_time)
            code, name = row.get("Symbol"), row.get("SymbolName")
            if code is not None:
                codes.add(str(code))
            if name is not None:
                names.add(str(name))
            quality["price_clock_missing_or_invalid"] += not math.isfinite(now)
            quality["last_missing_or_nonpositive"] += not (last > 0)
            quality["invalid_bbo_or_quantity"] += not valid
            quality["volume_missing_or_invalid"] += not (volume >= 0)
            quality["volume_clock_missing_or_invalid"] += not math.isfinite(volume_time)
            if math.isfinite(now):
                quality["price_clock_outside_regular_session"] += not start <= now < end
                if start <= now < end and code is not None:
                    active_codes.add(str(code))
                if previous_time is not None:
                    quality["same_price_clock_rows"] += now == previous_time
                    quality["backward_price_clock_rows"] += now < previous_time
                previous_time = now
                if math.isfinite(volume_time):
                    quality["volume_time_after_price_rows"] += volume_time > now
                    quality["volume_time_before_price_rows"] += volume_time < now
                    quality["volume_time_equal_price_rows"] += volume_time == now
            key = state_key(event)
            if key == previous_key:
                omitted += 1
                continue
            previous_key = key
            for field, value in zip(FIELDS, event):
                columns[field].append(value)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"読取中に入力が変化しました: {source}")
    if len(active_codes) != 1:
        raise ValueError(f"場内限月が一意ではありません: {source}: {sorted(active_codes)}")
    arrays = {key: np.asarray(values, dtype=DTYPES[key]) for key, values in columns.items()}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        raise FileExistsError(f"固定キャッシュを上書きしません: {cache_path}")
    temporary = cache_path.with_name(cache_path.name + ".tmp")
    with temporary.open("wb") as target:
        np.savez_compressed(target, **arrays)
    temporary.replace(cache_path)
    volume_audit = audit_volume(read_events(cache_path), session)
    return {"symbol": symbol, "session": session, "source_path": source.relative_to(data_root).as_posix(),
            "cache_path": (Path("キャッシュ") / symbol / cache_path.name).as_posix(),
            "source_size": before.st_size, "source_mtime_ns": before.st_mtime_ns,
            "raw_lines": raw_lines, "decoded_rows": decoded_rows, "events": len(arrays["now"]), "omitted_identical": omitted,
            "sha256_uncompressed": digest.hexdigest(), "sha256_cache": hash_file(cache_path),
            "cache_size": cache_path.stat().st_size, "contract_codes": sorted(codes), "contract_names": sorted(names),
            "in_session_contract_codes": sorted(active_codes), "quality": dict(quality), "volume_audit": volume_audit}


# ----------------------------------------
# 入力を固定する台帳と、数量採用可能性の集計

def summarize_quantity(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """
    機能: 探索用57場と後続3場を分け、数量状態と利用可能本数だけを集計する。
    引数: entries (list[dict[str, Any]]) はキャッシュ台帳の各場。
    返り値: dict[str, Any] は損益を含まない数量監査。
    """
    groups = []
    for symbol in ("NK225", "TOPIX"):
        for scope in ("探索57場", "後続3場"):
            selected = [entry for entry in entries if entry["symbol"] == symbol and
                        ((entry["session"] <= "2026-10-29_Day") == (scope == "探索57場"))]
            counts = sum((Counter(entry["volume_audit"]["counts"]) for entry in selected), Counter())
            groups.append({"symbol": symbol, "scope": scope, "sessions": len(selected), "counts": dict(counts),
                           "price_bars": sum(entry["volume_audit"]["price_bars"] for entry in selected),
                           "baseline_complete_bars": sum(entry["volume_audit"]["baseline_complete_bars"] for entry in selected),
                           "rvol_previous_twenty_available_bars": sum(entry["volume_audit"]["rvol_previous_twenty_available_bars"] for entry in selected),
                           "maximum_volume_lead_seconds": max((entry["volume_audit"]["maximum_volume_lead_seconds"] for entry in selected), default=0),
                           "maximum_volume_lag_seconds": max((entry["volume_audit"]["maximum_volume_lag_seconds"] for entry in selected), default=0)})
    return {"確認日": "2026-10-31", "分類": "入力監査のみ。後続3場の損益やシグナルは計算しない。",
            "時計の意味": "CurrentPriceTimeは現値時刻、TradingVolumeTimeは売買高時刻。いずれも受信時計ではない。",
            "一次資料": ["https://kabucom.github.io/kabusapi/ptal/push.html", "../kabus-controller/future_history_candles.go", "../kabus-controller/future_history_archive.go"],
            "source_code_commit": subprocess.check_output(["git", "-C", str(ROOT.parent / "kabus-controller"), "rev-parse", "HEAD"], text=True).strip(),
            "CSV生成": "受信時刻で分を進め、価格時計・数量時計の各分が受信分と同じときだけ更新。確定足の遅着は訂正しない。volume_completeは基準取得済み・減少なしの意味。5分は存在する1分だけ合算。稼働版がこのローカルコードと同じかは別途未確定。",
            "観測差分量の定義": "数量時計<=価格時計の非負累積のみ採用し、初回/減少/数量時計後退/足欠損後は基準再設定し当足を不完全にする。正常増分を採用した価格時計の5分区間へ寄せ、約定時刻には遡及しない。",
            "groups": groups}


def run(data_root: Path, output: Path, limit: int | None = None) -> None:
    """
    機能: 現存する対象入力を一度ずつキャッシュ化し、更新検出可能な台帳を保存する。
    引数: data_root/output (Path) は入出力、limit (int | None) は診断時の最大入力数。
    返り値: None。既存キャッシュはハッシュ・元サイズ・更新日時を検証して再利用する。
    """
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "入力キャッシュ台帳.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"schema_version": 1, "created_at_jst": datetime.now(JST).isoformat(),
                    "source_root": str(data_root.resolve()), "entries": [],
                    "Python": platform.python_version(), "numpy": np.__version__,
                    "JSON読取": f"orjson {orjson.__version__}" if orjson else "標準json",
                    "cache_columns": {key: np.dtype(dtype).str for key, dtype in DTYPES.items()}}
    if manifest["schema_version"] != 1 or Path(manifest["source_root"]).resolve() != data_root.resolve():
        raise ValueError("既存台帳の版または入力ルートが異なります")
    prior = {(entry["symbol"], entry["session"]): entry for entry in manifest["entries"]}
    paths = []
    for symbol in ("NK225", "TOPIX"):
        for folder in sorted(path for path in (data_root / symbol).iterdir() if path.is_dir()):
            source = folder / "book.jsonl.gz"
            if not source.is_file():
                source = folder / "book.jsonl"
            if source.is_file():
                paths.append((symbol, folder.name, source))
    if limit is not None:
        paths = paths[:limit]
    for number, (symbol, session, source) in enumerate(paths, 1):
        entry = prior.get((symbol, session))
        if entry is not None:
            old_source = data_root / entry["source_path"]
            stat = old_source.stat()
            if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
                raise RuntimeError(f"固定済み入力が変化しました: {old_source}")
            if hash_file(output / entry["cache_path"]) != entry["sha256_cache"]:
                raise RuntimeError(f"固定キャッシュが変化しました: {entry['cache_path']}")
        else:
            cache_path = output / "キャッシュ" / symbol / f"{session}.npz"
            entry = build_one(source, cache_path, symbol, session, data_root)
            manifest["entries"].append(entry)
            write_json(manifest_path, manifest)
        print(f"入力準備 {number}/{len(paths)} {symbol} {session} 原行{entry['raw_lines']} 状態{entry['events']} 数量有効足{entry['volume_audit']['baseline_complete_bars']}/{entry['volume_audit']['price_bars']}", flush=True)
    write_json(output / "数量監査.json", summarize_quantity(manifest["entries"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="損益を計算せず、原板の共通キャッシュと数量監査を準備する")
    parser.add_argument("--data-root", type=Path, default=ROOT.parent / "JP_OSE_Data" / "future")
    parser.add_argument("--output", type=Path, default=ROOT / "work" / "複合検証")
    parser.add_argument("--limit", type=int)
    arguments = parser.parse_args()
    run(arguments.data_root.resolve(), arguments.output.resolve(), arguments.limit)
