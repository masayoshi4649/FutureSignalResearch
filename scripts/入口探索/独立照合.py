"""固定入口を任意の順逆行幅で再ラベルした結果を、気配の直接比較で独立照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))
FIELDS = ("now", "line", "last", "bid", "ask", "valid", "volume", "volume_time")
RESULT_NUMBERS = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行",
                  "判定気配", "最大順行pt", "最大逆行pt", "所要分")


def file_sha(path: Path) -> str:
    """小型成果物またはキャッシュのSHA256を計算する。

    引数: path (Path) は読み取り対象。原板本文には使わない。
    返り値: str はSHA256の16進表記。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def show_path(path: Path) -> str:
    """成果物内へ記録するパスを可能なら研究ルートからの相対表記にする。

    引数: path (Path) は表示対象。
    返り値: str は相対または絶対のパス。
    """
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def session_times(session: str) -> tuple[float, float, float, float]:
    """固定された場内・新規停止・評価期限を独立に求める。

    引数: session (str) は開始日基準のYYYY-MM-DD_DayまたはNight。
    返り値: tuple[float, float, float, float] は開始、ザラバ終了、新規停止、期限のUnix秒。
    """
    day, part = session.split("_")
    date = datetime.fromisoformat(day).replace(tzinfo=JST)
    if part == "Day":
        values = (date.replace(hour=8, minute=45), date.replace(hour=15, minute=40),
                  date.replace(hour=15, minute=25), date.replace(hour=15, minute=35))
    elif part == "Night":
        following = date + timedelta(days=1)
        values = (date.replace(hour=17), following.replace(hour=5, minute=55),
                  following.replace(hour=5, minute=40), following.replace(hour=5, minute=50))
    else:
        raise ValueError(f"未対応の場名: {session}")
    return tuple(value.timestamp() for value in values)


def read_manifest(study: Path) -> tuple[dict[str, Any], Path]:
    """入力台帳の内容ハッシュ付き参照を、本体を読み込まず解決する。

    引数: study (Path) は今回の試行フォルダ。
    返り値: tuple[dict[str, Any], Path] は台帳内容と実体パス。
    """
    path = study / "入力台帳.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if "参照" in value:
        path = (path.parent / value["参照"]).resolve()
        if file_sha(path) != value["SHA256"]:
            raise ValueError("参照入力台帳のSHA256が不一致")
        value = json.loads(path.read_text(encoding="utf-8"))
    keys = [(entry["symbol"], entry["session"]) for entry in value["entries"]]
    if len(keys) != len(set(keys)) or keys != sorted(keys):
        raise ValueError("入力台帳の指数・場が重複または順序不正")
    return value, path


# ----------------------------------------
# キャッシュからの正常板抽出。分析.pyおよび既存の再生・判定処理は読み込まない。

def load_quotes(path: Path, entry: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[int, float], dict[str, int]]:
    """原順・場内・非後退で選別してから、正常板だけを独立に抽出する。

    引数: path (Path) は固定npz、entry (dict[str, Any]) は対応する入力台帳行。
    返り値: tuple は正常板4列、採用原行から時計への辞書、選別件数。
    """
    if path.stat().st_size != entry["cache_size"] or file_sha(path) != entry["sha256_cache"]:
        raise ValueError(f"キャッシュのサイズまたはSHA256が不一致: {path}")
    start, end, _, _ = session_times(entry["session"])
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != set(FIELDS):
            raise ValueError("キャッシュの8列が不一致")
        arrays = {key: archive[key] for key in FIELDS}
    if any(array.ndim != 1 for array in arrays.values()):
        raise ValueError("キャッシュが1次元列でない")
    lengths = {len(array) for array in arrays.values()}
    if lengths != {entry["events"]}:
        raise ValueError("キャッシュ列長が台帳と不一致")
    lines, now = arrays["line"], arrays["now"]
    if len(lines) and (lines[0] < 1 or lines[-1] > entry["raw_lines"] or np.any(np.diff(lines) <= 0)):
        raise ValueError("キャッシュの原行番号が非増加または範囲外")

    # ----------------------------------------
    # 時計選別は不正板も含めて行い、後から正常板へ絞る。
    positions = np.flatnonzero(np.isfinite(now) & (now >= start) & (now <= end))
    times = now[positions]
    if len(times):
        keep = np.r_[True, times[1:] >= np.maximum.accumulate(times[:-1])]
        positions = positions[keep]
    request_clocks = {int(lines[index]): float(now[index]) for index in positions}
    normal = positions[arrays["valid"][positions].astype(bool)]
    quotes = {key: arrays[key][normal] for key in ("now", "line", "bid", "ask")}
    if not len(normal):
        raise ValueError("場内の正常板がない")
    if not (np.all(np.isfinite(quotes["bid"])) and np.all(np.isfinite(quotes["ask"]))
            and np.all(quotes["bid"] > 0) and np.all(quotes["ask"] > quotes["bid"])):
        raise ValueError("キャッシュvalidと正常BBO価格が矛盾")
    quality = {"キャッシュ状態": len(now), "場内非後退状態": len(positions), "正常板": len(normal),
               "正常板価格時計300秒超空白": int(np.count_nonzero(np.diff(quotes["now"]) > 300))}
    return quotes, request_clocks, quality


