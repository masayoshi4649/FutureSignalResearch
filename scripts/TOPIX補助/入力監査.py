"""
機能: 予約済みTOPIX66場を各一回走査し、原入力と旧8列キャッシュを監査する。
引数: CLIの --実行許可 (bool) は実入力監査、--人工確認 (bool) は人工入力のみの確認。
返り値: CLI終了値0は監査一致。新指標・売買先着・損益は計算しない。
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import re
import sys
import tempfile
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work" / "TOPIX補助" / "00044"
RESERVATION = WORK / "入力予約.json"
RESERVATION_SHA = "c2943877ce220c7f32adf79df8517747c71f5863d70119bb8158c3d82f382eb7"
OLD_BASE = ROOT / "work" / "複合検証"
OLD_MANIFEST = OLD_BASE / "入力キャッシュ台帳.json"
OLD_MANIFEST_SHA = "96de20e6642c7370a2552e6a2555f4b6d1ac8bf15f181881ed4c092423161800"
NK_MANIFEST = ROOT / "study" / "00028_基準線復帰と上位一目の方向" / "入力台帳.json"
NK_MANIFEST_SHA = "680b831ee6bef1ec1cf49dc6283931f5b0ca9611f15f5c19d81af6e4738aaf9b"
PREP_PATH = ROOT / "scripts" / "複合検証" / "データ準備.py"
spec = importlib.util.spec_from_file_location("TOPIX44固定入力準備", PREP_PATH)
P = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = P
spec.loader.exec_module(P)
FIELDS = P.FIELDS
DTYPES = P.DTYPES
TIME_WORDS = re.compile(r"time|stamp|clock|時刻|時計|日時", re.I)
RECEIVE_WORDS = re.compile(r"receiv|recv|asof|sequence|seq$|serial|counter|受信|連番", re.I)
MARKET_WORDS = re.compile(r"exchange|market|securitytype|市場", re.I)
MONTH = re.compile(r"(?<!\d)(\d{2}|\d{4})/(\d{2})(?!\d)")


# ----------------------------------------
# 予約・パス・出典を確定してから原入力を開く

def sha(path: Path) -> str:
    """
    機能: ファイルのSHA256を得る。
    引数: path (Path) は対象。
    返り値: str は16進指紋。
    """
    return P.hash_file(path)


def read_json(path: Path) -> Any:
    """
    機能: UTF-8の小型JSONを読む。
    引数: path (Path) は対象。
    返り値: Any は復号内容。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    """
    機能: リポジトリ内の出典パスを表す。
    引数: path (Path) は内部ファイル。
    返り値: str はROOT相対パス。
    """
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def within(path: Path, parent: Path) -> Path:
    """
    機能: 解決済みパスが指定範囲内であることを確認する。
    引数: path/parent (Path) は対象と範囲。
    返り値: Path は安全確認済み絶対パス。
    """
    resolved = path.resolve()
    resolved.relative_to(parent.resolve())
    return resolved


def month_values(names: set[str] | list[str]) -> list[str]:
    """
    機能: 原商品名から限月年月を抽出する。
    引数: names (set[str] | list[str]) は商品名。
    返り値: list[str] は一意のYYYY-MM。
    """
    result = set()
    for name in names:
        for match in MONTH.finditer(name):
            year = int(match[1])
            result.add(f"{year + 2000 if year < 100 else year:04d}-{int(match[2]):02d}")
    return sorted(result)


