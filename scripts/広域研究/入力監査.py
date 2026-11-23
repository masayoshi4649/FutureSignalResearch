"""旧NK225入力を維持し、新4場の品質監査・キャッシュ準備だけを行う。"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import struct
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))
OLD_MANIFEST = ROOT / "study/00002_複数時間足と四系統の要因比較/入力台帳.json"
PREPARATION = ROOT / "scripts/複合検証/データ準備.py"
RESTORATION = ROOT / "scripts/複合検証/キャッシュ復元.py"
NEW_SESSIONS = ("2026-11-02_Day", "2026-11-02_Night", "2026-11-03_Day", "2026-11-03_Night")
DEFAULT_STUDY = ROOT / "study/00006_外部手法を1分3分5分で比較"


def sha(path: Path) -> str:
    """小型台帳・コード・キャッシュのSHA256を計算する。

    引数: path (Path) は読み取り対象。
    返り値: str はSHA256の16進表記。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expanded_sha(path: Path) -> tuple[str, int]:
    """新たに追加されたgzipの展開内容を、小さな塊で検査する。

    引数: path (Path) はgzip原板。非圧縮の旧原板は再走査しない。
    返り値: tuple[str, int] は展開SHA256と展開バイト数。CRC不正・途中切断は例外。
    """
    digest, size = hashlib.sha256(), 0
    with gzip.open(path, "rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def write_json(path: Path, value: Any) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON化可能な内容。
    返り値: None。非有限数は保存しない。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_preparation(expected: str) -> Any:
    """旧台帳と同じ版の原板準備コードだけを読み込む。

    引数: expected (str) は正式台帳の準備コードSHA256。
    返り値: Any はbuild_one/read_events等を持つ既存モジュール。
    """
    if sha(PREPARATION) != expected:
        raise ValueError("旧正式台帳の準備コードSHA256と現物が異なる")
    specification = importlib.util.spec_from_file_location("広域研究の固定入力準備", PREPARATION)
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


# ----------------------------------------
# ファイル構成と旧60場。価格値・価格方向は集計・表示しない。

def inventory(data_root: Path, old: dict[str, Any]) -> dict[str, Any]:
    """両指数のフォルダ名・ファイルサイズ・更新日時だけを列挙する。

    引数: data_root (Path) は原板ルート、old (dict[str, Any]) は旧正式台帳。
    返り値: dict[str, Any] は追加場名とファイル形式の一覧。
    """
    result = {}
    for symbol in ("NK225", "TOPIX"):
        previous = {entry["session"] for entry in old["entries"] if entry["symbol"] == symbol}
        folders = sorted(path for path in (data_root / symbol).iterdir() if path.is_dir())
        extra = []
        for folder in folders:
            if folder.name not in previous:
                extra.append({"場": folder.name, "ファイル": [
                    {"名前": path.name, "サイズ": path.stat().st_size, "更新ns": path.stat().st_mtime_ns}
                    for path in sorted(folder.iterdir()) if path.is_file()]})
        result[symbol] = {"フォルダ数": len(folders), "最初": folders[0].name,
                          "最後": folders[-1].name, "新規場": extra}
    return result


def audit_old(entries: list[dict[str, Any]], data_root: Path, cache_root: Path) -> list[dict[str, Any]]:
    """固定採用元・キャッシュを検証し、後から追加されたgzipだけ展開SHAを照合する。

    引数: entries (list[dict[str, Any]]) は旧NK60場、data_root/cache_root (Path) は固定入力ルート。
    返り値: list[dict[str, Any]] は各場の品質証跡。不一致は停止する。
    """
    result = []
    for entry in entries:
        source = data_root / entry["source_path"]
        status = source.stat()
        if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
            raise ValueError(f"旧固定原板のstatが変わった: {source}")
        target = cache_root / entry["cache_path"]
        if target.stat().st_size != entry["cache_size"] or sha(target) != entry["sha256_cache"]:
            raise ValueError(f"旧固定キャッシュが変わった: {target}")
        raw, compressed = source.parent / "book.jsonl", source.parent / "book.jsonl.gz"
        pair = {"rawあり": raw.is_file(), "gzipあり": compressed.is_file()}
        if raw.is_file() and compressed.is_file():
            with compressed.open("rb") as stream:
                stream.seek(-4, 2)
                expanded_size_mod = struct.unpack("<I", stream.read(4))[0]
            pair.update({"rawサイズ": raw.stat().st_size, "raw更新ns": raw.stat().st_mtime_ns,
                         "gzipサイズ": compressed.stat().st_size, "gzip更新ns": compressed.stat().st_mtime_ns,
                         "gzip展開長mod2^32": expanded_size_mod,
                         "rawサイズと展開長整合": raw.stat().st_size % (2 ** 32) == expanded_size_mod,
                         "rawがgzipより新しい": raw.stat().st_mtime_ns > compressed.stat().st_mtime_ns})
            if not pair["rawサイズと展開長整合"] or pair["rawがgzipより新しい"]:
                raise ValueError(f"raw/gzipの更新または長さが要調査: {source.parent}")
            if source.suffix != ".gz":
                current, length = expanded_sha(compressed)
                pair.update({"後から追加gzipの展開SHA256": current, "展開バイト数": length,
                             "旧固定raw展開SHA256一致": current == entry["sha256_uncompressed"]})
                if not pair["旧固定raw展開SHA256一致"]:
                    raise ValueError(f"追加gzipが固定rawと不一致: {compressed}")
                print(f"旧追加gzip確認 {entry['session']} 展開SHA一致", flush=True)
            else:
                pair["内容比較の範囲"] = "採用gzipのstat不変とキャッシュSHAを確認。非採用rawの内容同一性は長さ・更新順だけでは証明しない。"
        result.append({"場": entry["session"], "固定採用元": entry["source_path"],
                       "採用元stat一致": True, "固定キャッシュSHAサイズ一致": True,
                       "元展開SHA256_固定台帳参照": entry["sha256_uncompressed"],
                       "旧raw本文の全量再読": False, "raw_gzip比較": pair})
    return result


# ----------------------------------------
# 新4場のCSVは品質の真偽・時計だけを記録する。OHLC値や数量値を保存しない。

def audit_csv(path: Path, minutes: int, session: str) -> dict[str, Any]:
    """分足CSVの列・時計・closed・volume_complete・欠区間を確認する。

    引数: path (Path) はCSV、minutes (int) は1または5、session (str) は場名。
    返り値: dict[str, Any] は値を含まない形式・時間被覆・完結フラグの監査。
    """
    date = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        start, end = date.replace(hour=8, minute=45), date.replace(hour=15, minute=40)
    else:
        start, end = date.replace(hour=17), (date + timedelta(days=1)).replace(hour=5, minute=55)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns, rows = reader.fieldnames, list(reader)
    expected_columns = ["time", "open", "high", "low", "close", "volume", "volume_complete", "closed"]
    if columns != expected_columns:
        raise ValueError(f"新CSVの列が変わった: {path}")
    clocks, closed, complete = [], Counter(), Counter()
    for row in rows:
        stamp = datetime.fromisoformat(row["time"])
        if stamp.utcoffset() is None:
            raise ValueError("新CSVに時差なし時計")
        clocks.append(stamp)
        closed[row["closed"]] += 1
        complete[row["volume_complete"]] += 1
    width = minutes * 60
    regular = {int((stamp - start).total_seconds() // width) for stamp in clocks if start <= stamp < end}
    expected_count = int((end - start).total_seconds() // width)
    duplicates = len(clocks) - len(set(clocks))
    backward = sum(after < before for before, after in zip(clocks, clocks[1:]))
    aligned = all((stamp - start).total_seconds() % width == 0 for stamp in clocks)
    return {"ファイル": path.name, "SHA256": sha(path), "行数": len(rows), "列": columns,
            "先頭時計": clocks[0].isoformat() if clocks else None,
            "最終時計": clocks[-1].isoformat() if clocks else None,
            "時計重複": duplicates, "時計後退": backward, "区間整列": aligned,
            "closed内訳": dict(closed), "volume_complete内訳": dict(complete),
            "ザラバ期待区間": expected_count, "ザラバ観測区間": len(regular),
            "ザラバ欠区間": expected_count - len(regular),
            "ザラバ終端以後のCSV行数": sum(stamp >= end for stamp in clocks),
            "完全性の境界": "closed=trueは足の確定フラグ。収集漏れ・遅着不存在や全約定の完全性を保証しない。volume_completeは生成器の累積基準の状態。"}


def light_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """正式台帳へ足別数量の中間列を複製しない形へ変換する。

    引数: entry (dict[str, Any]) はbuild_oneの返り値。
    返り値: dict[str, Any] は入力識別・集計品質を保持した複製。
    """
    result = copy.deepcopy(entry)
    result["volume_audit"].pop("five_minute_bars", None)
    return result


def run(study: Path, output: Path, cache_root: Path) -> None:
    """旧60を固定維持し、指定4入力だけを準備して正式64場台帳を作る。

    引数: study/output/cache_root (Path) は正式試行・作業監査・共通キャッシュ。
    返り値: None。原板・旧台帳・旧キャッシュを変更せず、新4場の特徴や結果を計算しない。
    """
    old = json.loads(OLD_MANIFEST.read_text(encoding="utf-8"))
    data_root = Path(old["source_root"])
    entries = copy.deepcopy([entry for entry in old["entries"] if entry["symbol"] == "NK225"])
    if len(entries) != 60:
        raise ValueError("旧NK入力が60場でない")
    preparation = load_preparation(old["データ準備コードSHA256"])
    folders = inventory(data_root, old)
    old_checks = audit_old(entries, data_root, cache_root)
    manifest_path = study / "入力台帳.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    previous_by_session = {entry["session"]: entry for entry in previous["entries"]} if previous else {}
    new_quality = []
    for session in NEW_SESSIONS:
        prior = previous_by_session.get(session)
        folder = data_root / "NK225" / session
        if prior is None:
            source = folder / "book.jsonl.gz"
            if not source.is_file():
                source = folder / "book.jsonl"
            cache = cache_root / "キャッシュ/NK225" / f"{session}.npz"
            if cache.exists():
                raise FileExistsError(f"正式台帳未登録の既存キャッシュは上書きしない: {cache}")
            entry = light_entry(preparation.build_one(source, cache, "NK225", session, data_root))
        else:
            entry = copy.deepcopy(prior)
            source = data_root / entry["source_path"]
            status = source.stat()
            if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
                raise ValueError("固定した新4入力が変わった")
            cache = cache_root / entry["cache_path"]
            if cache.stat().st_size != entry["cache_size"] or sha(cache) != entry["sha256_cache"]:
                raise ValueError("固定した新4キャッシュが変わった")
        entries.append(entry)
        raw = folder / "book.jsonl"
        with raw.open("rb") as stream:
            stream.seek(-1, 2)
            final_newline = stream.read(1) == b"\n"
        new_quality.append({"場": session, "採用元": entry["source_path"], "採用元サイズ": entry["source_size"],
                            "採用元更新ns": entry["source_mtime_ns"], "原板行数": entry["raw_lines"],
                            "JSONオブジェクト行数": entry["decoded_rows"], "末尾改行あり": final_newline,
                            "展開SHA256": entry["sha256_uncompressed"], "キャッシュサイズ": entry["cache_size"],
                            "キャッシュSHA256": entry["sha256_cache"], "状態数": entry["events"],
                            "限月コード": entry["contract_codes"], "場内限月コード": entry["in_session_contract_codes"],
                            "原板品質": entry["quality"], "数量品質": entry["volume_audit"],
                            "CSV品質": [audit_csv(folder / f"candle_{minutes}min.csv", minutes, session) for minutes in (1, 5)],
                            "保留": "キャッシュは入力準備のみ。後続の選択固定前に特徴・方向・ラベル・損益のengineへロードしない。"})
        print(f"新入力品質準備 {session} 原板{entry['raw_lines']}行 キャッシュ{entry['cache_size']}B", flush=True)

    # ----------------------------------------
    # 台帳の旧60entryは辞書内容まで不変とし、後続4場を明示的に分ける。
    if entries[:60] != [entry for entry in old["entries"] if entry["symbol"] == "NK225"]:
        raise AssertionError("旧60entryを書き換えている")
    current = {"schema_version": 1, "created_at_jst": previous["created_at_jst"] if previous else datetime.now(JST).isoformat(),
               "source_root": str(data_root), "entries": entries, "Python": platform.python_version(),
               "numpy": preparation.np.__version__, "JSON読取": f"orjson {preparation.orjson.__version__}" if preparation.orjson else "標準json",
               "cache_columns": old["cache_columns"], "キャッシュ親": cache_root.relative_to(ROOT).as_posix(),
               "データ準備コードSHA256": sha(PREPARATION), "入力監査コードSHA256": sha(Path(__file__)),
               "元台帳": OLD_MANIFEST.relative_to(ROOT).as_posix(), "元台帳SHA256": sha(OLD_MANIFEST),
               "入力区分": {"既使用": [entry["session"] for entry in entries[:60]], "選択後まで保留": list(NEW_SESSIONS)},
               "用途": "旧NK60場を固定維持し、新NK4場は品質と入力固定だけを実施。新4場のラベル・特徴・方向傾向・損益は未確認。"}
    if previous is not None and previous != current:
        raise ValueError("既存00006台帳と再生成内容が異なる。上書きせず入力版を確認する")
    if previous is None:
        write_json(manifest_path, current)
    api_notes = {
        "cache": {"path": PREPARATION.relative_to(ROOT).as_posix(), "API": "read_events(path) -> Iterator[Event]",
                  "列": ["now", "line", "last", "bid", "ask", "valid", "volume", "volume_time"],
                  "意味": "価格時計Unix秒・原始物理行・Last・Buy1(Bid)・Sell1(Ask)・正常価格と両Qty>=1の真偽・累積数量・数量時計。完全同一連続状態だけ省略。"},
        "復元": {"path": RESTORATION.relative_to(ROOT).as_posix(), "API": "run(manifest_path,output,limit)",
                 "確認": "正式台帳source_pathを固定。準備コードSHA、採用元stat、既存cacheSHA、再生成時の展開SHA/cacheSHAを検証。"},
        "既存Python集約": {"path": "scripts/複合検証/再生.py", "API": "複数時間足/時間足指標/replay_session",
                          "限界": "5分→15/30分固定。入口分析candidate_rowsも5分固定で、1/3/5分の汎用engineではない。"},
        "Viewer": {"path": "../SessionTradeViewer/bars.go,data_io.go", "API": "GET /api/data または /api/chart の interval=raw|1|5|15、price=last|bid|ask|mid",
                   "限界": "3分は未対応。readMarketは価格時計原順・後退除外、Qtyの正常性はキャッシュvalidほど検査しない。表示分足を検証入力として逆用しない。"},
        "収集CSV": {"path": "../kabus-controller/future_history_candles.go", "API": "Apply/Advance/updateFive",
                    "限界": "受信時刻で1/5分を確定し、原板には受信時刻が残らない。既存CSVと価格時計再集約は一致保証がない。3分はない。"},
        "新集約への注意": "1/3/5分ともsession開始基準の半開区間を定義し、欠足補完・同時計順・確定利用時刻を明示。3分はDay415分/Night775分が割り切れず、末尾1分の部分足が生じる。未完部分を完全3分足と呼ばない。"}
    payload = {"確認日時": datetime.now(JST).isoformat(), "対象": "旧NK60入力と新NK4入力。TOPIXは追加フォルダと形式の列挙のみ。",
               "新4場への制約": "価格値・価格方向・到達ラベル・特徴・損益は集計表示していない。品質の時刻・件数・形式だけを報告する。",
               "原板を変更": False, "旧キャッシュを変更": False, "旧採用元stat全一致": True, "旧キャッシュSHA全一致": True,
               "旧raw全SHAの再読": "実施しない。stat不変を確認し、後から追加された7gzipだけ展開SHAを旧固定rawのSHAへ照合。53採用gzipの本文SHAは今回再計算していない。",
               "フォルダ一覧": folders, "旧60入力": old_checks, "新4品質": new_quality,
               "正式入力台帳": manifest_path.relative_to(ROOT).as_posix(), "正式入力台帳SHA256": sha(manifest_path),
               "入力数": len(entries), "旧キャッシュ合計B": sum(entry["cache_size"] for entry in entries[:60]),
               "新キャッシュ合計B": sum(entry["cache_size"] for entry in entries[60:]),
               "cache復元と足API": api_notes,
               "ソースSHA256": {path.relative_to(ROOT).as_posix(): sha(path) for path in (Path(__file__), PREPARATION, RESTORATION, OLD_MANIFEST)}}
    write_json(output / "入力監査.json", payload)
    print(json.dumps({"旧場数": 60, "追加場数": 4, "旧stat/cache一致": True,
                      "新cache合計B": payload["新キャッシュ合計B"], "新場の価格方向ラベル損益": "未確認・保留"}, ensure_ascii=False), flush=True)


def main() -> None:
    """00006の品質限定入力準備を実行する。

    引数: なし。CLIから正式試行・作業監査・共通cacheの親を取得する。
    返り値: None。新4場の特徴や成績を計算しない。
    """
    parser = argparse.ArgumentParser(description="旧NK60固定維持と新4場の品質限定入力準備")
    parser.add_argument("--study", type=Path, default=DEFAULT_STUDY)
    parser.add_argument("--output", type=Path, default=ROOT / "work/広域研究")
    parser.add_argument("--cache-root", type=Path, default=ROOT / "work/複合検証")
    args = parser.parse_args()
    run(args.study.resolve(), args.output.resolve(), args.cache_root.resolve())


if __name__ == "__main__":
    main()
