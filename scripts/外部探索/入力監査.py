"""外部固定commitの小型証拠と原板出典を照合し、新1場は品質だけ準備する。"""

from __future__ import annotations

from collections import Counter
import copy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/外部研究"
STUDY = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
OLD = ROOT / "study/00006_外部手法を1分3分5分で比較/入力台帳.json"
BASELINE = ROOT / "study/00002_複数時間足と四系統の要因比較/入力台帳.json"
COMMIT = "cf0717daa1eed78759f78a428bce50129e7f705b"
REPOSITORY = "masayoshi4649/FutureAlgorithmResearch"
NEW_SESSION = "2026-11-04_Day"
JST = timezone(timedelta(hours=9))


def sha(path: Path) -> str:
    """小型証拠とcacheのSHA256を求める。

    引数: path (Path) は入力。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    """UTF-8のJSONを読む。

    引数: path (Path) は入力。
    返り値: Any はJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: Any) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON化できる内容。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def blob_sha(body: bytes) -> str:
    """Git blobのオブジェクトIDを内容から検算する。

    引数: body (bytes) は取得したUTF-8本文。
    返り値: str はGitのSHA-1 blob ID。SHA256と区別する。
    """
    return hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()


def envelopes() -> tuple[dict, list[dict]]:
    """GitHub connectorで部分取得した小型ファイルの固定refとblob SHAを検証する。

    引数: なし。work/外部研究/取得の保存応答を使う。
    返り値: tuple[dict,list[dict]] は本文と出典一覧。
    """
    bodies, evidence = {}, []
    for path in sorted((WORK / "取得").glob("*.json")):
        data = read(path)
        if data["ref"] != COMMIT:
            raise ValueError("外部取得のrefが固定commitでない")
        body = data["content"].encode("utf-8")
        if blob_sha(body) != data["sha"]:
            raise ValueError(f"外部Git blobの本文が不一致: {path}")
        bodies[path.stem] = data["content"]
        evidence.append({"保存": path.relative_to(ROOT).as_posix(), "外部パス": data["path"],
                         "bytes": len(body), "Git_blob_SHA": data["sha"], "本文SHA256": hashlib.sha256(body).hexdigest(),
                         "URL": f"https://github.com/{REPOSITORY}/blob/{COMMIT}/{data['path']}"})
    return bodies, evidence


# ----------------------------------------
# 外部00170の原板SHAを既存入力版へ接合する。全巨大原板を再読しない。

def compare_external(bodies: dict, baseline: dict) -> dict:
    """外部入力114件のstat・全原行指紋・cache出典を比較する。

    引数: bodies (dict) は取得本文、baseline (dict) は旧00002台帳。
    返り値: dict は一致範囲と限界。不一致は停止する。
    """
    listing = json.loads(bodies["00170_input"])
    audit = json.loads(bodies["00170_audit"])
    original = {(entry["symbol"], entry["session"]): entry for entry in baseline["entries"]}
    audit_by_key = {(item["symbol"], item["session"]): item for item in audit}
    result = []
    for item in listing["files"]:
        key = item["symbol"], item["session"]
        entry, raw_audit = original[key], audit_by_key[key]
        raw = Path(baseline["source_root"]) / key[0] / key[1] / "book.jsonl"
        status = raw.stat()
        selected = Path(baseline["source_root"]) / entry["source_path"]
        selected_status = selected.stat()
        cache = ROOT / "work/複合検証" / entry["cache_path"]
        flags = {"外部raw参照パス一致": Path(item["path"]).resolve() == raw.resolve(),
                 "外部rawサイズ更新一致": (status.st_size, status.st_mtime_ns) == (item["bytes"], item["mtime_ns"]),
                 "外部全原行SHA一致": raw_audit["sha256"] == entry["sha256_uncompressed"],
                 "外部原行数一致": raw_audit["rows"] == entry["raw_lines"],
                 "固定採用元stat一致": (selected_status.st_size, selected_status.st_mtime_ns) == (entry["source_size"], entry["source_mtime_ns"]),
                 "固定cacheSHAサイズ一致": sha(cache) == entry["sha256_cache"] and cache.stat().st_size == entry["cache_size"]}
        if not all(flags.values()):
            raise ValueError(f"外部原板と既存入力が不一致: {key}: {flags}")
        result.append({"銘柄": key[0], "場": key[1], **flags, "原行数": entry["raw_lines"],
                       "展開SHA256": raw_audit["sha256"]})
    return {"入力数": len(result), "銘柄別": dict(Counter(item["銘柄"] for item in result)),
            "全件一致": True, "範囲": "2026-09-21_Day〜2026-10-29_Day、各57場。別標本として扱えない。",
            "比較": result, "証明の境界": "外部の全原行SHAをローカル固定台帳の展開SHAへ照合し、現物statとcacheSHAを再確認。今回114原板本文を全再走査した意味ではない。"}


