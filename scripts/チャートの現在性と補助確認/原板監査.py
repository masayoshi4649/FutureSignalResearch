"""固定81のG1規範を再用し、82の264会計を原板と照合する。"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import importlib.util
import json
from pathlib import Path


def load_fixed() -> object:
    """
    機能: 固定81監査を読み、対象キーだけ4会計へ設定する。
    引数: なし。
    返り値: object はメモリ上だけキー設定した独立監査器。
    """
    path = Path(__file__).resolve().parent.parent / "定時の現在根拠と部分利益保護/原板監査.py"
    spec = importlib.util.spec_from_file_location("fixed81_raw_for82", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in ("B0G1", "B1G1"))
    module.BASE.MODES = module.KEYS
    return module


FIXED = load_fixed()
KEYS = FIXED.KEYS
BASE = FIXED.BASE


def inspect_one(task: tuple) -> dict:
    """
    機能: 保存の対象集合を固定し、一場の4会計を固定81規範で検査する。
    引数: task (tuple) は結果根・データ根・場台帳。
    返り値: dict は指紋・差分・保護診断。売買は生成しない。
    """
    result_root, _, entry = task
    path = Path(result_root) / (entry["id"] + ".json")
    saved = BASE.read_json(path)
    assert set(saved["books"]) == set(KEYS), "4会計の欠落又は余計な対象"
    return FIXED.inspect_one(task)


def main() -> None:
    """
    機能: 全66既使用場を別workerで原板照合し、結果を新規保存する。
    引数: --results/--manifest/--out (Path)、--workers (int)。
    返り値: None。不一致は証拠保存後に非0終了する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", default=16, type=int)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("既存監査は上書きしません")
    ledger = BASE.read_json(args.manifest)
    assert len(ledger["sessions"]) == 66 and 1 <= args.workers <= 16
    tasks = [(str(args.results.resolve()), ledger["source_root"], entry) for entry in ledger["sessions"]]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(inspect_one, tasks))
    errors = sum(r["不一致数"] for r in rows)
    value = {"試行": 82, "成功": errors == 0, "場数": len(rows), "不一致数": errors,
        "照合項目数": sum(r["照合項目数"] for r in rows), "不一致": [e for r in rows for e in r["不一致"]],
        "入力台帳SHA256": BASE.sha(args.manifest), "固定81監査SHA256": BASE.sha(Path(FIXED.__file__)),
        "固定80監査SHA256": BASE.sha(Path(BASE.__file__)), "監査コードSHA256": BASE.sha(Path(__file__)),
        "新売買再生": 0, "対象場": rows}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "場数", "照合項目数", "不一致数")}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
