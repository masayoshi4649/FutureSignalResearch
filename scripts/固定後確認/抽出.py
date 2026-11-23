"""予約メタ情報を照合した原板だけを固定readerで一回抽出する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))
SPEC = importlib.util.spec_from_file_location("固定後確認の固定8列reader", ROOT/"scripts/複合検証/データ準備.py")
PREP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREP
SPEC.loader.exec_module(PREP)


def reserved_source(pointer: dict) -> tuple[Path, dict]:
    """予約した一原板のパスと期待statを解決する。

    引数: pointer(dict)は事前の条件参照と予約メタ情報。
    返り値: tuple[Path,dict]は原板と予約行。ファイル内容を開かない。
    """
    reservation = pointer["予約確認"]
    if reservation["場"] != pointer["新規確認場"]:
        raise ValueError("予約した場と新規確認場が不一致")
    entries = [r for r in reservation["ファイル"] if r["名前"] == "book.jsonl"]
    if len(entries) != 1:
        raise ValueError("予約したbook.jsonlは一つだけ必要")
    source = (Path(reservation["パス"])/"book.jsonl").resolve()
    if source.parent.name != pointer["新規確認場"]:
        raise ValueError("原板パスの場名が不一致")
    return source, entries[0]


def check_reservation(pointer: dict) -> Path:
    """サイズと更新nsだけを照合し、予約変更を開封前に拒否する。

    引数: pointer(dict)は予約を含む条件参照。
    返り値: Pathは一致した一原板。価格・CSV・内容hashは読まない。
    """
    source, expected = reserved_source(pointer)
    stat = source.stat()
    if (stat.st_size, stat.st_mtime_ns) != (expected["バイト"], expected["更新ns"]):
        raise ValueError("予約時から新原板のサイズ/更新nsが変化したため開封しません")
    return source


def extract(pointer: dict, work: Path, fixed_sha: str, authorized: bool = False) -> dict:
    """明示承認後にjournalを先に残し、固定readerで八列を一回抽出する。

    引数: pointer(dict)は予約、work(Path)はGit外出力、fixed_sha(str)は27固定指紋、authorized(bool)はrootの開封許可。
    返り値: dictは新一場の台帳。失敗しても最初の開封記録を消さず、既存cacheを上書きしない。
    """
    if not authorized:
        raise ValueError("rootの明示開封承認前には新原板を読みません")
    source = check_reservation(pointer)
    session = pointer["新規確認場"]
    work.mkdir(parents=True, exist_ok=True)
    journal_path, manifest_path = work/"初回開封記録.json", work/"新規入力台帳.json"
    if journal_path.exists() or manifest_path.exists():
        raise FileExistsError("初回開封済み又は失敗記録があります。未見の初回として再開封しません")
    cache = (work/"キャッシュ/NK225"/(session+".npz")).resolve()
    if cache.exists():
        raise FileExistsError("予約場のcacheを上書きしません")
    before = source.stat()
    journal = {"開封開始日時": datetime.now(JST).isoformat(), "状態": "初回抽出開始",
        "新規確認場": session, "27固定SHA256": fixed_sha, "予約サイズ": before.st_size,
        "予約更新ns": before.st_mtime_ns, "原板": str(source), "原板複製": False,
        "抽出コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "固定readerSHA256": PREP.hash_file(Path(PREP.__file__))}
    PREP.write_json(journal_path, journal)
    try:
        entry = PREP.build_one(source, cache, "NK225", session, source.parents[2])
        after = source.stat()
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ValueError("初回抽出中に新原板のstatが変化")
        # ----------------------------------------
        # 既存監査helperのcache基底から同じ一個のcacheを参照できるようにする。
        base = (ROOT/"work/複合検証").resolve()
        entry["cache_path"] = cache.relative_to(base, walk_up=True).as_posix()
        if (base/entry["cache_path"]).resolve() != cache or not cache.is_relative_to(work.resolve()):
            raise ValueError("新cache参照が予定work内の一ファイルへ解決しません")
        manifest = {"schema_version": 1, "source_root": str(source.parents[2]),
            "cache_base": base.relative_to(ROOT).as_posix(), "entries": [entry],
            "新規確認場数": 1, "全旧65は助走のみ": True, "原板複製": False,
            "27固定SHA256": fixed_sha, "入力抽出コードSHA256": journal["抽出コードSHA256"],
            "固定readerSHA256": journal["固定readerSHA256"]}
        PREP.write_json(manifest_path, manifest)
        journal.update(状態="初回抽出完了", 開封完了日時=datetime.now(JST).isoformat(),
            原板内容SHA256=entry["sha256_uncompressed"], cacheSHA256=entry["sha256_cache"],
            新規入力台帳SHA256=PREP.hash_file(manifest_path))
        PREP.write_json(journal_path, journal)
        return manifest
    except BaseException as error:
        journal.update(状態="初回抽出失敗", 失敗日時=datetime.now(JST).isoformat(),
            例外型=type(error).__name__, 失敗理由=str(error))
        PREP.write_json(journal_path, journal)
        raise