def external_fills(baseline: dict) -> dict:
    """取得済み57約定ファイルをGit blobと原板cacheの原行へ照合する。

    引数: baseline (dict) は両指数の既存入力。
    返り値: dict は全124片と62入口の原行対応・モデル差の監査。
    """
    source = read(WORK / "外部約定取得.json")
    if source["commit"] != COMMIT:
        raise ValueError("外部約定が固定commitでない")
    downloads = {item["path"]: item for item in source["downloads"]}
    inputs = {(entry["symbol"], entry["session"]): entry for entry in baseline["entries"]}
    counts, file_results = Counter(), []
    for item in source["files"]:
        body = downloads[item["path"]]["content"] if item["size"] else ""
        if len(body.encode("utf-8")) != item["size"] or blob_sha(body.encode("utf-8")) != item["sha"]:
            raise ValueError("外部約定blobの内容が不一致")
        match = re.fullmatch(r"NK225_(\d{4}-\d{2}-\d{2}_(?:Day|Night))_(.+)\.trades\.jsonl", item["path"])
        if not match:
            raise ValueError("外部約定名を解釈できない")
        session, suffix = match.groups()
        expected_method = "NK225_T170_" + suffix
        entry = inputs[("NK225", session)]
        fills = [json.loads(line) for line in body.splitlines() if line.strip()]
        exact = omitted = 0
        positions = {}
        with np.load(ROOT / "work/複合検証" / entry["cache_path"], allow_pickle=False) as a:
            for fill in fills:
                line = int(fill["source_line"])
                position = int(np.searchsorted(a["line"], line, side="right")) - 1
                if position < 0 or line > entry["raw_lines"]:
                    raise ValueError("外部約定の原行がcache範囲外")
                clock = datetime.fromisoformat(fill["timestamp"]).timestamp()
                side, opening = (1 if fill["type"].startswith("Long") else -1), fill["type"].endswith("N")
                expected = float(a["ask"][position] if (opening and side == 1) or (not opening and side == -1) else a["bid"][position])
                if not (float(a["now"][position]) == clock and fill["price"] == expected and bool(a["valid"][position])):
                    raise ValueError(f"外部約定の原行時計・BBO・正常性が不一致: {fill['id']}")
                if fill["qty"] != 10 or fill.get("fee_yen", 0) != 0 or fill["method_id"] != expected_method:
                    raise ValueError("外部約定の数量・費用・手法IDが想定と異なる")
                if not fill["position_id"].startswith(expected_method + "/NK225/" + session + "/"):
                    raise ValueError("外部建玉IDの所有が不一致")
                state = positions.setdefault(fill["position_id"], {"side": side, "qty": 0})
                if state["side"] != side:
                    raise ValueError("外部返済の建玉方向が不一致")
                state["qty"] += fill["qty"] if opening else -fill["qty"]
                if state["qty"] < 0:
                    raise ValueError("外部返済が新規数量を超過")
                counts[fill["type"]] += 1
                if int(a["line"][position]) == line:
                    exact += 1
                else:
                    omitted += 1
                if fill.get("decision_ns") is not None:
                    counts["意思決定と約定が同じ価格時計"] += fill["decision_ns"] / 1e9 == clock
                    counts["次の物理行モデル"] += fill["source_line"] == fill["decision_line"] + 1
        if any(state["qty"] for state in positions.values()):
            raise ValueError("外部約定に未返済建玉")
        counts["保持原行へ直接対応"] += exact
        counts["同一状態省略区間へ対応"] += omitted
        file_results.append({"ファイル": item["path"], "Git_blob_SHA": item["sha"], "bytes": item["size"],
                             "約定片": len(fills), "直接原行": exact, "同一省略区間": omitted, "全片一致": True})
    return {"ファイル数": len(file_results), "空ファイル数": sum(not item["約定片"] for item in file_results),
            "全片一致": True, "件数": dict(counts), "新規数": counts["LongN"] + counts["ShortN"],
            "片数": sum(counts[k] for k in ("LongN", "LongR", "ShortN", "ShortR")),
            "出所": "work/外部研究/外部約定取得.json", "出所SHA256": sha(WORK / "外部約定取得.json"),
            "原行解決": "完全同一状態の連続省略区間は、直前の保持状態へ対応する。原行番号をフィルタ後の番号に変換しない。",
            "モデル差": "元資料はmini10枚・fee省略0・次の物理行モデル。価格時計差0秒は実発注遅延0秒を意味しない。本研究のmicro1枚・1価格時計秒待ち・費用を既に適用した取引ではない。",
            "ファイル": file_results}