def plan() -> tuple[dict, dict, dict, list[dict], dict[str, str]]:
    """
    機能: 予約66場・既存60場・出力6場を内容閲覧前に照合する。
    引数: なし。
    返り値: tuple は予約、NK台帳、旧台帳、確定入出力計画、出典指紋。
    """
    bindings = {
        relative(RESERVATION): sha(RESERVATION),
        relative(NK_MANIFEST): sha(NK_MANIFEST),
        relative(OLD_MANIFEST): sha(OLD_MANIFEST),
        relative(PREP_PATH): sha(PREP_PATH),
        relative(Path(__file__)): sha(Path(__file__)),
    }
    assert bindings[relative(RESERVATION)] == RESERVATION_SHA, "予約SHA不一致"
    assert bindings[relative(NK_MANIFEST)] == NK_MANIFEST_SHA, "NK台帳SHA不一致"
    assert bindings[relative(OLD_MANIFEST)] == OLD_MANIFEST_SHA, "旧台帳SHA不一致"
    reservation, nk, old = read_json(RESERVATION), read_json(NK_MANIFEST), read_json(OLD_MANIFEST)
    assert reservation["NK入力台帳SHA256"] == NK_MANIFEST_SHA
    assert reservation["対象数"] == len(reservation["対象"]) == 66
    nk_entries = {entry["session"]: entry for entry in nk["entries"]}
    assert len(nk_entries) == 66 and all(e["symbol"] == "NK225" for e in nk_entries.values())
    sessions = [item["session"] for item in reservation["対象"]]
    assert len(set(sessions)) == 66 and set(sessions) == set(nk_entries)
    assert "2026-11-05_Day" not in sessions
    assert reservation["対象外"] == ["NK225/2026-11-05_Day", "TOPIX/2026-11-05_Day"]
    data_root = Path(nk["source_root"]).resolve()
    assert data_root == Path(old["source_root"]).resolve()
    assert data_root == (ROOT.parent / "JP_OSE_Data" / "future").resolve()
    prior = {entry["session"]: entry for entry in old["entries"] if entry["symbol"] == "TOPIX"}
    assert len(prior) == 60 and set(prior).issubset(sessions)
    output = []
    for item in reservation["対象"]:
        session = item["session"]
        assert item["symbol"] == "TOPIX"
        folder = (data_root / "TOPIX" / session).resolve()
        assert Path(item["入力フォルダ"]).resolve() == folder
        assert folder.name != "2026-11-05_Day"
        previous = prior.get(session)
        if previous is not None:
            source = within(data_root / previous["source_path"], folder)
            cache = within(OLD_BASE / previous["cache_path"], OLD_BASE / "キャッシュ" / "TOPIX")
            info = source.stat()
            assert (info.st_size, info.st_mtime_ns) == (previous["source_size"], previous["source_mtime_ns"])
            assert cache.stat().st_size == previous["cache_size"]
            assert sha(cache) == previous["sha256_cache"], f"旧cache指紋不一致 {session}"
        else:
            source = folder / "book.jsonl.gz"
            if not source.is_file():
                source = folder / "book.jsonl"
            source = within(source, folder)
            assert source.is_file()
            cache = within(WORK / "キャッシュ" / "TOPIX" / f"{session}.npz", WORK)
            assert not cache.exists(), f"新cacheを上書きしない {cache}"
            assert not cache.with_name(cache.name + ".tmp").exists()
        output.append({"session": session, "source": source, "cache": cache,
                       "prior": previous, "NK限月年月": month_values(nk_entries[session].get("contract_names", []))})
    assert sum(row["prior"] is None for row in output) == 6
    for name in ("入力台帳.json", "入力監査.json", "途中点検.json"):
        assert not (WORK / name).exists(), f"監査成果物を上書きしない {name}"
    return reservation, nk, old, output, bindings


# ----------------------------------------
# 全行のpayload構造と候補時計を値の巨大転記なしで調べる

