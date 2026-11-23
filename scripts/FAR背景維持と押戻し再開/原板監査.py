"""88の共通87金融を独立原板所有へ結び、初回利益contextも検査する。"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT/"scripts/FAR参照玉と可変数量の比較/原板監査.py"
OLD_SHA = "c545501e771f50ee2c31123ee7290291f7d6bf6ee90ae2467eece4eb6910a406"
KEYS = tuple(f"{p}_D{d}" for d in (0, 1) for p in ("S", "E0", "E1"))


def load_old() -> object:
    """
    機能: 固定87の価格・所有・G1規範を読取再用する。
    引数: なし。87完了時の指紋へ結ぶ。
    返り値: object は停止87監査。旧ファイルは編集しない。
    """
    assert hashlib.sha256(OLD_PATH.read_bytes()).hexdigest() == OLD_SHA
    spec = importlib.util.spec_from_file_location("raw87_for88", OLD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.KEYS = KEYS
    module.BASE.MODES = KEYS
    return module


OLD = load_old()
BASE = OLD.BASE


class Whole88(OLD.Whole87):
    """固定G1規範の全fill後に、診断専用の利益初回量・時点を検査する。"""

    def __init__(self, books: dict, audit: object) -> None:
        """
        機能: 6会計の独立所有と共有利益contextを初期化する。
        引数: books (dict)、audit (object) は保存会計と差分台帳。
        返り値: None。contextを売買・保護判定へ用いない。
        """
        super().__init__(books, audit)
        self.contexts = next(iter(books.values()))["_audit_profit_contexts88"]
        self.by_line = {}
        self.context_seen = Counter()
        self.expected = set()
        for row in self.contexts:
            self.by_line.setdefault(row["quote"]["line"], []).append(row)
            for t in row["triggered_by"]:
                identity = (t["book_key"], t["position_id"], t["flag_kind"])
                if identity in self.expected:
                    raise ValueError("初回利益contextのflag重複")
                self.expected.add(identity)

    def mark(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """
        機能: 旧全玉観測後の独立所有で初回利益contextを結ぶ。
        引数: line/index (int)、at/bid/ask (float) は正常採用原行。
        返り値: None。残量/確定額は旗瞬間ではなく同原行全fill後。
        """
        super().mark(line, index, at, bid, ask)
        for row in self.by_line.get(line, []):
            q = row["quote"]
            self.audit.check("利益contextの正常原行出典", (q["line"], q["index"], q["time"], q["bid"], q["ask"]), (line, index, at, bid, ask), 原行=line)
            for t in row["triggered_by"]:
                key, pid, kind = t["book_key"], t["position_id"], t["flag_kind"]
                identity = (key, pid, kind)
                self.context_seen[identity] += 1
                state = self.all[key].get(pid)
                self.audit.check("利益contextは実所有へ結合", state is not None, True, 候補=key, 実玉=pid)
                if state is None:
                    continue
                if kind not in ("residual", "whole"):
                    raise ValueError("未知の利益flag種別")
                first = state["residual_first" if kind == "residual" else "first"]
                self.audit.check("利益contextは独立初回原行", None if first is None else (first["原行"], first["Index"], first["時計"]), (line, index, at), 候補=key, 実玉=pid, 旗=kind)
                self.audit.check("利益contextは同原行全fill後の量と確定額", (t["remaining_after_fill"], t["closed_net_after_fill"]), (state["remaining"], float(state["realized"])), 候補=key, 実玉=pid, 旗=kind)

    def result(self) -> dict:
        """
        機能: 旧G1結果へ利益contextの全件結合検査を追加する。
        引数: なし。
        返り値: dict は独立全玉評価。未結合・重複を成功扱いしない。
        """
        output = super().result()
        self.audit.check("利益contextの全件一度結合", dict(self.context_seen), dict.fromkeys(self.expected, 1))
        actual = {(k, pid, kind) for k in KEYS for pid, state in self.all[k].items() for kind, field in (("residual", "residual_first"), ("whole", "first")) if state[field] is not None}
        self.audit.check("全初回利益flagへcontextを保存", self.expected, actual)
        return output


BASE.WholePosition = Whole88


def inspect_one(args: tuple[str, str, dict]) -> dict:
    """
    機能: 一場1走査で共通G1・価格・所有・初回利益contextを照合する。
    引数: args (tuple) は結果根・原板根・一場台帳。
    返り値: dict は差分と保護分母。event/Sourceは別の統合1走査へ委ねる。
    """
    result_root, data_root, entry = args
    path = Path(result_root)/(entry["id"]+".json")
    saved, before, audit = BASE.read_json(path), BASE.sha(path), BASE.Audit()
    assert set(saved["books"]) == set(KEYS)
    OLD.bind_source_anchors(saved, audit)
    normalized = deepcopy(saved)
    times = {o["request_time"] for b in saved["books"].values() for o in b["orders"] if o["kind"] == "entry"}
    quotes = [{"at": g["at"], "quote": g["c0"]["base"]["quote"]} for g in saved["grid_decisions"] if g["at"] in times]
    force_times = [BASE.bounds(saved["session"])[1]-600]
    quiet = [g["at"] for g in saved["grid_decisions"] if g["window"] == "静観"]
    if quiet:
        force_times.append(min(quiet))
    for key, book in normalized["books"].items():
        policy, delay = key.split("_D")
        assert policy in ("S", "E0", "E1") and book["mode"] == "S0G1" and book["source_policy"] == "S"
        assert book["hold_enabled"] is False and book["confirm_enabled"] is False and book["fill_delay_seconds"] == int(delay)
        assert all(t["method_id"] == "S0G1" for t in book["trades"])
        book["mode"] = key
        book["_audit_force_times85"] = force_times
        book["_audit_source_quotes85"] = quotes
        book["_audit_profit_contexts88"] = saved["profit_contexts"]
        for t in book["trades"]:
            t["method_id"] = key
    for info in entry["files"].values():
        BASE.verify_file(Path(data_root), info)
    summary = BASE.inspect_session(Path(data_root)/entry["files"]["NK225_book"]["path"], entry["id"], normalized, audit, True)
    for info in entry["files"].values():
        BASE.verify_file(Path(data_root), info)
    assert BASE.sha(path) == before
    return {"session": entry["id"], "再生結果SHA256": before, "照合項目数": audit.checks, "不一致数": audit.errors, "不一致": audit.details, "診断": summary}


def main() -> None:
    """
    機能: 固定66場396会計の原板G1と利益contextを照合する。
    引数: --results/--manifest/--out (Path)、--workers (int) は対象と並列数。
    返り値: None。差分は証拠保存後に非0終了し既存先は変更しない。
    """
    parser = argparse.ArgumentParser()
    for name in ("results", "manifest", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    assert not args.out.exists() and 1 <= args.workers <= 16
    ledger = BASE.read_json(args.manifest)
    assert len(ledger["sessions"]) == 66
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(inspect_one, [(str(args.results.resolve()), ledger["source_root"], e) for e in ledger["sessions"]]))
    errors = sum(r["不一致数"] for r in rows)
    value = {"試行": 88, "成功": errors == 0, "場数": 66, "会計数": 396, "不一致数": errors, "照合項目数": sum(r["照合項目数"] for r in rows),
        "監査コードSHA256": BASE.sha(Path(__file__)), "固定87監査SHA256": BASE.sha(OLD_PATH), "入力台帳SHA256": BASE.sha(args.manifest),
        "原板本文走査回数毎場": 1, "新売買再生": 0, "限界": "Source通知・event Close/TR/Last0/当原行Current出典は別統合1走査。元指標・Source生成器の独立再実装ではない。",
        "不一致": [x for r in rows for x in r["不一致"]], "対象場": rows}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "場数", "会計数", "不一致数", "照合項目数")}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