# ----------------------------------------
# 新1場はbuild_oneによる入力品質だけ準備し、特徴・価格方向・ラベルを作らない。

def prepare_new(old: dict) -> tuple[dict, dict]:
    """旧NK64entryを不変で維持し、11/4Dayの品質cacheだけ追加する。

    引数: old (dict) は00006の64場台帳。
    返り値: tuple[dict,dict] は65場正式台帳と新1場の品質記録。
    """
    preparation_path = ROOT / "scripts/複合検証/データ準備.py"
    if sha(preparation_path) != old["データ準備コードSHA256"]:
        raise ValueError("原板前処理コードが固定版から変更")
    spec = importlib.util.spec_from_file_location("外部探索の入力準備", preparation_path)
    preparation = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = preparation
    spec.loader.exec_module(preparation)
    entries = copy.deepcopy(old["entries"])
    if len(entries) != 64 or any(entry["symbol"] != "NK225" for entry in entries):
        raise ValueError("旧台帳がNK64場でない")
    for entry in entries:
        source = Path(old["source_root"]) / entry["source_path"]
        status = source.stat()
        if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
            raise ValueError("旧64採用元statが変更")
        if sha(ROOT / "work/複合検証" / entry["cache_path"]) != entry["sha256_cache"]:
            raise ValueError("旧64cacheが変更")
    target = STUDY / "入力台帳.json"
    existing = read(target) if target.is_file() else None
    source = Path(old["source_root"]) / "NK225" / NEW_SESSION / "book.jsonl"
    cache = ROOT / "work/複合検証/キャッシュ/NK225" / (NEW_SESSION + ".npz")
    if existing:
        new = existing["entries"][-1]
        status = source.stat()
        if (status.st_size, status.st_mtime_ns) != (new["source_size"], new["source_mtime_ns"]) or sha(cache) != new["sha256_cache"]:
            raise ValueError("固定した新1入力が変更")
    else:
        if cache.exists():
            raise ValueError("台帳未登録の新cacheを上書きしない")
        new = preparation.build_one(source, cache, "NK225", NEW_SESSION, Path(old["source_root"]))
        new = copy.deepcopy(new)
        new["volume_audit"].pop("five_minute_bars", None)
    entries.append(new)
    manifest = {**copy.deepcopy(old), "created_at_jst": existing["created_at_jst"] if existing else datetime.now(JST).isoformat(),
                "entries": entries, "元台帳": OLD.relative_to(ROOT).as_posix(), "元台帳SHA256": sha(OLD),
                "入力監査コードSHA256": sha(Path(__file__)), "データ準備コードSHA256": sha(preparation_path),
                "入力区分": {"既使用探索": [entry["session"] for entry in entries[:64]], "選択後まで保留": [NEW_SESSION]},
                "用途": "旧64を不変で維持。新1場は品質cacheのみ。新1の価格経路・特徴・ラベル・損益を選択固定前に利用しない。"}
    if entries[:64] != old["entries"]:
        raise AssertionError("旧64entryを変更している")
    if existing and existing != manifest:
        raise ValueError("既存00008台帳と再生成内容が異なるため上書きしない")
    if not existing:
        write(target, manifest)
    csv_quality = []
    for minutes in (1, 5):
        path = source.parent / f"candle_{minutes}min.csv"
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        clocks = [datetime.fromisoformat(row["time"]) for row in rows]
        csv_quality.append({"ファイル": path.name, "SHA256": sha(path), "列": fields, "行数": len(rows),
                            "先頭時計": clocks[0].isoformat(), "最終時計": clocks[-1].isoformat(),
                            "時計重複": len(clocks) - len(set(clocks)),
                            "時計後退": sum(right < left for left, right in zip(clocks, clocks[1:])),
                            "closed": dict(Counter(row["closed"] for row in rows)),
                            "volume_complete": dict(Counter(row["volume_complete"] for row in rows))})
    quality = {"場": NEW_SESSION, "原板行数": new["raw_lines"], "状態数": new["events"],
               "場内限月": new["in_session_contract_codes"], "原板品質": new["quality"],
               "数量品質": new["volume_audit"], "CSV品質": csv_quality, "cacheサイズ": new["cache_size"],
               "cacheSHA256": new["sha256_cache"], "新1の特徴ラベル損益": "未確認・保留",
               "完全性の境界": "closedは足の確定フラグで、全約定や通信欠落の不存在の証明ではない。"}
    return manifest, quality


