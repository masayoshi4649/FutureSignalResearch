"""固定89の通知・所有と公開足原板結合を四会計へ再用する。"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXED_PATH = ROOT / "scripts/FAR利益床と収穫配分の比較/Source通知監査.py"
FIXED_SHA = "91e5ff2721a01e83d3571130e09187ce68b76531a766f6ca11440b75156e0fd7"
KEYS = tuple(f"{p}_D{d}" for d in (0, 1) for p in ("H0G1", "H1G1"))


def load(path: Path, name: str) -> object:
    """
    機能: 明示された固定監査を独立したモジュール実体として読む。
    引数: path (Path)、name (str) は本文とモジュール名。
    返り値: object は公開された監査API。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


assert hashlib.sha256(FIXED_PATH.read_bytes()).hexdigest() == FIXED_SHA
FIXED = load(FIXED_PATH, "source89_for92")
FIXED.KEYS = KEYS
BASE = FIXED.BASE
PRICE_PATH = Path(__file__).with_name("価格構造.py")
PRICE = load(PRICE_PATH, "price92_for_source")
LEGACY_RAW = FIXED.RAW.RawEvents


class PriceRawEvents(LEGACY_RAW):
    """旧原板結合の直後に同じRecordを独立価格器へ渡す。"""

    def __init__(self, saved: dict, start: float, end: float, core: set, us: float, audit: object, check: object) -> None:
        """
        機能: 旧全call結合を維持し、新価格定時とcounterの索引を初期化する。
        引数: saved (dict)、start/end/us (float)、core (set)、audit/check (object) は旧APIと同じ。
        返り値: None。自ら原板を開かず旧一走査の配送だけを受ける。
        """
        super().__init__(saved, start, end, core, us, audit, check)
        self.price_tracker = PRICE.PriceTracker(saved["session"])
        self.price_by_at = {p["at"]: p for p in saved["price_decisions"]}
        FIXED.require(len(self.price_by_at) == len(saved["price_decisions"]) and set(self.price_by_at) == {g["at"] for g in saved["grid_decisions"]}, "独立価格の全定時集合が不一致")
        _, planned_grids, _, _ = FIXED.schedule(saved["session"])
        FIXED.require(set(self.price_by_at) == planned_grids, "独立価格と共有判断が全予定定時に一致しない")
        self.price_seen, self.price_records = set(), set()

    def call(self, at: float, origin: str, q: dict) -> None:
        """
        機能: 当時原板へ照合済みの公開Recordだけを独立器へ送り定時状態を照合する。
        引数: at (float)、origin (str)、q (dict) は同じ一走査の公開clockと原気配。
        返り値: None。旧k期限を新器の失効条件へ変換しない。
        """
        super().call(at, origin, q)
        record = self.records.get(self.ordinal)
        if record is not None:
            FIXED.require(self.ordinal not in self.price_records, "独立価格へRecordを二重配送")
            self.price_tracker.feed(record)
            self.price_records.add(self.ordinal)
        if origin == "core_timer" and at in self.price_by_at:
            FIXED.require(at not in self.price_seen, "独立価格定時を二重照合")
            self.check(self.audit, "原板同一走査の独立価格snapshot全文", self.price_by_at[at]["snapshot"], self.price_tracker.snapshot(at))
            self.price_seen.add(at)

    def finish(self, last: dict) -> dict:
        """
        機能: 旧trace/利益出典に新価格全定時・全Record・counterの計測完了を加える。
        引数: last (dict) は最後の受理NK原行。
        返り値: dict は同じ一走査内の旧出典と新価格の照合件数。
        """
        result = super().finish(last)
        FIXED.require(self.price_records == set(self.records) and self.price_seen == set(self.price_by_at), "独立価格の公開Record又は定時が未計測")
        self.check(self.audit, "原板同一走査の独立価格全counter", self.saved["price_counts"], self.price_tracker.counts())
        result["独立価格"] = {"実行": True, "Record結合数": len(self.price_records), "定時数": len(self.price_seen), "counter": self.price_tracker.counts(), "追加原板走査": 0}
        return result