class Inventory:
    """
    機能: 全JSON行の辞書キー構造・時計候補・市場区分を集約する。
    引数: コンストラクター引数なし。
    返り値: インスタンス。summary()はJSON化可能なdict。
    """
    def __init__(self) -> None:
        """
        機能: 全行構造・候補時計の空の集約を作る。
        引数: なし。
        返り値: None。
        """
        self.schemas = defaultdict(Counter)
        self.fields = {}
        self.categories = defaultdict(Counter)
        self.array_paths = Counter()
        self.rows = 0
        self.clocks = {}

    def observe(self, value: Any, path: str = "$") -> None:
        """
        機能: 一行に存在する全辞書・配列をたどり、時計候補を全件確認する。
        引数: value (Any) はJSON値、path (str) は階層。
        返り値: None。実際の受信時計という意味は推定しない。
        """
        if path == "$":
            self.rows += 1
        if isinstance(value, dict):
            self.schemas[path][tuple(sorted(value))] += 1
            for key, item in value.items():
                sub = path + "." + key
                if isinstance(item, (dict, list)):
                    self.observe(item, sub)
                elif TIME_WORDS.search(key) or RECEIVE_WORDS.search(key):
                    stat = self.fields.setdefault(sub, {"存在": 0, "非null": 0, "型": Counter(),
                                                        "時刻変換可能": 0, "時刻変換不可": 0,
                                                        "時計後退": 0, "受信連番名候補": bool(RECEIVE_WORDS.search(key)),
                                                        "先頭非null例": [], "_前時計": None})
                    stat["存在"] += 1
                    stat["非null"] += item is not None
                    stat["型"][type(item).__name__] += 1
                    if item is not None and len(stat["先頭非null例"]) < 2 and item not in stat["先頭非null例"]:
                        stat["先頭非null例"].append(item)
                    if TIME_WORDS.search(key) and item is not None:
                        timestamp = P.clock_seconds(item, self.clocks)
                        if math.isfinite(timestamp):
                            stat["時刻変換可能"] += 1
                            stat["時計後退"] += stat["_前時計"] is not None and timestamp < stat["_前時計"]
                            stat["_前時計"] = timestamp
                        else:
                            stat["時刻変換不可"] += 1
                if MARKET_WORDS.search(key) and not isinstance(item, (dict, list)):
                    self.categories[sub][json.dumps(item, ensure_ascii=False, sort_keys=True)] += 1
        elif isinstance(value, list):
            self.array_paths[path] += 1
            for item in value:
                if isinstance(item, (dict, list)):
                    self.observe(item, path + "[]")

    def summary(self) -> dict:
        """
        機能: 全行確認済みの構造・時計候補・市場値を小型JSONへまとめる。
        引数: なし。
        返り値: dict は個別原板を含まない集約。
        """
        nodes = {}
        for path, schemas in sorted(self.schemas.items()):
            keys = sorted(set().union(*(set(shape) for shape in schemas)))
            nodes[path] = {"全キー": keys,
                           "キー組合せ": [{"キー": list(shape), "件数": count}
                                        for shape, count in sorted(schemas.items())]}
        fields = {path: {key: dict(value) if isinstance(value, Counter) else value
                         for key, value in stat.items() if not key.startswith("_")}
                  for path, stat in sorted(self.fields.items())}
        candidates = [path for path, row in fields.items() if row["受信連番名候補"] and row["非null"]]
        return {"確認JSON行数": self.rows, "辞書階層": nodes, "配列階層": dict(self.array_paths),
                "時計連番候補": fields,
                "市場区分値": {key: dict(value) for key, value in sorted(self.categories.items())},
                "非null受信連番名候補": candidates,
                "意味の限定": "キー名による候補抽出。価格・数量・始高安・前値の時計を受信時計と呼ばない。原行番号は各商品ファイル内であり共通順序ではない。"}


def issue(counter: Counter, examples: dict, name: str, line: int, condition: bool) -> None:
    """
    機能: 不整合の件数と最大5件の原行番号を記録する。
    引数: counter/examples (dict) は集約、name (str) は項目、line (int) は行、condition (bool) は該当。
    返り値: None。
    """
    counter[name] += int(condition)
    if condition and len(examples.setdefault(name, [])) < 5:
        examples[name].append(line)