def label_direct(quotes: dict[str, np.ndarray], signal: float, cutoff: float, deadline: float,
                 side: int, adverse: float = 200, favorable: float = 400,
                 wait: float = 1, ttl: float = 30, allowed_gap: float = 300) -> dict[str, Any]:
    """全返済気配を直接比較して、最初の閾値到達・空白・期限を判定する。

    引数: quotes (dict[str, np.ndarray]) は原順の正常板4列、signal/cutoff/deadline (float) は時計秒、
    side (int) は買い1・売り-1、adverse/favorable (float) は価格幅、wait/ttl/allowed_gap (float) は秒。
    返り値: dict[str, Any] は新規・最終採用観測とラベル、追跡範囲だけのMFE/MAE。
    """
    if side not in (1, -1) or min(adverse, favorable) <= 0:
        raise ValueError("方向または価格幅が不正")
    result = {"ラベル": "未約定", "理由": "30秒内に正常板なし", **{key: None for key in RESULT_NUMBERS}}
    now = quotes["now"]
    possible = np.flatnonzero(now >= signal + wait)
    if not len(possible):
        return result
    first = int(possible[0])
    if now[first] > signal + ttl or now[first] >= cutoff:
        return result
    if deadline < now[first]:
        raise ValueError("新規時計より評価期限が前")
    entry = float(quotes["ask"][first] if side == 1 else quotes["bid"][first])
    mark = quotes["bid"] if side == 1 else quotes["ask"]

    # ----------------------------------------
    # 期限の等号を含む全観測を一括比較し、最初の到達位置を取り出す。
    in_time = np.flatnonzero(now[first:] <= deadline)
    last_in_time = first + int(in_time[-1])
    distances = side * (mark[first:last_in_time + 1] - entry)
    crossings = np.flatnonzero((distances <= -adverse) | (distances >= favorable))
    hit = first + int(crossings[0]) if len(crossings) else None

    # ----------------------------------------
    # 次の観測が期限後でも、期限前に300秒を超える空白が先に始まれば不明。
    left_times = now[first:-1]
    long_gaps = np.flatnonzero((np.diff(now[first:]) > allowed_gap) & (left_times + allowed_gap < deadline))
    gap_left = first + int(long_gaps[0]) if len(long_gaps) else None
    if hit is not None and (gap_left is None or hit <= gap_left):
        last = hit
        label = "順行先着" if side * (float(mark[last]) - entry) >= favorable else "逆行先着"
        reason = "返済気配の閾値初着"
    else:
        last = gap_left if gap_left is not None else last_in_time
        if gap_left is not None or deadline - now[last] > allowed_gap:
            label, reason = "観測不足", "正常板価格時計300秒超空白"
        elif now[-1] < deadline:
            label, reason = "観測不足", "入力末尾不足"
        else:
            label, reason = "期限未達", "期限内どちらも未到達"
    traced = side * (mark[first:last + 1] - entry)
    result.update({"ラベル": label, "理由": reason, "新規価格": entry,
                   "新規時計秒": float(now[first]), "新規原板行": int(quotes["line"][first]),
                   "判定時計秒": float(now[last]), "判定原板行": int(quotes["line"][last]),
                   "判定気配": float(mark[last]), "最大順行pt": float(max(0, np.max(traced))),
                   "最大逆行pt": float(max(0, -np.min(traced))),
                   "所要分": float((now[last] - now[first]) / 60)})
    return result


