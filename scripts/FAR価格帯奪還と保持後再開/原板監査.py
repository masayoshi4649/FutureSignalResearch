"""独立価格入口の四会計を固定89の金融G1規範へ結ぶ薄い監査。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXED_PATH = ROOT / "scripts/FAR利益床と収穫配分の比較/原板監査.py"
FIXED_SHA = "318573cde0969fb9c7ad7de55b9a860418f231e5c98a32ddd833d0a98d730ccf"
KEYS = tuple(f"{p}_D{d}" for d in (0, 1) for p in ("H0G1", "H1G1"))


def load_fixed() -> object:
    """
    機能: 固定89の所有・G1・初回利益規範を別モジュール実体で読む。
    引数: なし。
    返り値: object はキーだけ四会計へ限定した旧監査。旧本文は変更しない。
    """
    assert hashlib.sha256(FIXED_PATH.read_bytes()).hexdigest() == FIXED_SHA
    spec = importlib.util.spec_from_file_location("raw89_for92", FIXED_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.KEYS = KEYS
    module.OLD.KEYS = KEYS
    module.BASE.MODES = KEYS
    return module


FIXED = load_fixed()
BASE = FIXED.BASE


def inspect_one(args: tuple[str, str, dict]) -> dict:
    """
    機能: 一場一走査の金融検査を固定89へ委譲し外政策名だけ適合する。
    引数: args (tuple[str,str,dict]) は結果根・原板根・一場台帳。
    返り値: dict は価格・費用・G1義務・出典の差分と入力指紋。
    """
    result_root, data_root, entry = args
    path = Path(result_root) / (entry["id"] + ".json")
    saved, before, audit = BASE.read_json(path), BASE.sha(path), BASE.Audit()
    assert saved["session"] == entry["id"] and set(saved["books"]) == set(KEYS)
    FIXED.OLD.bind_source_anchors(saved, audit)
    normalized = deepcopy(saved)
    times = {o["request_time"] for b in saved["books"].values() for o in b["orders"] if o["kind"] == "entry"}
    quotes = [{"at": g["at"], "quote": g["c0"]["base"]["quote"]} for g in saved["grid_decisions"] if g["at"] in times]
    force_times = [BASE.bounds(saved["session"])[1] - 600]
    quiet = [g["at"] for g in saved["grid_decisions"] if g["window"] == "静観"]
    if quiet:
        force_times.append(min(quiet))
    for key, book in normalized["books"].items():
        policy, delay = key.split("_D")
        assert policy in ("H0G1", "H1G1") and book["mode"] == "S0G1" and book["source_policy"] == "S"
        assert book["hold_enabled"] is False and book["confirm_enabled"] is False and book["fill_delay_seconds"] == int(delay)
        assert all(t["method_id"] == "S0G1" for t in book["trades"])
        book["mode"] = key
        book["_audit_force_times85"] = force_times
        book["_audit_source_quotes85"] = quotes
        book["_audit_profit_contexts89"] = saved["profit_contexts"]
        for trade in book["trades"]:
            trade["method_id"] = key
    for info in entry["files"].values():
        BASE.verify_file(Path(data_root), info)
    summary = BASE.inspect_session(Path(data_root) / entry["files"]["NK225_book"]["path"], entry["id"], normalized, audit, True)
    for info in entry["files"].values():
        BASE.verify_file(Path(data_root), info)
    after = BASE.sha(path)
    assert after == before
    return {"session": entry["id"], "再生結果SHA256前": before, "再生結果SHA256後": after,
            "照合項目数": audit.checks, "不一致数": audit.errors, "不一致": audit.details, "診断": summary}


def main() -> None:
    """
    機能: 明示台帳の全場を一走査ずつ検査し新規の監査正本へ保存する。
    引数: --results/--manifest/--out (Path)、--workers (int) はCLI対象。
    返り値: None。不一致・例外・不足は非0で終了する。
    """
    parser = argparse.ArgumentParser(description="独立価格入口の金融G1原板監査")
    for name in ("results", "manifest", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    assert not args.out.exists() and 1 <= args.workers <= 16
    ledger_before, code_before = BASE.sha(args.manifest), BASE.sha(Path(__file__))
    ledger = BASE.read_json(args.manifest)
    assert len(ledger["sessions"]) == 66 and len({e["id"] for e in ledger["sessions"]}) == 66
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(inspect_one, [(str(args.results.resolve()), ledger["source_root"], e) for e in ledger["sessions"]]))
    assert BASE.sha(Path(__file__)) == code_before and BASE.sha(args.manifest) == ledger_before and BASE.sha(FIXED_PATH) == FIXED_SHA
    errors = sum(r["不一致数"] for r in rows)
    value = {"試行": 92, "成功": errors == 0, "処理完了": True, "場数": len(rows), "会計数": len(rows) * len(KEYS),
             "不一致数": errors, "照合項目数": sum(r["照合項目数"] for r in rows), "監査コードSHA256": code_before,
             "固定89監査SHA256": FIXED_SHA, "入力台帳SHA256": ledger_before, "原板本文走査回数毎場": 1,
             "新売買再生": 0, "限界": "入口の独立価格構造・E0資格は保存監査、公開Close/TRとSourceは別統合一走査。元数値器全前史の独立再実装ではない。",
             "不一致": [x for r in rows for x in r["不一致"]], "対象場": rows}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "場数", "会計数", "不一致数", "照合項目数")}, ensure_ascii=False))
    if not value["成功"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