def scan(source: Path, session: str) -> tuple[dict, dict[str, np.ndarray], dict]:
    """
    機能: 原ファイルを一回走査し固定prepと同じ8列と拡張入力監査を生成する。
    引数: source (Path) は予約内原板、session (str) は場。
    返り値: tuple は固定互換entry部分、8列配列、全payload・時計・価格監査。
    """
    before = source.stat()
    digest = hashlib.sha256()
    columns = {key: [] for key in FIELDS}
    clocks, codes, names, active_codes, active_names = {}, set(), set(), set(), set()
    quality, extended, examples = Counter(), Counter(), {}
    inventory = Inventory()
    raw_lines = decoded_rows = omitted = 0
    previous_key = previous_time = previous_volume_time = previous_volume = None
    start, end = P.session_bounds(session)
    finite_times, finite_vtimes = [], []
    price_ranges = {key: [None, None] for key in ("last", "bid", "ask")}
    opener = gzip.open if source.suffix.lower() == ".gz" else open
    with opener(source, "rb") as stream:
        for raw_lines, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                quality["blank_lines"] += 1
                continue
            row = P.orjson.loads(raw) if P.orjson else json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"オブジェクト以外の原板 {source}:{raw_lines}")
            decoded_rows += 1
            inventory.observe(row)
            now = P.clock_seconds(row.get("CurrentPriceTime"), clocks)
            volume_time = P.clock_seconds(row.get("TradingVolumeTime"), clocks)
            last, volume = P.finite_number(row.get("CurrentPrice")), P.finite_number(row.get("TradingVolume"))
            buy, sell = row.get("Buy1") or {}, row.get("Sell1") or {}
            bid, ask = P.finite_number(buy.get("Price")), P.finite_number(sell.get("Price"))
            bid_qty, ask_qty = P.finite_number(buy.get("Qty")), P.finite_number(sell.get("Qty"))
            valid = bid > 0 and ask > bid and bid_qty >= 1 and ask_qty >= 1
            event = P.Event(now, raw_lines, last, bid, ask, valid, volume, volume_time)
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
                finite_times.append(now)
                quality["price_clock_outside_regular_session"] += not start <= now < end
                if start <= now < end:
                    if code is not None:
                        active_codes.add(str(code))
                    if name is not None:
                        active_names.add(str(name))
                if previous_time is not None:
                    quality["same_price_clock_rows"] += now == previous_time
                    quality["backward_price_clock_rows"] += now < previous_time
                    issue(extended, examples, "価格時計後退", raw_lines, now < previous_time)
                previous_time = now
                if math.isfinite(volume_time):
                    quality["volume_time_after_price_rows"] += volume_time > now
                    quality["volume_time_before_price_rows"] += volume_time < now
                    quality["volume_time_equal_price_rows"] += volume_time == now
            if math.isfinite(volume_time):
                finite_vtimes.append(volume_time)
                if previous_volume_time is not None:
                    issue(extended, examples, "数量時計後退", raw_lines, volume_time < previous_volume_time)
                previous_volume_time = volume_time
            if math.isfinite(volume) and volume >= 0:
                if previous_volume is not None:
                    issue(extended, examples, "原累積数量減少", raw_lines, volume < previous_volume)
                previous_volume = volume
            issue(extended, examples, "Last正常かつBBO不正常", raw_lines, last > 0 and not valid)
            issue(extended, examples, "BBO正常かつLast不正常", raw_lines, valid and not last > 0)
            issue(extended, examples, "数量有限非負ゼロ", raw_lines, volume == 0)
            for field, value in (("last", last), ("bid", bid), ("ask", ask)):
                if math.isfinite(value) and value > 0:
                    lo, hi = price_ranges[field]
                    price_ranges[field] = [value if lo is None else min(lo, value),
                                           value if hi is None else max(hi, value)]
                    issue(extended, examples, field + "の0.5刻み外", raw_lines, not (value * 2).is_integer())
            key = P.state_key(event)
            if key == previous_key:
                omitted += 1
                continue
            previous_key = key
            for field, value in zip(FIELDS, event):
                columns[field].append(value)
    after = source.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "読取中の原入力変更"
    assert len(active_codes) == 1, f"場内限月が一意でない {session} {active_codes}"
    arrays = {key: np.asarray(value, dtype=DTYPES[key]) for key, value in columns.items()}
    entry = {"symbol": "TOPIX", "session": session, "source_size": before.st_size,
             "source_mtime_ns": before.st_mtime_ns, "raw_lines": raw_lines,
             "decoded_rows": decoded_rows, "events": len(arrays["now"]), "omitted_identical": omitted,
             "sha256_uncompressed": digest.hexdigest(), "contract_codes": sorted(codes),
             "contract_names": sorted(names), "in_session_contract_codes": sorted(active_codes),
             "quality": dict(quality), "限月年月": month_values(names)[0] if len(month_values(names)) == 1 else None,
             "場内限月年月": month_values(active_names)}
    audit = {"場": session, "全payload": inventory.summary(), "追加品質件数": dict(extended),
             "該当原行例": {key: value for key, value in examples.items() if value},
             "正価格範囲": price_ranges,
             "価格時計範囲": [min(finite_times), max(finite_times)] if finite_times else None,
             "数量時計範囲": [min(finite_vtimes), max(finite_vtimes)] if finite_vtimes else None,
             "場内商品名": sorted(active_names),
             "LastとBBO": "Lastを足の価格入力に使えることと、返済・新規に正常BBOを使えることは別。",
             "原入力走査回数": 1}
    return entry, arrays, audit