# ----------------------------------------
# CSV各行と原行参照の照合。指標値や条件群の再計算は対象にしない。

def number(value: str) -> float | None:
    """CSVの空欄を欠測、それ以外を有限数値として読む。

    引数: value (str) はCSVセル。
    返り値: float | None は有限数値または欠測。不正値は例外にする。
    """
    if value == "":
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("CSVへ非有限の数値が保存されている")
    return parsed


def compare(report: dict[str, Any], event: str, column: str, actual: Any, expected: Any,
            numeric: bool = False) -> None:
    """一つの照合を数え、不一致の先頭100例を記録する。

    引数: report (dict[str, Any]) は監査結果、event/column (str) は対象、
    actual/expected (Any) は実値と期待値、numeric (bool) は数値比較か。
    返り値: None。実データまたは分析成果物は変更しない。
    """
    report["照合項目数"] += 1
    if numeric and actual is not None and expected is not None:
        same = math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=1e-8)
    else:
        same = actual == expected
    if not same:
        report["不一致数"] += 1
        if len(report["不一致例"]) < 100:
            report["不一致例"].append({"イベントID": event, "列": column, "実値": actual, "期待値": expected})


def run(csv_path: Path, metadata_path: Path, output: Path, cache_root: Path) -> dict[str, Any]:
    """固定入口CSV・台帳とキャッシュから、新しい価格幅の全行を独立照合する。

    引数: csv_path/metadata_path/output (Path) は再ラベル表・メタ情報・照合結果、
    cache_root (Path) は固定キャッシュの親。
    返り値: dict[str, Any] は照合件数、入力証跡、不一致、監査範囲を含む結果。
    """
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    config = metadata["条件"]
    fixed = {"対象": "NK225", "正常板空白許容秒": 300, "新規待機秒": 1,
             "新規有効秒": 30, "確認遅延許容秒": 30, "入力場数": 60}
    if any(config.get(key) != value for key, value in fixed.items()) or min(config["逆行pt"], config["順行pt"]) <= 0:
        raise ValueError("独立照合が対応する時計・対象条件と不一致")
    adverse, favorable = float(config["逆行pt"]), float(config["順行pt"])
    study = ROOT / metadata["元試行"]
    source_csv = ROOT / metadata["元入口CSV"]
    for path, expected in metadata["入力SHA256"].items():
        if file_sha(ROOT / path) != expected:
            raise ValueError(f"固定入力のSHA256不一致: {path}")
    for path, expected in metadata["コードSHA256"].items():
        if file_sha(ROOT / path) != expected:
            raise ValueError(f"固定コードのSHA256不一致: {path}")
    if file_sha(csv_path) != metadata["出力CSV_SHA256"]:
        raise ValueError("再ラベルCSVのSHA256がメタ情報と不一致")
    manifest, manifest_path = read_manifest(study)
    entries = [entry for entry in manifest["entries"] if entry["symbol"] == "NK225"]
    if len(entries) != 60:
        raise ValueError("NK225の固定60場でない")
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    with source_csv.open(encoding="utf-8-sig", newline="") as source:
        originals = list(csv.DictReader(source))
    if len(rows) != len(originals) or len(rows) != metadata["固定入口行数"]:
        raise ValueError("再ラベルで入口の行数が変わっている")
    original_by_id = {row["イベントID"]: row for row in originals}
    if len(original_by_id) != len(originals):
        raise ValueError("元入口CSVのイベントIDが重複")
    by_session = defaultdict(list)
    for row in rows:
        by_session[row["場"]].append(row)
    sessions = {entry["session"] for entry in entries}
    if set(by_session) - sessions:
        raise ValueError("入力台帳に存在しない場がCSVにある")
    report = {"確認日時": datetime.now(JST).isoformat(), "一致": False, "照合項目数": 0,
              "不一致数": 0, "不一致例": [], "入口事例数": len(rows), "入力場数": len(entries),
              "Python": platform.python_version(), "NumPy": np.__version__, "場別": [], "入力コードSHA256一致": True,
              "条件": config,
              "方法": "ラベル準備.py・分析.py・再生コードを読み込まず、npzの場内非後退正常板を抽出。全返済気配を新しい順逆行幅で直接比較。区間木は使用しない。",
              "判定時計の意味": "閾値到達時はhit時計。それ以外は打切りまで最後に採用した正常板時計で、期限時計とは別。",
              "範囲": "元入口からの行順・全不変列・入口情報の保持、新規待機・有効期限・発動遅延、要求原行、新規と判定の原行/時計/気配、先着ラベル、MFE/MAE、新価格幅・ATR比・閾値/JSTを全行照合。",
              "限界": "特徴量・条件群・共通有効足の完全列挙は再計算しない。原板本文の再走査・SHA再計算はせず入力statとキャッシュSHAを確認。真の未観測経路・受信時刻・実約定可能性を立証しない。",
              "ファイルSHA256": {show_path(path): file_sha(path) for path in
                                   (Path(__file__), metadata_path, csv_path, source_csv, study / "入力台帳.json", manifest_path)}}
    compare(report, "全体", "元入口の行順", [row["イベントID"] for row in rows], [row["イベントID"] for row in originals])
    seen = set()
    pairs = defaultdict(list)
    labels_by_scope = defaultdict(Counter)
    for entry in entries:
        session = entry["session"]
        source_path = Path(manifest["source_root"]) / entry["source_path"]
        status = source_path.stat()
        if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
            raise ValueError(f"凍結原板のstatが不一致: {source_path}")
        cache_path = cache_root / entry["cache_path"]
        quotes, request_clocks, quality = load_quotes(cache_path, entry)
        start, end, cutoff, deadline = session_times(session)
        session_labels = Counter()
        for row in by_session[session]:
            event = row["イベントID"]
            compare(report, event, "イベントID一意", event in seen, False)
            seen.add(event)
            original = original_by_id[event]
            changed = set(RESULT_NUMBERS) | {"ラベル", "理由", "逆行線", "順行線", "新規時計JST", "判定時計JST",
                                            "400ptのATR倍", "200ptのATR倍"}
            for key in original:
                if key not in changed:
                    compare(report, event, "固定入力列:" + key, row[key], original[key])
            for key in ("新規価格", "新規時計秒", "新規原板行"):
                compare(report, event, "固定入口:" + key, number(row[key]), number(original[key]), True)
            compare(report, event, "旧価格幅列がない", "400ptのATR倍" not in row and "200ptのATR倍" not in row, True)
            compare(report, event, "順行幅pt", number(row["順行幅pt"]), favorable, True)
            compare(report, event, "逆行幅pt", number(row["逆行幅pt"]), adverse, True)
            compare(report, event, "順行幅のATR倍", number(row["順行幅のATR倍"]), favorable / float(row["ATR5"]), True)
            compare(report, event, "逆行幅のATR倍", number(row["逆行幅のATR倍"]), adverse / float(row["ATR5"]), True)
            side = int(row["side"])
            if side not in (1, -1):
                raise ValueError("CSVのsideが買い1・売り-1以外")
            signal, bar_end = float(row["要求時計秒"]), float(row["足終了時計秒"])
            request_line = int(row["要求原板行"])
            index = (bar_end - start) / 300 - 1
            compare(report, event, "足終了の場内5分整列", start < bar_end < end and index.is_integer(), True)
            compare(report, event, "イベントID構成", event, f"NK225_{session}_{int(index):03d}_{side}")
            compare(report, event, "方向", row["方向"], "買い" if side == 1 else "売り")
            compare(report, event, "要求原行の価格時計", request_clocks.get(request_line), signal, True)
            compare(report, event, "要求時計の場内・足終了後", bar_end <= signal < cutoff, True)
            compare(report, event, "新規停止時計秒", number(row["新規停止時計秒"]), cutoff, True)
            compare(report, event, "期限時計秒", number(row["期限時計秒"]), deadline, True)
            delay = signal - bar_end
            late = delay > 30
            compare(report, event, "確認遅延秒", number(row["確認遅延秒"]), delay, True)
            compare(report, event, "発動遅延超過", row["発動遅延超過"], str(late))
            pairs[(session, bar_end)].append((side, signal, request_line))

            # ----------------------------------------
            # 遅延超過は新規せず、その他は正常板の直接検索で検算する。
            if late:
                expected = {"ラベル": "未約定", "理由": "足確定確認が30秒超", **{key: None for key in RESULT_NUMBERS}}
            else:
                expected = label_direct(quotes, signal, cutoff, deadline, side, adverse=adverse, favorable=favorable)
            for key in ("ラベル", "理由"):
                compare(report, event, key, row[key], expected[key])
            for key in RESULT_NUMBERS:
                compare(report, event, key, number(row[key]), expected[key], True)
            for key, width in (("逆行線", -adverse), ("順行線", favorable)):
                threshold = None if expected["新規価格"] is None else expected["新規価格"] + side * width
                compare(report, event, key, number(row[key]), threshold, True)
            for clock in ("要求時計秒", "新規時計秒", "判定時計秒"):
                value = signal if clock == "要求時計秒" else expected[clock]
                text = "" if value is None else datetime.fromtimestamp(value, JST).isoformat()
                compare(report, event, clock.replace("秒", "JST"), row[clock.replace("秒", "JST")], text)
            scope = "学習40場" if session[:10] <= "2026-10-16" else ("条件選択10場" if session[:10] <= "2026-10-23" else "後続検査10場")
            if scope != "後続検査10場":
                labels_by_scope[scope][expected["ラベル"]] += 1
            session_labels[expected["ラベル"]] += 1
        report["場別"].append({"場": session, "入口事例数": len(by_session[session]),
                                "独立判定内訳": dict(session_labels) if session[:10] <= "2026-10-23" else "最終選択固定前の後続成績は表示しない。", "品質": quality,
                                "キャッシュ": show_path(cache_path), "キャッシュSHA256": entry["sha256_cache"],
                                "原板stat一致": True})
        print(f"独立照合 {len(report['場別'])}/{len(entries)} {session} 事例{len(by_session[session])}", flush=True)

    # ----------------------------------------
    # 同じ確定機会の買い・売りが揃い、要求時計と原行も一致するか確認する。
    for (session, bar_end), pair in pairs.items():
        event = f"{session}/{datetime.fromtimestamp(bar_end, JST).isoformat()}"
        compare(report, event, "同一機会の買い売り対", sorted(item[0] for item in pair), [-1, 1])
        compare(report, event, "同一機会の要求一致", len({item[1:] for item in pair}), 1)
    compare(report, "全体", "空の入口事例でない", bool(rows), True)
    report["独立判定内訳_報告可能範囲"] = {scope: dict(counts) for scope, counts in labels_by_scope.items()}
    report["後続検査10場"] = "全行を照合するが、最終選択固定前はラベル内訳を表示しない。"
    report["買い売り機会数"] = len(pairs)
    report["一致"] = report["不一致数"] == 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