def inspect_one(args: tuple[str, str, dict], require_price: bool = True) -> dict:
    """
    機能: 固定89の同じ一原板走査で通知・所有・公開Close/TRを照合する。
    引数: args (tuple[str,str,dict]) は結果根・原板根・一場台帳、require_price (bool) は正式時必須で限定旧器具だけfalse。
    返り値: dict は全通知・公開足・独立価格の原板出典。falseは新価格未計測を明示する。
    """
    FIXED.require(type(require_price) is bool, "独立価格必須の指定はboolに限定する")
    FIXED.RAW.RawEvents = PriceRawEvents if require_price else LEGACY_RAW
    try:
        result = FIXED.inspect_one(args)
    finally:
        FIXED.RAW.RawEvents = LEGACY_RAW
    if not require_price:
        result["入口足原板結合"]["独立価格"] = {"実行": False, "理由": "固定89の旧規範adapter器具だけを検査。新独立価格は未計測。"}
    return result


def main() -> None:
    """
    機能: 固定66場の通知と公開足を並列検査し新規の証拠へ保存する。
    引数: --results/--manifest/--out (Path)、--workers (int) はCLI対象。
    返り値: None。未計測・不一致・入力変更は非0で終了する。
    """
    parser = argparse.ArgumentParser(description="独立価格入口のSource・公開足原板監査")
    for name in ("results", "manifest", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    assert not args.out.exists() and 1 <= args.workers <= 16
    ledger_before, code_before, price_before = BASE.sha(args.manifest), BASE.sha(Path(__file__)), BASE.sha(PRICE_PATH)
    ledger = BASE.read_json(args.manifest)
    assert len(ledger["sessions"]) == 66 and len({e["id"] for e in ledger["sessions"]}) == 66
    tasks = [(str(args.results.resolve()), ledger["source_root"], entry) for entry in ledger["sessions"]]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(inspect_one, tasks))
    assert BASE.sha(Path(__file__)) == code_before and BASE.sha(args.manifest) == ledger_before and BASE.sha(FIXED_PATH) == FIXED_SHA and BASE.sha(PRICE_PATH) == price_before
    errors = sum(r["不一致数"] for r in rows)
    unchanged = all(r["入力前後不変"] for r in rows)
    summary = Counter()
    for row in rows:
        for book in row["各会計通知要約"]:
            summary.update({k: v for k, v in book.items() if k != "会計"})
    value = {"試行": 92, "成功": errors == 0 and unchanged, "処理完了": True, "場数": len(rows), "会計数": sum(r["会計数"] for r in rows),
             "Sourceイベント数": sum(r["Sourceイベント数"] for r in rows), "Source通知数": sum(r["Source通知数"] for r in rows),
             "Source効果数": sum(r["Source効果数"] for r in rows), "照合項目数": sum(r["照合項目数"] for r in rows),
             "不一致数": errors, "入力前後不変": unchanged, "入力台帳SHA256": ledger_before, "監査コードSHA256": code_before,
             "固定89通知監査SHA256": FIXED_SHA, "原板本文走査回数毎場": 1, "新売買再生": 0,
             "独立価格コードSHA256": price_before,
             "入口足原板結合": {"場数": len(rows), "原板結合trace": sum(r["入口足原板結合"]["原板結合trace"] for r in rows),
                                "利益snapshot": sum(r["入口足原板結合"]["利益snapshot"] for r in rows), "全call": sum(r["入口足原板結合"]["全call"] for r in rows)},
             "要約": dict(summary), "限界": FIXED.LIMITS,
             "不一致": [x for r in rows for x in r["不一致"]], "対象場": rows}
    assert value["会計数"] == 264 and all(r["入口足原板結合"]["独立価格"]["実行"] for r in rows)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "場数", "会計数", "Source通知数", "不一致数", "照合項目数")}, ensure_ascii=False))
    if not value["成功"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