# ----------------------------------------
# 旧60の全列比較と追加6の保存を分ける

def arrays_equal(arrays: dict[str, np.ndarray], path: Path) -> dict:
    """
    機能: 固定npzと再構成した全8列の型・長さ・NaN位置・値を比較する。
    引数: arrays (dict) は原順から再構成した列、path (Path) は固定cache。
    返り値: dict は列別厳密比較。浮動許容を設けない。
    """
    result = {}
    with np.load(path, allow_pickle=False) as old:
        assert set(old.files) == set(FIELDS), "旧cache列集合差"
        for field in FIELDS:
            a, b = arrays[field], old[field]
            same_dtype, same_shape = a.dtype == b.dtype, a.shape == b.shape
            same = same_dtype and same_shape and np.array_equal(a, b, equal_nan=True)
            result[field] = {"型": a.dtype.str, "行数": len(a), "型同値": same_dtype,
                             "形状同値": same_shape, "厳密同値": bool(same)}
    return result


def save_arrays(arrays: dict[str, np.ndarray], path: Path) -> None:
    """
    機能: 新6場専用の圧縮8列を原板複製なしで作成する。
    引数: arrays (dict) は列、path (Path) は所有work内の未存在パス。
    返り値: None。既存ファイルを上書きしない。
    """
    within(path, WORK)
    assert not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    assert not temporary.exists()
    with temporary.open("xb") as output:
        np.savez_compressed(output, **arrays)
    temporary.replace(path)


def events_from_arrays(arrays: dict[str, np.ndarray]):
    """
    機能: 入力数量監査へ固定8列を原順で渡す。
    引数: arrays (dict) は8列。
    返り値: iterator[Event] はPythonスカラー化したイベント。
    """
    for values in zip(*(arrays[field] for field in FIELDS)):
        yield P.Event(float(values[0]), int(values[1]), float(values[2]), float(values[3]),
                      float(values[4]), bool(values[5]), float(values[6]), float(values[7]))