# ----------------------------------------
# 実データを読まない境界条件の手計算確認。

def self_test() -> None:
    """直接判定の等号・先着・待機・空白・EOFを小さな合成経路で検算する。

    引数: なし。外部データや分析.pyは使用しない。
    返り値: None。不一致があればAssertionErrorにする。
    """
    cases = [
        ("買い順行等号後の逆行を無視", [(1, 995, 1000), (2, 1400, 1405), (3, 700, 705)], 1, 10, 100, "順行先着", 2, 400, 5),
        ("売り順行等号", [(1, 1000, 1005), (2, 595, 600), (3, 1295, 1300)], -1, 10, 100, "順行先着", 2, 400, 5),
        ("最初の正常板から逆行等号", [(1, 800, 1000), (2, 1400, 1405)], 1, 10, 100, "逆行先着", 1, 0, 200),
        ("1秒未満は入口にしない", [(0.5, 1, 2), (1, 995, 1000), (2, 800, 805)], 1, 10, 100, "逆行先着", 2, 0, 200),
        ("期限の等号は到達対象", [(1, 995, 1000), (100, 1400, 1405)], 1, 10, 100, "順行先着", 100, 400, 5),
        ("300秒ちょうどの空白", [(1, 995, 1000), (301, 1400, 1405)], 1, 10, 400, "順行先着", 301, 400, 5),
        ("300秒超空白が到達より先", [(1, 995, 1000), (302, 1400, 1405)], 1, 10, 400, "観測不足", 1, 0, 5),
        ("期限前のEOF", [(1, 995, 1000), (10, 1010, 1015)], 1, 20, 100, "観測不足", 10, 10, 5),
        ("期限まで300秒なら次観測が遅くても未達", [(1, 995, 1000), (400, 1000, 1005)], 1, 10, 301, "期限未達", 1, 0, 5),
    ]
    for name, values, side, cutoff, deadline, label, at, mfe, mae in cases:
        quotes = {"now": np.array([row[0] for row in values]), "line": np.arange(1, len(values) + 1),
                  "bid": np.array([row[1] for row in values]), "ask": np.array([row[2] for row in values])}
        result = label_direct(quotes, 0, cutoff, deadline, side)
        assert result["ラベル"] == label, (name, result)
        assert result["判定時計秒"] == at, (name, result)
        assert result["最大順行pt"] == mfe and result["最大逆行pt"] == mae, (name, result)
    quotes = {"now": np.array([30.]), "line": np.array([1]), "bid": np.array([995.]), "ask": np.array([1000.])}
    assert label_direct(quotes, 0, 31, 100, 1)["新規時計秒"] == 30
    assert label_direct(quotes, 0, 30, 100, 1)["ラベル"] == "未約定"
    assert label_direct(quotes, -1, 100, 100, 1)["ラベル"] == "未約定"
    narrower = [
        ("125逆行等号", [(1, 995, 1000), (2, 875, 880), (3, 1250, 1255)], 1, "逆行先着", 2, 0, 125),
        ("250順行等号", [(1, 995, 1000), (2, 1250, 1255), (3, 875, 880)], 1, "順行先着", 2, 250, 5),
        ("売り125逆行等号", [(1, 1000, 1005), (2, 1120, 1125), (3, 745, 750)], -1, "逆行先着", 2, 0, 125),
        ("売り250順行等号", [(1, 1000, 1005), (2, 745, 750), (3, 1120, 1125)], -1, "順行先着", 2, 250, 5),
    ]
    for name, values, side, label, at, mfe, mae in narrower:
        quotes = {"now": np.array([row[0] for row in values]), "line": np.arange(1, len(values) + 1),
                  "bid": np.array([row[1] for row in values]), "ask": np.array([row[2] for row in values])}
        result = label_direct(quotes, 0, 10, 100, side, adverse=125, favorable=250)
        assert result["ラベル"] == label and result["判定時計秒"] == at, (name, result)
        assert result["最大順行pt"] == mfe and result["最大逆行pt"] == mae, (name, result)
    print("独立判定の合成検算16件が通過", flush=True)


def main() -> None:
    """試行の全件照合または外部データを使わない合成検算を選ぶ。

    引数: なし。CLIの--csv/--meta/--output/--cache-root/--self-testを取得する。
    返り値: None。不一致のある全件照合はJSON保存後に終了コード1にする。
    """
    parser = argparse.ArgumentParser(description="入口事例の全件独立照合")
    parser.add_argument("--csv", type=Path, default=ROOT / "work/入口探索/入口250_125.csv")
    parser.add_argument("--meta", type=Path, default=ROOT / "work/入口探索/ラベル準備メタ.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache-root", type=Path, default=ROOT / "work/複合検証")
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return
    output = arguments.output or arguments.csv.parent / "独立照合結果.json"
    report = run(arguments.csv.resolve(), arguments.meta.resolve(), output.resolve(), arguments.cache_root.resolve())
    print(json.dumps({"一致": report["一致"], "入口事例数": report["入口事例数"],
                      "照合項目数": report["照合項目数"], "不一致数": report["不一致数"]}, ensure_ascii=False))
    if not report["一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
