"""84の6入口会計を固定83の独立G1規範へ接続し、原板へ照合する。"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import importlib.util
import json
from pathlib import Path


KEYS = tuple(f"{p}G1_D{d}" for d in (0, 1) for p in ("A0", "C0", "C1"))


def load_origin() -> object:
    """
    機能: 固定83の独立金融規範を別モジュールとして読み込む。
    引数: なし。
    返り値: object は6会計キーだけ差し替えた規範。固定元ファイルは変更しない。
    """
    path = Path(__file__).resolve().parent.parent / "構造否定と利益配分/原板監査.py"
    spec = importlib.util.spec_from_file_location("fixed83_for84", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.KEYS = KEYS
    module.BASE.MODES = KEYS
    return module


ORIGIN = load_origin()
BASE = ORIGIN.BASE


def normalize(result: dict) -> dict:
    """
    機能: 固定S0G1内部ラベルを検査してから独立監査の外キーへ写す。
    引数: result (dict) は一場6会計。
    返り値: dict は所有・価格・数量・時刻を変えずラベルだけ正規化した複写。
    """
    if set(result["books"]) != set(KEYS):
        raise ValueError("84の6会計集合に過不足")
    normalized = deepcopy(result)
    for key, book in normalized["books"].items():
        delay = int(key.rsplit("_D", 1)[1])
        if book["mode"] != "S0G1" or book["fill_delay_seconds"] != delay or any(t["method_id"] != "S0G1" for t in book["trades"]):
            raise ValueError("固定金融S0G1又は遅延・約定ラベルが不一致")
        book["mode"] = key
        for trade in book["trades"]:
            trade["method_id"] = key
    return normalized


def inspect_one(args: tuple) -> dict:
    """
    機能: 一場を原板から独立再構築し、6会計と連続保護を照合する。
    引数: args (tuple) は結果根・原板根・一場台帳。
    返り値: dict は差分・指紋・規範診断。新たな売買は生成しない。
    """
    result_root, data_root, entry = args
    path = Path(result_root) / f"{entry['id']}.json"
    result = BASE.read_json(path)
    before = BASE.sha(path)
    normalized = normalize(result)
    audit = BASE.Audit()
    ORIGIN.bind_structure(result, audit)
    for info in entry["files"].values():
        BASE.verify_file(Path(data_root), info)
    market = Path(data_root) / entry["files"]["NK225_book"]["path"]
    diagnosis = BASE.inspect_session(market, entry["id"], normalized, audit, True)
    for info in entry["files"].values():
        BASE.verify_file(Path(data_root), info)
    if BASE.sha(path) != before:
        raise ValueError("保存結果が監査中に変化")
    return {"session": entry["id"], "再生結果SHA256": before, "照合項目数": audit.checks, "不一致数": audit.errors, "不一致": audit.details, "診断": diagnosis}


def main() -> None:
    """
    機能: 全66場の独立金融・原板監査を明示入力で実行する。
    引数: --results/--manifest/--out (Path)、--workers (int) は対象と並列数。
    返り値: None。差・入力異常・既存出力があれば非0終了する。
    """
    parser = argparse.ArgumentParser()
    for name in ("results", "manifest", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("既存原板監査は上書きしません")
    ledger = BASE.read_json(args.manifest)
    assert len(ledger["sessions"]) == 66 and 1 <= args.workers <= 16
    tasks = [(str(args.results.resolve()), ledger["source_root"], entry) for entry in ledger["sessions"]]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(inspect_one, tasks))
    errors = [v for row in rows for v in row["不一致"]]
    count = sum(row["不一致数"] for row in rows)
    value = {"試行": 84, "成功": count == 0, "場数": len(rows), "照合項目数": sum(row["照合項目数"] for row in rows), "不一致数": count, "不一致": errors,
        "入力台帳SHA256": BASE.sha(args.manifest), "監査コードSHA256": BASE.sha(Path(__file__)),
        "固定83監査SHA256": BASE.sha(Path(__file__).resolve().parent.parent / "構造否定と利益配分/原板監査.py"),
        "固定80監査SHA256": BASE.sha(Path(__file__).resolve().parent.parent / "FAR後期15分移植/原板照合.py"),
        "金融内部モード": "全てS0G1。検査後のラベル正規化だけを行う。", "新売買再生": 0, "対象場": rows}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "場数", "照合項目数", "不一致数")}, ensure_ascii=False))
    if count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