def run() -> None:
    """
    機能: 予約限定監査を一回実行し小型台帳・証明を保存する。
    引数: なし。
    返り値: None。全入力照合後、不一致があれば非正常終了する。
    """
    reservation, nk, old, jobs, bindings = plan()
    entries, audits, differences, old_cache_pins = [], [], [], {}
    data_root = Path(nk["source_root"]).resolve()
    print(f"予約照合成功 TOPIX66/旧60/新6 SHA={RESERVATION_SHA}", flush=True)
    for number, job in enumerate(jobs, 1):
        session, source, cache, prior = (job[key] for key in ("session", "source", "cache", "prior"))
        print(f"原入力走査開始 {number}/66 {session} 旧={prior is not None}", flush=True)
        entry, arrays, audit = scan(source, session)
        entry["source_path"] = source.relative_to(data_root).as_posix()
        entry["cache_path"] = Path(__import__("os").path.relpath(cache, OLD_BASE)).as_posix()
        audit["NK限月年月"] = job["NK限月年月"]
        audit["NKと限月年月同値"] = entry["場内限月年月"] == job["NK限月年月"]
        audit["TOPIXラージ商品名"] = all(name.startswith("TOPIX先物 ") for name in entry["contract_names"])
        if not audit["NKと限月年月同値"] or not audit["TOPIXラージ商品名"]:
            differences.append({"場": session, "項目": "商品または限月年月", "値": entry["contract_names"]})
        if prior is not None:
            comparisons = arrays_equal(arrays, cache)
            audit["旧8列再構成"] = comparisons
            if not all(item["厳密同値"] for item in comparisons.values()):
                differences.append({"場": session, "項目": "旧8列再構成", "値": comparisons})
            audit["旧entry照合"] = {}
            for key in ("symbol", "session", "source_path", "source_size", "source_mtime_ns", "raw_lines",
                        "decoded_rows", "events", "omitted_identical", "sha256_uncompressed",
                        "contract_codes", "contract_names", "in_session_contract_codes", "quality"):
                same = entry[key] == prior[key]
                audit["旧entry照合"][key] = same
                if not same:
                    differences.append({"場": session, "項目": "旧entry." + key,
                                        "原再構成": entry[key], "旧": prior[key]})
            volume = {key: value for key, value in prior["volume_audit"].items() if key != "five_minute_bars"}
            entry["数量監査参照"] = {"ファイル": relative(OLD_MANIFEST), "SHA256": OLD_MANIFEST_SHA,
                                     "symbol": "TOPIX", "session": session, "キー": "volume_audit"}
            old_cache_pins[relative(cache)] = prior["sha256_cache"]
        else:
            save_arrays(arrays, cache)
            audit["新8列再読込"] = arrays_equal(arrays, cache)
            assert all(item["厳密同値"] for item in audit["新8列再読込"].values())
            volume_full = P.audit_volume(events_from_arrays(arrays), session)
            volume = {key: value for key, value in volume_full.items() if key != "five_minute_bars"}
            entry["数量監査参照"] = {"定義": relative(PREP_PATH), "SHA256": bindings[relative(PREP_PATH)],
                                     "方式": "固定audit_volumeを今回再構成8列へ適用。5分大量明細は保存しない。"}
        entry["volume_audit"] = volume
        entry["sha256_cache"], entry["cache_size"] = sha(cache), cache.stat().st_size
        audit["cache種別"] = "旧固定参照" if prior else "追加新規"
        audit["原圧縮または平文サイズ"] = entry["source_size"]
        audit["raw_lines"], audit["decoded_rows"], audit["events"] = entry["raw_lines"], entry["decoded_rows"], entry["events"]
        entries.append(entry)
        audits.append(audit)
        P.write_json(WORK / "途中点検.json", {"完了場数": number, "全場数": 66,
                                            "entries": entries, "監査": audits, "不一致": differences})
        print(f"原入力走査完了 {number}/66 {session} 原{entry['raw_lines']} 状態{entry['events']} 差{len(differences)}", flush=True)
    for path, digest in bindings.items():
        assert sha(ROOT / path) == digest, f"実行中に出典が変更 {path}"
    for path, digest in old_cache_pins.items():
        assert sha(ROOT / path) == digest, f"旧cache変更 {path}"
    quality_total = sum((Counter(entry["quality"]) for entry in entries), Counter())
    extended_total = sum((Counter(audit["追加品質件数"]) for audit in audits), Counter())
    receive_candidates = sorted(set().union(*(set(a["全payload"]["非null受信連番名候補"]) for a in audits)))
    source_keys = sorted(set().union(*(set(a["全payload"]["辞書階層"].get("$", {}).get("全キー", [])) for a in audits)))
    manifest = {"schema_version": 1, "created_at_jst": datetime.now(P.JST).isoformat(),
                "source_root": str(data_root), "cache_base": "work/複合検証",
                "entries": entries, "Python": platform.python_version(), "numpy": np.__version__,
                "JSON読取": f"orjson {P.orjson.__version__}" if P.orjson else "標準json",
                "cache_columns": {key: np.dtype(value).str for key, value in DTYPES.items()},
                "入力予約": relative(RESERVATION), "入力予約SHA256": RESERVATION_SHA,
                "旧台帳": relative(OLD_MANIFEST), "旧台帳SHA256": OLD_MANIFEST_SHA,
                "数量監査の限定": "観測差分量の基準継続であり真の全約定数量ではない。5分明細は旧台帳参照または省略。",
                "監査": relative(WORK / "入力監査.json"), "指標計算": False, "先着計算": False, "損益計算": False}
    P.write_json(WORK / "入力台帳.json", manifest)
    proof = {"確認日": "2026-11-05", "全件一致": not differences, "不一致数": len(differences),
             "不一致": differences, "入力予約SHA256": RESERVATION_SHA,
             "入力台帳SHA256": sha(WORK / "入力台帳.json"), "出典SHA256": bindings,
             "旧cacheSHA256": old_cache_pins, "旧cache不変": True,
             "対象場数": 66, "旧cache再構成場数": 60, "旧cache照合列数": 60 * len(FIELDS),
             "新cache場数": 6, "原入力走査回数": 66,
             "原行数": sum(e["raw_lines"] for e in entries),
             "JSON行数": sum(e["decoded_rows"] for e in entries), "状態数": sum(e["events"] for e in entries),
             "固定互換品質合計": dict(quality_total), "追加品質合計": dict(extended_total),
             "全場最上位キー": source_keys, "非null受信連番名候補": receive_candidates,
             "時計結論": "全予約原行を構造走査。候補の意味は別途解釈が必要。CurrentPriceTime/TradingVolumeTimeは受信時計ではなく、商品別原板行を跨商品順序に使えない。",
             "受信可用性": "価格時計strict事前でも実受信時点・共通順序を証明しない。遅延は入力規約上の仮定として別記する。",
             "呼値監査": "正のLast/bid/askが0.5pt格子上かを全行で検査。ゼロ/欠測は格子違反へ混ぜず別品質へ。",
             "LastとBBO": "Last値の足入力と、正数量かつask>bidの正常BBOによる約定可能性を分離。",
             "限月年月全場NK一致": all(a["NKと限月年月同値"] for a in audits),
             "予約対象外": reservation["対象外"], "予約対象外内容閲覧": False,
             "原板複製": False, "指標計算": False, "先着計算": False, "損益計算": False,
             "場別": audits}
    P.write_json(WORK / "入力監査.json", proof)
    (WORK / "途中点検.json").unlink()
    print(f"入力監査完了 66場 原{proof['原行数']} 状態{proof['状態数']} 差{len(differences)} "
          f"台帳SHA={proof['入力台帳SHA256']} 監査SHA={sha(WORK / '入力監査.json')}", flush=True)
    assert not differences, "入力監査に不一致あり。保存証明を確認し再起動しないこと。"


