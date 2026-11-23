# 固定88原板監査SHA256: d4a340471f7c9f572e24c20ef879679e27498e0528c5909b8bbc07d38d35dc14
"""89のG1/G2可変Sourceを独立原板所有と初回利益出典へ結ぶ。"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT/"scripts/FAR参照玉と可変数量の比較/原板監査.py"
OLD_SHA = "c545501e771f50ee2c31123ee7290291f7d6bf6ee90ae2467eece4eb6910a406"
KEYS = tuple(f"{p}_D{d}" for d in (0, 1) for p in ("E0G1", "E0G2", "E1G1", "E1G2"))


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
ceiling5 = OLD.ceiling5
HOLD_REASON = OLD.HOLD_REASON


class Whole89(OLD.Whole87):
    """固定G1規範の全fill後に、診断専用の利益初回量・時点を検査する。"""

    def __init__(self, books: dict, audit: object) -> None:
        """
        機能: 8会計の独立所有と共有利益contextを初期化する。
        引数: books (dict)、audit (object) は保存会計と差分台帳。
        返り値: None。contextを売買・保護判定へ用いない。
        """
        super().__init__(books, audit)
        for mode, book in books.items():
            if mode[:4].endswith("G2"):
                for order in book["orders"]:
                    if order["kind"] == "exit" and order["reason"] == "G2全量建値床・ATR追尾":
                        self.floor_orders[mode].setdefault(order["request_line"], []).append(order)
        self.contexts = next(iter(books.values()))["_audit_profit_contexts89"]
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

    def inspect_protection(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """
        機能: 共通ATRとG1/G2の私有床へ保持帯床を重ね、全fill後の残玉保護と同原行予約を検査する。
        引数: line/index (int)、at/bid/ask (float) は全fill後の原行。
        返り値: None。利確完了前の実現していない予算は利用しない。
        """
        for mode in KEYS:
            counts = self.protection[mode]
            for pid, state in self.active[mode].items():
                quantity = state["remaining"]
                if quantity <= 0:
                    continue
                lot = self.saved[mode][pid]
                atr = lot["entry_atr"]
                d = Decimal(125) if atr is None else min(Decimal(125), max(Decimal(15), ceiling5(Decimal(str(atr)))))
                self.audit.check("ATR由来固定幅", Decimal(str(lot["d"])), d, 候補=mode, 実玉=pid)
                price = Decimal(str(bid if state["side"] > 0 else ask))
                gain = state["side"] * (price - state["entry"])
                flagged = state["residual_first"] is not None
                floor = max(state["hold_base85"], Decimal(-125), state["best_gain"] - d)
                structure_floor = Decimal(str(state["structure_floor83"])) if state["structure_active83"] else None
                if structure_floor is not None:
                    floor = max(floor, structure_floor)
                    counts["構造活性原行"] += 1
                    if gain <= structure_floor:
                        counts["構造到達原行"] += 1
                        if state["structure_hit_at83"] is None:
                            state["structure_hit_at83"], state["structure_hit_index83"] = at, index
                cash_active = False
                if flagged:
                    if mode[:4].endswith("G2"):
                        floor = max(floor, Decimal(0))
                    else:
                        floor = max(floor, Decimal(0))
                        harvest = self.harvest[mode].get(pid)
                        issued = harvest is not None and harvest["request_line"] <= line and harvest["request_time"] <= at
                        if not issued and self.reserved[mode][pid] == 0 and gain * 10 - 122 > 0:
                            counts["利確要求義務原行"] += 1
                            counts["利確要求不足原行"] += 1
                            self.audit.check("G1正益後の即時利確要求", False, True, 候補=mode, 実玉=pid, 原行=line, 時計=at)
                        if issued and harvest["request_line"] == line:
                            counts["利確要求義務原行"] += 1
                            unit = gain * 10 - 122
                            if unit <= 0:
                                self.audit.check("G1利確の現在単価strict正", float(unit), "正", 候補=mode, 実玉=pid)
                            else:
                                needed = int(((222 * quantity + 1 - state["realized"]) / (unit + 222)).to_integral_value(rounding=ROUND_CEILING))
                                target = min(quantity, max(1, needed))
                                self.audit.check("G1確定益だけの利確量", harvest["quantity"], target, 候補=mode, 実玉=pid, 原行=line)
                                self.audit.check("G1必要量と充足可否", (harvest["harvest_needed"], harvest["harvest_feasible"]), (needed, needed <= quantity), 候補=mode, 実玉=pid)
                                counts["利確量検査"] += 1
                        if harvest is not None and self.harvest_filled[mode].get(pid, 0) >= harvest["quantity"]:
                            cash = ceiling5(max(Decimal(0), (222 + (Decimal(1) - state["realized"]) / quantity) / 10))
                            floor = max(floor, cash)
                            cash_active = True
                            state["cash_floor81"] = float(cash)
                            if not state["cash_active81"]:
                                state["cash_active81"] = True
                                state["cash_at81"] = at
                state["hold_base85"] = floor
                hold_floor = Decimal(str(state["hold_floor85"])) if state["hold_active85"] else None
                hold_binding = hold_floor is not None and hold_floor > floor
                if hold_floor is not None:
                    counts["保持帯活性原行"] += 1
                    floor = max(floor, hold_floor)
                    if gain <= hold_floor:
                        counts["保持帯到達原行"] += 1
                        if state["hold_hit_at85"] is None:
                            state["hold_hit_at85"], state["hold_hit_index85"], state["hold_hit_line85"] = at, index, line
                floor = max(state["floor81"], floor)
                state["floor81"] = floor
                for order in self.structure_orders[mode].get(line, []):
                    if order["position_id"] == pid:
                        binding = structure_floor is not None and gain <= structure_floor and floor == structure_floor
                        self.audit.check("構造理由は当時の拘束床到達", binding, True, 候補=mode, 実玉=pid, 原行=line)
                        self.audit.check("構造要求に最終床を保存", order["floor"], float(floor), 候補=mode, 実玉=pid, 原行=line)
                hit, hard = gain <= floor, gain <= -125
                expected_reason = None
                if hard:
                    expected_reason = "共通125pt保護"
                elif hit:
                    expected_reason = HOLD_REASON if hold_binding else ("G2全量建値床・ATR追尾" if flagged and mode[:4].endswith("G2") else "G1確定益予算・ATR追尾" if flagged and cash_active else "G1建値床・ATR追尾" if flagged else "正益前ATR損失追尾")
                for floor_order in self.floor_orders[mode].get(line, []):
                    if floor_order["position_id"] == pid:
                        self.audit.check("保持帯と旧床の理由優先", floor_order["reason"], expected_reason, 候補=mode, 実玉=pid, 原行=line)
                        self.audit.check("床要求に最終非緩和床", floor_order["floor"], float(floor), 候補=mode, 実玉=pid, 原行=line)
                counts["正常保有原行"] += 1
                counts["正益後保有原行"] += flagged
                counts["床到達原行"] += hit
                counts["125pt到達原行"] += hard
                counts["cash床原行"] += cash_active
                if hit or hard:
                    counts["返済義務原行"] += 1
                    shortage = max(0, quantity - self.reserved[mode][pid])
                    counts["予約不足原行"] += shortage > 0
                    counts["予約不足数量"] += shortage
                    self.audit.check("81床到達の全量予約", shortage, 0, 候補=mode, 実玉=pid, 原行=line, Index=index, 時計=at, 床=float(floor), 幅=float(gain))
                    if structure_floor is not None and gain <= structure_floor:
                        counts["構造要求不足原行"] += shortage > 0
                    if hold_floor is not None and gain <= hold_floor:
                        counts["保持帯要求不足原行"] += shortage > 0

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


BASE.WholePosition = Whole89


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
        assert policy in ("E0G1", "E0G2", "E1G1", "E1G2") and book["mode"] == "S0" + policy[-2:] and book["source_policy"] == "S"
        assert book["hold_enabled"] is False and book["confirm_enabled"] is False and book["fill_delay_seconds"] == int(delay)
        assert all(t["method_id"] == "S0" + policy[-2:] for t in book["trades"])
        book["mode"] = key
        book["_audit_force_times85"] = force_times
        book["_audit_source_quotes85"] = quotes
        book["_audit_profit_contexts89"] = saved["profit_contexts"]
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
    機能: 固定66場398会計の原板G1と利益contextを照合する。
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
    value = {"試行": 89, "成功": errors == 0, "場数": 66, "会計数": 528, "不一致数": errors, "照合項目数": sum(r["照合項目数"] for r in rows),
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