def main() -> None:
    """保存済みconnector証拠を監査し、入力台帳と作業JSONを保存する。

    引数: なし。巨大manifest・archive・リポジトリ全体は取得しない。
    返り値: None。不一致があれば停止する。
    """
    bodies, evidence = envelopes()
    baseline, old = read(BASELINE), read(OLD)
    same_data = compare_external(bodies, baseline)
    fills = external_fills(baseline)
    manifest, quality = prepare_new(old)
    archived = read(WORK / "tree_00161_archive.json")["tree"]
    data_root = Path(old["source_root"])
    inventory = {}
    for symbol in ("NK225", "TOPIX"):
        sessions = sorted(path.name for path in (data_root / symbol).iterdir() if path.is_dir())
        inventory[symbol] = {"場数": len(sessions), "最初": sessions[0], "最後": sessions[-1]}
    report = {"確認日時": datetime.now(JST).isoformat(), "固定commit": COMMIT, "repository": REPOSITORY,
              "外部小型証拠": evidence, "取得本文合計bytes": sum(item["bytes"] for item in evidence),
              "00170の同一性": same_data, "00170外部約定の原行照合": fills,
              "00161入力": {"資料上の範囲": "9/21〜10/27DayのNK53場、特徴生成にはTOPIXも含む106ファイル。",
                           "作成出典": "prepare161.pyはwork/entry160/inputs160.jsonのbooksと2市場fingerprintsだけを選び、30/10/13場へ分ける。",
                           "実入力台帳": "work/entry161/inputs161.jsonは直接管理treeに存在せず、内容・個別SHAの直接取得は未完了。",
                           "cache出典": "extract161.pyはsceneごとにread_market(NK225/TOPIX)と入力指紋を使い、stage/split/session.npzへ配列とメタを保存。",
                           "同一性の限界": "入力時期と出典は重なるが、00161の個別fingerprint実体を未取得なので00170同様のSHA一致を断定しない。",
                           "archiveメタ": [{"path": item["path"], "Git_blob_SHA": item["sha"], "bytes": item["size"]} for item in archived],
                           "archive本文取得": False},
              "保存形式": "保存データはtar.gzを最大48MiBのpartへ分割し、manifestに元パス・SHAを記録する方式。現行原板はJP_OSE_Dataを参照し旧book archiveを復元しない。",
              "取得しない大容量": {"保存データ/manifest.json": 40655266, "保存データ/保存計画.json": 13207844,
                                  "repository clone": False, "raw板archive取得復元": False},
              "現物フォルダ": inventory, "旧64entry不変": manifest["entries"][:64] == old["entries"],
              "新1品質": quality, "正式入力台帳": (STUDY / "入力台帳.json").relative_to(ROOT).as_posix(),
              "正式入力台帳SHA256": sha(STUDY / "入力台帳.json"), "入力場数": len(manifest["entries"]),
              "コードSHA256": sha(Path(__file__)),
              "注意": "00170の旧57場は同じ板と確認済みであり未見の外部追試ではない。外部mini10枚/費用0/次物理行モデルの金額をmicro1枚運用へ同額転用しない。新1の成績は固定後の一回確認まで開かない。"}
    write(WORK / "入力監査.json", report)
    print(json.dumps({"外部114同一": same_data["全件一致"], "外部約定片": fills["片数"], "原行照合": fills["全片一致"],
                      "入力場数": len(manifest["entries"]), "新1cacheB": quality["cacheサイズ"], "新1成績": "未確認・保留"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