# ----------------------------------------
# 実データを開かない人工確認

def artificial() -> dict:
    """
    機能: 原順保持・NaN・同一省略・全階層キー・時計後退・限月抽出を人工だけで確認する。
    引数: なし。
    返り値: dict は成功件数。
    """
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        rows = []
        base = {"Symbol": "161120005", "SymbolName": "TOPIX先物 26/12", "Exchange": 2,
                "ExchangeName": "大阪", "CurrentPriceTime": "2026-09-21T08:45:01+09:00",
                "TradingVolumeTime": "2026-09-21T08:45:01+09:00", "CurrentPrice": 3000.0,
                "TradingVolume": 10, "Buy1": {"Price": 2999.5, "Qty": 2}, "Sell1": {"Price": 3000.0, "Qty": 2}}
        rows.append(base)
        rows.append(dict(base))
        changed = {**base, "TradingVolume": 11, "late": {"receiveTime": "2026-09-21T08:45:02+09:00", "sequence": 3}}
        rows.append(changed)
        rows.append({**base, "CurrentPriceTime": "2026-09-21T08:45:00+09:00", "CurrentPrice": None})
        source = folder / "book.jsonl"
        source.write_bytes(b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n" for row in rows))
        entry, arrays, audit = scan(source, "2026-09-21_Day")
        assert arrays["line"].tolist() == [1, 3, 4]
        assert len(arrays["now"]) == 3 and entry["omitted_identical"] == 1
        assert math.isnan(arrays["last"][-1])
        assert audit["追加品質件数"]["価格時計後退"] == 1
        assert "$.late" in audit["全payload"]["辞書階層"]
        assert "$.late.receiveTime" in audit["全payload"]["非null受信連番名候補"]
        assert month_values(entry["contract_names"]) == ["2026-12"]
        expected = P.build_one(source, folder / "fixed.npz", "TOPIX", "2026-09-21_Day", folder)
        assert all(item["厳密同値"] for item in arrays_equal(arrays, folder / "fixed.npz").values())
        for key in ("raw_lines", "decoded_rows", "events", "omitted_identical", "quality", "sha256_uncompressed"):
            assert entry[key] == expected[key]
    return {"成功": True, "人工項目": 9, "原入力閲覧": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="予約TOPIX66の入力だけを一回監査する")
    parser.add_argument("--実行許可", action="store_true")
    parser.add_argument("--人工確認", action="store_true")
    arguments = parser.parse_args()
    if arguments.人工確認:
        print(json.dumps(artificial(), ensure_ascii=False))
    elif arguments.実行許可:
        run()
    else:
        parser.error("--実行許可 または --人工確認 が必要")
