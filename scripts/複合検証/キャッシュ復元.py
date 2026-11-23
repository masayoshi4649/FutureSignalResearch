"""正式な入力台帳で指定した原板だけから、作業キャッシュを復元する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def run(manifest_path: Path, output: Path, limit: int | None) -> None:
    """ハッシュで凍結した入力を使い、既存の同一キャッシュは再利用する。

    引数: manifest_path (Path) は正式台帳または参照、output (Path) はキャッシュ親、
    limit (int | None) は復元動作を少数入力で確認する場合の上限。
    返り値: None。不一致は停止し、異なる既存キャッシュを上書きしない。
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "参照" in data:
        reference = (manifest_path.parent / data["参照"]).resolve()
        if hashlib.sha256(reference.read_bytes()).hexdigest() != data["SHA256"]:
            raise ValueError("入力台帳の参照ハッシュ不一致")
        manifest_path = reference
        data = json.loads(reference.read_text(encoding="utf-8"))
    script = Path(__file__).with_name("データ準備.py")
    if hashlib.sha256(script.read_bytes()).hexdigest() != data["データ準備コードSHA256"]:
        raise ValueError("入力台帳作成時の準備コードと異なる")
    spec = importlib.util.spec_from_file_location("凍結データ準備", script)
    preparation = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = preparation
    spec.loader.exec_module(preparation)
    data_root = ROOT.parent / "JP_OSE_Data/future"
    entries = data["entries"] if limit is None else data["entries"][:limit]
    for number, entry in enumerate(entries, 1):
        source = data_root / entry["source_path"]
        status = source.stat()
        if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
            raise ValueError(f"入力版が変わった: {source}")
        target = output / entry["cache_path"]
        if target.exists():
            if preparation.hash_file(target) != entry["sha256_cache"]:
                raise ValueError(f"異なる既存キャッシュ: {target}")
        else:
            rebuilt = preparation.build_one(source, target, entry["symbol"], entry["session"], data_root)
            if rebuilt["sha256_uncompressed"] != entry["sha256_uncompressed"] or rebuilt["sha256_cache"] != entry["sha256_cache"]:
                raise ValueError(f"復元結果のハッシュが異なる: {source}")
        print(f"復元確認 {number}/{len(entries)} {entry['symbol']} {entry['session']}", flush=True)


def main() -> None:
    """凍結台帳と作業出力先をコマンド引数から取得する。

    引数: なし。argparseからmanifest/output/limitを取得する。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="work消去後も固定入力から同じキャッシュを再生成する")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "work/複合検証")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limitは正数を指定してください")
    run(args.manifest.resolve(), args.output.resolve(), args.limit)


if __name__ == "__main__":
    main()
